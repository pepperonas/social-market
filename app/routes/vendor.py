"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Vendor Routes - Placeholder
Purpose: Vendor dashboard and product management
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from functools import wraps
from app import db

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

    # Calculate actual revenue from completed orders
    from sqlalchemy import func
    total_revenue = db.session.query(
        func.coalesce(func.sum(Order.total_price), 0)
    ).filter(
        Order.vendor_id == current_user.id,
        Order.status == 'completed'
    ).scalar()

    stats = {
        'total_products': Product.query.filter_by(vendor_id=current_user.id).count(),
        'total_orders': Order.query.filter_by(vendor_id=current_user.id).count(),
        'total_sales': Order.query.filter_by(vendor_id=current_user.id, status='completed').count(),
        'total_revenue': float(total_revenue)
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
    """Vendor orders list with filtering"""
    from app.models.order import Order
    from flask import request
    
    # Get filter parameters
    status = request.args.get('status', '')
    page = request.args.get('page', 1, type=int)
    
    # Build query
    query = Order.query.filter_by(vendor_id=current_user.id)
    
    if status:
        query = query.filter_by(status=status)
    
    # Paginate results
    orders_pagination = query.order_by(Order.created_at.desc()).paginate(
        page=page,
        per_page=20,
        error_out=False
    )
    
    # Get order statistics
    from sqlalchemy import func
    stats = {
        'pending': Order.query.filter_by(vendor_id=current_user.id, status='pending').count(),
        'paid': Order.query.filter_by(vendor_id=current_user.id, status='paid').count(),
        'shipped': Order.query.filter_by(vendor_id=current_user.id, status='shipped').count(),
        'completed': Order.query.filter_by(vendor_id=current_user.id, status='completed').count(),
        'disputed': Order.query.filter_by(vendor_id=current_user.id, status='disputed').count()
    }
    
    return render_template('vendor/orders.html', 
                         orders=orders_pagination, 
                         stats=stats,
                         current_status=status)


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
    from app.models.user import User
    
    order = Order.query.get_or_404(order_id)
    
    # Verify vendor owns this order
    if str(order.vendor_id) != str(current_user.id):
        flash('You do not have permission to view this order', 'danger')
        return redirect(url_for('vendor.orders'))
    
    # Get buyer info
    buyer = User.query.get(order.buyer_id)
    
    # Get shipping info (decrypted) for paid orders
    shipping_name = None
    shipping_address = None
    if order.status not in ['pending', 'cancelled']:
        try:
            shipping_name = order.get_shipping_name()
            shipping_address = order.get_shipping_address()
        except:
            pass
    
    return render_template('vendor/order_detail.html', 
                         order=order, 
                         buyer=buyer,
                         shipping_name=shipping_name,
                         shipping_address=shipping_address)


@vendor_bp.route('/order/<uuid:order_id>/ship', methods=['POST'])
@login_required
@vendor_required
def ship_order(order_id):
    """Mark order as shipped"""
    from app.models.order import Order, OrderStatus
    from app import db
    
    order = Order.query.get_or_404(order_id)
    
    # Verify vendor owns this order
    if str(order.vendor_id) != str(current_user.id):
        flash('You do not have permission to modify this order', 'danger')
        return redirect(url_for('vendor.orders'))
    
    # Check if order can be shipped
    if order.status != 'paid':
        flash('Only paid orders can be marked as shipped', 'warning')
        return redirect(url_for('vendor.order_detail', order_id=order_id))
    
    tracking_number = request.form.get('tracking_number', '').strip()
    vendor_notes = request.form.get('vendor_notes', '').strip()
    
    try:
        order.transition_to(OrderStatus.SHIPPED, tracking_number=tracking_number)
        if vendor_notes:
            order.vendor_notes = vendor_notes
        db.session.commit()
        
        flash('Order marked as shipped!', 'success')
    except ValueError as e:
        flash(str(e), 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating order: {str(e)}', 'danger')
    
    return redirect(url_for('vendor.order_detail', order_id=order_id))


@vendor_bp.route('/order/<uuid:order_id>/cancel', methods=['POST'])
@login_required
@vendor_required
def cancel_order(order_id):
    """Cancel order (vendor side)"""
    from app.models.order import Order, OrderStatus
    from app import db
    
    order = Order.query.get_or_404(order_id)
    
    # Verify vendor owns this order
    if str(order.vendor_id) != str(current_user.id):
        flash('You do not have permission to modify this order', 'danger')
        return redirect(url_for('vendor.orders'))
    
    # Check if order can be cancelled
    if order.status not in ['pending', 'paid']:
        flash('This order cannot be cancelled', 'warning')
        return redirect(url_for('vendor.order_detail', order_id=order_id))
    
    cancel_reason = request.form.get('cancel_reason', '').strip()
    
    try:
        order.transition_to(OrderStatus.CANCELLED)
        order.vendor_notes = f'Cancelled by vendor: {cancel_reason}'
        db.session.commit()
        
        flash('Order cancelled', 'info')
    except ValueError as e:
        flash(str(e), 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error cancelling order: {str(e)}', 'danger')
    
    return redirect(url_for('vendor.orders'))


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


@vendor_bp.route('/product/<uuid:product_id>/upload-image', methods=['POST'])
@login_required
@vendor_required
def upload_product_image(product_id):
    """Upload image for product with EXIF stripping"""
    from app.models.product import Product, ProductImage
    from app.services.image_service import get_image_service
    from app import db
    import uuid
    
    product = Product.query.get_or_404(product_id)
    
    # Verify vendor owns this product
    if str(product.vendor_id) != str(current_user.id):
        flash('You do not have permission to modify this product', 'danger')
        return redirect(url_for('vendor.products'))
    
    # Check if file was uploaded
    if 'image' not in request.files:
        flash('No image file provided', 'danger')
        return redirect(url_for('vendor.edit_product', product_id=product_id))
    
    file = request.files['image']
    
    if file.filename == '':
        flash('No image selected', 'danger')
        return redirect(url_for('vendor.edit_product', product_id=product_id))
    
    # Process image
    image_service = get_image_service()
    result = image_service.save_image(
        file, 
        subfolder=f'products/{product_id}',
        create_thumbnail=True
    )
    
    if not result['success']:
        flash(f'Image upload failed: {result["error"]}', 'danger')
        return redirect(url_for('vendor.edit_product', product_id=product_id))
    
    try:
        # Check if this should be primary image
        existing_images = ProductImage.query.filter_by(product_id=product_id).count()
        is_primary = existing_images == 0
        
        # Create image record
        image = ProductImage(
            id=uuid.uuid4(),
            product_id=product_id,
            filename=result['filename'],
            filepath=result['filepath'],
            file_size=result['file_size'],
            mime_type='image/jpeg',  # After processing
            metadata_stripped=True,
            is_primary=is_primary,
            display_order=existing_images
        )
        
        db.session.add(image)
        db.session.commit()
        
        flash('Image uploaded successfully (metadata stripped for privacy)', 'success')
        
    except Exception as e:
        db.session.rollback()
        # Try to delete uploaded file
        image_service.delete_image(result['filepath'])
        flash(f'Error saving image: {str(e)}', 'danger')
    
    return redirect(url_for('vendor.edit_product', product_id=product_id))


@vendor_bp.route('/product/<uuid:product_id>/delete-image/<uuid:image_id>', methods=['POST'])
@login_required
@vendor_required
def delete_product_image(product_id, image_id):
    """Delete product image"""
    from app.models.product import Product, ProductImage
    from app.services.image_service import get_image_service
    from app import db
    
    product = Product.query.get_or_404(product_id)
    
    # Verify vendor owns this product
    if str(product.vendor_id) != str(current_user.id):
        flash('You do not have permission to modify this product', 'danger')
        return redirect(url_for('vendor.products'))
    
    image = ProductImage.query.get_or_404(image_id)
    
    # Verify image belongs to product
    if str(image.product_id) != str(product_id):
        flash('Image not found', 'danger')
        return redirect(url_for('vendor.edit_product', product_id=product_id))
    
    try:
        # Delete file
        image_service = get_image_service()
        image_service.delete_image(image.filepath)
        
        # Delete thumbnail if exists
        if hasattr(image, 'thumbnail_path') and image.thumbnail_path:
            image_service.delete_image(image.thumbnail_path)
        
        # Delete record
        db.session.delete(image)
        db.session.commit()
        
        flash('Image deleted', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting image: {str(e)}', 'danger')
    
    return redirect(url_for('vendor.edit_product', product_id=product_id))
