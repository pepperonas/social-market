"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Audit Service
Purpose: Centralized audit logging
"""

from sqlalchemy import text
from flask import request, current_app
from app import db


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

        db.session.execute(
            text(
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
            }
        )
        db.session.commit()
    except Exception as e:
        current_app.logger.error(f'Failed to log auth event: {e}')
        db.session.rollback()


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
        db.session.execute(
            text(
                "SELECT log_security_event(:event_type, :severity, 'application', "
                ":user_id, :ip_address, :description, :metadata)"
            ),
            {
                'event_type': event_type,
                'severity': severity,
                'user_id': user_id,
                'ip_address': ip_address or (request.remote_addr if request else None),
                'description': description,
                'metadata': metadata
            }
        )
        db.session.commit()
    except Exception as e:
        current_app.logger.error(f'Failed to log security event: {e}')
        db.session.rollback()


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
        order = Order.query.get(order_id)

        if not order:
            return

        db.session.execute(
            text(
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
            }
        )
        db.session.commit()
    except Exception as e:
        current_app.logger.error(f'Failed to log order event: {e}')
        db.session.rollback()


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
        message = Message.query.get(message_id)

        db.session.execute(
            text(
                "INSERT INTO message_audit (message_id, sender_id, recipient_id, action, encrypted) "
                "VALUES (:message_id, :sender_id, :recipient_id, :action, :encrypted)"
            ),
            {
                'message_id': message_id,
                'sender_id': sender_id,
                'recipient_id': recipient_id,
                'action': action,
                'encrypted': message.is_encrypted if message else True
            }
        )
        db.session.commit()
    except Exception as e:
        current_app.logger.error(f'Failed to log message event: {e}')
        db.session.rollback()


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

        db.session.execute(
            text(
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
            }
        )
        db.session.commit()
    except Exception as e:
        current_app.logger.error(f'Failed to log admin action: {e}')
        db.session.rollback()


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
        query = """
            SELECT * FROM security_events
            WHERE timestamp > NOW() - INTERVAL ':hours hours'
        """

        if severity:
            query += " AND severity = :severity"

        query += " ORDER BY timestamp DESC LIMIT 100"

        result = db.session.execute(
            text(query),
            {'hours': hours, 'severity': severity}
        )
        return result.fetchall()
    except Exception as e:
        current_app.logger.error(f'Failed to get security events: {e}')
        return []
