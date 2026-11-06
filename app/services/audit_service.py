"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Audit Service
Purpose: Centralized audit logging
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text
from flask import request, current_app
from app import db


def _bindable(value):
    """
    Make a parameter safe for every driver.

    psycopg2 adapts uuid.UUID and Decimal; sqlite3 does not, and neither adapts
    a dict -- metadata passed as a dict made the INSERT fail, and the event was
    lost without anyone noticing (the error was caught and logged at most).
    """
    if isinstance(value, (uuid.UUID, Decimal)):
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return value


def _write(sql, params, commit):
    """
    Execute one audit INSERT inside a SAVEPOINT.

    Every audit function used to end with db.session.commit() and, on failure,
    db.session.rollback(). Both acted on the CALLER's transaction:

    * the commit persisted whatever the caller had changed so far -- an audit
      call in the middle of checkout committed half an order;
    * the rollback threw the caller's pending work away, silently, whenever
      an audit row could not be written.

    The savepoint confines a failure to the audit row itself. ``commit`` is
    True only for events that must be recorded even if nothing else is
    (a failed login, a security event); order and message events are part of
    the action they describe and are committed -- or rolled back -- with it.
    Such committing calls therefore belong AFTER the caller's own commit,
    never in the middle of a business transaction.
    """
    with db.session.begin_nested():
        db.session.execute(text(sql), {k: _bindable(v) for k, v in params.items()})
    if commit:
        db.session.commit()


def log_auth_event(username, user_id, action, ip_address=None, session_id=None, failure_reason=None, metadata=None):
    """
    Log authentication event

    Args:
        username: Username
        user_id: User ID
        action: Action type (login_success, login_failed, etc.)
        ip_address: Client IP address
        session_id: Session ID (optional)
        failure_reason: Failure reason (optional)
        metadata: Additional metadata (optional)
    """
    try:
        user_agent = request.headers.get('User-Agent', '') if request else ''

        _write(
            (
                "SELECT log_auth_event(:username, :user_id, :action, :ip_address, "
                ":user_agent, :session_id, :failure_reason, :metadata)"
            ),
            {
                'username': username,
                'user_id': user_id,
                'action': action,
                'ip_address': ip_address or (request.remote_addr if request else None),
                'user_agent': user_agent,
                'session_id': session_id,
                'failure_reason': failure_reason,
                'metadata': metadata
            },
            commit=True,
        )
    except Exception as e:
        current_app.logger.error(f'Failed to log auth event: {e}')


def log_security_event(event_type, severity, description, user_id=None, ip_address=None, metadata=None):
    """
    Log security event

    Args:
        event_type: Type of security event
        severity: Severity level (critical, high, medium, low, info)
        description: Event description
        user_id: User ID (optional)
        ip_address: Client IP (optional)
        metadata: Additional metadata (optional)
    """
    try:
        _write(
            (
                "SELECT log_security_event(:event_type, :severity, 'application', "
                ":description, :user_id, :ip_address, :metadata)"
            ),
            {
                'event_type': event_type,
                'severity': severity,
                'description': description,
                'user_id': user_id,
                'ip_address': ip_address or (request.remote_addr if request else None),
                'metadata': metadata
            },
            commit=True,
        )
    except Exception as e:
        current_app.logger.error(f'Failed to log security event: {e}')


def log_order_event(order_id, action, metadata=None):
    """
    Log order/transaction event

    Args:
        order_id: Order ID
        action: Action type
        metadata: Additional metadata (optional)
    """
    try:
        from app.models.order import Order
        order = db.session.get(Order, order_id)

        if not order:
            return

        _write(
            (
                "INSERT INTO transaction_audit (transaction_id, buyer_id, vendor_id, "
                "product_id, action, amount, status, metadata) "
                "VALUES (:transaction_id, :buyer_id, :vendor_id, :product_id, "
                ":action, :amount, :status, :metadata)"
            ),
            {
                'transaction_id': order.id,
                'buyer_id': order.buyer_id,
                'vendor_id': order.vendor_id,
                'product_id': order.product_id,
                'action': action,
                'amount': order.total_price,
                'status': order.status,
                'metadata': metadata
            },
            commit=False,
        )
    except Exception as e:
        current_app.logger.error(f'Failed to log order event: {e}')


def log_message_event(message_id, sender_id, recipient_id, action):
    """
    Log message event

    Args:
        message_id: Message ID
        sender_id: Sender user ID
        recipient_id: Recipient user ID
        action: Action type (sent, read, deleted)
    """
    try:
        from app.models.message import Message
        message = db.session.get(Message, message_id)

        _write(
            (
                "INSERT INTO message_audit (message_id, sender_id, recipient_id, action, encrypted) "
                "VALUES (:message_id, :sender_id, :recipient_id, :action, :encrypted)"
            ),
            {
                'message_id': message_id,
                'sender_id': sender_id,
                'recipient_id': recipient_id,
                'action': action,
                'encrypted': message.is_encrypted if message else True
            },
            commit=False,
        )
    except Exception as e:
        current_app.logger.error(f'Failed to log message event: {e}')


def log_admin_action(admin_user_id, action, target_type, target_id, before_state=None, after_state=None, reason=None):
    """
    Log admin action for accountability

    Args:
        admin_user_id: Admin user ID
        action: Action performed
        target_type: Type of target (user, product, order, etc.)
        target_id: Target ID
        before_state: State before action (optional)
        after_state: State after action (optional)
        reason: Reason for action (optional)
    """
    try:
        import json

        _write(
            (
                "INSERT INTO admin_actions (admin_user_id, action, target_type, target_id, "
                "before_state, after_state, reason, ip_address) "
                "VALUES (:admin_user_id, :action, :target_type, :target_id, "
                ":before_state, :after_state, :reason, :ip_address)"
            ),
            {
                'admin_user_id': admin_user_id,
                'action': action,
                'target_type': target_type,
                'target_id': target_id,
                'before_state': json.dumps(before_state) if before_state else None,
                'after_state': json.dumps(after_state) if after_state else None,
                'reason': reason,
                'ip_address': request.remote_addr if request else None
            },
            commit=True,
        )
    except Exception as e:
        current_app.logger.error(f'Failed to log admin action: {e}')


def get_user_audit_log(user_id, limit=100):
    """
    Get audit log for specific user

    Args:
        user_id: User ID
        limit: Maximum number of entries

    Returns:
        list: Audit log entries
    """
    try:
        result = db.session.execute(
            text(
                "SELECT * FROM audit_log WHERE user_id = :user_id "
                "ORDER BY timestamp DESC LIMIT :limit"
            ),
            {'user_id': user_id, 'limit': limit}
        )
        return result.fetchall()
    except Exception as e:
        current_app.logger.error(f'Failed to get audit log: {e}')
        return []


def log_pgp_key_event(user_id, action, key_fingerprint=None, created_by='user', source='generated', metadata=None):
    """
    Log PGP key event for audit trail

    Args:
        user_id: User ID
        action: Action type (key_generated, key_uploaded, key_updated, key_deleted)
        key_fingerprint: PGP key fingerprint (optional)
        created_by: Who created the key (user, admin, cli)
        source: How key was created (generated, uploaded, imported)
        metadata: Additional metadata (optional)
    """
    try:
        import json

        # Build metadata
        audit_metadata = {
            'created_by': created_by,
            'source': source
        }

        if key_fingerprint:
            audit_metadata['fingerprint'] = key_fingerprint

        if metadata:
            audit_metadata.update(metadata)

        # Log to general audit_log
        _write(
            (
                "INSERT INTO audit_log (user_id, action, table_name, record_id, "
                "new_values, status, severity, metadata, ip_address, user_agent) "
                "VALUES (:user_id, :action, 'users', :record_id, :new_values, "
                "'success', 'info', :metadata, :ip_address, :user_agent)"
            ),
            {
                'user_id': user_id,
                'action': action,
                'record_id': user_id,
                'new_values': json.dumps({
                    'fingerprint': key_fingerprint,
                    'source': source,
                    'created_by': created_by
                }),
                'metadata': json.dumps(audit_metadata),
                'ip_address': request.remote_addr if request else None,
                'user_agent': request.headers.get('User-Agent', '') if request else 'CLI'
            },
            commit=True,
        )
        current_app.logger.info(f'PGP key event logged: {action} for user {user_id}')

    except Exception as e:
        current_app.logger.error(f'Failed to log PGP key event: {e}')


def get_recent_security_events(hours=24, severity=None):
    """
    Get recent security events

    Args:
        hours: Look back period in hours
        severity: Filter by severity (optional)

    Returns:
        list: Security events
    """
    try:
        # Was `NOW() - INTERVAL ':hours hours'`: a bind parameter inside a quoted
        # literal is never substituted, so this raised, was caught, and every
        # caller got [] -- "no events" whatever had happened. The cutoff is bound
        # as a timezone-aware value (the column is TIMESTAMPTZ; see jobs.security_scan).
        query = """
            SELECT * FROM security_events
            WHERE timestamp > :since
        """

        if severity:
            query += " AND severity = :severity"

        query += " ORDER BY timestamp DESC LIMIT 100"

        result = db.session.execute(
            text(query),
            {'since': datetime.now(timezone.utc) - timedelta(hours=hours), 'severity': severity}
        )
        return result.fetchall()
    except Exception as e:
        current_app.logger.error(f'Failed to get security events: {e}')
        return []
