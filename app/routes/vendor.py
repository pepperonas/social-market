"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Vendor Routes - Placeholder
Purpose: Vendor dashboard and product management
"""

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from functools import wraps

vendor_bp = Blueprint('vendor', __name__)


def vendor_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_vendor():
            flash('Vendor access required', 'error')
            return redirect(url_for('marketplace.index'))
        return f(*args, **kwargs)
    return decorated_function


@vendor_bp.route('/dashboard')
@login_required
@vendor_required
def dashboard():
    """Vendor dashboard"""
    from app.models.product import Product
    from app.models.order import Order
    from flask_login import current_user

    stats = {
        'total_products': Product.query.filter_by(vendor_id=current_user.id).count(),
        'total_orders': Order.query.filter_by(vendor_id=current_user.id).count(),
        'total_sales': Order.query.filter_by(vendor_id=current_user.id, status='completed').count(),
        'total_revenue': 0  # TODO: Calculate actual revenue
    }

    return render_template('vendor/dashboard.html', stats=stats)


@vendor_bp.route('/products')
@login_required
@vendor_required
def products():
    """Vendor products list"""
    from app.models.product import Product

    # Get all products for current vendor
    vendor_products = Product.query.filter_by(vendor_id=current_user.id).order_by(Product.created_at.desc()).all()

    return render_template('vendor/products.html', products=vendor_products)


@vendor_bp.route('/orders')
@login_required
@vendor_required
def orders():
    """Vendor orders list"""
    return render_template('vendor/orders.html')


@vendor_bp.route('/add-product', methods=['GET', 'POST'])
@login_required
@vendor_required
def add_product():
    """Add new product"""
    from app.models.product import Product, ProductCategory
    from app import db
    from flask import request
    import uuid
    from datetime import datetime

    if request.method == 'POST':
        try:
            # Get form data
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            price = float(request.form.get('price', 0))
            category_id = request.form.get('category_id', '')
            quantity = int(request.form.get('quantity', 0))
            is_digital = request.form.get('is_digital') == 'on'
            tags = request.form.get('tags', '').strip()

            # Validation
            if not title or len(title) < 3:
                flash('Title must be at least 3 characters', 'danger')
                return redirect(url_for('vendor.add_product'))

            if not description or len(description) < 10:
                flash('Description must be at least 10 characters', 'danger')
                return redirect(url_for('vendor.add_product'))

            if price <= 0:
                flash('Price must be greater than 0', 'danger')
                return redirect(url_for('vendor.add_product'))

            if not category_id:
                flash('Please select a category', 'danger')
                return redirect(url_for('vendor.add_product'))

            # Verify category exists
            category = ProductCategory.query.get(category_id)
            if not category:
                flash('Invalid category', 'danger')
                return redirect(url_for('vendor.add_product'))

            # Create product
            product = Product(
                id=uuid.uuid4(),
                vendor_id=current_user.id,
                category_id=category_id,
                title=title,
                description=description,
                price=price,
                quantity=quantity if not is_digital else 0,
                is_digital=is_digital,
                tags=tags if tags else None,
                is_active=True,
                is_approved=True,  # Auto-approve for training environment
                created_at=datetime.utcnow()
            )

            db.session.add(product)
            db.session.commit()

            flash(f'Product "{title}" created successfully!', 'success')
            return redirect(url_for('vendor.products'))

        except ValueError as e:
            flash(f'Invalid input: {str(e)}', 'danger')
            return redirect(url_for('vendor.add_product'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating product: {str(e)}', 'danger')
            return redirect(url_for('vendor.add_product'))

    # GET request - show form
    categories = ProductCategory.query.filter_by(is_active=True).order_by(ProductCategory.name).all()
    return render_template('vendor/add_product.html', categories=categories)


@vendor_bp.route('/order/<uuid:order_id>')
@login_required
@vendor_required
def order_detail(order_id):
    """View order details"""
    from app.models.order import Order
    order = Order.query.get_or_404(order_id)
    return render_template('vendor/orders.html')


@vendor_bp.route('/product/<uuid:product_id>/edit', methods=['GET', 'POST'])
@login_required
@vendor_required
def edit_product(product_id):
    """Edit existing product"""
    from app.models.product import Product, ProductCategory
    from app import db
    from flask import request
    from datetime import datetime

    product = Product.query.get_or_404(product_id)

    # Check if user is the vendor of this product
    if product.vendor_id != current_user.id:
        flash('You do not have permission to edit this product', 'danger')
        return redirect(url_for('vendor.products'))

    if request.method == 'POST':
        try:
            # Get form data
            product.title = request.form.get('title', '').strip()
            product.description = request.form.get('description', '').strip()
            product.price = float(request.form.get('price', 0))
            product.category_id = request.form.get('category_id', '')
            product.quantity = int(request.form.get('quantity', 0))
            product.is_digital = request.form.get('is_digital') == 'on'
            product.tags = request.form.get('tags', '').strip() or None
            product.updated_at = datetime.utcnow()

            # Validation
            if not product.title or len(product.title) < 3:
                flash('Title must be at least 3 characters', 'danger')
                return redirect(url_for('vendor.edit_product', product_id=product_id))

            if not product.description or len(product.description) < 10:
                flash('Description must be at least 10 characters', 'danger')
                return redirect(url_for('vendor.edit_product', product_id=product_id))

            if product.price <= 0:
                flash('Price must be greater than 0', 'danger')
                return redirect(url_for('vendor.edit_product', product_id=product_id))

            db.session.commit()
            flash(f'Product "{product.title}" updated successfully!', 'success')
            return redirect(url_for('vendor.products'))

        except ValueError as e:
            flash(f'Invalid input: {str(e)}', 'danger')
            return redirect(url_for('vendor.edit_product', product_id=product_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating product: {str(e)}', 'danger')
            return redirect(url_for('vendor.edit_product', product_id=product_id))

    # GET request - show form
    categories = ProductCategory.query.filter_by(is_active=True).order_by(ProductCategory.name).all()
    return render_template('vendor/edit_product.html', product=product, categories=categories)


@vendor_bp.route('/product/<uuid:product_id>/delete', methods=['POST'])
@login_required
@vendor_required
def delete_product(product_id):
    """Delete product"""
    from app.models.product import Product
    from app import db

    product = Product.query.get_or_404(product_id)

    # Check if user is the vendor of this product
    if product.vendor_id != current_user.id:
        flash('You do not have permission to delete this product', 'danger')
        return redirect(url_for('vendor.products'))

    try:
        product_title = product.title
        db.session.delete(product)
        db.session.commit()
        flash(f'Product "{product_title}" deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting product: {str(e)}', 'danger')

    return redirect(url_for('vendor.products'))
