"""Unit tests for the shopping cart (stock limits, self-purchase, totals)."""

import uuid
from decimal import Decimal

import pytest


@pytest.fixture
def cart_setup(app, sample_user, sample_vendor):
    from app import db
    from app.models.cart import Cart
    from app.models.product import Product, ProductCategory

    suffix = uuid.uuid4().hex[:8]
    category = ProductCategory(id=uuid.uuid4(), name=f'C {suffix}', slug=f'c-{suffix}')
    db.session.add(category)
    db.session.flush()

    def make_product(**over):
        fields = dict(
            id=uuid.uuid4(), vendor_id=sample_vendor.id, category_id=category.id,
            title=f'P {uuid.uuid4().hex[:6]}', description='d', price=Decimal('5.00'),
            quantity=10, is_digital=False, is_active=True, is_approved=True,
        )
        fields.update(over)
        item = Product(**fields)
        db.session.add(item)
        db.session.commit()
        return item

    cart = Cart.get_or_create(sample_user.id)
    yield cart, make_product

    try:
        cart.clear()
        db.session.commit()
    except Exception:
        db.session.rollback()


class TestAddItem:
    def test_add_creates_item(self, cart_setup):
        cart, make_product = cart_setup
        product = make_product()

        cart.add_item(product.id, 2)

        assert cart.total_items == 2

    def test_adding_twice_accumulates(self, cart_setup):
        cart, make_product = cart_setup
        product = make_product()

        cart.add_item(product.id, 2)
        cart.add_item(product.id, 3)

        assert cart.total_items == 5

    def test_cannot_exceed_stock(self, cart_setup):
        cart, make_product = cart_setup
        product = make_product(quantity=3)

        with pytest.raises(ValueError, match='Only 3'):
            cart.add_item(product.id, 4)

    def test_cannot_exceed_stock_via_accumulation(self, cart_setup):
        """Two additions that individually fit must not together exceed stock."""
        cart, make_product = cart_setup
        product = make_product(quantity=3)

        cart.add_item(product.id, 2)
        with pytest.raises(ValueError, match='Cannot add more'):
            cart.add_item(product.id, 2)

    def test_digital_product_ignores_stock(self, cart_setup):
        cart, make_product = cart_setup
        product = make_product(quantity=0, is_digital=True)

        cart.add_item(product.id, 99)
        assert cart.total_items == 99

    def test_inactive_product_rejected(self, cart_setup):
        cart, make_product = cart_setup
        with pytest.raises(ValueError, match='not available'):
            cart.add_item(make_product(is_active=False).id, 1)

    def test_unapproved_product_rejected(self, cart_setup):
        cart, make_product = cart_setup
        with pytest.raises(ValueError, match='not available'):
            cart.add_item(make_product(is_approved=False).id, 1)

    def test_unknown_product_rejected(self, cart_setup):
        cart, _ = cart_setup
        with pytest.raises(ValueError, match='not found'):
            cart.add_item(uuid.uuid4(), 1)

    def test_vendor_cannot_buy_own_product(self, app, sample_vendor, cart_setup):
        """A vendor buying their own listing would let them game ratings/sales."""
        from app.models.cart import Cart

        _, make_product = cart_setup
        product = make_product()
        vendor_cart = Cart.get_or_create(sample_vendor.id)

        with pytest.raises(ValueError, match='your own products'):
            vendor_cart.add_item(product.id, 1)


class TestUpdateAndRemove:
    def test_update_quantity(self, cart_setup):
        cart, make_product = cart_setup
        product = make_product()
        cart.add_item(product.id, 1)

        cart.update_item_quantity(product.id, 4)
        assert cart.total_items == 4

    def test_update_to_zero_removes(self, cart_setup):
        cart, make_product = cart_setup
        product = make_product()
        cart.add_item(product.id, 2)

        cart.update_item_quantity(product.id, 0)
        assert cart.total_items == 0

    def test_update_beyond_stock_rejected(self, cart_setup):
        cart, make_product = cart_setup
        product = make_product(quantity=2)
        cart.add_item(product.id, 1)

        with pytest.raises(ValueError, match='Only 2'):
            cart.update_item_quantity(product.id, 5)

    def test_update_unknown_item_rejected(self, cart_setup):
        cart, _ = cart_setup
        with pytest.raises(ValueError, match='not in cart'):
            cart.update_item_quantity(uuid.uuid4(), 1)

    def test_remove_item(self, cart_setup):
        cart, make_product = cart_setup
        product = make_product()
        cart.add_item(product.id, 2)

        cart.remove_item(product.id)
        assert cart.total_items == 0

    def test_clear_empties_cart(self, cart_setup):
        cart, make_product = cart_setup
        cart.add_item(make_product().id, 1)
        cart.add_item(make_product().id, 2)

        cart.clear()
        assert cart.total_items == 0


class TestTotals:
    def test_subtotal_sums_line_totals(self, cart_setup):
        cart, make_product = cart_setup
        cart.add_item(make_product(price=Decimal('5.00')).id, 2)
        cart.add_item(make_product(price=Decimal('3.50')).id, 1)

        assert cart.subtotal == Decimal('13.50')

    def test_grouped_by_vendor(self, cart_setup, sample_vendor):
        cart, make_product = cart_setup
        cart.add_item(make_product().id, 1)
        cart.add_item(make_product().id, 1)

        grouped = cart.get_items_grouped_by_vendor()
        assert list(grouped) == [str(sample_vendor.id)]
        assert len(grouped[str(sample_vendor.id)]) == 2


class TestValidation:
    def test_valid_cart_has_no_errors(self, cart_setup):
        cart, make_product = cart_setup
        cart.add_item(make_product().id, 1)

        assert cart.validate_items() == []

    def test_deactivated_product_reported(self, app, cart_setup):
        from app import db

        cart, make_product = cart_setup
        product = make_product()
        cart.add_item(product.id, 1)

        product.is_active = False
        db.session.commit()

        errors = cart.validate_items()
        assert len(errors) == 1 and 'no longer available' in errors[0]

    def test_stock_dropped_below_cart_quantity_reported(self, app, cart_setup):
        """Stock can shrink between adding to cart and checkout."""
        from app import db

        cart, make_product = cart_setup
        product = make_product(quantity=5)
        cart.add_item(product.id, 5)

        product.quantity = 2
        db.session.commit()

        errors = cart.validate_items()
        assert len(errors) == 1 and 'only 2 available' in errors[0]
