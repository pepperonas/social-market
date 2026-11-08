"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Product Model
Purpose: Product listings with security and metadata handling
"""

import uuid
from decimal import Decimal, InvalidOperation

from app.models.types import UUID
from sqlalchemy import CheckConstraint, Index

from app import db
from app.timeutil import utcnow


class ProductCategory(db.Model):
    """
    Product categories (LEGAL CATEGORIES ONLY for educational purposes)
    Examples: Books, Art, Digital Goods, Services
    """

    __tablename__ = 'product_categories'

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(100), unique=True, nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    # Relationships
    products = db.relationship('Product', backref='category', lazy='dynamic')

    def __repr__(self):
        return f'<ProductCategory {self.name}>'


class Product(db.Model):
    """
    Product model with security features:
    - UUID primary keys
    - Vendor association
    - Image metadata stripping
    - Search indexing
    - Audit trail
    """

    __tablename__ = 'products'

    # Primary identification
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False, index=True)
    category_id = db.Column(UUID(as_uuid=True), db.ForeignKey('product_categories.id'), nullable=False)

    # Product information
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)

    # Inventory
    quantity = db.Column(db.Integer, default=0)
    is_digital = db.Column(db.Boolean, default=False)

    # Status
    is_active = db.Column(db.Boolean, default=True)
    is_approved = db.Column(db.Boolean, default=False)  # set only by an admin, see approve()
    # Moderation trail (plan 2026-11, B1). Until then vendor.py wrote
    # is_approved=True itself, "auto-approve for training environment": the
    # column promised an admin check that did not exist.
    rejection_reason = db.Column(db.Text, nullable=True)
    moderated_at = db.Column(db.DateTime, nullable=True)
    moderated_by = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=True)

    # Search and discovery
    tags = db.Column(db.Text, nullable=True)  # Comma-separated tags
    search_vector = db.Column(db.Text, nullable=True)  # For full-text search

    # Statistics
    views = db.Column(db.Integer, default=0)
    sales = db.Column(db.Integer, default=0)

    # Ratings
    rating_average = db.Column(db.Float, default=0.0)
    rating_count = db.Column(db.Integer, default=0)

    # Timestamps
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    images = db.relationship('ProductImage', backref='product', lazy='dynamic',
                            cascade='all, delete-orphan')
    orders = db.relationship('Order', backref='product', lazy='dynamic')
    reviews = db.relationship('ProductReview', backref='product', lazy='dynamic',
                             cascade='all, delete-orphan')

    # Indexes for performance
    __table_args__ = (
        # Last line of defence behind parse_price / parse_stock / reserve_stock:
        # a request that slips past the Python checks still cannot store a free
        # product or sell stock that is not there.
        # The upper bound is not decoration: PostgreSQL sorts NaN above every
        # number, so `price > 0` alone is TRUE for NaN. `price <= 100000` is not.
        CheckConstraint('price > 0 AND price <= 100000', name='ck_product_price_positive'),
        CheckConstraint('quantity >= 0', name='ck_product_quantity_nonnegative'),
        Index('idx_product_vendor_active', vendor_id, is_active),
        Index('idx_product_category_active', category_id, is_active),
        Index('idx_product_price', price),
        Index('idx_product_created', created_at.desc()),
    )

    def __repr__(self):
        return f'<Product {self.title}>'

    # =============================================================================
    # Business Logic
    # =============================================================================

    def increment_views(self):
        """Count a view, in SQL (`self.views += 1` loses counts under concurrency)."""
        db.session.query(Product).filter(Product.id == self.id).update(
            {Product.views: db.func.coalesce(Product.views, 0) + 1}, synchronize_session=False)
        db.session.commit()

    # Upper bounds keep a typo from becoming a 7-digit price or a stock level
    # nobody will ever sell; they also stay well inside Numeric(10, 2).
    MAX_PRICE = Decimal('100000.00')
    MAX_STOCK = 100000

    @classmethod
    def parse_price(cls, raw):
        """
        Parse a price from a form field. Returns a Decimal or raises ValueError.

        Prices used to go through float(). float('nan') passes `price <= 0`
        (every comparison with NaN is False) and PostgreSQL's NUMERIC stores NaN
        happily; float('0.001') passes too and is stored as 0.00 -- a free
        product. Money is Decimal end to end, so it is parsed as one.
        """
        try:
            value = Decimal(str(raw).strip())
        except (InvalidOperation, ValueError):
            raise ValueError('Price must be a number, e.g. 19.99')
        if not value.is_finite():
            raise ValueError('Price must be a number, e.g. 19.99')
        if value != value.quantize(Decimal('0.01')):
            raise ValueError('Price can have at most two decimal places')
        if value <= 0:
            raise ValueError('Price must be greater than 0')
        if value > cls.MAX_PRICE:
            raise ValueError(f'Price must not exceed {cls.MAX_PRICE}')
        return value.quantize(Decimal('0.01'))

    @classmethod
    def parse_stock(cls, raw):
        """Parse a stock level from a form field: a whole number from 0 to MAX_STOCK."""
        try:
            value = int(str(raw).strip())
        except ValueError:
            raise ValueError('Stock must be a whole number')
        if not 0 <= value <= cls.MAX_STOCK:
            raise ValueError(f'Stock must be between 0 and {cls.MAX_STOCK}')
        return value

    def reserve_stock(self, quantity):
        """
        Take ``quantity`` units out of stock for an order, atomically.

        Returns False if there are not enough. Stock used to be decremented only
        when an order was *paid* -- which never happened -- so every pending
        order passed the availability check for the same last unit.

        The check and the decrement are one UPDATE with the condition in its
        WHERE clause. Reading the quantity in Python and writing it back would
        let two concurrent orders both see "1 left" and both succeed.
        """
        if self.is_digital:
            return True
        rows = db.session.query(Product).filter(
            Product.id == self.id,
            Product.quantity >= quantity,
        ).update({Product.quantity: Product.quantity - quantity}, synchronize_session=False)
        db.session.expire(self, ['quantity'])
        return rows == 1

    def release_stock(self, quantity):
        """Put reserved units back (order cancelled before it shipped)."""
        if self.is_digital:
            return
        db.session.query(Product).filter(Product.id == self.id).update(
            {Product.quantity: db.func.coalesce(Product.quantity, 0) + quantity}, synchronize_session=False)
        db.session.expire(self, ['quantity'])

    def record_sale(self, quantity=1):
        """
        Count ``quantity`` units as sold. Does NOT touch stock any more.

        History: this once decremented stock by a flat 1 whatever the order size
        (overselling); the fix made it subtract the real quantity -- at PAID.
        But stock has to be held from the moment an order is placed, so that is
        now reserve_stock()'s job, and a sale is counted when the order
        completes and the money actually moves. Counting at PAID would have
        needed undoing on every cancellation and refund.
        """
        quantity = max(1, int(quantity or 1))
        db.session.query(Product).filter(Product.id == self.id).update(
            {Product.sales: db.func.coalesce(Product.sales, 0) + quantity}, synchronize_session=False)
        db.session.expire(self, ['sales'])

    @property
    def primary_image_url(self):
        """
        URL of the product's primary image, or None.

        Templates used to interpolate `product.images[0]` straight into a src
        attribute, which renders the ProductImage *object*, not a URL -- and
        nothing served the files anyway. Go through this property so there is
        one place that knows how an image becomes a URL.
        """
        from flask import url_for

        image = (
            self.images.filter_by(is_primary=True).first()
            or self.images.order_by(ProductImage.display_order).first()
        )
        if not image:
            return None

        # Uploads are stored as 'products/<product id>/<file>' and must be
        # served from that subdirectory; the generated covers sit directly in
        # 'products/' (and record an absolute filepath, hence the fallback).
        # Using the bare filename sent every uploaded image to a 404.
        if image.filepath and image.filepath.startswith('products/'):
            relative = image.filepath[len('products/'):]
        else:
            relative = image.filename
        return url_for('marketplace.product_image', filename=relative)

    def is_in_stock(self):
        """Check if product is in stock"""
        if self.is_digital:
            return True
        return self.quantity > 0

    def can_purchase(self, quantity=1):
        """
        Check if product can be purchased

        Args:
            quantity: Number of items to purchase

        Returns:
            tuple: (bool, str) - (can_purchase, error_message)
        """
        if not self.is_active:
            return False, "Product is not active"

        if not self.is_approved:
            return False, "Product is not approved"

        if not self.is_digital and self.quantity < quantity:
            return False, "Insufficient quantity"

        return True, None

    # =============================================================================
    # Moderation (plan 2026-11, B1). None of these commit -- the route does.
    # =============================================================================

    # Fields whose change sends an approved product back to the queue. Price
    # and stock are the vendor's business; what the listing SAYS is what the
    # admin approved. Otherwise "approved" covers whatever the vendor edits in
    # afterwards -- approve a lamp, then rename it.
    REVIEWED_FIELDS = ('title', 'description', 'category_id', 'tags')

    @property
    def moderation_state(self):
        """'approved', 'rejected' or 'pending'."""
        if self.is_approved:
            return 'approved'
        return 'rejected' if self.rejection_reason else 'pending'

    def approve(self, admin):
        self.is_approved = True
        self.rejection_reason = None
        self.moderated_at = utcnow()
        self.moderated_by = admin.id

    def reject(self, admin, reason):
        reason = (reason or '').strip()
        if not reason:
            raise ValueError('A rejection needs a reason -- the vendor has to know what to fix')
        self.is_approved = False
        self.rejection_reason = reason[:2000]
        self.moderated_at = utcnow()
        self.moderated_by = admin.id

    def submit_for_review(self):
        """
        Back to the queue: changed content, changed images, or a rejected one edited.

        flag_modified forces is_approved into the UPDATE. SQLAlchemy writes
        changed columns only: a vendor who loaded the product while it was
        pending, then saved after an admin had approved it, set False on an
        object that already held False -- no change, no column in the UPDATE,
        and the approval survived content the admin never saw.
        """
        from sqlalchemy.orm.attributes import flag_modified
        self.is_approved = False
        self.rejection_reason = None
        self.moderated_at = None
        self.moderated_by = None
        flag_modified(self, 'is_approved')

    def content_fingerprint(self):
        """
        Hash of what an admin judges: the reviewed fields and the images.

        The moderation form carries the fingerprint of what it showed; a
        decision on a product whose fingerprint has moved is refused. Without
        it, an edit between opening the queue and clicking "approve" was
        approved unseen.
        """
        # JSON, not a joined string: with a separator character, a vendor who
        # typed that character could move text between fields and keep the
        # fingerprint (found by a security review of the first version).
        import hashlib
        import json
        content = [str(getattr(self, f) or '') for f in self.REVIEWED_FIELDS]
        content.append(sorted(str(image.filepath) for image in self.images))
        return hashlib.sha256(json.dumps(content).encode()).hexdigest()

    # =============================================================================
    # Search and Discovery
    # =============================================================================

    def update_search_vector(self):
        """Update search vector for full-text search"""
        # Combine searchable fields
        search_text = f"{self.title} {self.description} {self.tags or ''}"
        self.search_vector = search_text.lower()
        db.session.commit()

    def get_tags_list(self):
        """Get tags as list"""
        if not self.tags:
            return []
        return [tag.strip() for tag in self.tags.split(',')]

    def set_tags_list(self, tags_list):
        """Set tags from list"""
        self.tags = ','.join(tags_list)

    # =============================================================================
    # Ratings
    # =============================================================================

    def update_rating(self):
        """Recalculate average rating from reviews"""
        from sqlalchemy import func
        result = db.session.query(
            func.avg(ProductReview.rating),
            func.count(ProductReview.id)
        ).filter(
            ProductReview.product_id == self.id,
            ProductReview.is_approved == True
        ).first()

        self.rating_average = float(result[0]) if result[0] else 0.0
        self.rating_count = result[1] or 0

    # =============================================================================
    # Utility Methods
    # =============================================================================

    def to_dict(self, include_vendor=False):
        """Convert product to dictionary"""
        data = {
            'id': str(self.id),
            'title': self.title,
            'description': self.description,
            'price': float(self.price),
            'quantity': self.quantity if not self.is_digital else None,
            'is_digital': self.is_digital,
            'is_active': self.is_active,
            'category': self.category.name if self.category else None,
            'tags': self.get_tags_list(),
            'views': self.views,
            'sales': self.sales,
            'rating_average': self.rating_average,
            'rating_count': self.rating_count,
            'created_at': self.created_at.isoformat(),
            'images': [img.to_dict() for img in self.images.all()]
        }

        if include_vendor:
            data['vendor'] = {
                'id': str(self.vendor.id),
                'username': self.vendor.username,
                'rating': self.vendor.vendor_rating,
                'total_sales': self.vendor.vendor_total_sales
            }

        return data


class ProductImage(db.Model):
    """
    Product images with metadata stripping for privacy
    """

    __tablename__ = 'product_images'

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = db.Column(UUID(as_uuid=True), db.ForeignKey('products.id'), nullable=False)

    # Image information
    filename = db.Column(db.String(255), nullable=False)
    filepath = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)  # in bytes
    mime_type = db.Column(db.String(50), nullable=False)

    # Metadata stripped flag
    metadata_stripped = db.Column(db.Boolean, default=False)

    # Display order
    display_order = db.Column(db.Integer, default=0)
    is_primary = db.Column(db.Boolean, default=False)

    # Timestamps
    uploaded_at = db.Column(db.DateTime, default=utcnow)

    def __repr__(self):
        return f'<ProductImage {self.filename}>'

    def to_dict(self):
        """Convert image to dictionary"""
        return {
            'id': str(self.id),
            'filename': self.filename,
            'filepath': self.filepath,
            'is_primary': self.is_primary,
            'display_order': self.display_order
        }


class ProductReview(db.Model):
    """
    Product reviews and ratings
    """

    __tablename__ = 'product_reviews'

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = db.Column(UUID(as_uuid=True), db.ForeignKey('products.id'), nullable=False)
    buyer_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False)
    order_id = db.Column(UUID(as_uuid=True), db.ForeignKey('orders.id'), nullable=False)

    # Review content
    rating = db.Column(db.Integer, nullable=False)  # 1-5 stars
    title = db.Column(db.String(200), nullable=True)
    review_text = db.Column(db.Text, nullable=True)

    # Moderation
    is_approved = db.Column(db.Boolean, default=False)
    is_flagged = db.Column(db.Boolean, default=False)

    # Timestamps
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    buyer = db.relationship('User', foreign_keys=[buyer_id])

    # Constraints
    __table_args__ = (
        db.CheckConstraint('rating >= 1 AND rating <= 5', name='check_rating_range'),
        db.UniqueConstraint('product_id', 'buyer_id', 'order_id', name='uq_product_buyer_review'),
        Index('idx_review_product_approved', product_id, is_approved),
    )

    def __repr__(self):
        return f'<ProductReview {self.id}>'

    # Moderation (plan 2026-11, B2). buyer.py wrote is_approved=True itself.
    # A rejected review keeps is_flagged=True so it leaves the queue and stays
    # hidden; the reason goes to the admin audit log. None of these commit.

    @property
    def moderation_state(self):
        if self.is_approved:
            return 'approved'
        return 'rejected' if self.is_flagged else 'pending'

    def approve(self):
        self.is_approved = True
        self.is_flagged = False

    def reject(self):
        self.is_approved = False
        self.is_flagged = True

    def to_dict(self):
        """Convert review to dictionary"""
        return {
            'id': str(self.id),
            'rating': self.rating,
            'title': self.title,
            'review_text': self.review_text,
            'buyer_username': self.buyer.username,
            'created_at': self.created_at.isoformat()
        }


# =============================================================================
# Database Events
# =============================================================================

from sqlalchemy import event


@event.listens_for(Product, 'before_insert')
@event.listens_for(Product, 'before_update')
def update_product_search(mapper, connection, target):
    """Update search vector before saving"""
    search_text = f"{target.title} {target.description} {target.tags or ''}"
    target.search_vector = search_text.lower()


@event.listens_for(ProductReview, 'after_insert')
@event.listens_for(ProductReview, 'after_update')
def update_product_rating_on_review(mapper, connection, target):
    """Update product rating after review is added/updated"""
    # This will be called by the application after commit
    pass
