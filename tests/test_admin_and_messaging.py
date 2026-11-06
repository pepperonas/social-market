"""
Review round 3 (2026-11), step 5: admin actions, messaging, audit queries.

Each class pins one finding from docs/REVIEW-2026-11.md (P1-18 ... P1-25).
"""

import os
import shutil
import tempfile
import uuid
from unittest.mock import patch

import gnupg
import pytest

ADMIN_PW = 'AdminPassword123!'
USER_PW = 'TestPassword123!'


def login(app, user, password=USER_PW):
    client = app.test_client()
    response = client.post('/auth/login', data={'username': user.username, 'password': password})
    assert response.status_code in (302, 303)
    return client


def fresh(model, ident):
    from app import db

    db.session.expunge_all()
    return db.session.get(model, ident)


# =============================================================================
# P1-18 -- admin deactivate / activate
# =============================================================================

class TestAdminDeactivation:
    def test_admin_cannot_deactivate_themselves(self, app, sample_admin):
        """
        With a single admin, one POST would have locked administration out for
        good: nobody left to reactivate the account.
        """
        from app.models.user import User

        client = login(app, sample_admin, ADMIN_PW)
        client.post(f'/admin/user/{sample_admin.id}/deactivate')

        assert fresh(User, sample_admin.id).is_active is True

    def test_deactivation_is_audited_and_ends_sessions(self, app, sample_admin, sample_user):
        from app.models.user import User

        version = sample_user.session_version
        client = login(app, sample_admin, ADMIN_PW)
        with patch('app.services.audit_service.log_admin_action') as audit:
            client.post(f'/admin/user/{sample_user.id}/deactivate', data={'reason': 'spam'})

        user = fresh(User, sample_user.id)
        assert user.is_active is False
        assert user.session_version > version
        assert audit.call_args.kwargs['action'] == 'deactivate_user'
        assert audit.call_args.kwargs['reason'] == 'spam'

    def test_activation_is_audited(self, app, sample_admin, sample_user):
        from app import db
        from app.models.user import User

        user = fresh(User, sample_user.id)
        user.is_active = False
        db.session.commit()

        client = login(app, sample_admin, ADMIN_PW)
        with patch('app.services.audit_service.log_admin_action') as audit:
            client.post(f'/admin/user/{sample_user.id}/activate')

        assert fresh(User, sample_user.id).is_active is True
        assert audit.call_args.kwargs['action'] == 'activate_user'


# =============================================================================
# P1-20 / P1-21 -- CSP endpoints
# =============================================================================

class TestCspEndpoints:
    def test_broken_view_endpoint_is_gone(self, app, sample_admin):
        """POST /admin/csp-report returned None -> a 500 on every call."""
        client = login(app, sample_admin, ADMIN_PW)

        assert client.post('/admin/csp-report').status_code in (404, 405)

    def test_oversized_report_is_refused(self, client):
        response = client.post('/admin/csp-report-uri', data='x' * 20000,
                               content_type='application/csp-report')

        assert response.status_code == 413

    def test_report_cannot_forge_log_lines(self, client, caplog):
        forged = 'https://evil.example/\n2026-11-06 INFO Admin login successful'
        with patch('app.services.audit_service.log_security_event'):
            client.post('/admin/csp-report-uri', json={'csp-report': {
                'blocked-uri': forged, 'violated-directive': 'script-src'}})

        logged = '\n'.join(r.getMessage() for r in caplog.records if 'CSP' in r.getMessage())
        assert 'evil.example' in logged
        assert '\n' not in logged

    def test_metadata_is_a_mapping_not_a_repr(self, client):
        """str(dict) is a Python repr; the JSONB insert failed and the event was lost."""
        with patch('app.services.audit_service.log_security_event') as event:
            client.post('/admin/csp-report-uri', json={'csp-report': {
                'blocked-uri': 'inline', 'violated-directive': 'script-src', 'junk': 'x' * 50}})

        metadata = event.call_args.kwargs['metadata']
        assert isinstance(metadata, dict)
        assert 'junk' not in metadata, 'only known fields are kept'

    def test_non_object_body_is_a_400_not_a_500(self, client):
        assert client.post('/admin/csp-report-uri', json=[1, 2]).status_code == 400


# =============================================================================
# P1-23 -- the query that could never run
# =============================================================================

class TestRecentSecurityEvents:
    def test_recent_events_are_returned(self, app):
        """
        `INTERVAL ':hours hours'` put a bind parameter inside a string literal.
        It raised, the error was caught, and the function returned [] whatever
        had happened.
        """
        from sqlalchemy import text

        from app import db
        from app.services.audit_service import get_recent_security_events
        from app.timeutil import utcnow

        marker = f'marker-{uuid.uuid4().hex[:8]}'
        db.session.execute(text(
            "INSERT INTO security_events (timestamp, event_type, severity, description) "
            "VALUES (:ts, 'test', 'info', :d)"), {'ts': utcnow(), 'd': marker})
        db.session.commit()

        events = get_recent_security_events(hours=1)

        assert any(marker in str(tuple(row)) for row in events)


# =============================================================================
# P1-19 -- "mandatory" PGP encryption could be bypassed
# =============================================================================

@pytest.fixture(scope='module')
def keys():
    """Two throwaway keypairs: the recipient's, and somebody else's."""
    home = tempfile.mkdtemp(prefix='gpg-test-')
    os.chmod(home, 0o700)
    gpg = gnupg.GPG(gnupghome=home)
    made = {}
    for name in ('recipient', 'stranger'):
        result = gpg.gen_key(gpg.gen_key_input(
            key_type='RSA', key_length=2048, name_real=name,
            name_email=f'{name}@test.local', no_protection=True))
        made[name] = gpg.export_keys(str(result.fingerprint))
    made['encrypt'] = lambda text, who: str(gpg.encrypt(
        text, gpg.list_keys(keys=[f'{who}@test.local'])[0]['fingerprint'], always_trust=True))
    yield made
    shutil.rmtree(home, ignore_errors=True)


@pytest.fixture
def keyed_recipient(app, sample_vendor, keys):
    from app import db
    from app.models.user import User

    user = fresh(User, sample_vendor.id)
    user.pgp_public_key = keys['recipient']
    db.session.commit()
    return user


class TestManualModeIsVerified:
    """
    Manual mode checked the first and the last line only. This was stored with
    is_encrypted=True:

        -----BEGIN PGP MESSAGE-----
        meet me at 8, bring cash
        -----END PGP MESSAGE-----

    and every later "is it encrypted?" check trusted that flag.
    """

    def _send(self, app, sender, recipient, content):
        from app.models.message import Message

        client = login(app, sender)
        client.post(f'/messages/new/{recipient.id}',
                    data={'message': content, 'encryption_mode': 'manual'})
        return Message.query.filter_by(sender_id=sender.id, recipient_id=recipient.id).all()

    def test_plaintext_between_armour_lines_is_refused(self, app, sample_user, keyed_recipient):
        fake = '-----BEGIN PGP MESSAGE-----\nmeet me at 8\n-----END PGP MESSAGE-----'

        assert self._send(app, sample_user, keyed_recipient, fake) == []

    def test_message_for_somebody_else_is_refused(self, app, sample_user, keyed_recipient, keys):
        assert self._send(app, sample_user, keyed_recipient,
                          keys['encrypt']('hi', 'stranger')) == []

    def test_message_for_the_recipient_is_accepted(self, app, sample_user, keyed_recipient, keys):
        sent = self._send(app, sample_user, keyed_recipient, keys['encrypt']('hi', 'recipient'))

        assert len(sent) == 1 and sent[0].is_encrypted

    def test_recipient_is_notified(self, app, sample_user, keyed_recipient, keys):
        """notify_new_message() existed and nothing called it: messages arrived silently."""
        from app.models.notification import Notification

        self._send(app, sample_user, keyed_recipient, keys['encrypt']('hi', 'recipient'))

        assert Notification.query.filter_by(user_id=keyed_recipient.id,
                                            related_type='message').count() == 1

    def test_rejected_message_leaves_no_empty_thread(self, app, sample_user, keyed_recipient):
        """The thread was created before the content was checked."""
        from app.models.message import MessageThread

        self._send(app, sample_user, keyed_recipient, 'not encrypted at all')

        assert MessageThread.query.filter(
            MessageThread.participant_1_id.in_([sample_user.id, keyed_recipient.id]),
            MessageThread.participant_2_id.in_([sample_user.id, keyed_recipient.id]),
        ).count() == 0


# =============================================================================
# P1-25 -- CLI wrote private keys world-readable
# =============================================================================

class TestCliPrivateKeyFile:
    def test_saved_private_key_is_0600_and_never_overwrites(self, app, sample_user, tmp_path,
                                                          monkeypatch):
        from app.services.pgp_service import PGPService

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(PGPService, 'generate_keypair', lambda self, **kw: {
            'success': True, 'public_key': 'PUB', 'private_key': 'PRIV', 'fingerprint': 'F' * 40})
        monkeypatch.setattr('app.services.audit_service.log_pgp_key_event', lambda **kw: None)
        os.umask(0o022)

        runner = app.test_cli_runner()
        result = runner.invoke(args=['generate-pgp-keys', '--username', sample_user.username,
                                     '--passphrase', 'x' * 20, '--save-private'])
        assert result.exit_code == 0, result.output

        path = tmp_path / f'{sample_user.username}_private_key.asc'
        assert path.read_text() == 'PRIV'
        assert oct(path.stat().st_mode & 0o777) == '0o600'

        path.write_text('EXISTING')
        runner.invoke(args=['generate-pgp-keys', '--username', sample_user.username,
                            '--passphrase', 'x' * 20, '--save-private'], input='y\n')
        assert path.read_text() == 'EXISTING'


class TestSecurityPanelsShowWhatExists:
    """
    Found while testing step 5: the first security event in the test database
    broke the admin dashboard. The template read alert.created_at /
    alert.message / alert.severity_color; the raw SQL rows carry timestamp /
    description / severity. `.strftime()` on an undefined value raises even in
    production's lenient mode -- and the live database had held events since
    the step-2 test that morning, so the live dashboard was returning 500.

    The security page had panels for recent events and failed logins that the
    view never filled: both always said "none recorded".
    """

    @pytest.fixture
    def evidence(self, app):
        from sqlalchemy import text

        from app import db
        from app.timeutil import utcnow

        marker = f'evt-{uuid.uuid4().hex[:8]}'
        who = f'guesser_{uuid.uuid4().hex[:6]}'
        db.session.execute(text(
            "INSERT INTO security_events (timestamp, event_type, severity, description) "
            "VALUES (:ts, 'test', 'high', :d)"), {'ts': utcnow(), 'd': marker})
        db.session.execute(text(
            "INSERT INTO auth_log (timestamp, username, action, ip_address) "
            "VALUES (:ts, :u, 'login_failed_password', '192.0.2.7')"), {'ts': utcnow(), 'u': who})
        db.session.commit()
        return marker, who

    def test_dashboard_shows_the_alert(self, app, sample_admin, evidence):
        marker, _ = evidence
        html = login(app, sample_admin, ADMIN_PW).get('/admin/dashboard').get_data(as_text=True)

        assert marker in html
        assert 'bg-danger' in html, 'severity "high" gets a colour, not a bare "bg-"'

    def test_security_page_shows_events_and_failed_logins(self, app, sample_admin, evidence):
        marker, who = evidence
        response = login(app, sample_admin, ADMIN_PW).get('/admin/security')

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert marker in html
        assert who in html


# =============================================================================
# P1-24 -- IP blocking, wired in (manual only)
# =============================================================================

PUBLIC_IP = '93.184.216.34'  # a public address; TEST-NET ranges count as non-global


class TestIpBlocking:
    """
    SecurityService.block_ip / is_ip_blocked existed and had tests -- and
    nothing called them, and their table existed only in the SQLite test schema.
    Wired in during round 3, manual only (see auto_block_check for why).
    """

    @staticmethod
    def _client_from(app, ip):
        client = app.test_client()
        client.environ_base['REMOTE_ADDR'] = ip
        return client

    def test_blocked_address_is_refused(self, app):
        from app.services.security_service import SecurityService

        SecurityService.block_ip(PUBLIC_IP, 'test', duration_hours=1)
        try:
            response = self._client_from(app, PUBLIC_IP).get('/auth/login')
            assert response.status_code == 403
            assert self._client_from(app, '93.184.216.35').get('/auth/login').status_code == 200
        finally:
            SecurityService.unblock_ip(PUBLIC_IP)

        assert self._client_from(app, PUBLIC_IP).get('/auth/login').status_code == 200

    def test_expired_block_is_not_applied(self, app):
        """Expiry is compared with a bound UTC 'now', not the DB's NOW() in Europe/Berlin."""
        from datetime import timedelta

        from sqlalchemy import text

        from app import db
        from app.timeutil import utcnow

        db.session.execute(text(
            "INSERT INTO blocked_ips (ip_address, reason, expires_at) VALUES (:ip, 't', :exp)"),
            {'ip': PUBLIC_IP, 'exp': utcnow() - timedelta(minutes=1)})
        db.session.commit()
        try:
            assert self._client_from(app, PUBLIC_IP).get('/auth/login').status_code == 200
        finally:
            db.session.execute(text("DELETE FROM blocked_ips"))
            db.session.commit()

    def test_lookup_error_fails_open_and_rolls_back(self, app, monkeypatch):
        """
        is_ip_blocked swallowed errors without a rollback. In PostgreSQL a failed
        statement aborts the transaction, so every later query of the request
        failed -- with the table missing, that would have been every page.
        SQLite does not abort, so the rollback itself is what is checked.
        """
        from sqlalchemy import text

        from app import db

        rollbacks = []
        real_rollback = db.session.rollback
        monkeypatch.setattr(db.session, 'rollback',
                            lambda: (rollbacks.append(1), real_rollback())[1])
        db.session.execute(text('ALTER TABLE blocked_ips RENAME TO blocked_ips_away'))
        db.session.commit()
        try:
            assert app.test_client().get('/auth/login').status_code == 200, 'fails open'
            assert rollbacks, 'the failed lookup must be rolled back'
        finally:
            db.session.execute(text('ALTER TABLE blocked_ips_away RENAME TO blocked_ips'))
            db.session.commit()

    def test_admin_blocks_and_unblocks_with_audit(self, app, sample_admin):
        from app.services.security_service import SecurityService

        client = login(app, sample_admin, ADMIN_PW)
        with patch('app.services.audit_service.log_admin_action') as audit:
            client.post('/admin/ip/block', data={'ip_address': PUBLIC_IP, 'reason': 'abuse',
                                                 'hours': '2'})
            assert SecurityService.is_ip_blocked(PUBLIC_IP)[0] is True
            html = client.get('/admin/security').get_data(as_text=True)
            assert PUBLIC_IP in html

            client.post('/admin/ip/unblock', data={'ip_address': PUBLIC_IP})
            assert SecurityService.is_ip_blocked(PUBLIC_IP)[0] is False

        assert [c.kwargs['action'] for c in audit.call_args_list] == ['block_ip', 'unblock_ip']

    @pytest.mark.parametrize('ip', ['127.0.0.1', '10.0.0.5', '192.168.178.20', '::1',
                                    'not-an-ip', ''])
    def test_admin_cannot_block_non_public_or_invalid(self, app, sample_admin, ip):
        from app.services.security_service import SecurityService

        client = login(app, sample_admin, ADMIN_PW)
        client.post('/admin/ip/block', data={'ip_address': ip, 'reason': 'x', 'hours': '1'})

        assert SecurityService.get_blocked_ips() == []

    def test_admin_cannot_block_their_own_address(self, app, sample_admin):
        from app.services.security_service import SecurityService

        client = self._client_from(app, PUBLIC_IP)
        client.post('/auth/login', data={'username': sample_admin.username, 'password': ADMIN_PW})
        client.post('/admin/ip/block', data={'ip_address': PUBLIC_IP, 'reason': 'x', 'hours': '1'})

        assert SecurityService.get_blocked_ips() == []

    def test_non_admin_cannot_block(self, app, sample_user):
        from app.services.security_service import SecurityService

        login(app, sample_user).post('/admin/ip/block',
                                     data={'ip_address': PUBLIC_IP, 'reason': 'x', 'hours': '1'})

        assert SecurityService.get_blocked_ips() == []


class TestIpBlockCache:
    def test_unblock_takes_effect_at_once_in_this_process(self, app, monkeypatch):
        """The suite runs with the cache off; this turns it on to check it is invalidated."""
        from app.services.security_service import SecurityService

        monkeypatch.setitem(app.config, 'IP_BLOCK_CACHE_SECONDS', 60)
        client = TestIpBlocking._client_from(app, PUBLIC_IP)

        SecurityService.block_ip(PUBLIC_IP, 'test', duration_hours=1)
        assert client.get('/auth/login').status_code == 403   # now cached as blocked
        SecurityService.unblock_ip(PUBLIC_IP)

        assert client.get('/auth/login').status_code == 200

    def test_cache_stays_bounded_when_addresses_rotate(self, app, monkeypatch):
        """One entry per address and nothing ever evicted: rotating IPv6 addresses grew it forever."""
        from app.services import security_service

        monkeypatch.setitem(app.config, 'IP_BLOCK_CACHE_SECONDS', 60)
        monkeypatch.setattr(security_service, 'BLOCK_CACHE_MAX', 50)
        security_service._block_cache.clear()

        with app.test_request_context():
            for n in range(500):
                security_service.request_is_blocked(f'2001:db8::{n:x}')

        assert len(security_service._block_cache) <= 50
