"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Shopping Cart Model
Purpose: Secure shopping cart with session persistence
"""

import uuid
from datetime import datetime
from sqlalchemy.dialects.postgresql import UUID

from app import db


class Cart(db.Model):
    """
    Shopping cart model with security features:
    - UUID primary keys
    - User association
    - Session-based cart for guests (not implemented in training env)
    - Automatic cleanup of old carts
    """

    __tablename__ = 'carts'

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False, unique=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    items = db.relationship('CartItem', backref='cart', lazy='dynamic', cascade='all, delete-orphan')
    user = db.relationship('User', backref=db.backref('cart', uselist=False))

    def __repr__(self):
        return f'<Cart {self.id} - User {self.user_id}>'

    @classmethod
    def get_or_create(cls, user_id):
        """Get existing cart or create new one for user"""
        cart = cls.query.filter_by(user_id=user_id).first()
        if not cart:
            cart = cls(user_id=user_id)
            db.session.add(cart)
            db.session.commit()
        return cart

    def add_item(self, product_id, quantity=1):
        """
        Add item to cart or update quantity if exists
        
        Args:
            product_id: Product UUID
            quantity: Quantity to add
            
        Returns:
            CartItem: The cart item
            
        Raises:
            ValueError: If product not found or not available
        """
        from app.models.product import Product
        
        product = Product.query.get(product_id)
        if not product:
            raise ValueError('Product not found')
        
        if not product.is_active or not product.is_approved:
            raise ValueError('Product is not available')
        
        # Check if vendor is not the buyer
        if str(product.vendor_id) == str(self.user_id):
            raise ValueError('You cannot purchase your own products')
        
        # Check stock for physical products
        if not product.is_digital and product.quantity < quantity:
            raise ValueError(f'Only {product.quantity} items available')
        
        # Check if item already in cart
        item = CartItem.query.filter_by(cart_id=self.id, product_id=product_id).first()
        
        if item:
            new_quantity = item.quantity + quantity
            if not product.is_digital and product.quantity < new_quantity:
                raise ValueError(f'Cannot add more. Only {product.quantity} items available')
            item.quantity = new_quantity
            item.unit_price = product.price
        else:
            item = CartItem(
                cart_id=self.id,
                product_id=product_id,
                quantity=quantity,
                unit_price=product.price
            )
            db.session.add(item)
        
        db.session.commit()
        return item

    def update_item_quantity(self, product_id, quantity):
        """
        Update item quantity in cart
        
        Args:
            product_id: Product UUID
            quantity: New quantity (0 removes item)
        """
        from app.models.product import Product
        
        item = CartItem.query.filter_by(cart_id=self.id, product_id=product_id).first()
        if not item:
            raise ValueError('Item not in cart')
        
        if quantity <= 0:
            db.session.delete(item)
        else:
            product = Product.query.get(product_id)
            if not product.is_digital and product.quantity < quantity:
                raise ValueError(f'Only {product.quantity} items available')
            item.quantity = quantity
        
        db.session.commit()

    def remove_item(self, product_id):
        """Remove item from cart"""
        item = CartItem.query.filter_by(cart_id=self.id, product_id=product_id).first()
        if item:
            db.session.delete(item)
            db.session.commit()

    def clear(self):
        """Clear all items from cart"""
        CartItem.query.filter_by(cart_id=self.id).delete()
        db.session.commit()

    @property
    def total_items(self):
        """Get total number of items in cart"""
        return sum(item.quantity for item in self.items)

    @property
    def subtotal(self):
        """Get cart subtotal"""
        return sum(item.total_price for item in self.items)

    def get_items_grouped_by_vendor(self):
        """
        Get cart items grouped by vendor
        
        Returns:
            dict: {vendor_id: [CartItem, ...]}
        """
        from collections import defaultdict
        grouped = defaultdict(list)
        for item in self.items:
            grouped[str(item.product.vendor_id)].append(item)
        return dict(grouped)

    def validate_items(self):
        """
        Validate all cart items are still purchasable
        
        Returns:
            list: List of validation errors
        """
        errors = []
        for item in self.items:
            product = item.product
            if not product.is_active:
                errors.append(f'{product.title} is no longer available')
            elif not product.is_approved:
                errors.append(f'{product.title} is pending approval')
            elif not product.is_digital and product.quantity < item.quantity:
                errors.append(f'{product.title}: only {product.quantity} available')
        return errors


class CartItem(db.Model):
    """
    Cart item model
    """

    __tablename__ = 'cart_items'

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cart_id = db.Column(UUID(as_uuid=True), db.ForeignKey('carts.id'), nullable=False)
    product_id = db.Column(UUID(as_uuid=True), db.ForeignKey('products.id'), nullable=False)
    
    # Item details
    quantity = db.Column(db.Integer, nullable=False, default=1)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)  # Price at time of adding
    
    # Timestamps
    added_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    product = db.relationship('Product')

    # Unique constraint - one product per cart
    __table_args__ = (
        db.UniqueConstraint('cart_id', 'product_id', name='uq_cart_product'),
    )

    def __repr__(self):
        return f'<CartItem {self.product_id} x{self.quantity}>'

    @property
    def total_price(self):
        """Get total price for this item"""
        return self.unit_price * self.quantity

    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': str(self.id),
            'product': self.product.to_dict() if self.product else None,
            'quantity': self.quantity,
            'unit_price': float(self.unit_price),
            'total_price': float(self.total_price),
            'added_at': self.added_at.isoformat()
        }
