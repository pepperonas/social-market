"""
Test fixtures for Social Market application.
Uses SQLite in-memory database to avoid PostgreSQL dependency in tests.
"""

import os
import uuid
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

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
        # Create all tables (SQLite-compatible subset)
        _create_sqlite_tables(db)
        yield app
        db.drop_all()


def _create_sqlite_tables(db):
    """
    Create tables compatible with SQLite for testing.
    PostgreSQL-specific types (UUID, INET) are handled by SQLAlchemy's
    dialect adaptation.
    """
    from sqlalchemy import event, text

    # Monkeypatch UUID columns to work with SQLite (stored as strings)
    db.create_all()

    # Create stub stored procedures as no-ops (SQLite doesn't support them)
    # Tests that call these will mock the db.session.execute calls


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
        user = User(
            id=uuid.uuid4(),
            username='testbuyer',
            email='buyer@test.local',
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
        vendor = User(
            id=uuid.uuid4(),
            username='testvendor',
            email='vendor@test.local',
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
        admin = User(
            id=uuid.uuid4(),
            username='testadmin',
            email='admin@test.local',
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
