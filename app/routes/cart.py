"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Shopping Cart Routes
Purpose: Secure shopping cart management
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from decimal import Decimal
import uuid
from datetime import datetime

from app import db, limiter
from app.models.cart import Cart, CartItem
from app.models.product import Product
from app.models.order import Order
from app.services.escrow_service import EscrowService

cart_bp = Blueprint('cart', __name__)


@cart_bp.route('/')
@login_required
def view_cart():
    """View shopping cart"""
    cart = Cart.get_or_create(current_user.id)
    
    # Group items by vendor for multi-vendor checkout
    items_by_vendor = cart.get_items_grouped_by_vendor()
    
    # Get vendor info for each group
    from app.models.user import User
    vendors = {}
    for vendor_id in items_by_vendor.keys():
        vendor = User.query.get(vendor_id)
        if vendor:
            vendors[vendor_id] = vendor
    
    # Validate cart items
    validation_errors = cart.validate_items()
    
    return render_template('cart/view.html',
                         cart=cart,
                         items_by_vendor=items_by_vendor,
                         vendors=vendors,
                         validation_errors=validation_errors)


@cart_bp.route('/add', methods=['POST'])
@login_required
@limiter.limit("30 per minute")
def add_to_cart():
    """Add product to cart"""
    product_id = request.form.get('product_id')
    quantity = request.form.get('quantity', 1, type=int)
    
    if not product_id:
        flash('Product ID is required', 'danger')
        return redirect(request.referrer or url_for('marketplace.index'))
    
    if quantity < 1:
        quantity = 1
    
    try:
        cart = Cart.get_or_create(current_user.id)
        cart.add_item(product_id, quantity)
        flash('Product added to cart', 'success')
    except ValueError as e:
        flash(str(e), 'danger')
    except Exception as e:
        flash('Error adding to cart', 'danger')
    
    return redirect(request.referrer or url_for('marketplace.index'))


@cart_bp.route('/add-ajax', methods=['POST'])
@login_required
@limiter.limit("30 per minute")
def add_to_cart_ajax():
    """Add product to cart (AJAX)"""
    data = request.get_json()
    product_id = data.get('product_id')
    quantity = data.get('quantity', 1)
    
    if not product_id:
        return jsonify({'success': False, 'error': 'Product ID required'}), 400
    
    try:
        cart = Cart.get_or_create(current_user.id)
        item = cart.add_item(product_id, quantity)
        return jsonify({
            'success': True,
            'message': 'Product added to cart',
            'cart_total': cart.total_items,
            'item': item.to_dict()
        })
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': 'Error adding to cart'}), 500


@cart_bp.route('/update', methods=['POST'])
@login_required
@limiter.limit("30 per minute")
def update_quantity():
    """Update cart item quantity"""
    product_id = request.form.get('product_id')
    quantity = request.form.get('quantity', 1, type=int)
    
    if not product_id:
        flash('Product ID is required', 'danger')
        return redirect(url_for('cart.view_cart'))
    
    try:
        cart = Cart.get_or_create(current_user.id)
        cart.update_item_quantity(product_id, quantity)
        if quantity <= 0:
            flash('Item removed from cart', 'info')
        else:
            flash('Cart updated', 'success')
    except ValueError as e:
        flash(str(e), 'danger')
    except Exception as e:
        flash('Error updating cart', 'danger')
    
    return redirect(url_for('cart.view_cart'))


@cart_bp.route('/remove/<uuid:product_id>', methods=['POST'])
@login_required
def remove_from_cart(product_id):
    """Remove item from cart"""
    try:
        cart = Cart.get_or_create(current_user.id)
        cart.remove_item(product_id)
        flash('Item removed from cart', 'success')
    except Exception as e:
        flash('Error removing item', 'danger')
    
    return redirect(url_for('cart.view_cart'))


@cart_bp.route('/clear', methods=['POST'])
@login_required
def clear_cart():
    """Clear all items from cart"""
    try:
        cart = Cart.get_or_create(current_user.id)
        cart.clear()
        flash('Cart cleared', 'success')
    except Exception as e:
        flash('Error clearing cart', 'danger')
    
    return redirect(url_for('cart.view_cart'))


@cart_bp.route('/checkout', methods=['GET', 'POST'])
@login_required
@limiter.limit("10 per minute")
def checkout():
    """Checkout process"""
    cart = Cart.get_or_create(current_user.id)
    
    # Check if cart is empty
    if cart.total_items == 0:
        flash('Your cart is empty', 'warning')
        return redirect(url_for('marketplace.index'))
    
    # Validate items
    validation_errors = cart.validate_items()
    if validation_errors:
        for error in validation_errors:
            flash(error, 'danger')
        return redirect(url_for('cart.view_cart'))
    
    # Group items by vendor
    items_by_vendor = cart.get_items_grouped_by_vendor()
    
    from app.models.user import User
    vendors = {}
    for vendor_id in items_by_vendor.keys():
        vendor = User.query.get(vendor_id)
        if vendor:
            vendors[vendor_id] = vendor
    
    if request.method == 'POST':
        # Get shipping information
        shipping_name = request.form.get('shipping_name', '').strip()
        shipping_address = request.form.get('shipping_address', '').strip()
        buyer_notes = request.form.get('buyer_notes', '').strip()
        
        # Check if any items are physical and need shipping
        has_physical = any(not item.product.is_digital for item in cart.items)
        
        if has_physical and (not shipping_name or not shipping_address):
            flash('Shipping information is required for physical products', 'danger')
            return render_template('cart/checkout.html',
                                 cart=cart,
                                 items_by_vendor=items_by_vendor,
                                 vendors=vendors)
        
        try:
            # Create orders for each vendor
            orders_created = []
            from flask import current_app
            commission_percent = current_app.config.get('ESCROW_COMMISSION_PERCENT', 3.0)
            
            for vendor_id, items in items_by_vendor.items():
                for item in items:
                    # Calculate totals
                    total_price = item.unit_price * item.quantity
                    commission = total_price * Decimal(str(commission_percent / 100))
                    
                    # Create order
                    order = Order(
                        id=uuid.uuid4(),
                        buyer_id=current_user.id,
                        vendor_id=uuid.UUID(vendor_id),
                        product_id=item.product_id,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        total_price=total_price,
                        commission=commission,
                        is_digital=item.product.is_digital,
                        buyer_notes=buyer_notes if buyer_notes else None,
                        created_at=datetime.utcnow()
                    )
                    
                    db.session.add(order)
                    db.session.flush()  # Get the order ID
                    
                    # Set encrypted shipping info if physical
                    if not item.product.is_digital:
                        order.set_shipping_name(shipping_name)
                        order.set_shipping_address(shipping_address)
                    
                    # Create escrow
                    escrow_service = EscrowService()
                    escrow_service.create_escrow_for_order(order)
                    
                    orders_created.append(order)
            
            # Clear cart after successful checkout
            cart.clear()
            
            db.session.commit()
            
            flash(f'Successfully created {len(orders_created)} order(s)! Please proceed to payment.', 'success')
            
            # Redirect to first order if only one, otherwise to orders list
            if len(orders_created) == 1:
                return redirect(url_for('buyer.order_detail', order_id=orders_created[0].id))
            else:
                return redirect(url_for('buyer.orders'))
        
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating order: {str(e)}', 'danger')
            return render_template('cart/checkout.html',
                                 cart=cart,
                                 items_by_vendor=items_by_vendor,
                                 vendors=vendors)
    
    return render_template('cart/checkout.html',
                         cart=cart,
                         items_by_vendor=items_by_vendor,
                         vendors=vendors)


@cart_bp.route('/count')
@login_required
def cart_count():
    """Get cart item count (AJAX)"""
    cart = Cart.get_or_create(current_user.id)
    return jsonify({'count': cart.total_items})
