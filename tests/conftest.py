"""
Test fixtures for Social Market application.
Uses SQLite in-memory database to avoid PostgreSQL dependency in tests.
"""

import os
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


@pytest.fixture(scope='session')
def app():
    """Create application for testing."""
    from app import create_app, db

    app = create_app('testing')
    app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'WTF_CSRF_ENABLED': False,
        'SERVER_NAME': 'localhost',
        'RATELIMIT_ENABLED': False,
        'SESSION_TYPE': 'filesystem',
        'PASSWORD_PEPPER': 'a' * 64,
        'REDIS_URL': 'redis://localhost:6379/0',
    })

    with app.app_context():
        _create_sqlite_tables(db)

    yield app

    with app.app_context():
        db.drop_all()


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
        transaction_id VARCHAR(36), buyer_id VARCHAR(36) NOT NULL,
        vendor_id VARCHAR(36) NOT NULL, product_id VARCHAR(36),
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
            lambda: datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
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
        sess['_user_id'] = str(sample_user.id)
    return client


@pytest.fixture
def vendor_client(client, sample_vendor):
    """Create an authenticated vendor test client."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(sample_vendor.id)
    return client


@pytest.fixture
def admin_client(client, sample_admin):
    """Create an authenticated admin test client."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(sample_admin.id)
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
