"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Improvement plan 2026-11, step 5: reference code wired in or moved out honestly.

B3  SecurityService carried canary tokens and a honeypot check that nothing
    called -- the canary tables did not even exist. The honeypot is now wired
    in twice (a hidden registration field and decoy paths that scanners probe);
    both only REPORT, an admin decides on a block (same rule as B7). The canary
    code moved to examples/, out of the application package.
B6  cart.py announced a guest cart that never existed. The marketplace is
    login-only on purpose; the comment now says so.
"""

import os

import pytest
from sqlalchemy import text

SCANNER_IP = '93.184.216.41'
OTHER_SCANNER_IP = '93.184.216.42'
TRAP_FIELD = 'hp_website'


@pytest.fixture(autouse=True)
def _clean_slate(app):
    """Decoy hits are de-duplicated per process; events live in the shared test DB."""
    from app.services import security_service
    security_service._decoy_seen.clear()
    yield
    security_service._decoy_seen.clear()
    from app import db
    db.session.rollback()
    for table in ('blocked_ips', 'security_events'):
        db.session.execute(text(f'DELETE FROM {table} WHERE ip_address IN (:a, :b)'),  # nosec B608 -- fixed names
                           {'a': SCANNER_IP, 'b': OTHER_SCANNER_IP})
    db.session.commit()


@pytest.fixture
def events(monkeypatch):
    """
    Records every security event and still writes it. On SQLite the stored
    procedure behind log_security_event does not exist (the write fails
    silently), so the call itself is what the tests can see there; on
    PostgreSQL the row is checked as well.
    """
    from app.services import audit_service
    real = audit_service.log_security_event
    seen = []

    def spy(event_type, severity, description, **kwargs):
        seen.append({'type': event_type, 'severity': severity,
                     'description': description, **kwargs})
        return real(event_type, severity, description, **kwargs)

    monkeypatch.setattr(audit_service, 'log_security_event', spy)
    return seen


def _client(app, ip=SCANNER_IP):
    client = app.test_client()
    client.environ_base['REMOTE_ADDR'] = ip
    return client


def _is_postgres():
    from app import db
    return db.engine.dialect.name == 'postgresql'


def _registration(username, **extra):
    data = {
        'username': username,
        'email': f'{username}@example.org',
        'password': 'Correct-Horse-Battery-Staple-42!',
        'password_confirm': 'Correct-Horse-Battery-Staple-42!',
        'role': 'buyer',
        'terms_accepted': 'on',
    }
    data.update(extra)
    return data


def _user_exists(username):
    from app.models.user import User
    return User.query.filter_by(username=username).first() is not None


# =============================================================================
# B3 -- the registration form carries a trap field
# =============================================================================

class TestRegistrationTrap:
    def test_form_renders_the_trap_hidden_by_class_not_inline_style(self, app):
        html = app.test_client().get('/auth/register').get_data(as_text=True)

        field = html[html.index(f'name="{TRAP_FIELD}"') - 300:html.index(f'name="{TRAP_FIELD}"') + 200]
        assert 'class="hp-field"' in field          # hidden by the stylesheet: CSP blocks inline styles
        assert 'aria-hidden="true"' in field        # screen readers skip it
        assert 'tabindex="-1"' in field             # keyboard users never land in it
        assert 'autocomplete="off"' in field        # password managers do not fill it
        assert 'style=' not in field

    def test_stylesheet_takes_the_trap_out_of_view(self, app):
        css = app.test_client().get('/static/css/custom.css').get_data(as_text=True)

        rule = css[css.index('.hp-field'):]
        rule = rule[:rule.index('}')]
        assert 'position: absolute' in rule and '-10000px' in rule

    def test_filled_trap_creates_no_account_and_looks_like_success(self, app, events):
        response = _client(app).post('/auth/register', data=_registration('trapbot1', **{TRAP_FIELD: 'http://spam'}))

        assert response.status_code == 302
        assert response.headers['Location'].endswith('/auth/login')
        assert not _user_exists('trapbot1')
        assert [e['type'] for e in events] == ['honeypot_triggered']
        assert events[0]['ip_address'] == SCANNER_IP

    def test_filled_trap_wins_over_validation_errors(self, app, events):
        """A bot must not learn from error messages which fields it got wrong."""
        response = _client(app).post('/auth/register',
                                     data={'username': 'x', TRAP_FIELD: 'filled'})

        assert response.status_code == 302
        assert 'honeypot_triggered' in [e['type'] for e in events]

    def test_empty_trap_registers_normally(self, app, events):
        response = _client(app).post('/auth/register', data=_registration('human1', **{TRAP_FIELD: ''}))

        assert response.status_code == 302
        assert _user_exists('human1')
        assert 'honeypot_triggered' not in [e['type'] for e in events]

    def test_trap_never_blocks_the_address(self, app, events):
        from app.services.security_service import SecurityService

        _client(app).post('/auth/register', data=_registration('trapbot2', **{TRAP_FIELD: 'x'}))

        assert SecurityService.is_ip_blocked(SCANNER_IP)[0] is False


# =============================================================================
# B3 -- decoy paths that scanners probe
# =============================================================================

class TestDecoyPaths:
    @pytest.mark.parametrize('path', ['/wp-login.php', '/admin.php', '/.env', '/phpmyadmin/'])
    def test_decoy_is_recorded(self, app, events, path):
        response = _client(app).get(path)

        assert response.status_code == 404
        hits = [e for e in events if e['type'] == 'honeypot_path']
        assert len(hits) == 1
        assert path in hits[0]['description']
        assert hits[0]['ip_address'] == SCANNER_IP
        if _is_postgres():
            from app import db
            assert db.session.execute(text(
                "SELECT COUNT(*) FROM security_events WHERE event_type = 'honeypot_path' AND ip_address = :ip"),
                {'ip': SCANNER_IP}).scalar() == 1

    def test_decoy_answers_exactly_like_an_unknown_path(self, app, events):
        client = _client(app)
        decoy = client.get('/wp-login.php')
        unknown = client.get('/definitely-not-a-route')

        assert decoy.status_code == unknown.status_code == 404
        assert decoy.get_data() == unknown.get_data()
        assert decoy.headers['Content-Type'] == unknown.headers['Content-Type']

    def test_post_to_a_decoy_is_recorded_too(self, app, events, monkeypatch):
        """
        wp-login.php is mostly POSTed to by credential stuffers, without a CSRF
        token. With CSRF on (as in production) the decoy must still record the
        hit and answer 404 -- a CSRF 400 would hide it and give the decoy away.
        The test config turns CSRF off, so it is switched on here.
        """
        monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
        response = _client(app).post('/wp-login.php', data={'log': 'admin', 'pwd': 'admin'})

        assert response.status_code == 404
        assert [e['type'] for e in events] == ['honeypot_path']

    def test_csrf_still_guards_real_forms_in_that_setup(self, app, monkeypatch):
        """Control for the test above: the switch really turns CSRF on."""
        monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
        response = _client(app).post('/auth/register', data=_registration('nocsrf1'))

        assert response.status_code == 400

    def test_unknown_paths_are_not_decoys(self, app, events):
        _client(app).get('/definitely-not-a-route')

        assert events == []

    def test_repeated_hits_are_recorded_once_per_window(self, app, events):
        """A scanner sends thousands of requests; each must not become a database row."""
        client = _client(app)
        for _ in range(5):
            client.get('/wp-login.php')
        client.get('/.env')
        _client(app, OTHER_SCANNER_IP).get('/wp-login.php')

        hits = [(e['ip_address'], e['description']) for e in events if e['type'] == 'honeypot_path']
        assert len(hits) == 3

    def test_window_expiry_records_again(self, app, events, monkeypatch):
        from app.services import security_service

        clock = [1000.0]
        monkeypatch.setattr(security_service.time, 'monotonic', lambda: clock[0])
        client = _client(app)
        client.get('/wp-login.php')
        clock[0] += app.config.get('DECOY_LOG_WINDOW_SECONDS', 600) + 1
        client.get('/wp-login.php')

        assert len([e for e in events if e['type'] == 'honeypot_path']) == 2

    def test_seen_cache_is_bounded(self, app, events, monkeypatch):
        from app.services import security_service

        monkeypatch.setattr(security_service, 'DECOY_SEEN_MAX', 3)
        for n in range(10):
            _client(app, f'198.51.100.{n}').get('/wp-login.php')

        assert len(security_service._decoy_seen) <= 3

    def test_decoy_never_blocks_the_address(self, app, events):
        from app.services.security_service import SecurityService

        _client(app).get('/wp-login.php')

        assert SecurityService.is_ip_blocked(SCANNER_IP)[0] is False


# =============================================================================
# B3 -- what the traps found is offered to the admin, like a scan finding
# =============================================================================

def _admin_security_page(app, sample_admin):
    from tests.test_order_lifecycle import ADMIN_PW, login
    html = login(app, sample_admin, ADMIN_PW).get('/admin/security').get_data(as_text=True)
    start = html.index('id="block-suggestions"')
    return html[start:html.index('id="blocked-list"', start)]


def _event(ip, event_type):
    from app import db
    from tests.conftest import aware_utcnow
    db.session.execute(text(
        "INSERT INTO security_events (timestamp, event_type, severity, source, ip_address, description) "
        "VALUES (:ts, :t, 'medium', 'application', :ip, 'test')"),
        {'ts': aware_utcnow(), 't': event_type, 'ip': ip})
    db.session.commit()


class TestTrapsFeedTheSuggestions:
    def test_decoy_hit_is_offered_with_its_kind(self, app, sample_admin):
        from app.services.security_service import SecurityService

        _event(SCANNER_IP, 'honeypot_path')
        section = _admin_security_page(app, sample_admin)

        row = section[section.index(f'value="{SCANNER_IP}"') - 600:]
        assert '1 &times; decoy path' in row
        assert 'value="trap: 1 decoy path hit(s) in 24 h"' in row
        assert SecurityService.is_ip_blocked(SCANNER_IP)[0] is False

    def test_kinds_are_counted_separately(self, app, sample_admin):
        _event(SCANNER_IP, 'honeypot_path')
        _event(SCANNER_IP, 'honeypot_path')
        _event(SCANNER_IP, 'honeypot_triggered')
        _event(SCANNER_IP, 'suspicious_failed_logins')

        from app.services.security_service import block_suggestions
        with app.test_request_context('/'):
            suggestion = next(s for s in block_suggestions('127.0.0.1') if s['ip'] == SCANNER_IP)

        assert suggestion['findings'] == 4
        assert suggestion['kinds'] == {'failed_logins': 1, 'decoy_path': 2, 'trap_field': 1}

    def test_unrelated_events_are_not_suggestions(self, app):
        _event(SCANNER_IP, 'csp_violation')

        from app.services.security_service import block_suggestions
        with app.test_request_context('/'):
            assert SCANNER_IP not in [s['ip'] for s in block_suggestions('127.0.0.1')]


# =============================================================================
# B3 -- canary tokens are not pretended to exist
# =============================================================================

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestCanaryMovedOut:
    def test_service_no_longer_offers_canaries(self):
        from app.services.security_service import SecurityService

        for name in ('create_canary_token', 'trigger_canary', 'get_canary_alerts'):
            assert not hasattr(SecurityService, name)

    def test_application_package_does_not_mention_canary_tables(self):
        for folder, _dirs, files in os.walk(os.path.join(ROOT, 'app')):
            for name in files:
                if name.endswith(('.py', '.html', '.sql')):
                    with open(os.path.join(folder, name), encoding='utf-8') as fh:
                        assert 'canary_tokens' not in fh.read(), os.path.join(folder, name)

    def test_reference_lives_in_examples_with_the_disclaimer(self):
        path = os.path.join(ROOT, 'examples', 'canary_tokens.py')
        with open(path, encoding='utf-8') as fh:
            source = fh.read()

        assert 'EDUCATIONAL SECURITY TRAINING ENVIRONMENT' in source
        assert 'NOT WIRED IN' in source
        assert 'def trigger_canary' in source


# =============================================================================
# B6 -- no guest cart, and the code says so
# =============================================================================

class TestNoGuestCart:
    def test_cart_requires_login(self, app):
        response = app.test_client().get('/cart/')

        assert response.status_code in (302, 401)
        if response.status_code == 302:
            assert '/auth/login' in response.headers['Location']

    def test_model_no_longer_promises_a_guest_cart(self):
        from app.models import cart

        doc = cart.Cart.__doc__.lower()
        assert 'guest' not in doc.replace('no guest cart', '')
        assert 'login' in doc

    def test_model_does_not_promise_a_cleanup_job_that_does_not_exist(self):
        from app.models import cart

        doc = cart.Cart.__doc__.lower().replace('promise "automatic cleanup"', '')
        assert 'automatic cleanup' not in doc
