"""
Unit tests for the Order state machine.

The state machine is the integrity boundary of the marketplace: it decides when
money moves and when stock is consumed. Every illegal transition it fails to
reject is a way to get goods without paying (or to be paid without shipping).
"""

import uuid
from decimal import Decimal

import pytest


@pytest.fixture
def order_factory(app, sample_user, sample_vendor):
    from app import db
    from app.models.order import Order
    from app.models.product import Product, ProductCategory

    created = []
    suffix = uuid.uuid4().hex[:8]
    category = ProductCategory(id=uuid.uuid4(), name=f'C {suffix}', slug=f'c-{suffix}')
    db.session.add(category)
    db.session.flush()

    product = Product(
        id=uuid.uuid4(), vendor_id=sample_vendor.id, category_id=category.id,
        title=f'P {suffix}', description='d', price=Decimal('10.00'),
        quantity=100, is_digital=False, is_active=True, is_approved=True,
    )
    db.session.add(product)
    db.session.commit()

    def _make(status='pending', quantity=1):
        order = Order(
            id=uuid.uuid4(),
            buyer_id=sample_user.id,
            vendor_id=sample_vendor.id,
            product_id=product.id,
            quantity=quantity,
            unit_price=Decimal('10.00'),
            total_price=Decimal('10.00') * quantity,
            commission=Decimal('0.30'),
            status=status,
            is_digital=False,
        )
        db.session.add(order)
        db.session.commit()
        created.append(order)
        return order

    _make.product = product
    yield _make

    # Best effort: rows are uniquely named per test, so leftovers cannot collide
    # with the next one. Never let cleanup fail the test that just passed.
    for obj in created + [product, category]:
        try:
            db.session.delete(obj)
            db.session.commit()
        except Exception:
            db.session.rollback()


class TestAllowedTransitions:
    @pytest.mark.parametrize('src,dst', [
        ('pending', 'paid'),
        ('pending', 'cancelled'),
        ('paid', 'shipped'),
        ('paid', 'cancelled'),
        ('paid', 'disputed'),
        ('shipped', 'delivered'),
        ('shipped', 'disputed'),
        ('delivered', 'completed'),
        ('delivered', 'disputed'),
        ('disputed', 'refunded'),
        ('disputed', 'completed'),
    ])
    def test_allowed(self, order_factory, src, dst):
        ok, err = order_factory(status=src).can_transition_to(dst)
        assert ok is True, f'{src} -> {dst} should be allowed ({err})'


class TestForbiddenTransitions:
    @pytest.mark.parametrize('src,dst', [
        ('pending', 'shipped'),      # shipping without payment
        ('pending', 'delivered'),
        ('pending', 'completed'),    # completing without ever paying
        ('paid', 'completed'),       # skipping delivery
        ('paid', 'delivered'),
        ('shipped', 'paid'),         # going backwards
        ('completed', 'refunded'),   # refund after final state
        ('completed', 'disputed'),
        ('cancelled', 'paid'),       # reviving a cancelled order
        ('refunded', 'completed'),
    ])
    def test_forbidden(self, order_factory, src, dst):
        ok, err = order_factory(status=src).can_transition_to(dst)
        assert ok is False, f'{src} -> {dst} must be rejected'
        assert err and 'Cannot transition' in err

    def test_terminal_states_have_no_exit(self, order_factory):
        for terminal in ('completed', 'cancelled', 'refunded'):
            order = order_factory(status=terminal)
            for target in ('pending', 'paid', 'shipped', 'delivered'):
                ok, _ = order.can_transition_to(target)
                assert ok is False, f'{terminal} must be terminal (tried {target})'

    def test_transition_to_raises_on_illegal(self, order_factory):
        order = order_factory(status='pending')
        with pytest.raises(ValueError, match='Cannot transition'):
            order.transition_to('completed')

    def test_illegal_transition_leaves_status_untouched(self, order_factory):
        order = order_factory(status='pending')
        with pytest.raises(ValueError):
            order.transition_to('shipped')
        assert order.status == 'pending'


class TestPaidConsumesStock:
    def test_paying_reduces_stock_by_order_quantity(self, order_factory, mock_audit):
        product = order_factory.product
        before = product.quantity
        order = order_factory(status='pending', quantity=4)

        order.transition_to('paid')

        assert product.quantity == before - 4, 'stock must follow the ordered amount'

    def test_paid_sets_timestamp_and_deadline(self, order_factory, mock_audit):
        order = order_factory(status='pending')
        order.transition_to('paid')

        assert order.paid_at is not None
        assert order.auto_finalize_at is not None
        assert order.auto_finalize_at > order.paid_at


class TestShippingData:
    def test_shipping_name_roundtrip(self, order_factory):
        order = order_factory()
        order.set_shipping_name('Alice Example')
        assert order.get_shipping_name() == 'Alice Example'

    def test_shipping_address_roundtrip(self, order_factory):
        order = order_factory()
        order.set_shipping_address('Musterstr. 1\n12345 Berlin')
        assert order.get_shipping_address() == 'Musterstr. 1\n12345 Berlin'

    def test_shipping_is_not_stored_in_plaintext(self, order_factory):
        """Address must be encrypted at rest, not merely copied into a column."""
        order = order_factory()
        secret = 'Geheimstrasse 42'
        order.set_shipping_address(secret)

        raw = order.shipping_address_encrypted
        assert raw is not None
        assert secret.encode() not in (raw if isinstance(raw, bytes) else raw.encode())
