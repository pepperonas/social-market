"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Canary tokens -- reference code, NOT WIRED IN.

This used to live in app/services/security_service.py as methods nobody called,
writing to tables no migration created (improvement plan 2026-11, B3). It is
kept here as teaching material, outside the application package, so the app no
longer pretends to have a control it does not run.

The idea: plant a value that nothing legitimate ever uses -- a fake API key in
a config file, a URL in a document, a username no one owns. If it is ever
used, someone is reading what they should not, and you learn about it from the
attacker's own action.

What wiring it in would take (left as an exercise):

1. Apply CANARY_TABLES_SQL as a migration (and add the tables to the test
   schema in tests/conftest.py).
2. Call ``trigger_canary`` where the planted value would surface: the login
   route for a canary username, the API auth check for a canary key, a route
   for a canary URL. It must answer exactly as for any other unknown value,
   or the canary tells the attacker it is one.
3. Show ``canary_alerts`` on the admin security page.
4. Only the SHA-256 of the token is stored -- the planted value itself must
   never be readable from the database a thief might have copied.

The functions take a SQLAlchemy session and a request-like object so they can
be read and tried without the Flask application.
"""

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

CANARY_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS canary_tokens (
    id SERIAL PRIMARY KEY,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    token_type VARCHAR(50) NOT NULL,
    description TEXT,
    alert_email VARCHAR(255),
    trigger_count INTEGER DEFAULT 0,
    last_triggered_at TIMESTAMP,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS canary_triggers (
    id SERIAL PRIMARY KEY,
    canary_id INTEGER REFERENCES canary_tokens(id),
    ip_address INET,
    user_agent TEXT,
    triggered_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_canary_triggers_time ON canary_triggers(triggered_at);
"""

TOKEN_TYPES = ('url', 'username', 'file', 'api_key')


def _hash(token_value):
    return hashlib.sha256(token_value.encode()).hexdigest()


def create_canary_token(session, token_type, description, alert_email=None):
    """Plant a new canary. Returns the token -- the only time it is visible."""
    if token_type not in TOKEN_TYPES:
        raise ValueError(f'token_type must be one of {TOKEN_TYPES}')
    token_value = secrets.token_urlsafe(32)
    session.execute(text("""
        INSERT INTO canary_tokens (token_hash, token_type, description, alert_email, created_at, is_active)
        VALUES (:hash, :type, :desc, :email, NOW(), true)
    """), {'hash': _hash(token_value), 'type': token_type, 'desc': description, 'email': alert_email})
    session.commit()
    return {'token': token_value, 'type': token_type, 'description': description}


def trigger_canary(session, token_value, ip_address=None, user_agent=''):
    """
    Record a use of ``token_value`` if it is a canary. Returns True if it was.

    The caller must answer the request the same way either way.
    """
    canary = session.execute(text("""
        SELECT id, token_type, description FROM canary_tokens
        WHERE token_hash = :hash AND is_active = true
    """), {'hash': _hash(token_value)}).fetchone()
    if canary is None:
        return False

    session.execute(text("""
        INSERT INTO canary_triggers (canary_id, ip_address, user_agent, triggered_at, metadata)
        VALUES (:canary_id, :ip, :ua, NOW(), :meta)
    """), {'canary_id': canary.id, 'ip': ip_address, 'ua': user_agent,
           'meta': json.dumps({'type': canary.token_type, 'description': canary.description})})
    session.execute(text("""
        UPDATE canary_tokens SET trigger_count = trigger_count + 1, last_triggered_at = NOW()
        WHERE id = :id
    """), {'id': canary.id})
    session.commit()
    return True


def canary_alerts(session, hours=24):
    """
    Recent triggers, newest first.

    The original version wrote ``INTERVAL ':hours hours'`` -- a bind parameter
    inside a string literal is never substituted, so the query failed on every
    call and the broad ``except`` around it returned an empty list: "no alerts".
    A cutoff computed in Python avoids both the bug and the silence.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    return session.execute(text("""
        SELECT ct.id, ct.token_type, ct.description, tr.ip_address, tr.user_agent, tr.triggered_at
        FROM canary_tokens ct
        JOIN canary_triggers tr ON ct.id = tr.canary_id
        WHERE tr.triggered_at > :since
        ORDER BY tr.triggered_at DESC
    """), {'since': since}).fetchall()
