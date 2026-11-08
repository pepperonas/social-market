"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Improvement plan 2026-11, C2: races between two real database connections.

The order lifecycle claims every state change with a conditional UPDATE
(``... WHERE status = <what this request read>``). The SQLite suite could only
imitate a race with an artificially stale object: SQLite locks the whole file,
two writers never overlap.

Here the first request runs in the test's own session and keeps its transaction
open -- it holds the row lock. The second runs on a second connection in a
thread. The test checks in pg_stat_activity that the second one is really
WAITING on that lock before the first commits; only then is it a race and not
two requests one after the other. In READ COMMITTED, PostgreSQL re-evaluates the
second UPDATE's WHERE clause against the committed row, finds the condition no
longer true, and the second request must give up cleanly.
"""

import threading
import time

import pytest
from sqlalchemy import text

from tests.conftest import ON_POSTGRES
from tests.test_order_lifecycle import (  # noqa: F401 (people, shop are fixtures)
    buy_now, fresh, people, shop, stock,
)

pytestmark = pytest.mark.skipif(not ON_POSTGRES, reason='needs TEST_DATABASE_URL (PostgreSQL)')


def _waiting_on_a_lock():
    from app import db
    # pg_stat_activity is snapshotted on first access within a transaction
    # (stats_fetch_consistency = cache) -- and this session is inside the
    # first request's open transaction. Without clearing, the loop below kept
    # reading the picture from before the second request got there.
    db.session.execute(text('SELECT pg_stat_clear_snapshot()'))
    return db.session.execute(text(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE datname = current_database() AND wait_event_type = 'Lock'")).scalar()


def race(app, first, second):
    """
    Run ``first`` in this session without committing, then ``second`` on a
    second connection. Asserts that ``second`` blocks on ``first``'s lock, then
    commits ``first``. Returns {'value': ...} or {'error': exception} for
    ``second``, which is committed if it returned and rolled back if it raised.
    """
    from app import db

    first()
    outcome = {}

    def worker():
        with app.app_context():
            try:
                outcome['value'] = second()
                db.session.commit()
            except Exception as exc:  # noqa: BLE001 -- the outcome IS the test
                db.session.rollback()
                outcome['error'] = exc
            finally:
                db.session.remove()

    thread = threading.Thread(target=worker)
    thread.start()
    deadline = time.monotonic() + 5
    while not _waiting_on_a_lock():
        assert thread.is_alive(), f'second request did not wait: {outcome}'
        assert time.monotonic() < deadline, 'second request never reached the lock'
        time.sleep(0.02)

    db.session.commit()
    thread.join(10)
    assert not thread.is_alive(), 'second request still blocked after the commit'
    return outcome


def _fund_transactions(order_id):
    from app import db
    from app.models.escrow import Escrow, EscrowTransaction
    from app.models.order import Order

    db.session.expire_all()
    escrow_id = db.session.get(Order, order_id).escrow.id
    return db.session.query(EscrowTransaction).filter(
        EscrowTransaction.escrow_id == escrow_id,
        EscrowTransaction.transaction_type == 'fund').count(), db.session.get(Escrow, escrow_id)


class TestDoublePayment:
    def test_two_payments_fund_the_escrow_once(self, app, people, shop):
        from app import db
        from app.models.order import Order
        from app.services.escrow_service import EscrowService

        order = buy_now(people['buyer'], shop(stock=5))
        order_id = order.id

        outcome = race(
            app,
            lambda: EscrowService.pay_order(fresh(Order, order_id)),
            lambda: EscrowService.pay_order(db.session.get(Order, order_id)),
        )

        assert isinstance(outcome.get('error'), ValueError), outcome
        funds, escrow = _fund_transactions(order_id)
        assert funds == 1
        assert escrow.status == 'funded'
        assert fresh(Order, order_id).status == 'paid'


class TestLastUnit:
    def test_two_reservations_of_the_last_unit_succeed_once(self, app, shop):
        from app import db
        from app.models.product import Product

        product = shop(stock=1)
        product_id = product.id

        first_result = {}

        def first():
            first_result['value'] = fresh(Product, product_id).reserve_stock(1)

        outcome = race(app, first,
                       lambda: db.session.get(Product, product_id).reserve_stock(1))

        assert first_result['value'] is True
        assert outcome == {'value': False}, outcome
        assert stock(product) == 0


class TestCancelRacesShipping:
    def _paid_order(self, people, shop):
        product = shop(stock=5)
        order = buy_now(people['buyer'], product, 2)
        people['buyer'].post(f'/buyer/order/{order.id}/pay')
        assert fresh(type(order), order.id).status == 'paid'
        return product, order.id

    def test_cancel_first_then_ship_is_refused(self, app, people, shop):
        from app import db
        from app.models.order import Order, OrderStatus

        product, order_id = self._paid_order(people, shop)
        assert stock(product) == 3

        outcome = race(
            app,
            lambda: fresh(Order, order_id).transition_to(OrderStatus.CANCELLED),
            lambda: db.session.get(Order, order_id).transition_to(
                OrderStatus.SHIPPED, tracking_number='T-RACE'),
        )

        assert isinstance(outcome.get('error'), ValueError), outcome
        order = fresh(Order, order_id)
        assert order.status == 'cancelled'
        assert order.tracking_number is None
        assert order.escrow.status == 'refunded'
        assert stock(product) == 5  # returned once, not twice

    def test_ship_first_then_cancel_is_refused(self, app, people, shop):
        from app import db
        from app.models.order import Order, OrderStatus

        product, order_id = self._paid_order(people, shop)

        outcome = race(
            app,
            lambda: fresh(Order, order_id).transition_to(
                OrderStatus.SHIPPED, tracking_number='T-RACE'),
            lambda: db.session.get(Order, order_id).transition_to(OrderStatus.CANCELLED),
        )

        assert isinstance(outcome.get('error'), ValueError), outcome
        order = fresh(Order, order_id)
        assert order.status == 'shipped'
        assert order.escrow.status == 'funded'
        assert stock(product) == 3  # nothing went back for a shipped order
