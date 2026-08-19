"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Portable column types
Purpose: Keep the PostgreSQL schema unchanged while allowing the test suite
         to run on SQLite.

Why this module exists:
    The models used PostgreSQL-only types (``postgresql.UUID``, ``postgresql.INET``)
    directly. SQLite cannot compile either, so the SQLite-based test suite could
    never create its tables. These drop-in replacements render *identical* DDL on
    PostgreSQL and fall back to a portable type elsewhere.

Usage (unchanged at the call sites):
    from app.models.types import UUID, INET
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    last_login_ip = db.Column(INET, nullable=True)
"""

import uuid as _uuid

from sqlalchemy import String, Uuid
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import TypeDecorator


class UUID(TypeDecorator):
    """
    UUID column that renders as native UUID on PostgreSQL (identical DDL to the
    previous ``postgresql.UUID``) and as CHAR(32) elsewhere.

    Also accepts a *string* as a bind value. ``postgresql.UUID`` tolerated that
    -- psycopg2 adapted it -- and call sites rely on it, e.g. looking a user up
    by an id taken from the session (``User.query.get(session['...'])``).
    Plain ``sqlalchemy.Uuid`` would raise AttributeError there.
    """

    impl = Uuid
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or isinstance(value, _uuid.UUID):
            return value
        try:
            return _uuid.UUID(str(value))
        except (ValueError, AttributeError, TypeError):
            # Let the database reject it rather than masking a bad lookup
            return value

# ``INET`` is used bare (not called), so this is deliberately an *instance*.


INET = postgresql.INET().with_variant(String(45), "sqlite")

__all__ = ["UUID", "INET"]
