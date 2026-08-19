"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Escrow Model
Purpose: Escrow system for secure transactions (Educational Mock)
"""

import uuid
from datetime import datetime
from enum import Enum
from app.models.types import UUID
from sqlalchemy import Index

from app import db


class EscrowStatus(str, Enum):
    """Escrow status enum"""
    PENDING = 'pending'          # Escrow created, awaiting funding
    FUNDED = 'funded'            # Funds held in escrow
    RELEASED = 'released'        # Funds released to vendor
    REFUNDED = 'refunded'        # Funds refunded to buyer
    DISPUTED = 'disputed'        # Dispute in progress


class Escrow(db.Model):
    """
    Escrow model (Educational Mock Implementation):
    - Simulates multi-signature wallet
    - Educational demonstration only
    - NOT for real cryptocurrency transactions
    - Shows escrow lifecycle and dispute resolution
    """

    __tablename__ = 'escrows'

    # Primary identification
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = db.Column(UUID(as_uuid=True), db.ForeignKey('orders.id'), nullable=False, unique=True)

    # Participants
    buyer_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False)
    vendor_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False)

    # Amounts (in simulated currency)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    commission = db.Column(db.Numeric(10, 2), nullable=False)
    vendor_amount = db.Column(db.Numeric(10, 2), nullable=False)  # amount - commission

    # Status
    status = db.Column(db.String(20), nullable=False, default=EscrowStatus.PENDING.value, index=True)

    # Multi-sig simulation (educational only)
    # In real implementation, these would be cryptocurrency addresses
    buyer_address = db.Column(db.String(255), nullable=True)
    vendor_address = db.Column(db.String(255), nullable=True)
    platform_address = db.Column(db.String(255), nullable=True)
    escrow_address = db.Column(db.String(255), nullable=True)  # Multi-sig address

    # Transaction IDs (simulated)
    funding_tx_id = db.Column(db.String(255), nullable=True)
    release_tx_id = db.Column(db.String(255), nullable=True)
    refund_tx_id = db.Column(db.String(255), nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    funded_at = db.Column(db.DateTime, nullable=True)
    released_at = db.Column(db.DateTime, nullable=True)
    refunded_at = db.Column(db.DateTime, nullable=True)

    # Indexes
    __table_args__ = (
        Index('idx_escrow_buyer', buyer_id),
        Index('idx_escrow_vendor', vendor_id),
        Index('idx_escrow_status', status),
    )

    def __repr__(self):
        return f'<Escrow {self.id} - {self.status}>'

    # =============================================================================
    # Escrow Lifecycle
    # =============================================================================

    def fund(self, funding_tx_id=None):
        """
        Fund escrow (Educational Mock)

        Args:
            funding_tx_id: Simulated transaction ID

        Raises:
            ValueError: If escrow cannot be funded
        """
        if self.status != EscrowStatus.PENDING.value:
            raise ValueError("Escrow is not in pending state")

        # Simulate funding
        self.status = EscrowStatus.FUNDED.value
        self.funded_at = datetime.utcnow()
        self.funding_tx_id = funding_tx_id or self._generate_mock_tx_id()

        # Create transaction record
        self._create_transaction('fund', self.amount)

        db.session.commit()

    def release_to_vendor(self):
        """
        Release funds to vendor (Educational Mock)

        Raises:
            ValueError: If escrow cannot be released
        """
        if self.status not in [EscrowStatus.FUNDED.value, EscrowStatus.DISPUTED.value]:
            raise ValueError("Escrow is not in funded or disputed state")

        # Simulate release
        self.status = EscrowStatus.RELEASED.value
        self.released_at = datetime.utcnow()
        self.release_tx_id = self._generate_mock_tx_id()

        # Create transaction records
        self._create_transaction('release_vendor', self.vendor_amount)
        self._create_transaction('release_platform', self.commission)

        # Update vendor statistics
        from app.models.user import User
        vendor = User.query.get(self.vendor_id)
        if vendor:
            vendor.vendor_total_sales += 1
            db.session.commit()

        db.session.commit()

    def refund_to_buyer(self):
        """
        Refund funds to buyer (Educational Mock)

        Raises:
            ValueError: If escrow cannot be refunded
        """
        if self.status not in [EscrowStatus.FUNDED.value, EscrowStatus.DISPUTED.value]:
            raise ValueError("Escrow is not in funded or disputed state")

        # Simulate refund
        self.status = EscrowStatus.REFUNDED.value
        self.refunded_at = datetime.utcnow()
        self.refund_tx_id = self._generate_mock_tx_id()

        # Create transaction record
        self._create_transaction('refund', self.amount)

        db.session.commit()

    def mark_disputed(self):
        """Mark escrow as disputed"""
        if self.status != EscrowStatus.FUNDED.value:
            raise ValueError("Can only dispute funded escrow")

        self.status = EscrowStatus.DISPUTED.value
        db.session.commit()

    # =============================================================================
    # Helper Methods
    # =============================================================================

    def _generate_mock_tx_id(self):
        """
        Generate mock transaction ID for educational purposes

        Returns:
            str: Mock transaction ID
        """
        import secrets
        return f"mock_tx_{secrets.token_hex(16)}"

    def _create_transaction(self, transaction_type, amount):
        """
        Create escrow transaction record

        Args:
            transaction_type: Type of transaction
            amount: Transaction amount
        """
        transaction = EscrowTransaction(
            escrow_id=self.id,
            transaction_type=transaction_type,
            amount=amount,
            from_address=self._get_from_address(transaction_type),
            to_address=self._get_to_address(transaction_type),
            tx_id=self._generate_mock_tx_id()
        )
        db.session.add(transaction)

    def _get_from_address(self, transaction_type):
        """Get from address based on transaction type"""
        if transaction_type == 'fund':
            return self.buyer_address
        elif transaction_type in ['release_vendor', 'release_platform']:
            return self.escrow_address
        elif transaction_type == 'refund':
            return self.escrow_address
        return None

    def _get_to_address(self, transaction_type):
        """Get to address based on transaction type"""
        if transaction_type == 'fund':
            return self.escrow_address
        elif transaction_type == 'release_vendor':
            return self.vendor_address
        elif transaction_type == 'release_platform':
            return self.platform_address
        elif transaction_type == 'refund':
            return self.buyer_address
        return None

    # =============================================================================
    # Utility Methods
    # =============================================================================

    def to_dict(self):
        """Convert escrow to dictionary"""
        return {
            'id': str(self.id),
            'order_id': str(self.order_id),
            'amount': float(self.amount),
            'commission': float(self.commission),
            'vendor_amount': float(self.vendor_amount),
            'status': self.status,
            'created_at': self.created_at.isoformat(),
            'funded_at': self.funded_at.isoformat() if self.funded_at else None,
            'released_at': self.released_at.isoformat() if self.released_at else None,
            'refunded_at': self.refunded_at.isoformat() if self.refunded_at else None,
            'funding_tx_id': self.funding_tx_id,
            'release_tx_id': self.release_tx_id,
            'refund_tx_id': self.refund_tx_id
        }


class EscrowTransaction(db.Model):
    """
    Escrow transaction log (Educational Mock)
    Simulates blockchain transaction records
    """

    __tablename__ = 'escrow_transactions'

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    escrow_id = db.Column(UUID(as_uuid=True), db.ForeignKey('escrows.id'), nullable=False, index=True)

    # Transaction details
    transaction_type = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)

    # Addresses (simulated)
    from_address = db.Column(db.String(255), nullable=True)
    to_address = db.Column(db.String(255), nullable=True)

    # Transaction ID (simulated)
    tx_id = db.Column(db.String(255), nullable=False, unique=True)

    # Confirmations (simulated)
    confirmations = db.Column(db.Integer, default=0)
    confirmed = db.Column(db.Boolean, default=True)  # Auto-confirmed in mock

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    confirmed_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship
    escrow = db.relationship('Escrow', backref='transactions')

    def __repr__(self):
        return f'<EscrowTransaction {self.tx_id}>'

    def to_dict(self):
        """Convert transaction to dictionary"""
        return {
            'id': str(self.id),
            'transaction_type': self.transaction_type,
            'amount': float(self.amount),
            'from_address': self.from_address,
            'to_address': self.to_address,
            'tx_id': self.tx_id,
            'confirmations': self.confirmations,
            'confirmed': self.confirmed,
            'created_at': self.created_at.isoformat(),
            'confirmed_at': self.confirmed_at.isoformat() if self.confirmed_at else None
        }


# =============================================================================
# Database Events
# =============================================================================

from sqlalchemy import event


@event.listens_for(Escrow, 'before_insert')
def calculate_escrow_amounts(mapper, connection, target):
    """Calculate vendor amount before inserting escrow"""
    target.vendor_amount = target.amount - target.commission

    # Generate mock addresses for educational purposes
    if not target.buyer_address:
        target.buyer_address = f"buyer_{uuid.uuid4().hex[:16]}"
    if not target.vendor_address:
        target.vendor_address = f"vendor_{uuid.uuid4().hex[:16]}"
    if not target.platform_address:
        target.platform_address = f"platform_{uuid.uuid4().hex[:16]}"
    if not target.escrow_address:
        target.escrow_address = f"escrow_2of3_{uuid.uuid4().hex[:16]}"


@event.listens_for(Escrow, 'after_insert')
@event.listens_for(Escrow, 'after_update')
def audit_escrow_changes(mapper, connection, target):
    """Audit log for escrow changes"""
    from sqlalchemy import text
    connection.execute(
        text(
            "INSERT INTO transaction_audit (transaction_id, buyer_id, vendor_id, "
            "product_id, action, amount, status) "
            "VALUES (:transaction_id, :buyer_id, :vendor_id, :product_id, "
            ":action, :amount, :status)"
        ),
        {
            # Use the foreign key, not the relationship. During after_insert the
            # `order` backref is not necessarily populated yet, so this bound
            # NULL into transaction_audit.transaction_id -- which is NOT NULL,
            # so every escrow creation (i.e. every order) failed.
            'transaction_id': str(target.order_id) if target.order_id else None,
            'buyer_id': str(target.buyer_id),
            'vendor_id': str(target.vendor_id),
            # Reachable only through the order. escrow_service sets the
            # relationship explicitly so this is populated during the flush.
            'product_id': str(target.order.product_id) if target.order else None,
            'action': f'escrow_{target.status}',
            # Bind money as str, like the ids above: psycopg2 adapts Decimal,
            # sqlite3 does not. str() keeps the exact value; float() would not.
            'amount': str(target.amount) if target.amount is not None else None,
            'status': target.status
        }
    )
