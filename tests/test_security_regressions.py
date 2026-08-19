"""
Regression tests for issues found in the security review.

  * the configured password policy was never enforced
  * _is_safe_url() let backslash / protocol-relative targets through
  * stock was always decremented by exactly 1, regardless of order quantity
"""

import uuid

import pytest


class TestPasswordPolicy:
    """
    PASSWORD_MIN_LENGTH and the PASSWORD_REQUIRE_* flags exist in config but were
    ignored: set_password() only checked len(password) < 8.
    """

    def test_short_password_rejected(self, app, sample_user):
        with pytest.raises(ValueError, match='at least'):
            sample_user.set_password('Ab1!efg')  # 7 chars

    def test_password_below_configured_minimum_rejected(self, app, sample_user):
        """12 is the configured minimum -- an 11 char password must not pass."""
        assert app.config['PASSWORD_MIN_LENGTH'] == 12
        with pytest.raises(ValueError, match='at least 12'):
            sample_user.set_password('Abcdef123!x')  # 11 chars, otherwise valid

    def test_missing_uppercase_rejected(self, app, sample_user):
        with pytest.raises(ValueError, match='uppercase'):
            sample_user.set_password('abcdefgh123!')

    def test_missing_digit_rejected(self, app, sample_user):
        with pytest.raises(ValueError, match='digit'):
            sample_user.set_password('Abcdefghijk!')

    def test_missing_special_rejected(self, app, sample_user):
        with pytest.raises(ValueError, match='special'):
            sample_user.set_password('Abcdefghij123')

    def test_compliant_password_accepted(self, app, sample_user):
        sample_user.set_password('CompliantPass123!')
        assert sample_user.password_hash.startswith('$argon2id$')

    def test_rehash_path_skips_policy(self, app, sample_user):
        """
        Internal re-hashing must not re-validate: the password was already
        accepted, and a tightened policy would lock the user out mid-login.
        """
        sample_user.set_password('short1!A', enforce_policy=False)
        assert sample_user.password_hash.startswith('$argon2id$')


class TestOpenRedirect:
    """_is_safe_url() must only accept same-site targets."""

    @pytest.mark.parametrize('target', [
        '//evil.com',
        '/\\evil.com',        # browsers normalise \ to /
        '\\\\evil.com',
        'http://evil.com/x',
        'javascript:alert(1)',
        '',
    ])
    def test_external_targets_rejected(self, app, target):
        from app.routes.auth import _is_safe_url

        with app.test_request_context('/', base_url='http://localhost'):
            assert _is_safe_url(target) is False, f'{target!r} must be rejected'

    @pytest.mark.parametrize('target', [
        '/buyer/orders',
        '/vendor/dashboard?tab=1',
        'http://localhost/buyer/orders',
    ])
    def test_internal_targets_allowed(self, app, target):
        from app.routes.auth import _is_safe_url

        with app.test_request_context('/', base_url='http://localhost'):
            assert _is_safe_url(target) is True, f'{target!r} should be allowed'


class TestStockAccounting:
    """record_sale() must reduce stock by the amount actually ordered."""

    @pytest.fixture
    def product(self, app, sample_vendor):
        from app import db
        from app.models.product import Product, ProductCategory

        suffix = uuid.uuid4().hex[:8]
        category = ProductCategory(
            id=uuid.uuid4(), name=f'Cat {suffix}', slug=f'cat-{suffix}'
        )
        db.session.add(category)
        db.session.flush()

        item = Product(
            id=uuid.uuid4(),
            vendor_id=sample_vendor.id,
            category_id=category.id,
            title=f'Item {suffix}',
            description='Training item',
            price=10,
            quantity=10,
            is_digital=False,
        )
        db.session.add(item)
        db.session.commit()
        yield item
        db.session.delete(item)
        db.session.delete(category)
        db.session.commit()

    def test_sale_decrements_by_quantity(self, product):
        """Regression: ordering 4 units used to reduce stock by 1."""
        product.record_sale(4)

        assert product.quantity == 6
        assert product.sales == 4

    def test_default_is_single_unit(self, product):
        product.record_sale()

        assert product.quantity == 9
        assert product.sales == 1

    def test_stock_never_goes_negative(self, product):
        product.record_sale(999)

        assert product.quantity == 0

    def test_digital_product_keeps_stock(self, app, product):
        from app import db

        product.is_digital = True
        db.session.commit()

        product.record_sale(3)

        assert product.quantity == 10, 'digital goods are not stock-limited'
        assert product.sales == 3
