"""
Review round 3 (2026-11), step 6: running with ProductionConfig.

The live server ran with the base config. ProductionConfig adds
WTF_CSRF_SSL_STRICT, which rejects any HTTPS POST without a same-origin
Referer -- and the app told browsers never to send one (Referrer-Policy:
no-referrer). Switched on, every form would have failed. The policy is now
same-origin, and production refuses to start with fallback secrets.
"""

import re

import pytest

PW = 'TestPassword123!'


@pytest.fixture
def strict_csrf(app):
    """CSRF on, SSL-strict on -- what ProductionConfig does."""
    saved = {k: app.config[k] for k in ('WTF_CSRF_ENABLED', 'WTF_CSRF_SSL_STRICT')}
    app.config.update(WTF_CSRF_ENABLED=True, WTF_CSRF_SSL_STRICT=True)
    yield
    app.config.update(saved)


def _login_over_https(app, user, referer):
    client = app.test_client()
    html = client.get('/auth/login', base_url='https://localhost').get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    headers = {'Referer': referer} if referer else {}
    return client.post('/auth/login', base_url='https://localhost', headers=headers,
                       data={'csrf_token': token, 'username': user.username, 'password': PW})


class TestStrictCsrfWorksWithTheReferrerPolicy:
    def test_browser_sends_referer_under_same_origin_policy(self, app, client):
        assert client.get('/auth/login').headers['Referrer-Policy'] == 'same-origin'

    def test_form_post_with_same_origin_referer_passes(self, app, sample_user, strict_csrf):
        response = _login_over_https(app, sample_user, 'https://localhost/auth/login')

        assert response.status_code == 302

    def test_form_post_without_referer_fails(self, app, sample_user, strict_csrf):
        """What every form did under the old policy: browsers obeyed no-referrer."""
        assert _login_over_https(app, sample_user, None).status_code == 400


class TestProductionRefusesDevelopmentSecrets:
    @staticmethod
    def _fallbacks_in_config_py():
        """
        The fallback values as config.py actually has them -- read from there,
        not from DEVELOPMENT_SECRETS, or shortening that list would shorten the
        test with it (that is exactly what the first version of this test did).
        """
        import pathlib

        source = pathlib.Path('app/config.py').read_text()
        found = dict(re.findall(
            r"^\s+(SECRET_KEY|PASSWORD_PEPPER|DB_ENCRYPTION_KEY|TOTP_ENCRYPTION_KEY) = "
            r"os\.environ\.get\('\1'\) or '([^']+)'", source, re.M))
        assert set(found) == {'SECRET_KEY', 'PASSWORD_PEPPER', 'DB_ENCRYPTION_KEY',
                              'TOTP_ENCRYPTION_KEY'}
        return found

    @staticmethod
    def _real_values(names):
        """Strong stand-ins; TOTP_ENCRYPTION_KEY must also parse as a Fernet key."""
        from cryptography.fernet import Fernet
        values = {k: 'x' * 40 for k in names}
        values['TOTP_ENCRYPTION_KEY'] = Fernet.generate_key().decode()
        return values

    def test_fallback_secret_stops_startup(self):
        from app import refuse_development_secrets

        fallbacks = self._fallbacks_in_config_py()
        for name, value in fallbacks.items():
            config = self._real_values(fallbacks)
            config[name] = value
            with pytest.raises(RuntimeError, match=name):
                refuse_development_secrets(config)

    def test_real_secrets_pass(self):
        from app import refuse_development_secrets

        refuse_development_secrets(self._real_values(self._fallbacks_in_config_py()))

    def test_create_app_applies_the_check_for_production(self):
        import inspect

        import app as package

        source = inspect.getsource(package.create_app)
        assert "if config_name == 'production':" in source
        assert 'refuse_development_secrets(app.config)' in source


class TestInitAdminHasNoDefaultPassword:
    def test_generated_password_works_and_is_not_the_published_one(self, app, monkeypatch):
        from app import db
        from app.models.user import User

        existing = User.query.filter_by(username='admin').first()
        if existing:
            db.session.delete(existing)
            db.session.commit()
        monkeypatch.setitem(app.config, 'ADMIN_PASSWORD', None)

        result = app.test_cli_runner().invoke(args=['init-admin'])
        password = re.search(r'Password: (\S+)', result.output).group(1)

        assert password != 'ChangeMe123!'
        assert User.query.filter_by(username='admin').one().check_password(password)

        db.session.delete(User.query.filter_by(username='admin').one())
        db.session.commit()

    def test_configured_password_is_not_echoed(self, app, monkeypatch):
        from app import db
        from app.models.user import User

        monkeypatch.setitem(app.config, 'ADMIN_PASSWORD', 'Configured-Passw0rd!x')
        result = app.test_cli_runner().invoke(args=['init-admin'])

        assert 'Configured-Passw0rd!x' not in result.output
        admin = User.query.filter_by(username='admin').first()
        if admin:
            db.session.delete(admin)
            db.session.commit()


def test_login_page_does_not_advertise_admin_credentials(client):
    html = client.get('/auth/login').get_data(as_text=True)

    assert 'ChangeMe123!' not in html
