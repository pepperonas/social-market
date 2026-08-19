"""
Regression tests for two-factor authentication.

Each test here pins a bug that was found in review:
  * enabling 2FA on GET (locked users out of their own account)
  * the verification branch being unreachable dead code
  * deactivated/locked accounts logging in through the 2FA detour
  * TOTP codes being replayable inside their validity window
"""

import uuid
from unittest.mock import patch

import pyotp
import pytest


@pytest.fixture
def totp_user(app):
    """A buyer with a 2FA secret provisioned but 2FA not yet enabled."""
    from app import db
    from app.models.user import User

    # Unique per test: Flask reuses an already-active app context for requests,
    # so all tests share one SQLAlchemy session and its identity map. Recycling
    # a username let a later test authenticate as an earlier, already-deleted user.
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=uuid.uuid4(),
        username=f'totpuser_{suffix}',
        email=f'totp_{suffix}@test.local',
        role='buyer',
        is_active=True,
        is_verified=True,
    )
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    yield user
    try:
        db.session.delete(user)
        db.session.commit()
    except Exception:
        db.session.rollback()


PASSWORD = 'TestPassword123!'


def _login_as(client, user):
    """
    Log in through the real login route.

    Forging the session by writing `_user_id` directly is unreliable here:
    Flask-Login runs with session_protection='strong' and drops a session whose
    identifier does not match, which showed up as sporadic 302s depending on
    test order.
    """
    response = client.post('/auth/login',
                           data={'username': user.username, 'password': PASSWORD},
                           follow_redirects=False)
    assert response.status_code in (302, 303), 'login should redirect'
    return response


def _reload(user_id):
    """
    Re-read a user from the database.

    Flask-SQLAlchemy tears down its session when the per-request app context
    pops, so an object held by a fixture is stale after an HTTP request. Tests
    that assert on state written during a request must re-read it.
    """
    from app import db
    from app.models.user import User

    db.session.expire_all()
    return db.session.get(User, user_id)


class TestEnrolment:
    """Enabling 2FA must require proof that the user holds the secret."""

    @patch('app.routes.auth._log_auth_event')
    def test_get_does_not_enable_2fa(self, mock_log, client, totp_user, app):
        """
        Opening the setup page must NOT switch 2FA on.

        Regression: enable_two_factor() set the flag and committed while merely
        rendering the QR code, so abandoning the page locked the user out.
        """
        user_id = totp_user.id
        _login_as(client, totp_user)
        response = client.get('/auth/profile/2fa/enable')

        assert response.status_code == 200
        user = _reload(user_id)
        assert user.two_factor_secret is not None, 'a secret should be provisioned'
        assert user.two_factor_enabled is False, '2FA must stay off until verified'

    @patch('app.routes.auth._log_auth_event')
    def test_valid_code_enables_2fa(self, mock_log, client, totp_user, app):
        """The verification branch must be reachable and actually enable 2FA."""
        user_id = totp_user.id
        # Provision directly; the GET path is covered by the test above. Keeping
        # this test independent of a preceding request makes it order-robust.
        totp_user.begin_two_factor_setup()
        secret = totp_user.two_factor_secret
        assert secret is not None

        _login_as(client, totp_user)
        response = client.post('/auth/profile/2fa/enable',
                               data={'token': pyotp.TOTP(secret).now()},
                               follow_redirects=True)

        assert response.status_code == 200
        assert _reload(user_id).two_factor_enabled is True

    @patch('app.routes.auth._log_auth_event')
    def test_invalid_code_does_not_enable_2fa(self, mock_log, client, totp_user, app):
        user_id = totp_user.id
        totp_user.begin_two_factor_setup()

        _login_as(client, totp_user)
        response = client.post('/auth/profile/2fa/enable',
                               data={'token': '000000'}, follow_redirects=True)

        assert response.status_code == 200
        assert _reload(user_id).two_factor_enabled is False
        assert b'Invalid verification code' in response.data


class TestInactiveAccountCannotUse2FA:
    """Deactivation must not be bypassable through the 2FA detour."""

    @patch('app.routes.auth._log_auth_event')
    def test_deactivated_user_with_2fa_cannot_login(self, mock_log, client, totp_user, app):
        """
        Regression: login() checked two_factor_enabled BEFORE is_active, so a
        deactivated account was redirected to verify_2fa and logged in there.
        """
        from app import db

        totp_user.two_factor_secret = pyotp.random_base32()
        totp_user.two_factor_enabled = True
        totp_user.is_active = False
        db.session.commit()

        response = client.post('/auth/login', data={
            'username': totp_user.username,
            'password': PASSWORD,
        }, follow_redirects=False)

        # Must not hand the user over to the 2FA step
        assert '/auth/verify-2fa' not in response.headers.get('Location', '')
        with client.session_transaction() as sess:
            assert 'pending_2fa_user_id' not in sess

    @patch('app.routes.auth._log_auth_event')
    def test_verify_2fa_rejects_deactivated_user(self, mock_log, client, totp_user, app):
        """verify_2fa must re-check: the account can change after the password step."""
        from app import db

        secret = pyotp.random_base32()
        totp_user.two_factor_secret = secret
        totp_user.two_factor_enabled = True
        totp_user.is_active = True
        db.session.commit()

        # Reach the pending-2FA state legitimately...
        client.post('/auth/login', data={
            'username': totp_user.username,
            'password': PASSWORD,
        })

        # ...then the account gets deactivated
        user = _reload(totp_user.id)
        user.is_active = False
        db.session.commit()

        response = client.post('/auth/verify-2fa',
                               data={'token': pyotp.TOTP(secret).now()},
                               follow_redirects=False)

        assert response.status_code in (302, 303)
        assert '/auth/login' in response.headers.get('Location', '')
        with client.session_transaction() as sess:
            assert '_user_id' not in sess, 'must not be logged in'


class TestTotpReplay:
    """A code must not be usable twice inside its validity window."""

    def test_code_cannot_be_replayed(self, totp_user, app):
        from app import db

        totp_user.two_factor_secret = pyotp.random_base32()
        totp_user.two_factor_enabled = True
        db.session.commit()

        token = pyotp.TOTP(totp_user.two_factor_secret).now()

        assert totp_user.verify_totp(token) is True, 'first use must succeed'
        assert totp_user.verify_totp(token) is False, 'replay must be rejected'

    def test_wrong_code_rejected(self, totp_user, app):
        from app import db

        totp_user.two_factor_secret = pyotp.random_base32()
        totp_user.two_factor_enabled = True
        db.session.commit()

        assert totp_user.verify_totp('000000') is False

    def test_disabled_2fa_rejects_valid_code(self, totp_user, app):
        from app import db

        totp_user.two_factor_secret = pyotp.random_base32()
        totp_user.two_factor_enabled = False
        db.session.commit()

        token = pyotp.TOTP(totp_user.two_factor_secret).now()
        assert totp_user.verify_totp(token) is False
