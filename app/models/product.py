"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Product Model
Purpose: Product listings with security and metadata handling
"""

import uuid
from datetime import datetime
from app.models.types import UUID
from sqlalchemy import Index

from app import db


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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    is_approved = db.Column(db.Boolean, default=False)  # Admin approval required

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    images = db.relationship('ProductImage', backref='product', lazy='dynamic',
                            cascade='all, delete-orphan')
    orders = db.relationship('Order', backref='product', lazy='dynamic')
    reviews = db.relationship('ProductReview', backref='product', lazy='dynamic',
                             cascade='all, delete-orphan')

    # Indexes for performance
    __table_args__ = (
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
        """Increment product view count"""
        self.views += 1
        db.session.commit()

    def record_sale(self, quantity=1):
        """
        Record a sale of ``quantity`` units.

        Previously this always decremented stock by exactly 1 regardless of the
        order quantity, so an order for 10 units reduced stock by 1 (overselling),
        and ``sales`` counted orders rather than units sold.

        Args:
            quantity: Number of units sold
        """
        quantity = max(1, int(quantity or 1))

        self.sales += quantity
        if not self.is_digital:
            self.quantity = max(0, self.quantity - quantity)
        db.session.commit()

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

        return url_for('marketplace.product_image', filename=image.filename)

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
        db.session.commit()

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
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
