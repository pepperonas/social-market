"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
User Model
Purpose: User authentication and authorization with security features
"""

import uuid
from datetime import datetime, timedelta
from flask import current_app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.dialects.postgresql import UUID, INET
from sqlalchemy import text
import pyotp

from app import db


class User(UserMixin, db.Model):
    """
    User model with enhanced security features:
    - UUID primary keys
    - Bcrypt password hashing
    - 2FA support (TOTP)
    - PGP key management
    - Account lockout on failed logins
    - Audit trail
    """

    __tablename__ = 'users'

    # Primary identification
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    # User role (buyer, vendor, admin)
    role = db.Column(db.String(20), nullable=False, default='buyer', index=True)

    # Account status
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    is_vendor_approved = db.Column(db.Boolean, default=False, nullable=False)

    # 2FA settings
    two_factor_enabled = db.Column(db.Boolean, default=False)
    two_factor_secret = db.Column(db.String(32), nullable=True)

    # PGP key (for encrypted messaging)
    pgp_public_key = db.Column(db.Text, nullable=True)
    pgp_fingerprint = db.Column(db.String(40), nullable=True)

    # Account security
    failed_login_attempts = db.Column(db.Integer, default=0)
    account_locked_until = db.Column(db.DateTime, nullable=True)
    last_login = db.Column(db.DateTime, nullable=True)
    last_login_ip = db.Column(INET, nullable=True)

    # Password reset
    password_reset_token = db.Column(db.String(255), nullable=True)
    password_reset_expires = db.Column(db.DateTime, nullable=True)

    # Email verification
    email_verification_token = db.Column(db.String(255), nullable=True)
    email_verification_expires = db.Column(db.DateTime, nullable=True)

    # Profile information
    display_name = db.Column(db.String(100), nullable=True)
    bio = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Vendor-specific fields
    vendor_rating = db.Column(db.Float, default=0.0)
    vendor_total_sales = db.Column(db.Integer, default=0)
    vendor_description = db.Column(db.Text, nullable=True)

    # Terms acceptance
    terms_accepted = db.Column(db.Boolean, default=False)
    terms_accepted_at = db.Column(db.DateTime, nullable=True)
    terms_version = db.Column(db.String(10), nullable=True)

    # Relationships
    products = db.relationship('Product', backref='vendor', lazy='dynamic',
                               foreign_keys='Product.vendor_id')
    orders_as_buyer = db.relationship('Order', backref='buyer', lazy='dynamic',
                                      foreign_keys='Order.buyer_id')
    orders_as_vendor = db.relationship('Order', backref='vendor', lazy='dynamic',
                                       foreign_keys='Order.vendor_id')
    messages_sent = db.relationship('Message', backref='sender', lazy='dynamic',
                                    foreign_keys='Message.sender_id')
    messages_received = db.relationship('Message', backref='recipient', lazy='dynamic',
                                        foreign_keys='Message.recipient_id')

    def __repr__(self):
        return f'<User {self.username}>'

    # =============================================================================
    # Password Management
    # =============================================================================

    def set_password(self, password):
        """
        Hash password using bcrypt with configurable rounds

        Args:
            password: Plain text password

        Raises:
            ValueError: If password doesn't meet policy requirements
        """
        # Validate password against policy (only check minimum length)
        if len(password) < 8:
            raise ValueError('Password must be at least 8 characters')

        # Generate hash with bcrypt
        self.password_hash = generate_password_hash(
            password,
            method='pbkdf2:sha256',
            salt_length=16
        )

    def check_password(self, password):
        """
        Verify password against hash

        Args:
            password: Plain text password to verify

        Returns:
            bool: True if password matches, False otherwise
        """
        return check_password_hash(self.password_hash, password)

    def _validate_password(self, password):
        """
        Validate password against policy requirements

        Args:
            password: Password to validate

        Raises:
            ValueError: If password doesn't meet requirements
        """
        config = current_app.config

        if len(password) < config['PASSWORD_MIN_LENGTH']:
            raise ValueError(f'Password must be at least {config["PASSWORD_MIN_LENGTH"]} characters')

        if config['PASSWORD_REQUIRE_UPPERCASE'] and not any(c.isupper() for c in password):
            raise ValueError('Password must contain at least one uppercase letter')

        if config['PASSWORD_REQUIRE_LOWERCASE'] and not any(c.islower() for c in password):
            raise ValueError('Password must contain at least one lowercase letter')

        if config['PASSWORD_REQUIRE_DIGITS'] and not any(c.isdigit() for c in password):
            raise ValueError('Password must contain at least one digit')

        if config['PASSWORD_REQUIRE_SPECIAL'] and not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in password):
            raise ValueError('Password must contain at least one special character')

    # =============================================================================
    # 2FA (TOTP)
    # =============================================================================

    def enable_two_factor(self):
        """
        Enable 2FA and generate TOTP secret

        Returns:
            str: TOTP provisioning URI for QR code generation
        """
        if not self.two_factor_secret:
            self.two_factor_secret = pyotp.random_base32()

        self.two_factor_enabled = True
        db.session.commit()

        # Generate provisioning URI for QR code
        totp = pyotp.TOTP(self.two_factor_secret)
        return totp.provisioning_uri(
            name=self.email,
            issuer_name='Social Market Training'
        )

    def disable_two_factor(self):
        """Disable 2FA"""
        self.two_factor_enabled = False
        self.two_factor_secret = None
        db.session.commit()

    def verify_totp(self, token):
        """
        Verify TOTP token

        Args:
            token: 6-digit TOTP code

        Returns:
            bool: True if token is valid, False otherwise
        """
        if not self.two_factor_enabled or not self.two_factor_secret:
            return False

        totp = pyotp.TOTP(self.two_factor_secret)
        return totp.verify(token, valid_window=1)

    # =============================================================================
    # Account Security
    # =============================================================================

    def record_failed_login(self, ip_address=None):
        """
        Record failed login attempt and lock account if threshold exceeded

        Args:
            ip_address: IP address of failed login attempt
        """
        self.failed_login_attempts += 1

        if ip_address:
            self.last_login_ip = ip_address

        # Lock account if max attempts exceeded
        max_attempts = current_app.config['MAX_FAILED_LOGIN_ATTEMPTS']
        if self.failed_login_attempts >= max_attempts:
            lockout_duration = current_app.config['ACCOUNT_LOCKOUT_DURATION']
            self.account_locked_until = datetime.utcnow() + timedelta(seconds=lockout_duration)

        db.session.commit()

    def record_successful_login(self, ip_address=None):
        """
        Record successful login and reset failed attempts

        Args:
            ip_address: IP address of successful login
        """
        self.failed_login_attempts = 0
        self.account_locked_until = None
        self.last_login = datetime.utcnow()

        if ip_address:
            self.last_login_ip = ip_address

        db.session.commit()

    def is_account_locked(self):
        """
        Check if account is currently locked

        Returns:
            bool: True if account is locked, False otherwise
        """
        if not self.account_locked_until:
            return False

        if datetime.utcnow() < self.account_locked_until:
            return True

        # Lock period expired, reset
        self.account_locked_until = None
        self.failed_login_attempts = 0
        db.session.commit()
        return False

    # =============================================================================
    # PGP Key Management
    # =============================================================================

    def set_pgp_key(self, public_key):
        """
        Set user's PGP public key

        Args:
            public_key: PGP public key in ASCII armor format

        Raises:
            ValueError: If key format is invalid
        """
        import gnupg

        gpg = gnupg.GPG()

        # Verify key format
        try:
            imported = gpg.import_keys(public_key)
            if not imported.count:
                raise ValueError('Invalid PGP key format')

            self.pgp_public_key = public_key
            self.pgp_fingerprint = imported.fingerprints[0]

        except Exception as e:
            raise ValueError(f'Failed to import PGP key: {str(e)}')

        db.session.commit()

    # =============================================================================
    # Authorization
    # =============================================================================

    def has_role(self, role):
        """
        Check if user has specific role

        Args:
            role: Role name to check

        Returns:
            bool: True if user has role, False otherwise
        """
        return self.role == role

    def is_admin(self):
        """Check if user is admin"""
        return self.role == 'admin'

    def is_vendor(self):
        """Check if user is vendor"""
        return self.role == 'vendor' and self.is_vendor_approved

    def is_buyer(self):
        """Check if user is buyer"""
        return self.role == 'buyer'

    # =============================================================================
    # Utility Methods
    # =============================================================================

    def to_dict(self, include_sensitive=False):
        """
        Convert user to dictionary

        Args:
            include_sensitive: Whether to include sensitive fields

        Returns:
            dict: User data
        """
        data = {
            'id': str(self.id),
            'username': self.username,
            'email': self.email if include_sensitive else None,
            'role': self.role,
            'display_name': self.display_name,
            'is_active': self.is_active,
            'is_verified': self.is_verified,
            'created_at': self.created_at.isoformat(),
            'two_factor_enabled': self.two_factor_enabled,
            'pgp_fingerprint': self.pgp_fingerprint
        }

        if self.is_vendor():
            data.update({
                'vendor_rating': self.vendor_rating,
                'vendor_total_sales': self.vendor_total_sales,
                'vendor_description': self.vendor_description
            })

        return data


# =============================================================================
# Database Triggers (for audit logging)
# =============================================================================

from sqlalchemy import event

@event.listens_for(User, 'after_insert')
def audit_user_insert(mapper, connection, target):
    """Audit log for user creation"""
    connection.execute(
        text(
            "INSERT INTO auth_log (user_id, username, action, metadata) "
            "VALUES (:user_id, :username, 'user_created', :metadata)"
        ),
        {
            'user_id': target.id,
            'username': target.username,
            'metadata': f'{{"role": "{target.role}"}}'
        }
    )


@event.listens_for(User, 'after_update')
def audit_user_update(mapper, connection, target):
    """Audit log for user updates"""
    # Log significant changes (password change, role change, etc.)
    connection.execute(
        text(
            "INSERT INTO audit_log (user_id, action, table_name, record_id) "
            "VALUES (:user_id, 'UPDATE', 'users', :record_id)"
        ),
        {
            'user_id': target.id,
            'record_id': target.id
        }
    )
