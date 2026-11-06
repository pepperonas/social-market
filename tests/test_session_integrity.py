"""
Review round 3 (2026-11), authentication and account findings.

Every class here pins one defect from docs/REVIEW-2026-11.md. Each test was seen
red against the unfixed code before the fix went in.

The common thread: a login is more than the moment the password is checked.
Deactivating an account, changing a password, or turning 2FA off all have to
reach the sessions that already exist -- in this browser, in the other browser,
and in the remember-me cookie that outlives both.
"""

import pathlib
import re
import uuid
from unittest.mock import patch

import pyotp
import pytest

PASSWORD = 'TestPassword123!'
NEW_PASSWORD = 'Another-Passw0rd!x'


# =============================================================================
# Helpers
# =============================================================================

def _login(client, user, password=PASSWORD, **extra):
    response = client.post('/auth/login',
                           data={'username': user.username, 'password': password, **extra},
                           follow_redirects=False)
    assert response.status_code in (302, 303), 'login should redirect'
    return response


def _reload(user_id):
    from app import db
    from app.models.user import User

    db.session.expire_all()
    return db.session.get(User, user_id)


def _is_logged_in(client):
    """A protected page answers 200 when logged in and redirects to login otherwise."""
    response = client.get('/auth/profile', follow_redirects=False)
    return response.status_code == 200


def _code_only(path):
    """Source without comments and docstrings -- the docs quote removed code."""
    source = pathlib.Path(path).read_text()
    source = re.sub(r'"""[\s\S]*?"""', '', source)
    return re.sub(r'#.*', '', source)


@pytest.fixture
def second_client(app):
    """Another browser: same user, separate cookie jar."""
    return app.test_client()


@pytest.fixture
def twofa_user(app):
    from app import db
    from app.models.user import User

    suffix = uuid.uuid4().hex[:8]
    user = User(id=uuid.uuid4(), username=f'tfa_{suffix}', email=f'tfa_{suffix}@test.local',
                role='buyer', is_active=True, is_verified=True)
    user.set_password(PASSWORD)
    user.two_factor_secret = pyotp.random_base32()
    user.two_factor_enabled = True
    db.session.add(user)
    db.session.commit()
    yield user
    try:
        db.session.delete(user)
        db.session.commit()
    except Exception:
        db.session.rollback()


# =============================================================================
# K3 -- existing sessions must not outlive the account state they were made for
# =============================================================================

class TestDeactivationEndsSessions:
    """
    `is_active` was checked at login and nowhere else. The user loader returned
    the user unconditionally, so an admin deactivating an account changed nothing
    for a session that was already open -- including a deactivated admin's.
    """

    def test_deactivated_user_is_logged_out_on_next_request(self, client, sample_user):
        from app import db

        _login(client, sample_user)
        assert _is_logged_in(client)

        user = _reload(sample_user.id)
        user.is_active = False
        db.session.commit()

        assert not _is_logged_in(client)


class TestPasswordChangeEndsOtherSessions:
    """
    Changing the password left every other session alive unless a checkbox --
    unchecked by default -- was ticked. The usual reason to change a password is
    that someone else might have it; their session is exactly the one to end.
    """

    def _change(self, client):
        return client.post('/account/change-password', data={
            'current_password': PASSWORD,
            'new_password': NEW_PASSWORD,
            'confirm_password': NEW_PASSWORD,
        }, follow_redirects=False)

    def test_other_browser_is_logged_out(self, client, second_client, sample_user):
        _login(client, sample_user)
        _login(second_client, sample_user)
        assert _is_logged_in(second_client)

        self._change(client)

        assert not _is_logged_in(second_client)

    def test_the_browser_that_changed_it_stays_logged_in(self, client, sample_user):
        _login(client, sample_user)

        response = self._change(client)

        assert response.status_code in (302, 303)
        assert _is_logged_in(client)

    def test_old_session_identifier_no_longer_loads_the_user(self, app, sample_user):
        """
        Covers the remember-me cookie too: it stores the same identifier that
        the session does (`get_id()`), and both go through the user loader.
        """
        from app import db, login_manager

        old_id = sample_user.get_id()
        assert login_manager._user_callback(old_id) is not None

        user = _reload(sample_user.id)
        user.set_password(NEW_PASSWORD)
        db.session.commit()

        assert login_manager._user_callback(old_id) is None
        assert login_manager._user_callback(_reload(sample_user.id).get_id()) is not None

    def test_terminate_all_sessions_ends_the_other_browser(self, client, second_client, sample_user):
        _login(client, sample_user)
        _login(second_client, sample_user)

        client.post('/account/sessions/terminate-all')

        assert not _is_logged_in(second_client)
        assert _is_logged_in(client)


class TestRememberCookie:
    """
    REMEMBER_COOKIE_* was never configured, so Flask-Login's defaults applied:
    valid for 365 days, sent over plain HTTP, no SameSite.
    """

    def test_remember_cookie_is_hardened(self, app):
        from datetime import timedelta

        assert app.config.get('REMEMBER_COOKIE_HTTPONLY') is True
        assert app.config.get('REMEMBER_COOKIE_SAMESITE') == 'Lax'
        assert 'REMEMBER_COOKIE_SECURE' in app.config
        assert app.config.get('REMEMBER_COOKIE_DURATION') <= timedelta(days=30)


class TestSessionIdRotatesOnLogin:
    """
    The session id carried over from before the login. Anyone who could plant
    a session id in the victim's browser beforehand (session fixation) would
    share the authenticated session afterwards.
    """

    @staticmethod
    def _sid(client):
        cookie = client.get_cookie('marketplace_session')
        return cookie.value if cookie else None

    def test_session_id_changes_on_login(self, client, sample_user):
        with client.session_transaction() as sess:
            sess['planted'] = 'before-login'
        before = self._sid(client)
        assert before

        _login(client, sample_user)

        assert self._sid(client) != before

    @patch('app.routes.auth._log_auth_event')
    def test_session_id_changes_after_2fa(self, mock_log, client, twofa_user):
        _login(client, twofa_user)  # -> pending 2FA, session already exists
        before = self._sid(client)

        client.post('/auth/verify-2fa',
                    data={'token': pyotp.TOTP(twofa_user.two_factor_secret).now()})

        assert _is_logged_in(client)
        assert self._sid(client) != before


# =============================================================================
# Profile form
# =============================================================================

class TestEditProfile:
    """
    The template posted `email`, `current_password` and `new_password`; the route
    read `display_name` and `bio`. Every save therefore blanked both fields,
    ignored what the user had typed, and flashed "Profile updated successfully".
    """

    def test_form_posts_the_fields_the_route_reads(self, client, sample_user):
        _login(client, sample_user)
        html = client.get('/auth/profile/edit').get_data(as_text=True)
        names = set(re.findall(r'name="([a-z_]+)"', html))

        assert {'display_name', 'bio'} <= names
        assert not names & {'email', 'current_password', 'new_password'}, (
            'the route does not read these; a field it ignores is a promise it breaks'
        )

    def test_saving_keeps_what_was_typed(self, client, sample_user):
        _login(client, sample_user)
        client.post('/auth/profile/edit', data={'display_name': 'Bob', 'bio': 'Hello'})

        user = _reload(sample_user.id)
        assert (user.display_name, user.bio) == ('Bob', 'Hello')

    def test_overlong_display_name_is_refused_not_a_500(self, client, sample_user):
        _login(client, sample_user)
        response = client.post('/auth/profile/edit',
                               data={'display_name': 'x' * 500, 'bio': ''})

        assert response.status_code == 200
        assert _reload(sample_user.id).display_name != 'x' * 500


# =============================================================================
# Two-factor authentication
# =============================================================================

class TestTwoFactorBruteForce:
    """
    Wrong 2FA codes did not count towards the account lockout; only a per-IP
    rate limit stood between a stolen password and the 1-in-a-million code.
    """

    @patch('app.routes.auth._log_auth_event')
    def test_wrong_codes_lock_the_account(self, mock_log, app, client, twofa_user):
        _login(client, twofa_user)
        limit = app.config['MAX_FAILED_LOGIN_ATTEMPTS']

        for _ in range(limit):
            client.post('/auth/verify-2fa', data={'token': '000000'})

        assert _reload(twofa_user.id).is_account_locked()

    @patch('app.routes.auth._log_auth_event')
    def test_locked_account_cannot_finish_2fa(self, mock_log, app, client, twofa_user):
        _login(client, twofa_user)
        for _ in range(app.config['MAX_FAILED_LOGIN_ATTEMPTS']):
            client.post('/auth/verify-2fa', data={'token': '000000'})

        client.post('/auth/verify-2fa',
                    data={'token': pyotp.TOTP(twofa_user.two_factor_secret).now()})

        assert not _is_logged_in(client)


class TestTotpInputValidation:
    """
    hmac.compare_digest raises TypeError for non-ASCII str, and the form value
    went in unchecked: a code like '１２３４５６' (full-width digits) was a 500.
    """

    def test_non_ascii_code_is_rejected_not_raised(self, twofa_user):
        assert twofa_user.verify_totp('１２３４５６') is False

    @patch('app.routes.auth._log_auth_event')
    def test_non_ascii_code_over_http(self, mock_log, client, twofa_user):
        _login(client, twofa_user)
        response = client.post('/auth/verify-2fa', data={'token': 'ü23456'})

        assert response.status_code == 200


class TestQrCodeRenders:
    """The route passed raw base64 to `<img src=...>`; the QR code never showed."""

    def test_qr_is_a_data_uri(self, client, sample_user):
        _login(client, sample_user)
        html = client.get('/auth/profile/2fa/enable').get_data(as_text=True)

        match = re.search(r'<img src="([^"]+)" alt="QR Code"', html)
        assert match
        assert match.group(1).startswith('data:image/png;base64,')


class TestTwoFactorCanBeTurnedOff:
    """
    The disable route existed, but no page linked to it -- and it asked only for
    the password, which is exactly the factor 2FA is meant not to rely on alone.
    """

    def test_security_page_offers_disable_when_enabled(self, client, twofa_user):
        from app import db

        user = _reload(twofa_user.id)
        user.two_factor_enabled = False
        db.session.commit()
        _login(client, twofa_user)
        user = _reload(twofa_user.id)
        user.two_factor_enabled = True
        db.session.commit()

        html = client.get('/account/security').get_data(as_text=True)
        assert 'action="/auth/profile/2fa/disable"' in html

    def test_disable_requires_a_current_code(self, client, twofa_user):
        from app import db

        user = _reload(twofa_user.id)
        user.two_factor_enabled = False
        db.session.commit()
        _login(client, twofa_user)
        user = _reload(twofa_user.id)
        user.two_factor_enabled = True
        db.session.commit()

        client.post('/auth/profile/2fa/disable', data={'password': PASSWORD})
        assert _reload(twofa_user.id).two_factor_enabled is True

        client.post('/auth/profile/2fa/disable', data={
            'password': PASSWORD,
            'token': pyotp.TOTP(twofa_user.two_factor_secret).now(),
        })
        assert _reload(twofa_user.id).two_factor_enabled is False


class TestDeleteAccountWith2FA:
    def test_delete_requires_a_code_when_2fa_is_on(self, client, twofa_user):
        from app import db

        user = _reload(twofa_user.id)
        user.two_factor_enabled = False
        db.session.commit()
        _login(client, twofa_user)
        user = _reload(twofa_user.id)
        user.two_factor_enabled = True
        db.session.commit()

        client.post('/account/delete-account', data={
            'password': PASSWORD,
            'confirmation': f'DELETE {twofa_user.username}',
        })

        assert _reload(twofa_user.id).is_active is True


# =============================================================================
# Rate limits on pages that only display a form
# =============================================================================

class TestRateLimitsCountOnlySubmissions:
    """
    `@limiter.limit("5 per hour")` on change_password counted GET as well:
    opening the page five times locked the user out of changing their password
    for an hour. Checked at the decorator, because the limiter cannot be switched
    on after the app was built: Flask-Limiter reads RATELIMIT_ENABLED once, in
    init_app. (That is also why the media "not rate limited" test is blind --
    see docs/REVIEW-2026-11.md.)
    """

    @pytest.mark.parametrize('path, view', [
        ('app/routes/account.py', 'change_password'),
        ('app/routes/account.py', 'delete_account'),
        ('app/routes/auth.py', 'verify_2fa'),
    ])
    def test_limit_applies_to_post_only(self, path, view):
        source = _code_only(path)
        head = source[:source.index(f'def {view}(')].rstrip('\n').split('\n')
        decorators = []
        while head and head[-1].startswith('@'):
            decorators.append(head.pop())
        limits = [d for d in decorators if d.startswith('@limiter.limit(')]

        assert limits, f'{view} should be rate limited'
        for limit in limits:
            assert "methods=['POST']" in limit, (
                f'{view}: the limit must count submissions, not page views: {limit}'
            )


# =============================================================================
# Generated PGP keys
# =============================================================================

class TestGeneratedPrivateKeyLeavesTheSession:
    """
    The UI promised the private key was "not stored on the server". It sat in the
    Redis-backed session until the session expired, downloaded or not.
    """

    def test_private_key_is_dropped_after_download(self, client, sample_user):
        _login(client, sample_user)
        with client.session_transaction() as sess:
            sess['generated_keys'] = {
                'public_key': 'PUB', 'private_key': 'PRIV', 'keyid': 'ABCD',
                'fingerprint': 'F' * 40, 'key_length': 4096, 'created_at': 'now',
                'success': True, 'warning': '',
            }

        response = client.get('/auth/download-key/private')
        assert response.get_data(as_text=True) == 'PRIV'

        with client.session_transaction() as sess:
            assert 'PRIV' not in str(sess.get('generated_keys'))


# =============================================================================
# Username enumeration
# =============================================================================

class TestLoginDoesNotRevealAccounts:
    """
    "Account is temporarily locked" was shown before the password was checked,
    so it confirmed that a username exists to anyone who typed it. And an
    unknown username skipped Argon2 entirely, which a stopwatch can tell apart.
    """

    @staticmethod
    def _flash(html):
        return re.findall(r'class="alert[^"]*"[^>]*>\s*(.*?)\s*<', html, re.S)

    def _locked_login(self, client, user, password):
        from datetime import timedelta

        from app import db
        from app.timeutil import utcnow

        locked = _reload(user.id)
        locked.account_locked_until = utcnow() + timedelta(minutes=15)
        db.session.commit()
        return client.post('/auth/login', data={
            'username': user.username, 'password': password,
        }).get_data(as_text=True)

    def test_locked_account_answers_the_same_for_right_and_wrong_password(self, app, sample_user):
        """
        No password oracle during a lock.

        Attempts made while an account is locked are not counted. The first fix
        for the enumeration finding showed "locked" only for a correct password
        -- so guessing could continue through the lockout and the right guess was
        announced. (Caught by an automated security review of that commit.)
        """
        right = self._locked_login(app.test_client(), sample_user, PASSWORD)
        wrong = self._locked_login(app.test_client(), sample_user, 'wrong-password')

        assert self._flash(right) == self._flash(wrong)
        assert 'locked' not in ' '.join(self._flash(right)).lower().replace('sign-in is paused', '')

    def test_unknown_user_gets_the_same_answer(self, app, sample_user):
        wrong = self._locked_login(app.test_client(), sample_user, 'wrong-password')
        unknown = app.test_client().post('/auth/login', data={
            'username': f'nobody_{uuid.uuid4().hex[:8]}', 'password': 'whatever',
        }).get_data(as_text=True)

        assert self._flash(unknown) == self._flash(wrong)

    def test_unknown_user_still_costs_a_hash_verification(self, client):
        with patch('app.routes.auth.burn_password_check') as burn:
            client.post('/auth/login', data={
                'username': f'nobody_{uuid.uuid4().hex[:8]}', 'password': 'whatever',
            })

        assert burn.called


class TestReauthFormsCountTowardsLockout:
    """
    Turning off 2FA, changing the password and deleting the account re-check
    secrets for someone who already holds a session -- the position of whoever
    stole one. Wrong guesses there were not counted, and disable_2fa had no rate
    limit, so the forms were a guessing machine behind the login. (Found by an
    automated security review of the step-2 commit.)
    """

    @pytest.mark.parametrize('url, data', [
        ('/auth/profile/2fa/disable', {'password': 'wrong', 'token': '000000'}),
        ('/account/change-password', {'current_password': 'wrong',
                                      'new_password': NEW_PASSWORD,
                                      'confirm_password': NEW_PASSWORD}),
        ('/account/delete-account', {'password': 'wrong', 'confirmation': 'x'}),
    ])
    def test_failures_lock_the_account_and_end_the_session(self, app, client, sample_user,
                                                           url, data):
        _login(client, sample_user)
        for _ in range(app.config['MAX_FAILED_LOGIN_ATTEMPTS']):
            client.post(url, data=data)

        assert _reload(sample_user.id).is_account_locked()
        assert not _is_logged_in(client)

    def test_disable_2fa_is_rate_limited(self):
        source = _code_only('app/routes/auth.py')
        head = source[:source.index('def disable_2fa(')].rstrip('\n').split('\n')
        decorators = []
        while head and head[-1].startswith('@'):
            decorators.append(head.pop())

        assert any(d.startswith('@limiter.limit(') and "methods=['POST']" in d
                   for d in decorators)

    def test_lock_ends_parallel_sessions_too(self, app, client, second_client, sample_user):
        """
        Someone guessing with a stolen session can hold more than one. The first
        version ended only the session that tripped the lock. (Automated review
        of commit 7ad961b.)
        """
        _login(client, sample_user)
        _login(second_client, sample_user)
        for _ in range(app.config['MAX_FAILED_LOGIN_ATTEMPTS']):
            client.post('/account/change-password', data={
                'current_password': 'wrong', 'new_password': NEW_PASSWORD,
                'confirm_password': NEW_PASSWORD})

        assert not _is_logged_in(second_client)

    @pytest.mark.parametrize('url, data', [
        ('/auth/profile/2fa/disable', {'password': PASSWORD}),
        ('/account/change-password', {'current_password': PASSWORD,
                                      'new_password': NEW_PASSWORD,
                                      'confirm_password': NEW_PASSWORD}),
    ])
    def test_correct_secret_during_lock_achieves_nothing(self, client, twofa_user, url, data):
        """Counting failures is not enough if a check made during the lock still answers."""
        from datetime import timedelta

        from app import db
        from app.timeutil import utcnow

        user = _reload(twofa_user.id)
        user.two_factor_enabled = False
        db.session.commit()
        _login(client, twofa_user)
        user = _reload(twofa_user.id)
        user.two_factor_enabled = True
        user.account_locked_until = utcnow() + timedelta(minutes=15)
        db.session.commit()
        old_hash = user.password_hash

        client.post(url, data={**data, 'token': pyotp.TOTP(twofa_user.two_factor_secret).now()})

        user = _reload(twofa_user.id)
        assert user.two_factor_enabled is True
        assert user.password_hash == old_hash
        assert not _is_logged_in(client)

    def test_account_cannot_be_deleted_during_lock(self, client, twofa_user):
        from datetime import timedelta

        from app import db
        from app.timeutil import utcnow

        user = _reload(twofa_user.id)
        user.two_factor_enabled = False
        db.session.commit()
        _login(client, twofa_user)
        user = _reload(twofa_user.id)
        user.two_factor_enabled = True
        user.account_locked_until = utcnow() + timedelta(minutes=15)
        db.session.commit()

        client.post('/account/delete-account', data={
            'password': PASSWORD,
            'token': pyotp.TOTP(twofa_user.two_factor_secret).now(),
            'confirmation': f'DELETE {twofa_user.username}',
        })

        assert _reload(twofa_user.id).is_active is True
