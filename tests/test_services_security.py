"""
Unit tests for SecurityService detection logic.

Focus is on the pure decision functions (honeypot, IP blocking bookkeeping).
These are the pieces that decide whether a request is treated as hostile, so a
silent regression here disables a control without any visible symptom.
"""

import pytest


@pytest.fixture(autouse=True)
def security_tables(app):
    """
    Create the security tables. They live in SECURITY_TABLES_SQL as PostgreSQL
    DDL (SERIAL/INET/JSONB), so a SQLite-compatible equivalent is used here.
    """
    from sqlalchemy import text
    from app import db

    ddl = [
        """
        CREATE TABLE IF NOT EXISTS blocked_ips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_address VARCHAR(45) NOT NULL UNIQUE,
            reason TEXT NOT NULL,
            blocked_by VARCHAR(100) DEFAULT 'system',
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS canary_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            token_type VARCHAR(50) NOT NULL,
            description TEXT,
            alert_email VARCHAR(255),
            trigger_count INTEGER DEFAULT 0,
            last_triggered_at TIMESTAMP,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS canary_triggers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canary_id INTEGER,
            ip_address VARCHAR(45),
            user_agent TEXT,
            triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT
        )
        """,
    ]
    for statement in ddl:
        db.session.execute(text(statement))
    db.session.commit()

    yield

    for table in ('canary_triggers', 'canary_tokens', 'blocked_ips'):
        try:
            db.session.execute(text(f'DELETE FROM {table}'))
            db.session.commit()
        except Exception:
            db.session.rollback()


class TestHoneypot:
    """
    Honeypot fields are invisible to humans. Anything that fills them is
    automation -- but only if the check actually looks at the right fields.
    """

    def test_empty_form_is_not_a_bot(self, app):
        from app.services.security_service import SecurityService

        assert SecurityService.check_honeypot({'username': 'alice'}) is False

    def test_absent_honeypot_fields_are_not_a_bot(self, app):
        from app.services.security_service import SecurityService

        assert SecurityService.check_honeypot({}) is False

    def test_blank_honeypot_is_not_a_bot(self, app, mock_audit):
        """A present-but-empty field is what a real browser submits."""
        from app.services.security_service import SecurityService

        assert SecurityService.check_honeypot({'hp_email': ''}) is False

    @pytest.mark.parametrize('field', ['hp_email', 'hp_website', 'hp_phone'])
    def test_filled_honeypot_is_a_bot(self, app, mock_audit, field):
        from app.services.security_service import SecurityService

        with app.test_request_context('/'):
            assert SecurityService.check_honeypot({field: 'anything'}) is True

    def test_custom_field_list_is_respected(self, app, mock_audit):
        from app.services.security_service import SecurityService

        with app.test_request_context('/'):
            assert SecurityService.check_honeypot(
                {'trap': 'filled'}, honeypot_fields=['trap']
            ) is True

    def test_default_fields_ignored_when_custom_list_given(self, app, mock_audit):
        from app.services.security_service import SecurityService

        assert SecurityService.check_honeypot(
            {'hp_email': 'filled'}, honeypot_fields=['other']
        ) is False


class TestIpBlocking:
    def test_unknown_ip_is_not_blocked(self, app):
        from app.services.security_service import SecurityService

        blocked, reason = SecurityService.is_ip_blocked('203.0.113.9')
        assert blocked is False and reason is None

    def test_blocked_ip_is_reported(self, app, mock_audit):
        from app.services.security_service import SecurityService

        SecurityService.block_ip('203.0.113.10', 'testing', duration_hours=1)

        blocked, reason = SecurityService.is_ip_blocked('203.0.113.10')
        assert blocked is True
        assert reason == 'testing', 'the reason must survive for the audit trail'

    def test_unblock_restores_access(self, app, mock_audit):
        from app.services.security_service import SecurityService

        SecurityService.block_ip('203.0.113.11', 'testing', duration_hours=1)
        SecurityService.unblock_ip('203.0.113.11')

        assert SecurityService.is_ip_blocked('203.0.113.11')[0] is False

    def test_expired_block_no_longer_applies(self, app, mock_audit):
        """A block with a past expiry must not keep a user locked out forever."""
        from sqlalchemy import text
        from app import db
        from app.services.security_service import SecurityService

        SecurityService.block_ip('203.0.113.12', 'testing', duration_hours=1)
        db.session.execute(
            text("UPDATE blocked_ips SET expires_at = :past WHERE ip_address = :ip"),
            {'past': '2000-01-01 00:00:00', 'ip': '203.0.113.12'}
        )
        db.session.commit()

        assert SecurityService.is_ip_blocked('203.0.113.12')[0] is False

    def test_blocking_is_per_address(self, app, mock_audit):
        from app.services.security_service import SecurityService

        SecurityService.block_ip('203.0.113.13', 'testing', duration_hours=1)
        assert SecurityService.is_ip_blocked('203.0.113.14')[0] is False

    def test_blocked_list_contains_the_entry(self, app, mock_audit):
        from app.services.security_service import SecurityService

        SecurityService.block_ip('203.0.113.15', 'noisy scanner', duration_hours=1)
        listed = [row for row in SecurityService.get_blocked_ips()]

        assert any('203.0.113.15' in str(row) for row in listed)


class TestFailureMode:
    """
    Documented behaviour, not an endorsement: every lookup here is wrapped in a
    broad `except Exception` that returns "not blocked". The control therefore
    FAILS OPEN -- a database hiccup silently disables IP blocking rather than
    denying the request.

    Blue team takeaway: decide fail-open vs fail-closed deliberately, and make
    the choice visible. A security control that degrades silently is worse than
    one that is absent, because the dashboard still shows it as enabled.
    """

    def test_lookup_failure_reports_not_blocked(self, app, monkeypatch):
        from app import db
        from app.services.security_service import SecurityService

        def boom(*args, **kwargs):
            raise RuntimeError('database unavailable')

        monkeypatch.setattr(db.session, 'execute', boom)

        blocked, reason = SecurityService.is_ip_blocked('203.0.113.99')

        assert blocked is False, 'current design fails open'
        assert reason is None

    def test_listing_failure_returns_empty_list(self, app, monkeypatch):
        from app import db
        from app.services.security_service import SecurityService

        monkeypatch.setattr(
            db.session, 'execute',
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError('down'))
        )

        assert SecurityService.get_blocked_ips() == []
