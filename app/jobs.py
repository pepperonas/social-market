"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Background jobs

Plain functions, one registry, one entry point (`flask run-job NAME ...`).

Until review round 3 these lived in app/tasks.py as Celery tasks. That module
set `celery = None` and then decorated every task with `@celery.task`, so it
raised AttributeError on import -- and since nothing imported it, nobody
noticed. The docker-compose worker loaded an empty Celery instance, the beat
schedule was never applied, and the live server ran no worker at all. Escrow
auto-finalisation, expiry of messages and the failed-login scan had never run.

Keeping the jobs free of Celery means they can be called -- and tested -- the
same way everywhere: by systemd timers on the server (deploy/systemd/), by the
thin Celery wrapper in app/tasks.py under docker-compose, and by the suite.

Every job raises on failure. The old tasks returned {'success': False}, which
no scheduler can tell apart from success.
"""

from collections import namedtuple
from datetime import datetime, timedelta, timezone

from flask import current_app
from sqlalchemy import text

from app import db
from app.timeutil import utcnow

# schedule: 'hourly' or 'daily' -- the timer that runs the job (deploy/systemd/)
Job = namedtuple('Job', 'func schedule description')


def auto_finalize_orders():
    """Complete delivered orders whose dispute window has run out (releases escrow)."""
    from app.services.escrow_service import EscrowService

    return {'finalized': EscrowService.process_auto_finalization()}


def expire_unpaid_orders():
    """
    Cancel orders that were never paid, so their reserved stock returns.

    Since round 3 an order holds its stock from the moment it is placed. Without
    this job a single abandoned checkout would take the last units of a product
    off the market for good.
    """
    from app.models.order import Order, OrderStatus

    hours = current_app.config['ORDER_PAYMENT_TIMEOUT_HOURS']
    cutoff = utcnow() - timedelta(hours=hours)
    stale = Order.query.filter(Order.status == OrderStatus.PENDING.value,
                               Order.created_at < cutoff).all()

    cancelled, failed = 0, 0
    for order in stale:
        try:
            order.transition_to(OrderStatus.CANCELLED)
            order.admin_notes = f'Cancelled automatically: unpaid after {hours} hours'
            db.session.commit()
            cancelled += 1
        except Exception as exc:
            # One order changed underneath us (paid in the meantime, say) must
            # not stop the others -- but it must not go unnoticed either.
            db.session.rollback()
            failed += 1
            current_app.logger.warning('Could not expire order %s: %s', order.id, exc)

    return {'cancelled': cancelled, 'failed': failed}


def purge_expired_messages():
    """Delete messages past their expires_at (MESSAGE_RETENTION_DAYS)."""
    from app.models.message import Message

    deleted = Message.query.filter(Message.expires_at < utcnow()) \
        .delete(synchronize_session=False)
    db.session.commit()
    return {'deleted': deleted}


def purge_expired_notifications():
    """Delete notifications past their expires_at."""
    from app.models.notification import Notification

    deleted = Notification.query.filter(Notification.expires_at < utcnow()) \
        .delete(synchronize_session=False)
    db.session.commit()
    return {'deleted': deleted}


# Failed authentication attempts per IP within the window that count as a burst
SCAN_WINDOW = timedelta(hours=1)
SCAN_THRESHOLD = 10


def security_scan():
    """
    Report IP addresses with a burst of failed authentication attempts.

    The old query matched `action = 'login_failed'`. No such action is ever
    written -- the app logs 'login_failed_password', 'login_failed_locked',
    '2fa_failed', 'reauth_failed' -- so the scan could not find anything. It
    also used a PostgreSQL-only INTERVAL literal; the cutoff is now bound.

    The cutoff is timezone-AWARE on purpose. auth_log.timestamp is TIMESTAMPTZ,
    and the live database session runs in Europe/Berlin: a naive UTC value is
    read as Berlin local time there, which silently stretched the one-hour
    window to two hours in winter and three in summer. (Not visible in the
    SQLite test suite, which has no time zones at all -- checked against the
    real database instead.)
    """
    from app.services.audit_service import log_security_event

    rows = db.session.execute(text("""
        SELECT ip_address, COUNT(*) AS failures
        FROM auth_log
        WHERE (action LIKE 'login_failed%' OR action IN ('2fa_failed', 'reauth_failed'))
          AND timestamp > :since
          AND ip_address IS NOT NULL
        GROUP BY ip_address
        HAVING COUNT(*) > :threshold
    """), {'since': datetime.now(timezone.utc) - SCAN_WINDOW,
          'threshold': SCAN_THRESHOLD}).fetchall()

    suspicious = [str(ip) for ip, _ in rows]
    for ip, failures in rows:
        log_security_event(
            'suspicious_failed_logins', 'high',
            f'{failures} failed authentication attempts from {ip} in the last hour',
            ip_address=str(ip))

    return {'suspicious_ips': suspicious}


JOBS = {
    'auto-finalize-orders': Job(auto_finalize_orders, 'hourly',
                                'Complete delivered orders after the dispute window'),
    'expire-unpaid-orders': Job(expire_unpaid_orders, 'hourly',
                                'Cancel unpaid orders, return their stock'),
    'security-scan': Job(security_scan, 'hourly',
                         'Report IPs with bursts of failed logins'),
    'purge-expired-messages': Job(purge_expired_messages, 'daily',
                                  'Delete messages past their retention'),
    'purge-expired-notifications': Job(purge_expired_notifications, 'daily',
                                       'Delete expired notifications'),
}

# Not jobs of this application any more, and why:
# * create_backup ran /app/scripts/backup.sh -- the database is backed up by the
#   host (pg_dump in the VPS backup), which is where a backup belongs: an app
#   that can delete its own backups is no backup.
# * run_file_integrity_check ran /app/monitoring/file_integrity_monitor.py, a
#   container path. File integrity is the host's job as well.
# * cleanup_rate_limit_logs emptied a table nothing writes to: rate limits live
#   in Redis (Flask-Limiter), the rate_limit_log table is never used.
