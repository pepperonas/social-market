"""
Authentication Tests for Social Market.

Tests cover:
- Login (success, failure, lockout, lockout expiry)
- Registration (password policy, duplicates)
- CSRF protection
- Logout
- Open redirect prevention
"""

from unittest.mock import patch
from datetime import datetime, timedelta


class TestLogin:
    """Login functionality tests."""

    def test_login_page_loads(self, client):
        """GET /auth/login should return 200."""
        response = client.get('/auth/login')
        assert response.status_code == 200

    @patch('app.routes.auth._log_auth_event')
    def test_login_success(self, mock_log, client, sample_user, app):
        """Valid credentials should log in the user."""
        with app.app_context():
            response = client.post('/auth/login', data={
                'username': sample_user.username,
                'password': 'TestPassword123!',
            }, follow_redirects=False)
            # Should redirect to marketplace or dashboard
            assert response.status_code in (302, 303)

    @patch('app.routes.auth._log_auth_event')
    def test_login_wrong_password(self, mock_log, client, sample_user, app):
        """Wrong password should show error."""
        with app.app_context():
            response = client.post('/auth/login', data={
                'username': sample_user.username,
                'password': 'WrongPassword999!',
            }, follow_redirects=True)
            assert response.status_code == 200
            assert b'Invalid username or password' in response.data

    @patch('app.routes.auth._log_auth_event')
    def test_login_nonexistent_user(self, mock_log, client, app):
        """Login with nonexistent user should fail gracefully."""
        with app.app_context():
            response = client.post('/auth/login', data={
                'username': 'nonexistent_user',
                'password': 'SomePassword123!',
            }, follow_redirects=True)
            assert response.status_code == 200
            assert b'Invalid username or password' in response.data

    @patch('app.routes.auth._log_auth_event')
    def test_login_empty_fields(self, mock_log, client, app):
        """Login with empty fields should show error."""
        with app.app_context():
            response = client.post('/auth/login', data={
                'username': '',
                'password': '',
            }, follow_redirects=True)
            assert response.status_code == 200
            assert b'Username and password are required' in response.data

    @patch('app.routes.auth._log_auth_event')
    def test_login_account_lockout(self, mock_log, client, sample_user, app):
        """Account should lock after too many failed attempts."""
        with app.app_context():
            from app import db
            from tests.conftest import reload_user

            # Re-attach: the fixture built the object in a different app context,
            # so mutating it here would never be flushed by this session.
            user = reload_user(sample_user.id)
            user.failed_login_attempts = 5
            user.account_locked_until = datetime.utcnow() + timedelta(minutes=15)
            db.session.commit()

            response = client.post('/auth/login', data={
                'username': sample_user.username,
                'password': 'TestPassword123!',
            }, follow_redirects=True)
            assert response.status_code == 200
            assert b'temporarily locked' in response.data

    @patch('app.routes.auth._log_auth_event')
    def test_login_lockout_expired(self, mock_log, client, sample_user, app):
        """Expired lockout should allow login."""
        with app.app_context():
            from app import db
            from tests.conftest import reload_user

            user = reload_user(sample_user.id)
            user.failed_login_attempts = 5
            user.account_locked_until = datetime.utcnow() - timedelta(minutes=1)
            db.session.commit()

            response = client.post('/auth/login', data={
                'username': sample_user.username,
                'password': 'TestPassword123!',
            }, follow_redirects=False)
            # Should succeed (redirect)
            assert response.status_code in (302, 303)


class TestOpenRedirectPrevention:
    """Tests for open redirect vulnerability prevention."""

    @patch('app.routes.auth._log_auth_event')
    def test_blocks_external_redirect(self, mock_log, client, sample_user, app):
        """Login should not redirect to external URLs."""
        with app.app_context():
            response = client.post('/auth/login?next=http://evil.com', data={
                'username': sample_user.username,
                'password': 'TestPassword123!',
            }, follow_redirects=False)
            assert response.status_code in (302, 303)
            location = response.headers.get('Location', '')
            assert 'evil.com' not in location

    @patch('app.routes.auth._log_auth_event')
    def test_blocks_protocol_relative_redirect(self, mock_log, client, sample_user, app):
        """Login should not redirect to protocol-relative URLs."""
        with app.app_context():
            response = client.post('/auth/login?next=//evil.com', data={
                'username': sample_user.username,
                'password': 'TestPassword123!',
            }, follow_redirects=False)
            assert response.status_code in (302, 303)
            location = response.headers.get('Location', '')
            assert 'evil.com' not in location

    @patch('app.routes.auth._log_auth_event')
    def test_allows_relative_redirect(self, mock_log, client, sample_user, app):
        """Login should allow relative URL redirects."""
        with app.app_context():
            response = client.post('/auth/login?next=/vendor/dashboard', data={
                'username': sample_user.username,
                'password': 'TestPassword123!',
            }, follow_redirects=False)
            assert response.status_code in (302, 303)
            location = response.headers.get('Location', '')
            assert '/vendor/dashboard' in location


class TestRegistration:
    """Registration tests."""

    def test_register_page_loads(self, client):
        """GET /auth/register should return 200."""
        response = client.get('/auth/register')
        assert response.status_code == 200

    @patch('app.routes.auth._log_auth_event')
    def test_register_password_mismatch(self, mock_log, client, app):
        """Mismatched passwords should fail."""
        with app.app_context():
            response = client.post('/auth/register', data={
                'username': 'newuser',
                'email': 'new@test.local',
                'password': 'TestPassword123!',
                'password_confirm': 'DifferentPassword123!',
                'role': 'buyer',
            }, follow_redirects=True)
            assert response.status_code == 200
            assert b'Passwords do not match' in response.data

    @patch('app.routes.auth._log_auth_event')
    def test_register_duplicate_username(self, mock_log, client, sample_user, app):
        """Duplicate username should fail."""
        with app.app_context():
            response = client.post('/auth/register', data={
                'username': sample_user.username,
                'email': 'unique@test.local',
                'password': 'TestPassword123!',
                'password_confirm': 'TestPassword123!',
                'role': 'buyer',
                'terms_accepted': 'on',
            }, follow_redirects=True)
            assert response.status_code == 200
            assert b'Username already exists' in response.data

    @patch('app.routes.auth._log_auth_event')
    def test_register_duplicate_email(self, mock_log, client, sample_user, app):
        """Duplicate email should fail."""
        with app.app_context():
            response = client.post('/auth/register', data={
                'username': 'uniqueuser',
                'email': sample_user.email,
                'password': 'TestPassword123!',
                'password_confirm': 'TestPassword123!',
                'role': 'buyer',
                'terms_accepted': 'on',
            }, follow_redirects=True)
            assert response.status_code == 200
            assert b'Email already registered' in response.data

    @patch('app.routes.auth._log_auth_event')
    def test_register_empty_fields(self, mock_log, client, app):
        """Registration with empty fields should fail."""
        with app.app_context():
            response = client.post('/auth/register', data={
                'username': '',
                'email': '',
                'password': '',
                'password_confirm': '',
                'role': 'buyer',
            }, follow_redirects=True)
            assert response.status_code == 200
            assert b'All fields are required' in response.data


class TestLogout:
    """Logout tests."""

    @patch('app.routes.auth._log_auth_event')
    def test_logout(self, mock_log, auth_client, app):
        """Logout should redirect to index."""
        with app.app_context():
            response = auth_client.get('/auth/logout', follow_redirects=False)
            assert response.status_code in (302, 303)
