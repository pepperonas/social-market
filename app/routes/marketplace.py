"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Marketplace Routes
Purpose: Public marketplace browsing and product discovery
"""

from werkzeug.exceptions import NotFound
from flask import Blueprint, render_template, request, abort
from flask_login import login_required
from sqlalchemy import or_, and_

from app import limiter
from app.models.product import Product, ProductCategory, ProductReview

marketplace_bp = Blueprint('marketplace', __name__)


@marketplace_bp.route('/')
@login_required
@limiter.limit("10 per second")
def index():
    """
    Marketplace homepage
    - Featured products
    - Recently listed
    - Top rated
    """
    # Get featured products (active, approved, in stock)
    featured_products = Product.query.filter_by(
        is_active=True,
        is_approved=True
    ).order_by(Product.rating_average.desc()).limit(12).all()

    # Get recent products
    recent_products = Product.query.filter_by(
        is_active=True,
        is_approved=True
    ).order_by(Product.created_at.desc()).limit(12).all()

    # Get categories
    categories = ProductCategory.query.filter_by(is_active=True).all()

    return render_template('marketplace/index.html',
                          featured_products=featured_products,
                          recent_products=recent_products,
                          categories=categories)


@marketplace_bp.route('/media/products/<path:filename>')
@limiter.exempt
def product_image(filename):
    """
    Serve a product image.

    Exempt from rate limiting on purpose. The default limit is 10 requests per
    second per client, and a listing page references twenty images -- so the
    app throttled its own page into blank tiles (measured: 10x200, 10x429).
    A rate limit exists to bound expensive or abusable work; applying it to
    static bytes turns a protection into a self-inflicted denial of service.

    `send_from_directory` resolves the path and refuses anything that escapes
    the directory, which is the control that matters here -- but the filename is
    also matched against a strict pattern first, so a traversal attempt is
    rejected before it reaches the filesystem rather than after.
    """
    import os
    import re

    from flask import abort, current_app, send_from_directory

    if not re.fullmatch(r'[A-Za-z0-9._-]{1,120}', filename):
        abort(404)

    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'products')
    try:
        return send_from_directory(folder, filename, max_age=3600)
    except NotFound:
        abort(404)


@marketplace_bp.route('/search')
@login_required
@limiter.limit("10 per second")
def search():
    """
    Product search with filters
    - Search by title/description
    - Filter by category
    - Filter by price range
    - Sort options
    """
    # Get search parameters
    query = request.args.get('q', '').strip()
    category_id = request.args.get('category')
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    sort_by = request.args.get('sort', 'relevance')
    page = request.args.get('page', 1, type=int)

    # Build query
    products_query = Product.query.filter_by(
        is_active=True,
        is_approved=True
    )

    # Search filter
    if query:
        search_filter = or_(
            Product.title.ilike(f'%{query}%'),
            Product.description.ilike(f'%{query}%'),
            Product.search_vector.ilike(f'%{query.lower()}%')
        )
        products_query = products_query.filter(search_filter)

    # Category filter
    if category_id:
        products_query = products_query.filter_by(category_id=category_id)

    # Price range filter
    if min_price is not None:
        products_query = products_query.filter(Product.price >= min_price)
    if max_price is not None:
        products_query = products_query.filter(Product.price <= max_price)

    # Sorting
    if sort_by == 'price_asc':
        products_query = products_query.order_by(Product.price.asc())
    elif sort_by == 'price_desc':
        products_query = products_query.order_by(Product.price.desc())
    elif sort_by == 'rating':
        products_query = products_query.order_by(Product.rating_average.desc())
    elif sort_by == 'newest':
        products_query = products_query.order_by(Product.created_at.desc())
    else:  # relevance (default)
        products_query = products_query.order_by(Product.views.desc())

    # Pagination
    products = products_query.paginate(page=page, per_page=24, error_out=False)

    # Get categories for filter
    categories = ProductCategory.query.filter_by(is_active=True).all()

    return render_template('marketplace/search.html',
                          products=products,
                          categories=categories,
                          query=query,
                          category_id=category_id,
                          sort_by=sort_by)


@marketplace_bp.route('/product/<uuid:product_id>')
@login_required
@limiter.limit("10 per second")
def product_detail(product_id):
    """
    Product detail page
    - Product information
    - Vendor information
    - Reviews
    - Similar products
    """
    product = Product.query.get_or_404(product_id)

    # Check if product is accessible
    if not product.is_active or not product.is_approved:
        abort(404)

    # Increment view count
    product.increment_views()

    # Get reviews
    reviews = ProductReview.query.filter_by(
        product_id=product.id,
        is_approved=True
    ).order_by(ProductReview.created_at.desc()).limit(10).all()

    # Get similar products (same category)
    similar_products = Product.query.filter(
        and_(
            Product.category_id == product.category_id,
            Product.id != product.id,
            Product.is_active == True,
            Product.is_approved == True
        )
    ).order_by(Product.rating_average.desc()).limit(6).all()

    return render_template('marketplace/product_detail.html',
                          product=product,
                          reviews=reviews,
                          similar_products=similar_products)


@marketplace_bp.route('/category/<uuid:category_id>')
@login_required
@limiter.limit("10 per second")
def category(category_id):
    """Browse products by category"""
    category = ProductCategory.query.get_or_404(category_id)

    if not category.is_active:
        abort(404)

    page = request.args.get('page', 1, type=int)
    sort_by = request.args.get('sort', 'newest')

    # Build query
    products_query = Product.query.filter_by(
        category_id=category_id,
        is_active=True,
        is_approved=True
    )

    # Sorting
    if sort_by == 'price_asc':
        products_query = products_query.order_by(Product.price.asc())
    elif sort_by == 'price_desc':
        products_query = products_query.order_by(Product.price.desc())
    elif sort_by == 'rating':
        products_query = products_query.order_by(Product.rating_average.desc())
    else:  # newest
        products_query = products_query.order_by(Product.created_at.desc())

    # Pagination
    products = products_query.paginate(page=page, per_page=24, error_out=False)

    return render_template('marketplace/category.html',
                          category=category,
                          products=products,
                          sort_by=sort_by)


@marketplace_bp.route('/vendor/<uuid:vendor_id>')
@login_required
@limiter.limit("10 per second")
def vendor_profile(vendor_id):
    """Public vendor profile"""
    from app.models.user import User

    vendor = User.query.get_or_404(vendor_id)

    if not vendor.is_vendor() or not vendor.is_active:
        abort(404)

    # Get vendor's products
    page = request.args.get('page', 1, type=int)
    products = Product.query.filter_by(
        vendor_id=vendor_id,
        is_active=True,
        is_approved=True
    ).order_by(Product.created_at.desc()).paginate(page=page, per_page=24, error_out=False)

    return render_template('marketplace/vendor_profile.html',
                          vendor=vendor,
                          products=products)
