"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Celery Tasks
Purpose: Background task processing
"""

from celery import Celery
from celery.schedules import crontab
from flask import current_app


def make_celery(app):
    """Create Celery instance"""
    celery = Celery(
        app.import_name,
        backend=app.config['CELERY_RESULT_BACKEND'],
        broker=app.config['CELERY_BROKER_URL']
    )

    celery.conf.update(app.config)

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery


# Tasks will be initialized in __init__.py
celery = None


@celery.task(name='tasks.process_auto_finalization')
def process_auto_finalization():
    """
    Process auto-finalization for delivered orders
    Runs every hour
    """
    from app.services.escrow_service import get_escrow_service

    try:
        count = get_escrow_service().process_auto_finalization()
        current_app.logger.info(f'Auto-finalization processed: {count} orders')
        return {'success': True, 'count': count}
    except Exception as e:
        current_app.logger.error(f'Auto-finalization failed: {e}')
        return {'success': False, 'error': str(e)}


@celery.task(name='tasks.cleanup_expired_messages')
def cleanup_expired_messages():
    """
    Delete expired messages
    Runs daily
    """
    from datetime import datetime
    from app import db
    from app.models.message import Message

    try:
        deleted = Message.query.filter(
            Message.expires_at < datetime.utcnow()
        ).delete()

        db.session.commit()

        current_app.logger.info(f'Cleaned up {deleted} expired messages')
        return {'success': True, 'deleted': deleted}
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Message cleanup failed: {e}')
        return {'success': False, 'error': str(e)}


@celery.task(name='tasks.cleanup_rate_limit_logs')
def cleanup_rate_limit_logs():
    """
    Clean up old rate limit logs
    Runs daily
    """
    from sqlalchemy import text
    from app import db

    try:
        result = db.session.execute(text("SELECT cleanup_rate_limit_logs()"))
        deleted_count = result.scalar()

        db.session.commit()

        current_app.logger.info(f'Cleaned up {deleted_count} rate limit logs')
        return {'success': True, 'deleted': deleted_count}
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Rate limit cleanup failed: {e}')
        return {'success': False, 'error': str(e)}


@celery.task(name='tasks.run_security_checks')
def run_security_checks():
    """
    Run security checks
    Runs every 6 hours
    """
    from app.services.audit_service import log_security_event

    try:
        # Check for suspicious activity
        # This is a simplified version - could be much more sophisticated

        # Check for excessive failed logins
        from sqlalchemy import text
        from app import db

        result = db.session.execute(text("""
            SELECT ip_address, COUNT(*) as failed_count
            FROM auth_log
            WHERE action = 'login_failed'
              AND timestamp > NOW() - INTERVAL '1 hour'
            GROUP BY ip_address
            HAVING COUNT(*) > 10
        """))

        suspicious_ips = result.fetchall()

        for ip, count in suspicious_ips:
            log_security_event(
                'suspicious_failed_logins',
                'high',
                f'Excessive failed logins from {ip}: {count} attempts',
                ip_address=ip
            )

        current_app.logger.info(f'Security checks completed: {len(suspicious_ips)} suspicious IPs')
        return {'success': True, 'suspicious_ips': len(suspicious_ips)}

    except Exception as e:
        current_app.logger.error(f'Security checks failed: {e}')
        return {'success': False, 'error': str(e)}


@celery.task(name='tasks.create_backup')
def create_backup():
    """
    Create encrypted backup
    Runs daily
    """
    import subprocess

    try:
        result = subprocess.run(
            ['/app/scripts/backup.sh'],
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout
        )

        if result.returncode == 0:
            current_app.logger.info('Backup completed successfully')
            return {'success': True, 'output': result.stdout}
        else:
            current_app.logger.error(f'Backup failed: {result.stderr}')
            return {'success': False, 'error': result.stderr}

    except subprocess.TimeoutExpired:
        current_app.logger.error('Backup timeout')
        return {'success': False, 'error': 'Backup timeout'}
    except Exception as e:
        current_app.logger.error(f'Backup failed: {e}')
        return {'success': False, 'error': str(e)}


@celery.task(name='tasks.run_file_integrity_check')
def run_file_integrity_check():
    """
    Run file integrity check
    Runs every hour
    """
    import subprocess

    try:
        result = subprocess.run(
            ['python', '/app/monitoring/file_integrity_monitor.py', '--check'],
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )

        # FIM returns non-zero if changes detected
        if result.returncode == 0:
            current_app.logger.info('File integrity check: PASSED')
            return {'success': True, 'changes_detected': False}
        else:
            current_app.logger.warning('File integrity check: CHANGES DETECTED')
            from app.services.audit_service import log_security_event
            log_security_event(
                'file_integrity_violation',
                'critical',
                'File integrity check detected unauthorized changes',
                metadata={'output': result.stdout}
            )
            return {'success': True, 'changes_detected': True, 'output': result.stdout}

    except Exception as e:
        current_app.logger.error(f'File integrity check failed: {e}')
        return {'success': False, 'error': str(e)}


# Celery Beat Schedule
def get_celery_schedule():
    """Get Celery Beat schedule"""
    return {
        # Auto-finalization every hour
        'process-auto-finalization': {
            'task': 'tasks.process_auto_finalization',
            'schedule': crontab(minute=0),  # Every hour at :00
        },
        # Cleanup expired messages daily at 2 AM
        'cleanup-expired-messages': {
            'task': 'tasks.cleanup_expired_messages',
            'schedule': crontab(hour=2, minute=0),
        },
        # Cleanup rate limit logs daily at 3 AM
        'cleanup-rate-limit-logs': {
            'task': 'tasks.cleanup_rate_limit_logs',
            'schedule': crontab(hour=3, minute=0),
        },
        # Security checks every 6 hours
        'run-security-checks': {
            'task': 'tasks.run_security_checks',
            'schedule': crontab(minute=0, hour='*/6'),
        },
        # Daily backup at 4 AM
        'create-backup': {
            'task': 'tasks.create_backup',
            'schedule': crontab(hour=4, minute=0),
        },
        # File integrity check every hour
        'run-file-integrity-check': {
            'task': 'tasks.run_file_integrity_check',
            'schedule': crontab(minute=30),  # Every hour at :30
        },
    }
