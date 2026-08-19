"""
Regression tests for templates that render audit-log rows.

Found by clicking through the deployed instance: /account/security returned a
500 because the template sliced `login.user_agent[:50]`, and the auth_log rows
written by the SQLAlchemy event listeners carry no user_agent at all.

Blue team relevance: the security overview is exactly the page a defender opens
when something looks wrong. A page that 500s on incomplete audit data fails at
the moment it is needed -- and audit data is *routinely* incomplete, because it
is written from several code paths that know different amounts about the request.
"""

import pytest
from sqlalchemy import text


def _login(client, user, password='TestPassword123!'):
    response = client.post('/auth/login',
                           data={'username': user.username, 'password': password},
                           follow_redirects=False)
    assert response.status_code in (302, 303)


@pytest.fixture
def auth_log_row_without_user_agent(app, sample_user):
    """Insert an auth_log entry with NULL user_agent and NULL ip, as the listeners do."""
    from app import db

    db.session.execute(
        text("INSERT INTO auth_log (user_id, username, action, ip_address, user_agent) "
             "VALUES (:uid, :name, 'login_success', NULL, NULL)"),
        {'uid': str(sample_user.id), 'name': sample_user.username}
    )
    db.session.commit()
    yield
    db.session.execute(text("DELETE FROM auth_log WHERE user_id = :uid"),
                       {'uid': str(sample_user.id)})
    db.session.commit()


class TestSecurityPageNullSafety:
    def test_security_page_renders_with_null_user_agent(
        self, client, sample_user, auth_log_row_without_user_agent
    ):
        """Regression: this returned 500 in production."""
        _login(client, sample_user)

        response = client.get('/account/security')

        assert response.status_code == 200, (
            'security overview must survive audit rows with missing fields'
        )

    def test_security_page_shows_placeholder_not_crash(
        self, client, sample_user, auth_log_row_without_user_agent
    ):
        _login(client, sample_user)
        body = client.get('/account/security').data

        assert b'unknown' in body or b'-' in body

    def test_security_page_renders_without_any_history(self, client, sample_user):
        """A brand new account has no auth_log rows at all."""
        _login(client, sample_user)

        assert client.get('/account/security').status_code == 200


class TestNoUnguardedSlicesInTemplates:
    """
    Static guard: slicing a value straight out of an audit row is the exact
    shape of the bug above. Any new occurrence must carry a fallback.
    """

    @pytest.mark.parametrize('field', ['user_agent', 'ip_address', 'reason', 'description'])
    def test_no_unguarded_slice_of_nullable_audit_fields(self, field):
        import pathlib
        import re

        offenders = []
        for path in pathlib.Path('app/templates').rglob('*.html'):
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                # e.g. {{ login.user_agent[:50] }} with no `or` fallback and no `if`
                for match in re.finditer(rf'(\w+)\.{field}\[', line):
                    guarded = ' or ' in line or ' if ' in line
                    if not guarded:
                        offenders.append(f'{path}:{lineno}: {line.strip()[:80]}')

        assert not offenders, (
            f'unguarded slice of a nullable audit field ({field}):\n' + '\n'.join(offenders)
        )
