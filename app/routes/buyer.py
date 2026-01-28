"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Buyer Routes - Placeholder
Purpose: Buyer orders and purchases
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models.order import Order
from app.models.product import Product
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
    try:
        # Get form data
        product_id = request.form.get('product_id')
        quantity = int(request.form.get('quantity', 1))

        # Validate product
        product = Product.query.get_or_404(product_id)

        # Check if product is active
        if not product.active:
            flash('This product is no longer available', 'warning')
            return redirect(url_for('marketplace.product_detail', product_id=product_id))

        # Check if user is not the vendor
        if product.vendor_id == current_user.id:
            flash('You cannot purchase your own product', 'warning')
            return redirect(url_for('marketplace.product_detail', product_id=product_id))

        # Calculate total
        total_amount = product.price * quantity

        # Create order
        order = Order(
            id=uuid.uuid4(),
            buyer_id=current_user.id,
            vendor_id=product.vendor_id,
            product_id=product.id,
            quantity=quantity,
            unit_price=product.price,
            total_amount=total_amount,
            status='pending',
            created_at=datetime.utcnow()
        )

        db.session.add(order)
        db.session.commit()

        flash(f'Order placed successfully! Order ID: {order.id}', 'success')
        return redirect(url_for('buyer.order_detail', order_id=order.id))

    except ValueError:
        flash('Invalid quantity', 'danger')
        return redirect(url_for('marketplace.product_detail', product_id=product_id))
    except Exception as e:
        db.session.rollback()
        flash(f'Error creating order: {str(e)}', 'danger')
        return redirect(url_for('marketplace.product_detail', product_id=product_id))
