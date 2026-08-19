"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Message Model
Purpose: PGP-encrypted messaging system for buyer-vendor communication
"""

import uuid
from datetime import datetime, timedelta
from app.models.types import UUID
from sqlalchemy import Index

from app import db


class MessageThread(db.Model):
    """
    Message thread between any two users (buyer-vendor, admin-user, etc.)
    Supports:
    - Admin ↔ Buyer
    - Admin ↔ Vendor
    - Buyer ↔ Vendor
    - Admin ↔ Admin
    """

    __tablename__ = 'message_threads'

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Participants (flexible - any user can message any user)
    participant_1_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False)
    participant_2_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False)

    # Legacy fields (for backwards compatibility during migration)
    buyer_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=True)
    vendor_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=True)

    # Optional order association
    order_id = db.Column(UUID(as_uuid=True), db.ForeignKey('orders.id'), nullable=True)

    # Thread metadata
    subject = db.Column(db.String(200), nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_message_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    messages = db.relationship('Message', backref='thread', lazy='dynamic',
                              cascade='all, delete-orphan',
                              order_by='Message.created_at.desc()')

    participant_1 = db.relationship('User', foreign_keys=[participant_1_id])
    participant_2 = db.relationship('User', foreign_keys=[participant_2_id])

    # Legacy relationships
    buyer = db.relationship('User', foreign_keys=[buyer_id])
    vendor = db.relationship('User', foreign_keys=[vendor_id])

    # Indexes
    __table_args__ = (
        Index('idx_thread_participant_1', participant_1_id),
        Index('idx_thread_participant_2', participant_2_id),
        Index('idx_thread_order', order_id),
        # Ensure unique thread per participant pair (ordered)
        db.CheckConstraint('participant_1_id != participant_2_id', name='chk_different_participants'),
    )

    def __repr__(self):
        return f'<MessageThread {self.id}>'

    def get_participant(self, user_id):
        """
        Get the other participant in the thread

        Args:
            user_id: Current user's ID

        Returns:
            User: The other participant
        """
        if str(self.participant_1_id) == str(user_id):
            return self.participant_2
        return self.participant_1

    def get_unread_count(self, user_id):
        """
        Get unread message count for user

        Args:
            user_id: User ID

        Returns:
            int: Number of unread messages
        """
        return self.messages.filter_by(
            recipient_id=user_id,
            is_read=False
        ).count()

    def mark_all_read(self, user_id):
        """
        Mark all messages as read for user

        Args:
            user_id: User ID
        """
        self.messages.filter_by(
            recipient_id=user_id,
            is_read=False
        ).update({'is_read': True, 'read_at': datetime.utcnow()})
        db.session.commit()

    def is_participant(self, user_id):
        """
        Check if user is participant in thread

        Args:
            user_id: User ID to check

        Returns:
            bool: True if user is participant
        """
        return str(self.participant_1_id) == str(user_id) or \
               str(self.participant_2_id) == str(user_id)

    @staticmethod
    def find_or_create_thread(participant_1_id, participant_2_id, order_id=None, subject=None):
        """
        Find existing thread or create new one

        Args:
            participant_1_id: First participant ID
            participant_2_id: Second participant ID
            order_id: Optional order ID
            subject: Optional thread subject

        Returns:
            MessageThread: Existing or new thread
        """
        # Ensure consistent ordering (lower UUID first)
        if str(participant_1_id) > str(participant_2_id):
            participant_1_id, participant_2_id = participant_2_id, participant_1_id

        # Try to find existing thread
        thread = MessageThread.query.filter(
            db.or_(
                db.and_(
                    MessageThread.participant_1_id == participant_1_id,
                    MessageThread.participant_2_id == participant_2_id
                ),
                db.and_(
                    MessageThread.participant_1_id == participant_2_id,
                    MessageThread.participant_2_id == participant_1_id
                )
            )
        ).first()

        if thread:
            return thread

        # Create new thread
        thread = MessageThread(
            id=uuid.uuid4(),
            participant_1_id=participant_1_id,
            participant_2_id=participant_2_id,
            order_id=order_id,
            subject=subject,
            is_active=True
        )

        db.session.add(thread)
        db.session.commit()

        return thread

    def to_dict(self, current_user_id=None):
        """Convert thread to dictionary"""
        data = {
            'id': str(self.id),
            'subject': self.subject,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat(),
            'last_message_at': self.last_message_at.isoformat(),
            'order_id': str(self.order_id) if self.order_id else None
        }

        if current_user_id:
            other_participant = self.get_participant(current_user_id)
            data['participant'] = {
                'id': str(other_participant.id),
                'username': other_participant.username,
                'role': other_participant.role
            }
            data['unread_count'] = self.get_unread_count(current_user_id)

        return data


class Message(db.Model):
    """
    Individual message with PGP encryption:
    - End-to-end encrypted content
    - Encrypted with recipient's public key
    - Auto-deletion after retention period
    - Audit trail for security
    """

    __tablename__ = 'messages'

    # Primary identification
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id = db.Column(UUID(as_uuid=True), db.ForeignKey('message_threads.id'), nullable=False)

    # Participants
    sender_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False)
    recipient_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False)

    # Optional order association
    order_id = db.Column(UUID(as_uuid=True), db.ForeignKey('orders.id'), nullable=True)

    # Message content (encrypted)
    # Encrypted with recipient's PGP public key
    content_encrypted = db.Column(db.LargeBinary, nullable=False)
    is_encrypted = db.Column(db.Boolean, default=True)

    # Message metadata (not encrypted)
    has_attachment = db.Column(db.Boolean, default=False)
    attachment_filename = db.Column(db.String(255), nullable=True)

    # Read status
    is_read = db.Column(db.Boolean, default=False)
    read_at = db.Column(db.DateTime, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)

    # Deletion (OPSEC)
    is_deleted_by_sender = db.Column(db.Boolean, default=False)
    is_deleted_by_recipient = db.Column(db.Boolean, default=False)

    # Indexes
    __table_args__ = (
        Index('idx_message_thread', thread_id, created_at.desc()),
        Index('idx_message_sender', sender_id),
        Index('idx_message_recipient', recipient_id),
        Index('idx_message_expires', expires_at),
    )

    def __repr__(self):
        return f'<Message {self.id}>'

    # =============================================================================
    # Message Encryption (PGP)
    # =============================================================================

    def encrypt_and_set_content(self, plain_text, recipient_public_key):
        """
        Encrypt message content with recipient's PGP public key

        Args:
            plain_text: Plain text message content
            recipient_public_key: Recipient's PGP public key

        Raises:
            ValueError: If encryption fails
        """
        import gnupg

        gpg = gnupg.GPG()

        try:
            # Import recipient's public key
            gpg.import_keys(recipient_public_key)

            # Encrypt message
            encrypted = gpg.encrypt(plain_text, recipient_public_key)

            if not encrypted.ok:
                raise ValueError(f"Encryption failed: {encrypted.status}")

            self.content_encrypted = str(encrypted).encode('utf-8')
            self.is_encrypted = True

        except Exception as e:
            raise ValueError(f"Failed to encrypt message: {str(e)}")

    def decrypt_content(self, private_key, passphrase=None):
        """
        Decrypt message content with recipient's private key

        Args:
            private_key: Recipient's PGP private key
            passphrase: Private key passphrase (if any)

        Returns:
            str: Decrypted message content

        Raises:
            ValueError: If decryption fails
        """
        import gnupg

        if not self.is_encrypted:
            return self.content_encrypted.decode('utf-8')

        gpg = gnupg.GPG()

        try:
            # Import private key
            gpg.import_keys(private_key)

            # Decrypt message
            decrypted = gpg.decrypt(
                self.content_encrypted.decode('utf-8'),
                passphrase=passphrase
            )

            if not decrypted.ok:
                raise ValueError(f"Decryption failed: {decrypted.status}")

            return str(decrypted)

        except Exception as e:
            raise ValueError(f"Failed to decrypt message: {str(e)}")

    # =============================================================================
    # Message Lifecycle
    # =============================================================================

    def mark_as_read(self):
        """Mark message as read"""
        if not self.is_read:
            self.is_read = True
            self.read_at = datetime.utcnow()
            db.session.commit()

    def delete_for_user(self, user_id):
        """
        Delete message for specific user

        Args:
            user_id: User ID
        """
        if str(self.sender_id) == str(user_id):
            self.is_deleted_by_sender = True
        elif str(self.recipient_id) == str(user_id):
            self.is_deleted_by_recipient = True

        # If deleted by both, actually delete the message
        if self.is_deleted_by_sender and self.is_deleted_by_recipient:
            db.session.delete(self)

        db.session.commit()

    def is_visible_to(self, user_id):
        """
        Check if message is visible to user

        Args:
            user_id: User ID

        Returns:
            bool: True if visible, False otherwise
        """
        if str(self.sender_id) == str(user_id):
            return not self.is_deleted_by_sender
        elif str(self.recipient_id) == str(user_id):
            return not self.is_deleted_by_recipient
        return False

    def should_auto_delete(self):
        """Check if message should be auto-deleted"""
        if not self.expires_at:
            return False
        return datetime.utcnow() >= self.expires_at

    # =============================================================================
    # Utility Methods
    # =============================================================================

    def to_dict(self, user_id=None, include_content=False, private_key=None, passphrase=None):
        """
        Convert message to dictionary

        Args:
            user_id: Current user ID
            include_content: Whether to include decrypted content
            private_key: Private key for decryption (if include_content=True)
            passphrase: Passphrase for private key

        Returns:
            dict: Message data
        """
        data = {
            'id': str(self.id),
            'thread_id': str(self.thread_id),
            'sender_id': str(self.sender_id),
            'recipient_id': str(self.recipient_id),
            'is_encrypted': self.is_encrypted,
            'has_attachment': self.has_attachment,
            'is_read': self.is_read,
            'read_at': self.read_at.isoformat() if self.read_at else None,
            'created_at': self.created_at.isoformat(),
            'expires_at': self.expires_at.isoformat() if self.expires_at else None
        }

        # Include sender/recipient usernames
        data['sender_username'] = self.sender.username
        data['recipient_username'] = self.recipient.username

        # Decrypt content if requested and user has access
        if include_content and private_key and str(self.recipient_id) == str(user_id):
            try:
                data['content'] = self.decrypt_content(private_key, passphrase)
            except ValueError as e:
                data['content'] = f"[Decryption failed: {str(e)}]"
        elif include_content:
            data['content'] = "[Encrypted]"

        return data


# =============================================================================
# Database Events
# =============================================================================

from sqlalchemy import event


@event.listens_for(Message, 'before_insert')
def set_message_expiry(mapper, connection, target):
    """Set message expiry date before insert"""
    from flask import current_app

    if not target.expires_at:
        retention_days = current_app.config.get('MESSAGE_RETENTION_DAYS', 30)
        target.expires_at = datetime.utcnow() + timedelta(days=retention_days)


@event.listens_for(Message, 'after_insert')
def update_thread_timestamp(mapper, connection, target):
    """Update thread's last message timestamp"""
    from sqlalchemy import text
    connection.execute(
        text(
            "UPDATE message_threads SET last_message_at = :timestamp "
            "WHERE id = :thread_id"
        ),
        {
            # Bind ids as str: psycopg2 adapts uuid.UUID, other drivers do not.
            'timestamp': target.created_at,
            'thread_id': str(target.thread_id)
        }
    )


@event.listens_for(Message, 'after_insert')
def audit_message_sent(mapper, connection, target):
    """Audit log for message sent"""
    from sqlalchemy import text
    connection.execute(
        text(
            "INSERT INTO message_audit (message_id, sender_id, recipient_id, action, encrypted) "
            "VALUES (:message_id, :sender_id, :recipient_id, 'sent', :encrypted)"
        ),
        {
            'message_id': str(target.id),
            'sender_id': str(target.sender_id),
            'recipient_id': str(target.recipient_id),
            'encrypted': target.is_encrypted
        }
    )
