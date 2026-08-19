"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Notification Model
Purpose: User notifications for orders, messages, security alerts
"""

import uuid
from datetime import datetime
from app.models.types import UUID
from sqlalchemy import Index

from app import db


class NotificationType:
    """Notification type constants"""
    ORDER_RECEIVED = 'order_received'
    ORDER_PAID = 'order_paid'
    ORDER_SHIPPED = 'order_shipped'
    ORDER_DELIVERED = 'order_delivered'
    ORDER_COMPLETED = 'order_completed'
    ORDER_DISPUTED = 'order_disputed'
    ORDER_CANCELLED = 'order_cancelled'

    NEW_MESSAGE = 'new_message'

    NEW_REVIEW = 'new_review'

    SECURITY_ALERT = 'security_alert'
    LOGIN_NEW_DEVICE = 'login_new_device'
    PASSWORD_CHANGED = 'password_changed'
    TWO_FA_ENABLED = '2fa_enabled'

    SYSTEM = 'system'
    PROMOTION = 'promotion'


class Notification(db.Model):
    """
    User notification model:
    - UUID primary keys
    - Multiple notification types
    - Read/unread tracking
    - Action URLs
    - Auto-expiration
    """

    __tablename__ = 'notifications'

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False, index=True)

    # Notification content
    notification_type = db.Column(db.String(50), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)

    # Related object (optional)
    related_type = db.Column(db.String(50), nullable=True)  # 'order', 'message', 'product'
    related_id = db.Column(UUID(as_uuid=True), nullable=True)

    # Action URL (optional)
    action_url = db.Column(db.String(500), nullable=True)
    action_text = db.Column(db.String(100), nullable=True)

    # Status
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    read_at = db.Column(db.DateTime, nullable=True)

    # Priority
    priority = db.Column(db.String(20), default='normal')  # low, normal, high, urgent

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)  # Auto-delete after

    # Relationships
    user = db.relationship('User', backref=db.backref('notifications', lazy='dynamic'))

    # Indexes
    __table_args__ = (
        Index('idx_notification_user_unread', user_id, is_read),
        Index('idx_notification_created', created_at.desc()),
    )

    def __repr__(self):
        return f'<Notification {self.id} - {self.notification_type}>'

    def mark_as_read(self):
        """Mark notification as read"""
        if not self.is_read:
            self.is_read = True
            self.read_at = datetime.utcnow()
            db.session.commit()

    def is_expired(self):
        """Check if notification has expired"""
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return True
        return False

    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': str(self.id),
            'type': self.notification_type,
            'title': self.title,
            'message': self.message,
            'is_read': self.is_read,
            'priority': self.priority,
            'action_url': self.action_url,
            'action_text': self.action_text,
            'created_at': self.created_at.isoformat(),
            'related_type': self.related_type,
            'related_id': str(self.related_id) if self.related_id else None
        }

    @classmethod
    def create(cls, user_id, notification_type, title, message,
               related_type=None, related_id=None,
               action_url=None, action_text=None,
               priority='normal', expires_days=30):
        """
        Create new notification

        Args:
            user_id: Target user ID
            notification_type: Type from NotificationType
            title: Notification title
            message: Notification message
            related_type: Related object type (optional)
            related_id: Related object ID (optional)
            action_url: URL for action button (optional)
            action_text: Text for action button (optional)
            priority: Priority level
            expires_days: Days until expiration (0 = no expiration)

        Returns:
            Notification: Created notification
        """
        from datetime import timedelta

        expires_at = None
        if expires_days > 0:
            expires_at = datetime.utcnow() + timedelta(days=expires_days)

        notification = cls(
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            message=message,
            related_type=related_type,
            related_id=related_id,
            action_url=action_url,
            action_text=action_text,
            priority=priority,
            expires_at=expires_at
        )

        db.session.add(notification)
        db.session.commit()

        return notification

    @classmethod
    def get_unread_count(cls, user_id):
        """Get count of unread notifications for user"""
        return cls.query.filter_by(user_id=user_id, is_read=False).count()

    @classmethod
    def get_recent(cls, user_id, limit=10, include_read=False):
        """
        Get recent notifications for user

        Args:
            user_id: User ID
            limit: Max notifications to return
            include_read: Whether to include read notifications

        Returns:
            list: Notifications
        """
        query = cls.query.filter_by(user_id=user_id)

        if not include_read:
            query = query.filter_by(is_read=False)

        return query.order_by(cls.created_at.desc()).limit(limit).all()

    @classmethod
    def mark_all_read(cls, user_id):
        """Mark all notifications as read for user"""
        cls.query.filter_by(user_id=user_id, is_read=False).update({
            'is_read': True,
            'read_at': datetime.utcnow()
        })
        db.session.commit()

    @classmethod
    def cleanup_expired(cls):
        """Delete expired notifications"""
        cls.query.filter(cls.expires_at < datetime.utcnow()).delete()
        db.session.commit()


# =============================================================================
# Notification Helper Functions
# =============================================================================

def notify_order_status(order, old_status, new_status):
    """Send notification for order status change"""
    from flask import url_for

    # Notification to buyer
    buyer_messages = {
        'paid': ('Payment Confirmed', f'Your order #{str(order.id)[:8]} has been confirmed.'),
        'shipped': ('Order Shipped', f'Your order #{str(order.id)[:8]} has been shipped!'),
        'delivered': ('Delivery Confirmed', f'Your order #{str(order.id)[:8]} was marked as delivered.'),
        'completed': ('Order Completed', f'Your order #{str(order.id)[:8]} is complete. Thank you!'),
        'disputed': ('Dispute Opened', f'A dispute has been opened for order #{str(order.id)[:8]}.'),
        'cancelled': ('Order Cancelled', f'Your order #{str(order.id)[:8]} has been cancelled.'),
    }

    # Notification to vendor
    vendor_messages = {
        'pending': ('New Order!', f'You have a new order #{str(order.id)[:8]}.'),
        'paid': ('Payment Received', f'Payment confirmed for order #{str(order.id)[:8]}.'),
        'disputed': ('Dispute Opened', f'A dispute has been opened for order #{str(order.id)[:8]}.'),
        'completed': ('Order Completed', f'Order #{str(order.id)[:8]} completed. Funds released!'),
    }

    try:
        # Notify buyer
        if new_status in buyer_messages:
            title, message = buyer_messages[new_status]
            Notification.create(
                user_id=order.buyer_id,
                notification_type=f'order_{new_status}',
                title=title,
                message=message,
                related_type='order',
                related_id=order.id,
                action_url=url_for('buyer.order_detail', order_id=order.id),
                action_text='View Order'
            )

        # Notify vendor
        if new_status in vendor_messages:
            title, message = vendor_messages[new_status]
            Notification.create(
                user_id=order.vendor_id,
                notification_type=f'order_{new_status}',
                title=title,
                message=message,
                related_type='order',
                related_id=order.id,
                action_url=url_for('vendor.order_detail', order_id=order.id),
                action_text='View Order'
            )

    except Exception as e:
        from flask import current_app
        current_app.logger.error(f'Failed to send order notification: {e}')


def notify_new_message(sender, recipient, thread):
    """Send notification for new message"""
    from flask import url_for

    try:
        Notification.create(
            user_id=recipient.id,
            notification_type=NotificationType.NEW_MESSAGE,
            title='New Message',
            message=f'You have a new message from {sender.username}.',
            related_type='message',
            related_id=thread.id,
            action_url=url_for('messages.thread', thread_id=thread.id),
            action_text='Read Message'
        )
    except Exception as e:
        from flask import current_app
        current_app.logger.error(f'Failed to send message notification: {e}')


def notify_security_event(user_id, event_type, title, message, priority='high'):
    """Send security alert notification"""
    try:
        Notification.create(
            user_id=user_id,
            notification_type=NotificationType.SECURITY_ALERT,
            title=title,
            message=message,
            priority=priority,
            action_url='/account/security',
            action_text='Security Settings'
        )
    except Exception as e:
        from flask import current_app
        current_app.logger.error(f'Failed to send security notification: {e}')
