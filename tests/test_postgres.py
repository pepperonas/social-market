"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Improvement plan 2026-11, C1: what only a real PostgreSQL can show.

The whole suite runs against PostgreSQL when TEST_DATABASE_URL points at one
(CI does, see .github/workflows/ci.yml). This module holds the checks that have
no SQLite meaning at all -- the pgcrypto functions, the session time zone, the
schema built from the SQL files -- and is skipped on SQLite.

What the first PostgreSQL run found:
  * encrypt_data() read app.encryption_key, which nothing ever set. pgp_sym_
    encrypt() with a NULL key returns NULL, so checkout stored every shipping
    name and address as NULL -- silently, on the live server. SQLite binds
    encrypt_data to the app's own Fernet and could not see it.
  * postgres/audit-logging.sql did not apply to a fresh database (NOW() in an
    index predicate), so every index after that line was missing live.
"""


import pytest
from sqlalchemy import text

from tests.conftest import ON_POSTGRES
from tests.test_order_lifecycle import people, shop  # noqa: F401 (fixtures)

pytestmark = pytest.mark.skipif(not ON_POSTGRES, reason='needs TEST_DATABASE_URL (PostgreSQL)')


def _scalar(sql, **params):
    from app import db
    return db.session.execute(text(sql), params).scalar()


class TestHarness:
    """If these fail, the rest of the PostgreSQL run proves less than it claims."""

    def test_session_time_zone_is_the_live_one(self):
        # Naive-UTC bugs only show in a zone that is not UTC.
        assert _scalar('SHOW timezone') == 'Europe/Berlin'

    def test_audit_script_applied_completely(self):
        # The last index of postgres/audit-logging.sql -- present only if the
        # script ran to the end.
        names = {r[0] for r in __import__('app').db.session.execute(text(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"))}
        assert {'idx_rate_limit_log_cleanup', 'idx_admin_actions_target',
                'idx_transaction_audit_vendor', 'idx_message_audit_sender'} <= names

    def test_tests_run_inside_a_transaction(self):
        # A pooled connection left in autocommit (the schema build uses it)
        # would make every rollback test vacuous. A transaction-local setting
        # must survive to the next statement.
        from app import db
        db.session.execute(text("SELECT set_config('harness.probe', 'on', true)"))
        assert _scalar("SELECT current_setting('harness.probe', true)") == 'on'
        db.session.rollback()

    def test_lifecycle_constraints_exist_without_the_one_shot_migration(self):
        names = {r[0] for r in __import__('app').db.session.execute(text(
            "SELECT conname FROM pg_constraint WHERE contype = 'c'"))}
        assert {'ck_product_price_positive', 'ck_product_quantity_nonnegative',
                'ck_cart_item_quantity_positive', 'ck_order_quantity_positive',
                'ck_order_total_nonnegative'} <= names


class TestColumnEncryption:
    """encrypt_data()/decrypt_data(): the pgcrypto layer under Order.shipping_*."""

    def test_the_app_connection_carries_the_key(self, app):
        assert _scalar("SELECT current_setting('app.encryption_key', true)") == \
            app.config['DB_ENCRYPTION_KEY']

    def test_roundtrip(self):
        token = _scalar('SELECT encrypt_data(:v)', v='Hauptstr. 1')
        assert token is not None
        assert b'Hauptstr' not in bytes(token)
        assert _scalar('SELECT decrypt_data(:t)', t=token) == 'Hauptstr. 1'

    def test_missing_key_fails_closed(self):
        """Without a key, encryption must raise -- never store NULL."""
        from app import db
        from sqlalchemy.exc import DBAPIError
        with pytest.raises(DBAPIError, match='encryption key'):
            db.session.execute(text("SELECT set_config('app.encryption_key', '', true)"))
            db.session.execute(text("SELECT encrypt_data('x')")).scalar()
        db.session.rollback()

    def test_wrong_key_fails_closed(self):
        """A wrong key must not read as 'no address on file'."""
        from app import db
        from sqlalchemy.exc import DBAPIError
        token = _scalar('SELECT encrypt_data(:v)', v='secret')
        db.session.commit()
        with pytest.raises(DBAPIError):
            db.session.execute(text("SELECT set_config('app.encryption_key', 'wrong', true)"))
            db.session.execute(text('SELECT decrypt_data(:t)'), {'t': token}).scalar()
        db.session.rollback()

    def test_decrypting_null_is_null(self):
        assert _scalar('SELECT decrypt_data(NULL)') is None


class TestCheckoutKeepsTheShippingAddress:
    """The live symptom, end to end: a physical order placed over HTTP."""

    def test_vendor_can_read_what_the_buyer_entered(self, people, shop):
        from app import db
        from app.models.order import Order

        product = shop(stock=5)
        buyer = people['buyer']
        buyer.post('/cart/add', data={'product_id': str(product.id), 'quantity': '1'})
        buyer.post('/cart/checkout', data={
            'shipping_name': 'Alice Example',
            'shipping_address': 'Hauptstr. 1, 10115 Berlin',
        })

        db.session.expire_all()
        order = Order.query.filter_by(product_id=product.id).one()
        assert order.get_shipping_name() == 'Alice Example'
        assert order.get_shipping_address() == 'Hauptstr. 1, 10115 Berlin'
