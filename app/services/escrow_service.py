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
            order_id=order.id,
            buyer_id=order.buyer_id,
            vendor_id=order.vendor_id,
            amount=order.total_price,
            commission=commission,
            vendor_amount=vendor_amount
        )

        db.session.add(escrow)
        db.session.commit()

        log_order_event(order.id, 'escrow_created')

        return escrow

    @staticmethod
    def fund_escrow(escrow, funding_tx_id=None):
        """
        Fund escrow (mock)

        Args:
            escrow: Escrow object
            funding_tx_id: Transaction ID (optional, will generate if not provided)

        Returns:
            bool: Success
        """
        try:
            escrow.fund(funding_tx_id)

            # Update order status
            order = Order.query.get(escrow.order_id)
            if order:
                order.transition_to(OrderStatus.PAID)

            log_order_event(escrow.order_id, 'escrow_funded')
            log_security_event(
                'escrow_funded',
                'info',
                f'Escrow funded for order {escrow.order_id}',
                user_id=escrow.buyer_id
            )

            return True

        except Exception as e:
            current_app.logger.error(f'Failed to fund escrow: {e}')
            return False

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
                user_id=escrow.vendor_id
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
                user_id=escrow.buyer_id
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
        from datetime import datetime

        # Find orders ready for auto-finalization
        orders_to_finalize = Order.query.filter(
            Order.status == OrderStatus.DELIVERED,
            Order.auto_finalize_at <= datetime.utcnow()
        ).all()

        count = 0
        for order in orders_to_finalize:
            try:
                # Auto-finalize order
                order.transition_to(OrderStatus.COMPLETED)

                log_order_event(order.id, 'order_auto_finalized')
                log_security_event(
                    'order_auto_finalized',
                    'info',
                    f'Order {order.id} auto-finalized',
                    user_id=order.buyer_id
                )

                count += 1

            except Exception as e:
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
