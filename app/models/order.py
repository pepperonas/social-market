"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Order Model
Purpose: Order management with escrow integration
"""

import uuid
from decimal import Decimal
from datetime import timedelta
from enum import Enum
from app.models.types import UUID
from sqlalchemy import CheckConstraint, Index
from sqlalchemy.orm.attributes import set_committed_value

from app import db
from app.timeutil import utcnow


class OrderStatus(str, Enum):
    """Order status enum"""
    PENDING = 'pending'              # Order created, awaiting payment
    PAID = 'paid'                    # Payment confirmed, awaiting shipment
    SHIPPED = 'shipped'              # Order shipped
    DELIVERED = 'delivered'          # Order delivered (buyer confirmation)
    COMPLETED = 'completed'          # Order completed, escrow released
    CANCELLED = 'cancelled'          # Order cancelled
    DISPUTED = 'disputed'            # Dispute opened
    REFUNDED = 'refunded'           # Order refunded


class Order(db.Model):
    """
    Order model with escrow integration:
    - UUID primary keys
    - State machine for order lifecycle
    - Encrypted shipping information
    - Dispute handling
    - Auto-finalization
    """

    __tablename__ = 'orders'

    # Primary identification
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Participants
    buyer_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False, index=True)
    vendor_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False, index=True)
    product_id = db.Column(UUID(as_uuid=True), db.ForeignKey('products.id'), nullable=False)

    # Order details
    quantity = db.Column(db.Integer, nullable=False, default=1)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    total_price = db.Column(db.Numeric(10, 2), nullable=False)
    commission = db.Column(db.Numeric(10, 2), nullable=False)  # Platform commission

    # Status
    status = db.Column(db.String(20), nullable=False, default=OrderStatus.PENDING.value, index=True)

    # Shipping information (encrypted in database)
    # These fields will be encrypted using pgcrypto encrypt_data()
    shipping_address_encrypted = db.Column(db.LargeBinary, nullable=True)
    shipping_name_encrypted = db.Column(db.LargeBinary, nullable=True)
    tracking_number = db.Column(db.String(100), nullable=True)

    # Digital delivery
    is_digital = db.Column(db.Boolean, default=False)
    digital_content_url = db.Column(db.Text, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    paid_at = db.Column(db.DateTime, nullable=True)
    shipped_at = db.Column(db.DateTime, nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Auto-finalization
    auto_finalize_at = db.Column(db.DateTime, nullable=True)

    # Dispute
    is_disputed = db.Column(db.Boolean, default=False)
    dispute_opened_at = db.Column(db.DateTime, nullable=True)
    dispute_reason = db.Column(db.Text, nullable=True)
    dispute_resolved_at = db.Column(db.DateTime, nullable=True)

    # Notes
    buyer_notes = db.Column(db.Text, nullable=True)
    vendor_notes = db.Column(db.Text, nullable=True)
    admin_notes = db.Column(db.Text, nullable=True)

    # Relationships
    escrow = db.relationship('Escrow', backref='order', uselist=False, cascade='all, delete-orphan')
    messages = db.relationship('Message', backref='order', lazy='dynamic')

    # Indexes
    __table_args__ = (
        CheckConstraint('quantity > 0', name='ck_order_quantity_positive'),
        CheckConstraint('total_price >= 0', name='ck_order_total_nonnegative'),
        Index('idx_order_buyer_status', buyer_id, status),
        Index('idx_order_vendor_status', vendor_id, status),
        Index('idx_order_created', created_at.desc()),
        Index('idx_order_auto_finalize', auto_finalize_at),
    )

    def __repr__(self):
        return f'<Order {self.id} - {self.status}>'

    # =============================================================================
    # Order Lifecycle
    # =============================================================================

    @property
    def status_color(self):
        """
        Bootstrap contextual colour for the status badge.

        Templates render `bg-{{ order.status_color }}`. Without this the class
        came out as bare "bg-" -- every badge unstyled, and nothing to indicate
        that a status was ever meant to be colour-coded.
        """
        return {
            OrderStatus.PENDING.value: 'secondary',
            OrderStatus.PAID.value: 'info',
            OrderStatus.SHIPPED.value: 'primary',
            OrderStatus.DELIVERED.value: 'success',
            OrderStatus.COMPLETED.value: 'success',
            OrderStatus.CANCELLED.value: 'dark',
            OrderStatus.DISPUTED.value: 'warning',
            OrderStatus.REFUNDED.value: 'danger',
        }.get(self.status, 'secondary')

    def can_transition_to(self, new_status):
        """
        Check if order can transition to new status

        Args:
            new_status: Target status

        Returns:
            tuple: (bool, str) - (can_transition, error_message)
        """
        valid_transitions = {
            OrderStatus.PENDING: [OrderStatus.PAID, OrderStatus.CANCELLED],
            OrderStatus.PAID: [OrderStatus.SHIPPED, OrderStatus.CANCELLED, OrderStatus.DISPUTED],
            OrderStatus.SHIPPED: [OrderStatus.DELIVERED, OrderStatus.DISPUTED],
            OrderStatus.DELIVERED: [OrderStatus.COMPLETED, OrderStatus.DISPUTED],
            OrderStatus.COMPLETED: [],
            OrderStatus.CANCELLED: [],
            OrderStatus.DISPUTED: [OrderStatus.REFUNDED, OrderStatus.COMPLETED],
            OrderStatus.REFUNDED: []
        }

        current = OrderStatus(self.status)
        target = OrderStatus(new_status)

        if target in valid_transitions.get(current, []):
            return True, None
        else:
            return False, f"Cannot transition from {current.value} to {target.value}"

    def transition_to(self, new_status, **kwargs):
        """
        Move the order to ``new_status`` and apply the side effects.

        Two changes from the original, both about doing it exactly once:

        * The status is claimed with a conditional UPDATE (``WHERE status =
          <the state this object believes in>``). The old code compared the
          in-memory status and then wrote it, so two requests -- a double click
          on "complete", or the click racing the auto-finaliser -- could both
          pass and both release the escrow. Now one of them changes a row and
          the other gets rowcount 0 and a ValueError.
        * Nothing here commits. It used to commit itself (as did the escrow,
          the stock update and the shipping-field setters), so a failure half
          way left half a state change persisted. The caller commits once;
          a failure rolls everything back together.

        Raises:
            ValueError: if the transition is not allowed or the order changed
                underneath this object.
        """
        new_status = OrderStatus(new_status)
        can_transition, error = self.can_transition_to(new_status)
        if not can_transition:
            raise ValueError(error)

        old_status = self.status
        rows = db.session.query(Order).filter(
            Order.id == self.id,
            Order.status == old_status,
        ).update({Order.status: new_status.value}, synchronize_session=False)
        if rows != 1:
            db.session.expire(self, ['status'])
            raise ValueError('The order was changed in the meantime; reload and try again')
        set_committed_value(self, 'status', new_status.value)

        handler = {
            OrderStatus.PAID: self._handle_paid,
            OrderStatus.SHIPPED: self._handle_shipped,
            OrderStatus.DELIVERED: self._handle_delivered,
            OrderStatus.COMPLETED: self._handle_completed,
            OrderStatus.CANCELLED: self._handle_cancelled,
            OrderStatus.DISPUTED: self._handle_disputed,
            OrderStatus.REFUNDED: self._handle_refunded,
        }[new_status]
        handler(old_status=old_status, **kwargs)

        from app.services.audit_service import log_order_event
        log_order_event(self.id, f'status_change_{old_status}_to_{new_status.value}')

    def _handle_paid(self, **kwargs):
        """
        Payment confirmed. Stock was already reserved when the order was placed;
        the auto-finalise clock starts at delivery, not here (see _handle_delivered).
        """
        self.paid_at = utcnow()

    def _handle_shipped(self, tracking_number=None, **kwargs):
        """Handle order shipped transition"""
        self.shipped_at = utcnow()
        if tracking_number:
            self.tracking_number = tracking_number

    def _handle_delivered(self, **kwargs):
        """
        Delivered: start the auto-finalise clock.

        It used to be set at payment (paid_at + ESCROW_AUTO_RELEASE_DAYS) and
        never moved. An order delivered late was then finalised almost at once,
        before the buyer's dispute window -- which counts from delivery -- had
        run. The clock now starts here and never ends before that window does.
        """
        from flask import current_app

        self.delivered_at = utcnow()
        days = max(current_app.config['ESCROW_AUTO_RELEASE_DAYS'],
                   current_app.config['ESCROW_DISPUTE_WINDOW_DAYS'])
        self.auto_finalize_at = self.delivered_at + timedelta(days=days)

    def _handle_completed(self, **kwargs):
        """Completed: the money moves to the vendor and the sale counts."""
        self.completed_at = utcnow()
        if kwargs.get('old_status') == OrderStatus.DISPUTED.value:
            self.dispute_resolved_at = self.completed_at
        if self.escrow:
            self.escrow.release_to_vendor()
        self.product.record_sale(self.quantity)

    def _handle_cancelled(self, old_status=None, **kwargs):
        """
        Cancelled before shipping: stock goes back, and a paid order's escrow is
        refunded.

        There was no handler. Cancelling a paid order left the escrow `funded`
        for ever -- the buyer never got the money back -- and the stock booked
        for the order stayed gone.
        """
        self.product.release_stock(self.quantity)
        if self.escrow:
            if old_status == OrderStatus.PAID.value:
                self.escrow.refund_to_buyer()
            else:
                self.escrow.cancel()

    def _handle_disputed(self, reason=None, **kwargs):
        """
        Dispute opened: freeze the escrow.

        Escrow.mark_disputed() existed but nothing called it, so the money stayed
        `funded` during a dispute and the escrow health check, which counts
        disputed escrows, always reported "healthy".
        """
        self.is_disputed = True
        self.dispute_opened_at = utcnow()
        if reason:
            self.dispute_reason = reason
        if self.escrow and self.escrow.status == 'funded':
            self.escrow.mark_disputed()

    def _handle_refunded(self, **kwargs):
        """Dispute decided for the buyer: the escrow goes back to them."""
        self.dispute_resolved_at = utcnow()
        if self.escrow:
            self.escrow.refund_to_buyer()

    # =============================================================================
    # Shipping Information (Encrypted)
    # =============================================================================

    def set_shipping_address(self, address):
        """
        Set encrypted shipping address

        Args:
            address: Plain text shipping address
        """
        from sqlalchemy import text
        result = db.session.execute(
            text("SELECT encrypt_data(:address)"),
            {'address': address}
        ).scalar()
        self.shipping_address_encrypted = result  # caller commits (checkout is one transaction)

    def get_shipping_address(self):
        """
        Get decrypted shipping address

        Returns:
            str: Plain text shipping address
        """
        if not self.shipping_address_encrypted:
            return None

        from sqlalchemy import text
        result = db.session.execute(
            text("SELECT decrypt_data(:encrypted)"),
            {'encrypted': self.shipping_address_encrypted}
        ).scalar()
        return result

    def set_shipping_name(self, name):
        """Set encrypted shipping name"""
        from sqlalchemy import text
        result = db.session.execute(
            text("SELECT encrypt_data(:name)"),
            {'name': name}
        ).scalar()
        self.shipping_name_encrypted = result  # caller commits

    def get_shipping_name(self):
        """Get decrypted shipping name"""
        if not self.shipping_name_encrypted:
            return None

        from sqlalchemy import text
        result = db.session.execute(
            text("SELECT decrypt_data(:encrypted)"),
            {'encrypted': self.shipping_name_encrypted}
        ).scalar()
        return result

    # =============================================================================
    # Auto-Finalization
    # =============================================================================

    def should_auto_finalize(self):
        """Check if order should be auto-finalized"""
        if self.status != OrderStatus.DELIVERED.value:
            return False

        if not self.auto_finalize_at:
            return False

        return utcnow() >= self.auto_finalize_at

    def auto_finalize(self):
        """Auto-finalize order (release escrow)"""
        if self.should_auto_finalize():
            self.transition_to(OrderStatus.COMPLETED)

    # =============================================================================
    # Dispute Handling
    # =============================================================================

    def can_open_dispute(self):
        """Check if dispute can be opened"""
        from flask import current_app

        # Can only dispute in certain states
        if self.status not in [OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.DELIVERED]:
            return False, "Cannot dispute order in current state"

        # Check if within dispute window
        if self.status == OrderStatus.DELIVERED and self.delivered_at:
            dispute_window = current_app.config['ESCROW_DISPUTE_WINDOW_DAYS']
            window_end = self.delivered_at + timedelta(days=dispute_window)
            if utcnow() > window_end:
                return False, "Dispute window has expired"

        return True, None

    def open_dispute(self, reason):
        """
        Open dispute for order

        Args:
            reason: Dispute reason

        Raises:
            ValueError: If dispute cannot be opened
        """
        can_dispute, error = self.can_open_dispute()
        if not can_dispute:
            raise ValueError(error)

        self.transition_to(OrderStatus.DISPUTED, reason=reason)

    # =============================================================================
    # Utility Methods
    # =============================================================================

    def calculate_totals(self):
        """Calculate order totals and commission"""
        from flask import current_app

        self.total_price = Decimal(self.unit_price) * self.quantity

        # Calculate commission. Money is Numeric -> Decimal; multiplying a
        # Decimal by a float raises TypeError, so the percentage is converted
        # via str() (Decimal(0.03) would carry binary float error).
        commission_percent = Decimal(str(current_app.config['ESCROW_COMMISSION_PERCENT']))
        self.commission = (self.total_price * commission_percent / Decimal('100')).quantize(Decimal('0.01'))

    def to_dict(self, include_sensitive=False):
        """Convert order to dictionary"""
        data = {
            'id': str(self.id),
            'product': self.product.to_dict(),
            'quantity': self.quantity,
            'unit_price': float(self.unit_price),
            'total_price': float(self.total_price),
            'commission': float(self.commission),
            'status': self.status,
            'is_digital': self.is_digital,
            'created_at': self.created_at.isoformat(),
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
            'shipped_at': self.shipped_at.isoformat() if self.shipped_at else None,
            'delivered_at': self.delivered_at.isoformat() if self.delivered_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'is_disputed': self.is_disputed
        }

        if include_sensitive:
            data.update({
                'shipping_address': self.get_shipping_address(),
                'shipping_name': self.get_shipping_name(),
                'tracking_number': self.tracking_number,
                'buyer_notes': self.buyer_notes,
                'vendor_notes': self.vendor_notes
            })

        return data


# =============================================================================
# Database Events
# =============================================================================

from sqlalchemy import event


@event.listens_for(Order, 'before_insert')
def calculate_order_totals(mapper, connection, target):
    """Calculate totals before inserting order"""
    from flask import current_app

    target.total_price = Decimal(target.unit_price) * target.quantity

    # Calculate commission. See calculate_totals(): Decimal * float is a
    # TypeError, and this listener runs on EVERY insert -- it made order
    # creation fail outright whenever unit_price came back from the DB as
    # Decimal (i.e. always, in the real checkout path).
    commission_percent = Decimal(str(current_app.config.get('ESCROW_COMMISSION_PERCENT', 3.0)))
    target.commission = (target.total_price * commission_percent / Decimal('100')).quantize(Decimal('0.01'))
