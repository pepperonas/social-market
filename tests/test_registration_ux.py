"""
Registration form: usable *and* safe.

Two failures motivated this file:

1. The terms checkbox was named `terms`, the route read `terms_accepted`. Every
   registration through the web UI was rejected with "you must accept the
   terms" -- a field-name typo that made the feature completely unusable and
   that no test noticed, because the tests posted the form field directly.
2. A rejected submission wiped everything the user had typed.

The security half matters as much as the usability half: echoing input back
into HTML is exactly how reflected XSS happens, and echoing a *password* back
would put it in the DOM and the bfcache.
"""

import pytest
from unittest.mock import patch

VALID = {
    'username': 'freshuser',
    'email': 'fresh@test.local',
    'password': 'CorrectHorse-Battery-9!',
    'password_confirm': 'CorrectHorse-Battery-9!',
    'role': 'buyer',
    'terms_accepted': 'on',
}


def post(client, **overrides):
    data = dict(VALID)
    data.update(overrides)
    return client.post('/auth/register', data=data, follow_redirects=True)


class TestFieldNameContract:
    """The template must submit the field names the route actually reads."""

    def test_terms_checkbox_name_matches_route(self):
        import pathlib
        import re

        html = pathlib.Path('app/templates/auth/register.html').read_text()
        route = pathlib.Path('app/routes/auth.py').read_text()

        checkbox = re.search(r'<input[^>]*type="checkbox"[^>]*>', html)
        assert checkbox, 'register form must have the terms checkbox'
        name = re.search(r'name="([^"]+)"', checkbox.group(0)).group(1)

        assert f"request.form.get('{name}'" in route, (
            f'template submits "{name}" but the route never reads it -- '
            f'this exact mismatch made registration impossible'
        )

    @pytest.mark.parametrize('field', ['username', 'email', 'password', 'password_confirm', 'role'])
    def test_every_read_field_exists_in_template(self, field):
        import pathlib

        html = pathlib.Path('app/templates/auth/register.html').read_text()
        assert f'name="{field}"' in html


class TestInputIsPreserved:
    @patch('app.routes.auth._log_auth_event')
    def test_username_survives_a_rejected_submission(self, _log, client):
        response = post(client, password_confirm='mismatch')

        assert b'freshuser' in response.data, 'username must not be wiped'

    @patch('app.routes.auth._log_auth_event')
    def test_email_survives_a_rejected_submission(self, _log, client):
        response = post(client, password_confirm='mismatch')

        assert b'fresh@test.local' in response.data

    @patch('app.routes.auth._log_auth_event')
    def test_role_selection_survives(self, _log, client):
        response = post(client, role='vendor', password_confirm='mismatch')
        body = response.get_data(as_text=True)

        assert 'value="vendor" selected' in body or 'value="vendor"  selected' in body

    @patch('app.routes.auth._log_auth_event')
    def test_terms_checkbox_stays_ticked(self, _log, client):
        response = post(client, password_confirm='mismatch')

        assert b'checked' in response.data

    @patch('app.routes.auth._log_auth_event')
    def test_password_is_never_echoed_back(self, _log, client):
        """Re-rendering a password puts it in the DOM and the back/forward cache."""
        secret = 'SuperSecretValue-42!'
        response = post(client, password=secret, password_confirm='mismatch')

        assert secret.encode() not in response.data, (
            'the password must not be reflected into the HTML'
        )


class TestAllErrorsAtOnce:
    @patch('app.routes.auth._log_auth_event')
    def test_multiple_problems_reported_together(self, _log, client):
        response = post(client, username='', email='nope', password='short')
        body = response.get_data(as_text=True)

        assert 'username' in body.lower()
        assert 'email address' in body.lower()
        assert '12 characters' in body

    @patch('app.routes.auth._log_auth_event')
    def test_rejected_submission_returns_400(self, _log, client):
        assert post(client, username='').status_code == 400

    @patch('app.routes.auth._log_auth_event')
    def test_password_policy_is_reported_in_detail(self, _log, client):
        response = post(client, password='alllowercase', password_confirm='alllowercase')
        body = response.get_data(as_text=True)

        assert 'upper case' in body.lower()
        assert 'digit' in body.lower()


class TestReflectionIsEscaped:
    """Echoing input back is only safe because Jinja escapes it."""

    @patch('app.routes.auth._log_auth_event')
    def test_html_in_username_is_escaped(self, _log, client):
        payload = '<script>alert(1)</script>'
        response = post(client, username=payload, password_confirm='mismatch')
        body = response.get_data(as_text=True)

        assert '<script>alert(1)</script>' not in body, 'reflected XSS'
        assert '&lt;script&gt;' in body or 'alert' not in body

    @patch('app.routes.auth._log_auth_event')
    def test_quote_breakout_in_email_is_escaped(self, _log, client):
        payload = '" autofocus onfocus="alert(1)'
        response = post(client, email=payload, password_confirm='mismatch')
        body = response.get_data(as_text=True)

        assert 'onfocus="alert(1)"' not in body


class TestHappyPath:
    @patch('app.routes.auth._log_auth_event')
    def test_valid_registration_succeeds(self, _log, client, app):
        from app import db
        from app.models.user import User

        response = post(client, username='happyuser', email='happy@test.local')

        assert response.status_code == 200
        created = User.query.filter_by(username='happyuser').first()
        assert created is not None

        db.session.delete(created)
        db.session.commit()
