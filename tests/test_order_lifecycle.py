"""
Review round 3 (2026-11), step 3: the order lifecycle, end to end, over HTTP.

The central finding of the review: an order could never leave `pending`.
Nothing called Order.transition_to(PAID) or EscrowService.fund_escrow, and a
vendor can only ship a paid order -- so shipping, delivery, completion, escrow
release, reviews and disputes were all unreachable in the running application.
The live database had exactly one order, status `pending`.

443 tests were green at the time. They set order states directly
(`order_factory(status='delivered')`) and therefore tested the bricks, never
whether the bricks were connected. The tests here only ever move an order
through the routes a user would click.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

BUYER_PW = 'TestPassword123!'
ADMIN_PW = 'AdminPassword123!'


# =============================================================================
# Fixtures and helpers
# =============================================================================

@pytest.fixture
def shop(app, sample_vendor):
    """Make products of sample_vendor; returns a factory."""
    from app import db
    from app.models.product import Product, ProductCategory

    suffix = uuid.uuid4().hex[:8]
    category = ProductCategory(id=uuid.uuid4(), name=f'Cat {suffix}', slug=f'cat-{suffix}')
    db.session.add(category)
    db.session.commit()

    def make(price='20.00', stock=5, digital=False, vendor=None):
        product = Product(
            id=uuid.uuid4(), vendor_id=(vendor or sample_vendor).id,
            category_id=category.id, title=f'Item {uuid.uuid4().hex[:6]}',
            description='a product for the lifecycle tests', price=Decimal(price),
            quantity=0 if digital else stock, is_digital=digital,
            is_active=True, is_approved=True,
        )
        db.session.add(product)
        db.session.commit()
        return product

    make.category = category
    return make


@pytest.fixture
def other_vendor(app):
    from app import db
    from app.models.user import User

    suffix = uuid.uuid4().hex[:8]
    vendor = User(id=uuid.uuid4(), username=f'vendor2_{suffix}', email=f'v2_{suffix}@test.local',
                  role='vendor', is_active=True, is_verified=True, is_vendor_approved=True)
    vendor.set_password(BUYER_PW)
    db.session.add(vendor)
    db.session.commit()
    return vendor


def login(app, user, password=BUYER_PW):
    client = app.test_client()
    response = client.post('/auth/login', data={'username': user.username, 'password': password})
    assert response.status_code in (302, 303)
    return client


def fresh(model, ident):
    from app import db

    db.session.expire_all()
    return db.session.get(model, ident)


def buy_now(client, product, quantity=1):
    from app.models.order import Order

    client.post('/buyer/create-order',
                data={'product_id': str(product.id), 'quantity': str(quantity)})
    return Order.query.filter_by(product_id=product.id).order_by(Order.created_at.desc()).first()


def stock(product):
    from app.models.product import Product

    return fresh(Product, product.id).quantity


def escrow_status(order):
    from app.models.order import Order

    return fresh(Order, order.id).escrow.status


def status(order):
    from app.models.order import Order

    return fresh(Order, order.id).status


@pytest.fixture
def people(app, sample_user, sample_vendor, sample_admin):
    """Logged-in clients for buyer, vendor and admin."""
    return {
        'buyer': login(app, sample_user),
        'vendor': login(app, sample_vendor),
        'admin': login(app, sample_admin, ADMIN_PW),
    }


# =============================================================================
# K1 -- the happy path exists
# =============================================================================

class TestHappyPath:
    def test_pending_to_completed_through_the_routes(self, app, people, shop, sample_vendor):
        from app.models.user import User

        product = shop(stock=5)
        sales_before = fresh(User, sample_vendor.id).vendor_total_sales or 0

        order = buy_now(people['buyer'], product, 2)
        assert status(order) == 'pending'

        people['buyer'].post(f'/buyer/order/{order.id}/pay')
        assert status(order) == 'paid'
        assert escrow_status(order) == 'funded'

        people['vendor'].post(f'/vendor/order/{order.id}/ship', data={'tracking_number': 'T1'})
        assert status(order) == 'shipped'

        people['buyer'].post(f'/buyer/order/{order.id}/confirm-delivery')
        assert status(order) == 'delivered'

        people['buyer'].post(f'/buyer/order/{order.id}/complete')
        assert status(order) == 'completed'
        assert escrow_status(order) == 'released'
        assert fresh(User, sample_vendor.id).vendor_total_sales == sales_before + 1

    def test_order_page_offers_the_payment_step(self, people, shop):
        order = buy_now(people['buyer'], shop())

        html = people['buyer'].get(f'/buyer/order/{order.id}').get_data(as_text=True)

        assert f'/buyer/order/{order.id}/pay' in html

    def test_only_the_buyer_can_pay(self, people, shop):
        order = buy_now(people['buyer'], shop())

        people['vendor'].post(f'/buyer/order/{order.id}/pay')

        assert status(order) == 'pending'

    def test_paying_twice_funds_once(self, people, shop):
        from app.models.escrow import EscrowTransaction

        order = buy_now(people['buyer'], shop())
        people['buyer'].post(f'/buyer/order/{order.id}/pay')
        people['buyer'].post(f'/buyer/order/{order.id}/pay')

        escrow_id = fresh(type(order), order.id).escrow.id
        funds = EscrowTransaction.query.filter_by(escrow_id=escrow_id, transaction_type='fund').count()
        assert funds == 1


# =============================================================================
# Stock
# =============================================================================

class TestStock:
    """
    Stock was only decremented at PAID -- which never happened -- so every
    pending order passed the availability check for the same last unit.
    """

    def test_order_reserves_stock(self, people, shop):
        product = shop(stock=5)
        buy_now(people['buyer'], product, 2)

        assert stock(product) == 3

    def test_last_unit_cannot_be_sold_twice(self, app, people, shop, sample_user):
        from app.models.order import Order

        product = shop(stock=1)
        buy_now(people['buyer'], product, 1)
        buy_now(people['buyer'], product, 1)

        assert Order.query.filter_by(product_id=product.id).count() == 1
        assert stock(product) == 0

    def test_buyer_can_cancel_an_unpaid_order_and_stock_returns(self, people, shop):
        product = shop(stock=3)
        order = buy_now(people['buyer'], product, 2)

        people['buyer'].post(f'/buyer/order/{order.id}/cancel')

        assert status(order) == 'cancelled'
        assert stock(product) == 3


# =============================================================================
# Cancellation and refunds
# =============================================================================

class TestCancellation:
    def test_cancelling_a_paid_order_refunds_the_escrow(self, people, shop):
        """It used to leave the escrow `funded` forever: the buyer never got the money back."""
        product = shop(stock=3)
        order = buy_now(people['buyer'], product, 1)
        people['buyer'].post(f'/buyer/order/{order.id}/pay')

        people['vendor'].post(f'/vendor/order/{order.id}/cancel', data={'cancel_reason': 'oos'})

        assert status(order) == 'cancelled'
        assert escrow_status(order) == 'refunded'
        assert stock(product) == 3

    def test_buyer_cannot_cancel_a_paid_order_alone(self, people, shop):
        """Once paid, the vendor may already be packing; a dispute is the buyer's way out."""
        order = buy_now(people['buyer'], shop())
        people['buyer'].post(f'/buyer/order/{order.id}/pay')

        people['buyer'].post(f'/buyer/order/{order.id}/cancel')

        assert status(order) == 'paid'


# =============================================================================
# Disputes
# =============================================================================

class TestDisputes:
    """
    Escrow.mark_disputed had no caller and no route resolved a dispute: an
    order in `disputed` stayed there, its money frozen, and the escrow health
    check reported "healthy" because no escrow was ever marked disputed.
    """

    def _disputed(self, people, shop):
        order = buy_now(people['buyer'], shop())
        people['buyer'].post(f'/buyer/order/{order.id}/pay')
        people['buyer'].post(f'/buyer/order/{order.id}/dispute', data={'reason': 'never arrived'})
        assert status(order) == 'disputed'
        return order

    def test_dispute_freezes_the_escrow(self, people, shop):
        order = self._disputed(people, shop)

        assert escrow_status(order) == 'disputed'

    @pytest.mark.parametrize('decision, order_after, escrow_after', [
        ('refund', 'refunded', 'refunded'),
        ('release', 'completed', 'released'),
    ])
    def test_admin_resolves(self, people, shop, decision, order_after, escrow_after):
        order = self._disputed(people, shop)

        people['admin'].post(f'/admin/order/{order.id}/resolve',
                             data={'decision': decision, 'notes': 'checked'})

        assert status(order) == order_after
        assert escrow_status(order) == escrow_after

    def test_admin_dashboard_lists_open_disputes(self, people, shop):
        order = self._disputed(people, shop)

        html = people['admin'].get('/admin/dashboard').get_data(as_text=True)

        assert f'/admin/order/{order.id}/resolve' in html

    def test_buyer_cannot_resolve_their_own_dispute(self, people, shop):
        order = self._disputed(people, shop)

        people['buyer'].post(f'/admin/order/{order.id}/resolve', data={'decision': 'refund'})

        assert status(order) == 'disputed'


# =============================================================================
# Auto-finalisation
# =============================================================================

class TestAutoFinalisation:
    def test_deadline_counts_from_delivery(self, app, people, shop):
        """
        It was set at payment (paid_at + 14 days) and never moved, so an order
        delivered late was finalised almost immediately -- before the buyer's
        dispute window had run.
        """
        from app.models.order import Order

        order = buy_now(people['buyer'], shop())
        people['buyer'].post(f'/buyer/order/{order.id}/pay')
        people['vendor'].post(f'/vendor/order/{order.id}/ship', data={'tracking_number': 'T'})
        people['buyer'].post(f'/buyer/order/{order.id}/confirm-delivery')

        order = fresh(Order, order.id)
        window = timedelta(days=app.config['ESCROW_DISPUTE_WINDOW_DAYS'])
        assert order.auto_finalize_at >= order.delivered_at + window

    def test_failed_finalisation_is_rolled_back(self, app, people, shop, monkeypatch):
        """
        transition_to() sets the status before the escrow release, and the loop
        had no rollback: a failed release left COMPLETED in the session for the
        next commit to persist -- an order marked done whose money never moved.
        """
        from app.models.escrow import Escrow
        from app.models.order import Order
        from app.services.escrow_service import EscrowService
        from app.timeutil import utcnow
        from app import db

        order = buy_now(people['buyer'], shop())
        people['buyer'].post(f'/buyer/order/{order.id}/pay')
        people['vendor'].post(f'/vendor/order/{order.id}/ship', data={'tracking_number': 'T'})
        people['buyer'].post(f'/buyer/order/{order.id}/confirm-delivery')
        due = fresh(Order, order.id)
        due.auto_finalize_at = utcnow() - timedelta(minutes=1)
        db.session.commit()

        def boom(self):
            raise RuntimeError('wallet unreachable')
        monkeypatch.setattr(Escrow, 'release_to_vendor', boom)

        EscrowService.process_auto_finalization()
        db.session.commit()  # whatever the next request would have committed

        assert status(order) == 'delivered'


# =============================================================================
# Concurrency: state changes are claimed, not assumed
# =============================================================================

class TestStateChangesAreAtomic:
    """
    complete_order() and the auto-finaliser both checked the status and then
    acted. Two requests (or a request racing the job) could both see
    `delivered` and both release the escrow. A stale object stands in for the
    second request here: the row has moved on, the object in hand has not.
    """

    def _delivered(self, people, shop):
        order = buy_now(people['buyer'], shop())
        people['buyer'].post(f'/buyer/order/{order.id}/pay')
        people['vendor'].post(f'/vendor/order/{order.id}/ship', data={'tracking_number': 'T'})
        people['buyer'].post(f'/buyer/order/{order.id}/confirm-delivery')
        return order

    def test_escrow_is_released_once(self, people, shop):
        from sqlalchemy import text
        from sqlalchemy.orm.attributes import set_committed_value

        from app import db
        from app.models.escrow import Escrow, EscrowTransaction
        from app.models.order import Order

        order = self._delivered(people, shop)
        escrow = fresh(Order, order.id).escrow
        assert escrow.status == 'funded'

        # Another request releases it first
        db.session.execute(text("UPDATE escrows SET status = 'released' WHERE id = :id"),
                           {'id': escrow.id.hex})
        db.session.commit()  # the other request is done
        # This request still holds the state it read before. (commit() expired
        # the object; without this it would simply re-read 'released', and the
        # old check-then-act code would pass the test too.)
        set_committed_value(escrow, 'status', 'funded')
        with pytest.raises(ValueError):
            escrow.release_to_vendor()
        db.session.rollback()

        releases = EscrowTransaction.query.filter_by(
            escrow_id=escrow.id, transaction_type='release_vendor').count()
        assert releases == 0
        assert fresh(Escrow, escrow.id).status == 'released'

    def test_order_transition_from_a_stale_state_is_refused(self, people, shop):
        from sqlalchemy import text
        from sqlalchemy.orm.attributes import set_committed_value

        from app import db
        from app.models.order import Order

        order = self._delivered(people, shop)
        stale = fresh(Order, order.id)

        db.session.execute(text("UPDATE orders SET status = 'disputed' WHERE id = :id"),
                           {'id': order.id.hex})
        db.session.commit()
        set_committed_value(stale, 'status', 'delivered')  # what this request read
        with pytest.raises(ValueError):
            stale.transition_to('completed')
        db.session.rollback()

        assert status(order) == 'disputed'


class TestPaymentLeavesTheCommitToTheCaller:
    def test_pay_order_does_not_commit(self, people, shop, monkeypatch):
        """
        The audit call inside EscrowService.pay_order() committed the session,
        so the payment was persisted before the caller (the route) committed --
        and a concurrent second payment no longer met an open transaction.
        Found by the PostgreSQL race tests (tests/test_concurrency_pg.py).
        """
        from app import db
        from app.models.order import Order
        from app.services.escrow_service import EscrowService

        from app.services import audit_service

        order = buy_now(people['buyer'], shop(stock=5))
        commits, audit_commit_flags = [], []
        monkeypatch.setattr(db.session, 'commit', lambda: commits.append(1))
        # On SQLite the log_* stored procedures do not exist, so the audit write
        # fails before it would commit -- watching session.commit alone was blind
        # there. The flag each audit write is called with is the real contract.
        real_write = audit_service._write
        monkeypatch.setattr(audit_service, '_write', lambda sql, params, commit: (
            audit_commit_flags.append(commit), real_write(sql, params, commit))[1])

        EscrowService.pay_order(fresh(Order, order.id))

        assert audit_commit_flags and not any(audit_commit_flags)
        assert commits == []
        db.session.rollback()
        assert status(order) == 'pending'


# =============================================================================
# Checkout
# =============================================================================

class TestCheckout:
    def _cart(self, client, *pairs):
        for product, quantity in pairs:
            client.post('/cart/add', data={'product_id': str(product.id), 'quantity': str(quantity)})

    def _checkout(self, client):
        return client.post('/cart/checkout', data={
            'shipping_name': 'Bob', 'shipping_address': 'Somewhere 1'})

    def test_checkout_creates_orders_and_reserves_stock(self, people, shop):
        from app.models.order import Order

        a, b = shop(stock=4), shop(stock=4)
        self._cart(people['buyer'], (a, 1), (b, 2))

        self._checkout(people['buyer'])

        assert Order.query.filter(Order.product_id.in_([a.id, b.id])).count() == 2
        assert (stock(a), stock(b)) == (3, 2)

    def test_failure_halfway_leaves_nothing_behind(self, people, shop, other_vendor, monkeypatch):
        """
        create_escrow_for_order() and set_shipping_*() committed inside the item
        loop, so a failure at item 2 left item 1's order committed, the cart
        intact -- and a retry ordered item 1 twice.
        """
        from app.models.cart import CartItem
        from app.models.order import Order
        from app.services import escrow_service

        a, b = shop(stock=4), shop(stock=4, vendor=other_vendor)
        self._cart(people['buyer'], (a, 1), (b, 1))
        real = escrow_service.EscrowService.create_escrow_for_order
        calls = []

        def second_fails(order):
            calls.append(order)
            if len(calls) == 2:
                raise RuntimeError('escrow service down')
            return real(order)
        monkeypatch.setattr(escrow_service.EscrowService, 'create_escrow_for_order',
                            staticmethod(second_fails))

        self._checkout(people['buyer'])

        assert len(calls) == 2
        assert Order.query.filter(Order.product_id.in_([a.id, b.id])).count() == 0
        assert (stock(a), stock(b)) == (4, 4)
        assert CartItem.query.filter(CartItem.product_id.in_([a.id, b.id])).count() == 2

    def test_price_change_after_adding_is_not_silently_ignored(self, people, shop):
        """The cart's snapshot price went straight into the order."""
        from app import db
        from app.models.order import Order
        from app.models.product import Product

        product = shop(price='20.00')
        self._cart(people['buyer'], (product, 1))
        changed = fresh(Product, product.id)
        changed.price = Decimal('35.00')
        db.session.commit()

        self._checkout(people['buyer'])
        assert Order.query.filter_by(product_id=product.id).count() == 0, (
            'the buyer must see the new price before ordering'
        )

        self._checkout(people['buyer'])
        order = Order.query.filter_by(product_id=product.id).one()
        assert order.unit_price == Decimal('35.00')


# =============================================================================
# K4 -- quantities and prices
# =============================================================================

class TestQuantities:
    @pytest.mark.parametrize('quantity', [-5, 0, 1.5, 'abc', True, None, 10 ** 9])
    def test_ajax_add_rejects_bad_quantity(self, people, shop, quantity):
        """
        The JSON route passed `quantity` straight to Cart.add_item: -5 made a
        negative cart line, a negative order total and an escrow with a negative
        amount.
        """
        from app.models.cart import CartItem

        product = shop(stock=5)
        response = people['buyer'].post('/cart/add-ajax',
                                        json={'product_id': str(product.id), 'quantity': quantity})

        assert response.status_code == 400
        assert CartItem.query.filter_by(product_id=product.id).count() == 0

    def test_update_rejects_negative_quantity(self, people, shop):
        from app.models.cart import CartItem

        product = shop(stock=5)
        people['buyer'].post('/cart/add', data={'product_id': str(product.id), 'quantity': '2'})

        people['buyer'].post('/cart/update', data={'product_id': str(product.id), 'quantity': '-3'})

        item = CartItem.query.filter_by(product_id=product.id).first()
        assert item is None or item.quantity > 0

    def test_database_refuses_non_positive_quantities(self, app, sample_user, shop):
        """The model check is the first line; the CHECK constraint is the one that cannot be skipped."""
        from sqlalchemy.exc import IntegrityError

        from app import db
        from app.models.cart import Cart, CartItem

        cart = Cart.get_or_create(sample_user.id)
        db.session.add(CartItem(cart_id=cart.id, product_id=shop().id, quantity=-1,
                                unit_price=Decimal('1.00')))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


class TestPrices:
    """
    Prices went through float(): NaN passed `price <= 0` (every comparison
    with NaN is False), and 0.001 passed and was stored as 0.00 -- a free
    product.
    """

    @pytest.mark.parametrize('raw', ['nan', 'inf', '-1', '0', '0.001', '12.345', '1e9', 'abc', ''])
    def test_bad_prices_are_refused(self, app, shop, sample_vendor, raw):
        from app.models.product import Product

        client = login(app, sample_vendor)
        title = f'Priced {uuid.uuid4().hex[:6]}'
        client.post('/vendor/add-product', data={
            'title': title, 'description': 'long enough description', 'price': raw,
            'category_id': str(shop.category.id), 'quantity': '1'})

        assert Product.query.filter_by(title=title).count() == 0

    def test_good_price_is_stored_exactly(self, app, shop, sample_vendor):
        from app.models.product import Product

        client = login(app, sample_vendor)
        title = f'Priced {uuid.uuid4().hex[:6]}'
        client.post('/vendor/add-product', data={
            'title': title, 'description': 'long enough description', 'price': '19.99',
            'category_id': str(shop.category.id), 'quantity': '1'})

        assert Product.query.filter_by(title=title).one().price == Decimal('19.99')

    def test_edit_refuses_negative_stock(self, app, shop, sample_vendor):
        product = shop(stock=3)
        client = login(app, sample_vendor)
        html = client.post(f'/vendor/product/{product.id}/edit', data={
            'title': product.title, 'description': product.description, 'price': '20.00',
            'category_id': str(shop.category.id), 'quantity': '-5'},
            follow_redirects=True).get_data(as_text=True)

        assert stock(product) == 3
        # Not only refused by the CHECK constraint (the second layer, which ends
        # in a generic error) -- refused up front, with a reason the vendor can act on.
        assert 'Stock must be between' in html
