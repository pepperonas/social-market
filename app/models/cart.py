"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Shopping Cart Model
Purpose: Secure shopping cart with session persistence
"""

import uuid
from app.models.types import UUID

from app import db
from app.timeutil import utcnow


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
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

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

        quantity = self.parse_quantity(quantity)

        product = db.session.get(Product, product_id)
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

    MAX_QUANTITY = 1000

    @classmethod
    def parse_quantity(cls, raw):
        """
        A cart quantity: a whole number from 1 to MAX_QUANTITY, or ValueError.

        Lives on the model so every route goes through it. The form route clamped
        its input, the JSON route did not: {"quantity": -5} produced a negative
        cart line, a negative order total and an escrow with a negative amount.
        bool is refused explicitly -- it is an int subclass, True would be 1.
        """
        if isinstance(raw, bool) or raw is None:
            raise ValueError('Quantity must be a whole number')
        if isinstance(raw, float):
            if not raw.is_integer():
                raise ValueError('Quantity must be a whole number')
            raw = int(raw)
        try:
            value = int(str(raw).strip())
        except ValueError:
            raise ValueError('Quantity must be a whole number')
        if not 1 <= value <= cls.MAX_QUANTITY:
            raise ValueError(f'Quantity must be between 1 and {cls.MAX_QUANTITY}')
        return value

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

        if quantity == 0:
            quantity = 0  # explicit removal
        else:
            quantity = self.parse_quantity(quantity)

        if quantity == 0:
            db.session.delete(item)
        else:
            product = db.session.get(Product, product_id)
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
            elif item.unit_price != product.price:
                # The cart keeps the price from the moment the item was added, and
                # checkout used to charge exactly that. Show the new price and let
                # the buyer decide again; the next checkout charges it.
                errors.append(f'{product.title}: price changed from '
                              f'{item.unit_price} to {product.price} -- please review your cart')
                item.unit_price = product.price
                db.session.commit()
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
    added_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    # Relationships
    product = db.relationship('Product')

    # Unique constraint - one product per cart
    __table_args__ = (
        db.UniqueConstraint('cart_id', 'product_id', name='uq_cart_product'),
        db.CheckConstraint('quantity > 0', name='ck_cart_item_quantity_positive'),
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
