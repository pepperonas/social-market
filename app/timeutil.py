"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Time helpers.

``datetime.utcnow()`` is deprecated since Python 3.12. Its documented
replacement, ``datetime.now(timezone.utc)``, returns an *aware* datetime, and
that is not a drop-in change here: every ``DateTime`` column in this schema is
naive (``TIMESTAMP WITHOUT TIME ZONE``) and holds UTC by convention. Mixing the
two raises ``TypeError: can't compare offset-naive and offset-aware datetimes``
the first time an aware "now" meets a value read back from the database —
in an expiry check, a lockout window, an escrow deadline.

So the helper keeps the old *value* (naive UTC) and only replaces the
deprecated *call*. Migrating the schema to aware timestamps is a separate,
deliberate change: columns, comparisons and tests would have to move together.
"""
from datetime import datetime, timezone


def utcnow():
    """Current time in UTC as a naive datetime (same value as the old utcnow())."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
