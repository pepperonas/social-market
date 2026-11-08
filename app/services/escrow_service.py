"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Escrow Service
Purpose: Educational mock escrow system management
"""

from flask import current_app
from app import db
from app.models.escrow import Escrow, EscrowStatus
from app.models.order import Order, OrderStatus
from app.services.audit_service import log_order_event, log_security_event
from app.timeutil import utcnow


class EscrowService:
    """
    Educational Mock Escrow Service
    Simulates multi-signature wallet escrow system
    NOT for real cryptocurrency transactions
    """

    @staticmethod
    def create_escrow_for_order(order):
        """
        Create escrow for an order

        Args:
            order: Order object

        Returns:
            Escrow: Created escrow object
        """
        # Calculate amounts
        commission = order.commission
        vendor_amount = order.total_price - commission

        # Create escrow
        escrow = Escrow(
            # Set the relationship, not just the FK: the audit listener runs
            # during the flush and reads target.order to reach product_id.
            order=order,
            order_id=order.id,
            buyer_id=order.buyer_id,
            vendor_id=order.vendor_id,
            amount=order.total_price,
            commission=commission,
            vendor_amount=vendor_amount
        )

        db.session.add(escrow)
        db.session.flush()  # no commit: checkout creates all its orders in ONE transaction

        log_order_event(order.id, 'escrow_created')

        return escrow

    @staticmethod
    def pay_order(order):
        """
        Simulated payment: fund the escrow and mark the order paid.

        This is the step that was missing. fund_escrow() existed but nothing
        called it, and nothing else moved an order to PAID -- so no order could
        ever be shipped, delivered, completed, reviewed or disputed. In this
        training environment "paying" is a button; in a real marketplace it is
        a confirmed deposit to the escrow address.

        Raises ValueError if the order is not payable. The caller commits.
        """
        if order.escrow is None:
            raise ValueError('This order has no escrow')
        order.escrow.fund()
        order.transition_to(OrderStatus.PAID)
        log_security_event(
            'escrow_funded', 'info', f'Escrow funded for order {order.id}',
            user_id=order.buyer_id, commit=False)  # the caller commits -- see docstring

    @staticmethod
    def release_escrow_to_vendor(escrow):
        """
        Release escrow funds to vendor

        Args:
            escrow: Escrow object

        Returns:
            bool: Success
        """
        try:
            escrow.release_to_vendor()

            log_order_event(escrow.order_id, 'escrow_released_vendor')
            log_security_event(
                'escrow_released',
                'info',
                f'Escrow released to vendor for order {escrow.order_id}',
                user_id=escrow.vendor_id, commit=False
            )

            return True

        except Exception as e:
            current_app.logger.error(f'Failed to release escrow: {e}')
            return False

    @staticmethod
    def refund_escrow_to_buyer(escrow):
        """
        Refund escrow to buyer

        Args:
            escrow: Escrow object

        Returns:
            bool: Success
        """
        try:
            escrow.refund_to_buyer()

            log_order_event(escrow.order_id, 'escrow_refunded')
            log_security_event(
                'escrow_refunded',
                'info',
                f'Escrow refunded to buyer for order {escrow.order_id}',
                user_id=escrow.buyer_id, commit=False
            )

            return True

        except Exception as e:
            current_app.logger.error(f'Failed to refund escrow: {e}')
            return False

    @staticmethod
    def process_auto_finalization():
        """
        Process auto-finalization for orders
        Called by scheduled task

        Returns:
            int: Number of orders auto-finalized
        """

        # Find orders ready for auto-finalization
        orders_to_finalize = Order.query.filter(
            Order.status == OrderStatus.DELIVERED,
            Order.auto_finalize_at <= utcnow()
        ).all()

        count = 0
        for order in orders_to_finalize:
            try:
                # Auto-finalize order -- one commit per order, so one failure
                # does not take the others with it...
                order.transition_to(OrderStatus.COMPLETED)
                log_order_event(order.id, 'order_auto_finalized')
                db.session.commit()

                log_security_event(
                    'order_auto_finalized',
                    'info',
                    f'Order {order.id} auto-finalized',
                    user_id=order.buyer_id
                )

                count += 1

            except Exception as e:
                # ...and a failure is rolled back. There was no rollback here:
                # a failed escrow release left COMPLETED pending in the session,
                # and the next order's commit persisted it -- an order marked
                # done whose money never moved.
                db.session.rollback()
                current_app.logger.error(f'Failed to auto-finalize order {order.id}: {e}')

        if count > 0:
            current_app.logger.info(f'Auto-finalized {count} orders')

        return count

    @staticmethod
    def check_escrow_health():
        """
        Check health of escrow system

        Returns:
            dict: Health status
        """
        # Count escrows by status
        escrows_pending = Escrow.query.filter_by(status=EscrowStatus.PENDING).count()
        escrows_funded = Escrow.query.filter_by(status=EscrowStatus.FUNDED).count()
        escrows_disputed = Escrow.query.filter_by(status=EscrowStatus.DISPUTED).count()

        return {
            'pending': escrows_pending,
            'funded': escrows_funded,
            'disputed': escrows_disputed,
            'healthy': escrows_disputed == 0
        }


# Singleton instance
_escrow_service = None


def get_escrow_service():
    """Get escrow service instance"""
    global _escrow_service
    if _escrow_service is None:
        _escrow_service = EscrowService()
    return _escrow_service
