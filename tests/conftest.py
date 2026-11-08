"""
Test fixtures for Social Market application.

Default: SQLite in memory, no server needed. With TEST_DATABASE_URL pointing at
a PostgreSQL server, the same suite runs against a schema built exactly the way
production builds it (improvement plan 2026-11, C1) -- see _create_pg_schema.
"""

import os
import sqlite3
import uuid
from datetime import datetime

import pytest
from unittest.mock import MagicMock

# Set testing environment before importing app
os.environ['TESTING'] = 'true'
os.environ['SECRET_KEY'] = 'test-secret-key-for-testing-only'
os.environ['PASSWORD_PEPPER'] = 'a' * 64  # 64-char test pepper
os.environ['WTF_CSRF_ENABLED'] = 'false'
os.environ['RATELIMIT_ENABLED'] = 'false'

TEST_DATABASE_URL = os.environ.get('TEST_DATABASE_URL') or 'sqlite:///:memory:'
ON_POSTGRES = TEST_DATABASE_URL.startswith('postgresql')
# CI sets this for its PostgreSQL run. Without it, a mistyped or missing
# TEST_DATABASE_URL would fall back to SQLite, skip every PostgreSQL-only test
# and still report green.
if os.environ.get('REQUIRE_POSTGRES') == '1' and not ON_POSTGRES:
    raise RuntimeError('REQUIRE_POSTGRES=1 but TEST_DATABASE_URL is not a PostgreSQL URL')

# Imported only now: importing anything under ``app`` runs app/__init__.py and
# app/config.py, whose class attributes read the environment at import time.
# An import above the block above would build the config without the test pepper.
from app.timeutil import utcnow  # noqa: E402

# Python 3.12 deprecated sqlite3's implicit datetime adapter. Register the same
# conversion explicitly (ISO format with a space, what the default produced) so
# the SQLite test database keeps storing timestamps exactly as before.
sqlite3.register_adapter(datetime, lambda value: value.isoformat(' '))


@pytest.fixture(scope='session')
def app():
    """Create application for testing."""
    from app import create_app, db

    app = create_app('testing')
    app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': TEST_DATABASE_URL,
        'WTF_CSRF_ENABLED': False,
        'SERVER_NAME': 'localhost',
        'RATELIMIT_ENABLED': False,
        'PASSWORD_PEPPER': 'a' * 64,
        'REDIS_URL': 'redis://localhost:6379/0',
    })

    with app.app_context():
        if ON_POSTGRES:
            _create_pg_schema(db)
        else:
            _create_sqlite_tables(db)

    @app.teardown_request
    def _forget_loaded_user(exc):
        """
        Make every request resolve its user from its own cookies again.

        Within one test, requests share the per-test app context (see
        _app_context below), and Flask-Login caches the loaded user on `g`. The
        second request therefore saw the first request's user -- even from a
        different test client, and even after that user's session had been
        invalidated. A test of "the other browser is logged out" could not fail.
        Production pushes a fresh app context per request; this restores that.
        """
        from flask import g
        g.pop('_login_user', None)

    yield app

    with app.app_context():
        db.session.remove()
        if ON_POSTGRES:
            _drop_pg_schema(db)
        else:
            db.drop_all()
        # Close the pooled in-memory connection; otherwise it is only released
        # by the garbage collector at exit ("ResourceWarning: unclosed database").
        db.engine.dispose()


@pytest.fixture(autouse=True)
def _app_context(app):
    """
    Give every test its own application context.

    Flask reuses an already-active app context instead of pushing a new one per
    request, and `g` lives on that context. A session-wide context therefore let
    Flask-Login's cached `current_user` leak from one test into the next, which
    showed up as order-dependent 302s. Pushing and popping per test isolates it.
    """
    with app.app_context():
        yield


# Audit tables live in postgres/audit-logging.sql, not in the SQLAlchemy models,
# so db.create_all() does not create them. SQLAlchemy event listeners INSERT into
# them on every write -- without these tables the writes fail. Mirrored here in a
# SQLite-compatible form so the audit path is actually exercised in tests.
AUDIT_TABLES_DDL = (
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
        user_id VARCHAR(36), session_id VARCHAR(255), ip_address VARCHAR(45),
        user_agent TEXT, action VARCHAR(50) NOT NULL, table_name VARCHAR(100),
        record_id VARCHAR(36), old_values TEXT, new_values TEXT, query TEXT,
        status VARCHAR(20) DEFAULT 'success', error_message TEXT,
        severity VARCHAR(20) DEFAULT 'info', metadata TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS auth_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
        username VARCHAR(255), user_id VARCHAR(36), action VARCHAR(50) NOT NULL,
        ip_address VARCHAR(45), user_agent TEXT, session_id VARCHAR(255),
        failure_reason VARCHAR(255), metadata TEXT
    )
    """,
    """
    -- Mirrors migrations/add_blocked_ips.sql. Checked on every request since
    -- round 3; without the table each request ran the fail-open error path.
    CREATE TABLE IF NOT EXISTS blocked_ips (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ip_address VARCHAR(45) NOT NULL UNIQUE,
        reason TEXT NOT NULL,
        blocked_by VARCHAR(100) DEFAULT 'system',
        expires_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS security_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
        event_type VARCHAR(100) NOT NULL, severity VARCHAR(20) NOT NULL,
        source VARCHAR(100), user_id VARCHAR(36), ip_address VARCHAR(45),
        description TEXT NOT NULL, metadata TEXT,
        resolved BOOLEAN DEFAULT 0, resolved_at TIMESTAMP, resolved_by VARCHAR(36)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS message_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
        message_id VARCHAR(36) NOT NULL, sender_id VARCHAR(36) NOT NULL,
        recipient_id VARCHAR(36) NOT NULL, action VARCHAR(50) NOT NULL,
        encrypted BOOLEAN DEFAULT 1, metadata TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transaction_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
        -- NOT NULL exactly as in postgres/audit-logging.sql. A test schema that
        -- is more permissive than production is worse than none: it passes the
        -- very writes the real database rejects. This column being nullable
        -- here is why a NULL transaction_id reached production undetected.
        transaction_id VARCHAR(36) NOT NULL, buyer_id VARCHAR(36) NOT NULL,
        vendor_id VARCHAR(36) NOT NULL, product_id VARCHAR(36) NOT NULL,
        action VARCHAR(50) NOT NULL, amount DECIMAL(12, 2),
        status VARCHAR(50), metadata TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS admin_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
        admin_user_id VARCHAR(36) NOT NULL, action VARCHAR(100) NOT NULL,
        target_type VARCHAR(50), target_id VARCHAR(36),
        before_state TEXT, after_state TEXT, reason TEXT
    )
    """,
)


def _register_sqlite_functions(db):
    """
    Provide the PostgreSQL-side functions the app relies on to SQLite.

    encrypt_data()/decrypt_data() are pgcrypto-backed stored functions in
    production; here they are bound to the application's own Fernet-based
    CryptoService -- real encryption, not a stub, so tests can meaningfully
    assert that plaintext never reaches the column.
    """
    from sqlalchemy import event
    from app.services.crypto_service import CryptoService

    engine = db.engine
    if engine.dialect.name != 'sqlite':
        return

    def _register(dbapi_connection, _record=None):
        dbapi_connection.create_function(
            'encrypt_data', 1,
            lambda value: None if value is None else CryptoService.encrypt(value)
        )
        dbapi_connection.create_function(
            'decrypt_data', 1,
            lambda value: None if value is None else CryptoService.decrypt(value)
        )
        # Several security queries use PostgreSQL's NOW(). Without it SQLite
        # raises, and the broad `except` in SecurityService turns that into
        # "not blocked" -- the control would silently fail open in tests.
        dbapi_connection.create_function(
            'NOW', 0,
            lambda: utcnow().strftime('%Y-%m-%d %H:%M:%S')
        )

    event.listen(engine, 'connect', _register)

    # A connection may already be checked out. Do NOT dispose the pool to force
    # a reconnect: for sqlite:///:memory: that would throw the whole database
    # away. Register on the existing connection instead.
    raw = engine.raw_connection()
    try:
        _register(raw.driver_connection)
    finally:
        raw.close()


def _create_sqlite_tables(db):
    """Create the model tables plus the SQL-defined audit tables."""
    from sqlalchemy import text

    _register_sqlite_functions(db)
    db.create_all()
    for ddl in AUDIT_TABLES_DDL:
        db.session.execute(text(ddl))
    db.session.commit()


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The production database is built in this order: the SQL init scripts (functions,
# audit tables, grants), then `flask init-db` (db.create_all), then every file in
# migrations/. The test schema follows the same path, so a migration that does not
# apply to a fresh database, or a constraint the models do not know about, shows
# up here instead of on the server.
PG_INIT_SCRIPTS = ('postgres/pgcrypto-setup.sql', 'postgres/audit-logging.sql')
PG_MIGRATIONS = (
    'migrations/add_participant_columns.sql',
    'migrations/add_pgp_key_timestamps.sql',
    'migrations/add_two_factor_last_counter.sql',
    'migrations/add_blocked_ips.sql',
    'migrations/add_session_version.sql',
    # NOT order_lifecycle_integrity.sql: it is a one-shot upgrade. It reserves
    # the stock of orders that were pending before the change -- running it a
    # second time would take that stock again -- and its CHECK constraints are
    # in the models, so db.create_all() already made them. test_postgres.py
    # checks that they exist.
    'migrations/encrypt_two_factor_secret.sql',
    'migrations/pgcrypto_fail_closed.sql',
    'migrations/audit_indexes_catchup.sql',
)


def _autocommit_connection(db):
    """
    A raw connection in autocommit mode, for DDL scripts with their own BEGIN.

    The mode must be switched back before the connection returns to the pool:
    the pool's reset only rolls back, it does not restore autocommit -- every
    later test on that connection would run without a transaction, and a
    rollback test would prove nothing.
    """
    from contextlib import contextmanager

    @contextmanager
    def _cm():
        raw = db.engine.raw_connection()
        raw.driver_connection.autocommit = True
        try:
            yield raw.driver_connection
        finally:
            raw.driver_connection.autocommit = False
            raw.close()
    return _cm()


def _run_sql_file(connection, relative_path):
    with open(os.path.join(REPO_ROOT, relative_path), encoding='utf-8') as fh:
        sql = fh.read()
    with connection.cursor() as cur:
        cur.execute(sql)


def _create_pg_schema(db):
    """Build the PostgreSQL test schema the way production does (see above)."""
    _drop_pg_schema(db)
    with _autocommit_connection(db) as conn:
        with conn.cursor() as cur:
            # Roles the init scripts GRANT to (postgres/init.sql creates them in
            # production; it needs psql variables, so only its effect is copied).
            for role in ('marketplace_app', 'marketplace_audit'):
                cur.execute(
                    "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = %s) "
                    "THEN EXECUTE format('CREATE ROLE %%I NOLOGIN', %s); END IF; END $$",
                    (role, role))
            cur.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
            cur.execute('CREATE EXTENSION IF NOT EXISTS pgcrypto')
            # The live database runs its sessions in Europe/Berlin. Naive-UTC
            # bugs only show in a zone that is not UTC.
            cur.execute('SELECT current_database()')
            dbname = cur.fetchone()[0]
            cur.execute(f'ALTER DATABASE "{dbname}" SET timezone TO \'Europe/Berlin\'')
        for path in PG_INIT_SCRIPTS:
            _run_sql_file(conn, path)

    db.create_all()
    db.session.commit()

    with _autocommit_connection(db) as conn:
        for path in PG_MIGRATIONS:
            _run_sql_file(conn, path)

    # Fresh connections for the tests: they pick up the database's time zone,
    # and none of them has been through the DDL above.
    db.session.remove()
    db.engine.dispose()


def _drop_pg_schema(db):
    with _autocommit_connection(db) as conn:
        with conn.cursor() as cur:
            cur.execute('DROP SCHEMA IF EXISTS public CASCADE')
            cur.execute('CREATE SCHEMA public')


def aware_utcnow():
    """
    The current time as a timezone-AWARE UTC value -- for writing into the
    audit tables, whose timestamp columns are TIMESTAMPTZ.

    A naive utcnow() is read as session-local time by PostgreSQL. The live
    database (and the PostgreSQL suite) runs its sessions in Europe/Berlin, so
    a naive value lands one hour in the past in winter and two in summer --
    outside a one-hour scan window. SQLite has no time zones and never showed
    it. The app itself leaves these columns to DEFAULT NOW().
    """
    from datetime import timezone
    return datetime.now(timezone.utc)


def reload_user(user_id):
    """
    Re-read a user in the *current* app context.

    Flask-SQLAlchemy scopes db.session to the app context and drops it on
    teardown, so an object created by a fixture (or written during an HTTP
    request) is stale or attached to a different session. Tests that mutate or
    assert on persisted state must go through this.
    """
    from app import db
    from app.models.user import User

    db.session.expire_all()
    return db.session.get(User, user_id)


class QueryCounter:
    """
    Counts SQL statements issued inside a `with` block.

    Used to pin down N+1 regressions: an endpoint whose query count grows with
    the number of rows will fail the corresponding assertion.
    """

    def __init__(self):
        self.statements = []

    @property
    def count(self):
        return len(self.statements)

    def __enter__(self):
        from sqlalchemy import event
        from app import db

        self._engine = db.engine

        def _record(conn, cursor, statement, parameters, context, executemany):
            self.statements.append(statement)

        self._listener = _record
        event.listen(self._engine, 'before_cursor_execute', _record)
        return self

    def __exit__(self, *exc):
        from sqlalchemy import event

        event.remove(self._engine, 'before_cursor_execute', self._listener)
        return False


@pytest.fixture
def query_counter():
    """Factory for QueryCounter context managers."""
    return QueryCounter


@pytest.fixture(scope='function')
def db_session(app):
    """Create a fresh database session for each test."""
    from app import db

    with app.app_context():
        db.create_all()
        yield db.session
        db.session.rollback()
        db.drop_all()


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Create CLI test runner."""
    return app.test_cli_runner()


@pytest.fixture
def sample_user(app):
    """Create a sample buyer user."""
    from app import db
    from app.models.user import User

    with app.app_context():
        suffix = uuid.uuid4().hex[:8]
        user = User(
            id=uuid.uuid4(),
            username=f'testbuyer_{suffix}',
            email=f'buyer_{suffix}@test.local',
            role='buyer',
            is_active=True,
            is_verified=True,
        )
        user.set_password('TestPassword123!')
        db.session.add(user)
        db.session.commit()
        yield user
        # Cleanup
        try:
            db.session.delete(user)
            db.session.commit()
        except Exception:
            db.session.rollback()


@pytest.fixture
def sample_vendor(app):
    """Create a sample approved vendor user."""
    from app import db
    from app.models.user import User

    with app.app_context():
        suffix = uuid.uuid4().hex[:8]
        vendor = User(
            id=uuid.uuid4(),
            username=f'testvendor_{suffix}',
            email=f'vendor_{suffix}@test.local',
            role='vendor',
            is_active=True,
            is_verified=True,
            is_vendor_approved=True,
        )
        vendor.set_password('TestPassword123!')
        db.session.add(vendor)
        db.session.commit()
        yield vendor
        try:
            db.session.delete(vendor)
            db.session.commit()
        except Exception:
            db.session.rollback()


@pytest.fixture
def sample_admin(app):
    """Create a sample admin user."""
    from app import db
    from app.models.user import User

    with app.app_context():
        suffix = uuid.uuid4().hex[:8]
        admin = User(
            id=uuid.uuid4(),
            username=f'testadmin_{suffix}',
            email=f'admin_{suffix}@test.local',
            role='admin',
            is_active=True,
            is_verified=True,
        )
        admin.set_password('AdminPassword123!')
        db.session.add(admin)
        db.session.commit()
        yield admin
        try:
            db.session.delete(admin)
            db.session.commit()
        except Exception:
            db.session.rollback()


@pytest.fixture
def auth_client(client, sample_user):
    """Create an authenticated test client (buyer)."""
    with client.session_transaction() as sess:
        sess['_user_id'] = sample_user.get_id()
    return client


@pytest.fixture
def vendor_client(client, sample_vendor):
    """Create an authenticated vendor test client."""
    with client.session_transaction() as sess:
        sess['_user_id'] = sample_vendor.get_id()
    return client


@pytest.fixture
def admin_client(client, sample_admin):
    """Create an authenticated admin test client."""
    with client.session_transaction() as sess:
        sess['_user_id'] = sample_admin.get_id()
    return client


@pytest.fixture
def mock_audit(monkeypatch):
    """Mock all audit service calls to avoid PostgreSQL stored procedure calls."""
    mock_log_auth = MagicMock()
    mock_log_security = MagicMock()
    mock_log_admin = MagicMock()
    mock_log_pgp = MagicMock()

    monkeypatch.setattr('app.services.audit_service.log_auth_event', mock_log_auth)
    monkeypatch.setattr('app.services.audit_service.log_security_event', mock_log_security)
    monkeypatch.setattr('app.services.audit_service.log_admin_action', mock_log_admin)
    monkeypatch.setattr('app.services.audit_service.log_pgp_key_event', mock_log_pgp)

    return {
        'auth': mock_log_auth,
        'security': mock_log_security,
        'admin': mock_log_admin,
        'pgp': mock_log_pgp,
    }
