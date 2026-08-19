"""
The "buy now" path (`POST /buyer/create-order`).

Reported from the running demo as:

    Error creating order: 'Product' object has no attribute 'active'

That message is three separate defects in one line:

1. `product.active` -- the column is `is_active`. The guard did not return
   False, it raised, so the availability check never ran at all.
2. Behind it, `total_amount=` was passed to Order, which has no such column.
   Fixing (1) alone would have moved the crash one line down.
3. The handler flashed `str(exc)` to the user, which is how an internal model
   attribute name ended up on a page. That is information disclosure, and it is
   also why the bug was reported with such a precise message.

The route also skipped approval, stock and escrow -- all of which the cart
checkout path does. There were no tests for any of it.
"""

import uuid
from decimal import Decimal

import pytest


@pytest.fixture
def sellable(app, sample_vendor):
    from app import db
    from app.models.product import Product, ProductCategory

    suffix = uuid.uuid4().hex[:8]
    category = ProductCategory(id=uuid.uuid4(), name=f'C {suffix}', slug=f'c-{suffix}')
    db.session.add(category)
    db.session.flush()

    made = []

    def _make(**over):
        fields = dict(
            id=uuid.uuid4(), vendor_id=sample_vendor.id, category_id=category.id,
            title=f'Sellable {uuid.uuid4().hex[:6]}', description='d',
            price=Decimal('20.00'), quantity=5, is_digital=False,
            is_active=True, is_approved=True,
        )
        fields.update(over)
        product = Product(**fields)
        db.session.add(product)
        db.session.commit()
        made.append(product)
        return product

    yield _make

    for obj in made + [category]:
        try:
            db.session.delete(obj)
            db.session.commit()
        except Exception:
            db.session.rollback()


def _login(client, user, password='TestPassword123!'):
    response = client.post('/auth/login',
                           data={'username': user.username, 'password': password},
                           follow_redirects=False)
    assert response.status_code in (302, 303)


def _order(client, product, quantity=1):
    return client.post('/buyer/create-order',
                       data={'product_id': str(product.id), 'quantity': str(quantity)},
                       follow_redirects=True)


class TestHappyPath:
    def test_order_is_created(self, client, sample_user, sellable):
        from app.models.order import Order

        product = sellable()
        _login(client, sample_user)

        response = _order(client, product, 2)

        assert response.status_code == 200
        order = Order.query.filter_by(product_id=product.id).first()
        assert order is not None
        assert order.quantity == 2

    def test_totals_are_computed_not_taken_from_the_form(self, client, sample_user, sellable):
        """Money is derived server-side; the client only picks a quantity."""
        from app.models.order import Order

        product = sellable(price=Decimal('20.00'))
        _login(client, sample_user)
        _order(client, product, 3)

        order = Order.query.filter_by(product_id=product.id).first()
        assert order.total_price == Decimal('60.00')
        assert order.commission > 0

    def test_escrow_is_created(self, client, sample_user, sellable):
        """A buy-now order without escrow silently skips buyer protection."""
        from app.models.order import Order

        product = sellable()
        _login(client, sample_user)
        _order(client, product)

        order = Order.query.filter_by(product_id=product.id).first()
        assert order.escrow is not None

    def test_starts_pending(self, client, sample_user, sellable):
        from app.models.order import Order

        product = sellable()
        _login(client, sample_user)
        _order(client, product)

        assert Order.query.filter_by(product_id=product.id).first().status == 'pending'


class TestRefusals:
    def _no_order(self, product):
        from app.models.order import Order

        return Order.query.filter_by(product_id=product.id).first() is None

    def test_inactive_product_refused(self, client, sample_user, sellable):
        """The original `product.active` typo meant this never ran."""
        product = sellable(is_active=False)
        _login(client, sample_user)

        _order(client, product)
        assert self._no_order(product)

    def test_unapproved_product_refused(self, client, sample_user, sellable):
        product = sellable(is_approved=False)
        _login(client, sample_user)

        _order(client, product)
        assert self._no_order(product)

    def test_more_than_stock_refused(self, client, sample_user, sellable):
        product = sellable(quantity=2)
        _login(client, sample_user)

        _order(client, product, 5)
        assert self._no_order(product)

    def test_vendor_cannot_buy_own_product(self, client, sample_vendor, sellable):
        product = sellable()
        _login(client, sample_vendor)

        _order(client, product)
        assert self._no_order(product)

    @pytest.mark.parametrize('quantity', ['0', '-3'])
    def test_non_positive_quantity_refused(self, client, sample_user, sellable, quantity):
        product = sellable()
        _login(client, sample_user)

        _order(client, product, quantity)
        assert self._no_order(product)

    def test_non_numeric_quantity_refused(self, client, sample_user, sellable):
        product = sellable()
        _login(client, sample_user)

        client.post('/buyer/create-order',
                    data={'product_id': str(product.id), 'quantity': 'lots'},
                    follow_redirects=True)
        assert self._no_order(product)

    def test_anonymous_cannot_order(self, client, sellable):
        product = sellable()
        response = client.post('/buyer/create-order',
                               data={'product_id': str(product.id), 'quantity': '1'},
                               follow_redirects=False)

        assert response.status_code in (302, 303)
        assert self._no_order(product)


class TestErrorsAreNotLeaked:
    """
    The handler used to flash str(exc). Internal attribute names, and anything
    else an exception carries, do not belong on a page a user can see.
    """

    def test_failure_message_is_generic(self, client, sample_user, sellable, monkeypatch):
        from app.services import escrow_service

        product = sellable()
        _login(client, sample_user)

        def boom(self, order):
            raise RuntimeError("Product' object has no attribute 'active'")

        monkeypatch.setattr(escrow_service.EscrowService, 'create_escrow_for_order', boom)

        body = _order(client, product).get_data(as_text=True)

        assert 'no attribute' not in body, 'internal error text reached the page'
        assert 'Could not place the order' in body

    def test_source_does_not_flash_the_exception(self):
        import pathlib
        import re

        source = pathlib.Path('app/routes/buyer.py').read_text()
        source = re.sub(r'#.*', '', source)  # the comment explains the old bug

        assert 'flash(f\'Error creating order: {str(e)}\'' not in source
        assert 'str(exc)' not in source.split('current_app.logger')[0]
