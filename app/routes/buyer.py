"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Buyer Routes - Placeholder
Purpose: Buyer orders and purchases
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from app import db
from app.models.order import Order, OrderStatus
from app.models.product import Product
from app.services.escrow_service import EscrowService
from datetime import datetime
import uuid

buyer_bp = Blueprint('buyer', __name__)


@buyer_bp.route('/orders')
@login_required
def orders():
    """Buyer orders list"""
    from app.models.order import Order
    buyer_orders = Order.query.filter_by(buyer_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template('buyer/orders.html', orders=buyer_orders)


@buyer_bp.route('/order/<uuid:order_id>')
@login_required
def order_detail(order_id):
    """Order detail"""
    order = Order.query.get_or_404(order_id)

    # Check if user is the buyer of this order
    if order.buyer_id != current_user.id:
        flash('You do not have permission to view this order', 'danger')
        return redirect(url_for('buyer.orders'))

    return render_template('buyer/order_detail.html', order=order)


@buyer_bp.route('/create-order', methods=['POST'])
@login_required
def create_order():
    """Create new order"""
    product_id = request.form.get('product_id')

    try:
        quantity = int(request.form.get('quantity', 1))
    except (TypeError, ValueError):
        flash('Invalid quantity', 'danger')
        return redirect(url_for('marketplace.product_detail', product_id=product_id))

    if quantity < 1:
        flash('Quantity must be at least 1', 'danger')
        return redirect(url_for('marketplace.product_detail', product_id=product_id))

    product = Product.query.get_or_404(product_id)

    # Go through the model's own gate rather than re-implementing it here.
    # This route used to check `product.active` -- a column that does not exist
    # (it is `is_active`) -- so the check raised AttributeError instead of
    # returning False, and it never looked at approval or stock at all.
    purchasable, reason = product.can_purchase(quantity)
    if not purchasable:
        flash(reason or 'This product is no longer available', 'warning')
        return redirect(url_for('marketplace.product_detail', product_id=product_id))

    if str(product.vendor_id) == str(current_user.id):
        flash('You cannot purchase your own product', 'warning')
        return redirect(url_for('marketplace.product_detail', product_id=product_id))

    try:
        order = Order(
            id=uuid.uuid4(),
            buyer_id=current_user.id,
            vendor_id=product.vendor_id,
            product_id=product.id,
            quantity=quantity,
            unit_price=product.price,
            # total_price and commission are computed by the before_insert
            # listener. The old code passed `total_amount`, which is not a
            # column, so the insert raised before it ever reached the database.
            is_digital=product.is_digital,
            status=OrderStatus.PENDING.value,
            created_at=datetime.utcnow()
        )
        db.session.add(order)
        db.session.flush()

        # Same escrow guarantee as the cart checkout path; a "buy now" order
        # without escrow would silently skip the buyer protection.
        EscrowService().create_escrow_for_order(order)

        db.session.commit()

    except Exception as exc:
        db.session.rollback()
        # Log the detail, show the user a generic message. The previous version
        # flashed str(exc), which put internal model attribute names (and
        # potentially SQL) straight onto the page.
        current_app.logger.exception('Order creation failed for product %s: %s', product_id, exc)
        flash('Could not place the order. Please try again.', 'danger')
        return redirect(url_for('marketplace.product_detail', product_id=product_id))

    flash(f'Order placed successfully! Order ID: {order.id}', 'success')
    return redirect(url_for('buyer.order_detail', order_id=order.id))


@buyer_bp.route('/order/<uuid:order_id>/confirm-delivery', methods=['POST'])
@login_required
def confirm_delivery(order_id):
    """Confirm order delivery"""
    from app.models.order import OrderStatus

    order = Order.query.get_or_404(order_id)

    # Check if user is the buyer of this order
    if order.buyer_id != current_user.id:
        flash('You do not have permission to modify this order', 'danger')
        return redirect(url_for('buyer.orders'))

    # Check if order can be confirmed
    if order.status != 'shipped':
        flash('Only shipped orders can be confirmed as delivered', 'warning')
        return redirect(url_for('buyer.order_detail', order_id=order_id))

    try:
        order.transition_to(OrderStatus.DELIVERED)
        db.session.commit()
        flash('Delivery confirmed! You can now leave a review.', 'success')
    except ValueError as e:
        flash(str(e), 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error confirming delivery: {str(e)}', 'danger')

    return redirect(url_for('buyer.order_detail', order_id=order_id))


@buyer_bp.route('/order/<uuid:order_id>/complete', methods=['POST'])
@login_required
def complete_order(order_id):
    """Complete order and release escrow"""
    from app.models.order import OrderStatus

    order = Order.query.get_or_404(order_id)

    # Check if user is the buyer of this order
    if order.buyer_id != current_user.id:
        flash('You do not have permission to modify this order', 'danger')
        return redirect(url_for('buyer.orders'))

    # Check if order can be completed
    if order.status != 'delivered':
        flash('Only delivered orders can be completed', 'warning')
        return redirect(url_for('buyer.order_detail', order_id=order_id))

    try:
        order.transition_to(OrderStatus.COMPLETED)
        db.session.commit()
        flash('Order completed! Funds have been released to the vendor.', 'success')
    except ValueError as e:
        flash(str(e), 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error completing order: {str(e)}', 'danger')

    return redirect(url_for('buyer.order_detail', order_id=order_id))


@buyer_bp.route('/order/<uuid:order_id>/dispute', methods=['POST'])
@login_required
def dispute_order(order_id):
    """Open dispute for order"""
    order = Order.query.get_or_404(order_id)

    # Check if user is the buyer of this order
    if order.buyer_id != current_user.id:
        flash('You do not have permission to dispute this order', 'danger')
        return redirect(url_for('buyer.orders'))

    reason = request.form.get('reason', '').strip()

    if not reason:
        flash('Please provide a reason for the dispute', 'danger')
        return redirect(url_for('buyer.order_detail', order_id=order_id))

    try:
        order.open_dispute(reason)
        db.session.commit()
        flash('Dispute opened. An administrator will review your case.', 'warning')
    except ValueError as e:
        flash(str(e), 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error opening dispute: {str(e)}', 'danger')

    return redirect(url_for('buyer.order_detail', order_id=order_id))


@buyer_bp.route('/order/<uuid:order_id>/review', methods=['GET', 'POST'])
@login_required
def leave_review(order_id):
    """Leave a product review"""
    from app.models.product import ProductReview

    order = Order.query.get_or_404(order_id)

    # Check if user is the buyer of this order
    if order.buyer_id != current_user.id:
        flash('You do not have permission to review this order', 'danger')
        return redirect(url_for('buyer.orders'))

    # Check if order is completed
    if order.status not in ['completed', 'delivered']:
        flash('You can only review completed orders', 'warning')
        return redirect(url_for('buyer.order_detail', order_id=order_id))

    # Check if review already exists
    existing_review = ProductReview.query.filter_by(
        product_id=order.product_id,
        buyer_id=current_user.id,
        order_id=order_id
    ).first()

    if existing_review:
        flash('You have already reviewed this order', 'info')
        return redirect(url_for('buyer.order_detail', order_id=order_id))

    if request.method == 'POST':
        rating = request.form.get('rating', type=int)
        title = request.form.get('title', '').strip()
        review_text = request.form.get('review_text', '').strip()

        # Validation
        if not rating or rating < 1 or rating > 5:
            flash('Please select a rating between 1 and 5', 'danger')
            return render_template('buyer/leave_review.html', order=order)

        try:
            review = ProductReview(
                product_id=order.product_id,
                buyer_id=current_user.id,
                order_id=order.id,
                rating=rating,
                title=title if title else None,
                review_text=review_text if review_text else None,
                is_approved=True  # Auto-approve in training environment
            )

            db.session.add(review)
            db.session.commit()

            # Update product rating
            order.product.update_rating()

            flash('Thank you for your review!', 'success')
            return redirect(url_for('buyer.order_detail', order_id=order_id))

        except Exception as e:
            db.session.rollback()
            flash(f'Error submitting review: {str(e)}', 'danger')

    return render_template('buyer/leave_review.html', order=order)
