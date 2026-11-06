"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Shopping Cart Routes
Purpose: Secure shopping cart management
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
import uuid

from app import db, limiter
from app.models.cart import Cart, CartItem
from app.models.order import Order
from app.services.escrow_service import EscrowService
from app.timeutil import utcnow


class _OutOfStock(Exception):
    def __init__(self, title):
        super().__init__(title)
        self.title = title


class _CartChanged(Exception):
    pass


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
        vendor = db.session.get(User, vendor_id)
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
    except Exception:
        flash('Error adding to cart', 'danger')

    return redirect(request.referrer or url_for('marketplace.index'))


@cart_bp.route('/add-ajax', methods=['POST'])
@login_required
@limiter.limit("30 per minute")
def add_to_cart_ajax():
    """Add product to cart (AJAX)"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Expected a JSON object'}), 400
    product_id = data.get('product_id')
    # Validated in Cart.add_item (Cart.parse_quantity). This route used to pass
    # the raw JSON value through, so {"quantity": -5} became a negative order.
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
    except Exception:
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
    except Exception:
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
    except Exception:
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
    except Exception:
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
        vendor = db.session.get(User, vendor_id)
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

        # One transaction for the whole checkout.
        #
        # This used to commit inside the item loop: create_escrow_for_order()
        # and set_shipping_*() each committed (and so did every audit call). A
        # failure at item 2 left item 1's order committed while the cart stayed
        # full -- and the retry ordered item 1 a second time. Nothing in here
        # commits now; the single commit at the end makes it all or nothing.
        items = list(cart.items)
        try:
            orders_created = []
            for item in items:
                product = item.product
                if not product.reserve_stock(item.quantity):
                    raise _OutOfStock(product.title)

                order = Order(
                    id=uuid.uuid4(),
                    buyer_id=current_user.id,
                    vendor_id=product.vendor_id,
                    product_id=product.id,
                    quantity=item.quantity,
                    # The current price -- validate_items() refused the checkout
                    # above if it differs from what the buyer last saw.
                    unit_price=product.price,
                    # total_price and commission: before_insert listener
                    is_digital=product.is_digital,
                    buyer_notes=buyer_notes if buyer_notes else None,
                    created_at=utcnow()
                )
                db.session.add(order)
                db.session.flush()

                if not product.is_digital:
                    order.set_shipping_name(shipping_name)
                    order.set_shipping_address(shipping_address)

                EscrowService.create_escrow_for_order(order)
                orders_created.append(order)

            # Empty the cart in the same transaction, and claim it: if a second,
            # concurrent submit of the same cart got here first, its delete
            # already took these rows and this one deletes fewer than it
            # ordered -- abort instead of creating the orders twice.
            deleted = CartItem.query.filter(
                CartItem.id.in_([item.id for item in items])
            ).delete(synchronize_session=False)
            if deleted != len(items):
                raise _CartChanged()

            db.session.commit()

        except _OutOfStock as exc:
            db.session.rollback()
            flash(f'{exc.title} is no longer available in that quantity', 'danger')
            return redirect(url_for('cart.view_cart'))
        except _CartChanged:
            db.session.rollback()
            flash('Your cart changed while checking out. Please review it.', 'warning')
            return redirect(url_for('cart.view_cart'))
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Checkout failed for user %s', current_user.id)
            flash('Could not complete the checkout. Nothing was ordered; please try again.',
                  'danger')
            return redirect(url_for('cart.view_cart'))

        flash(f'Successfully created {len(orders_created)} order(s)! Please proceed to payment.',
              'success')
        if len(orders_created) == 1:
            return redirect(url_for('buyer.order_detail', order_id=orders_created[0].id))
        return redirect(url_for('buyer.orders'))

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
