"""Unit tests for the Product model (stock, purchasability, tags, ratings)."""

import uuid

import pytest


@pytest.fixture
def category(app):
    from app import db
    from app.models.product import ProductCategory

    suffix = uuid.uuid4().hex[:8]
    cat = ProductCategory(id=uuid.uuid4(), name=f'Cat {suffix}', slug=f'cat-{suffix}')
    db.session.add(cat)
    db.session.commit()
    yield cat
    db.session.delete(cat)
    db.session.commit()


@pytest.fixture
def make_product(app, sample_vendor, category):
    from app import db
    from app.models.product import Product

    created = []

    def _make(**overrides):
        suffix = uuid.uuid4().hex[:8]
        fields = dict(
            id=uuid.uuid4(),
            vendor_id=sample_vendor.id,
            category_id=category.id,
            title=f'Product {suffix}',
            description='Training item',
            price=25,
            quantity=5,
            is_digital=False,
            is_active=True,
            is_approved=True,
        )
        fields.update(overrides)
        item = Product(**fields)
        db.session.add(item)
        db.session.commit()
        created.append(item)
        return item

    yield _make

    for item in created:
        try:
            db.session.delete(item)
            db.session.commit()
        except Exception:
            db.session.rollback()


class TestStock:
    def test_in_stock_when_quantity_positive(self, make_product):
        assert make_product(quantity=1).is_in_stock() is True

    def test_out_of_stock_at_zero(self, make_product):
        assert make_product(quantity=0).is_in_stock() is False

    def test_digital_is_always_in_stock(self, make_product):
        assert make_product(quantity=0, is_digital=True).is_in_stock() is True

    def test_record_sale_reduces_by_quantity(self, make_product):
        item = make_product(quantity=10)
        item.record_sale(3)
        assert (item.quantity, item.sales) == (7, 3)

    def test_record_sale_clamps_at_zero(self, make_product):
        item = make_product(quantity=2)
        item.record_sale(5)
        assert item.quantity == 0

    def test_record_sale_treats_zero_as_one(self, make_product):
        """Guard against a falsy quantity silently selling nothing."""
        item = make_product(quantity=4)
        item.record_sale(0)
        assert item.quantity == 3

    def test_digital_sale_keeps_quantity(self, make_product):
        item = make_product(quantity=4, is_digital=True)
        item.record_sale(2)
        assert item.quantity == 4
        assert item.sales == 2


class TestCanPurchase:
    def test_active_approved_in_stock(self, make_product):
        ok, err = make_product().can_purchase(1)
        assert ok is True and err is None

    def test_inactive_rejected(self, make_product):
        ok, err = make_product(is_active=False).can_purchase(1)
        assert ok is False and 'not active' in err

    def test_unapproved_rejected(self, make_product):
        ok, err = make_product(is_approved=False).can_purchase(1)
        assert ok is False and 'not approved' in err

    def test_more_than_stock_rejected(self, make_product):
        ok, err = make_product(quantity=2).can_purchase(3)
        assert ok is False and 'Insufficient' in err

    def test_exactly_stock_allowed(self, make_product):
        ok, _ = make_product(quantity=3).can_purchase(3)
        assert ok is True

    def test_digital_ignores_stock(self, make_product):
        ok, _ = make_product(quantity=0, is_digital=True).can_purchase(99)
        assert ok is True


class TestTagsAndViews:
    def test_tags_roundtrip(self, make_product):
        item = make_product()
        item.set_tags_list(['alpha', 'beta'])
        assert item.get_tags_list() == ['alpha', 'beta']

    def test_empty_tags_returns_empty_list(self, make_product):
        item = make_product()
        item.set_tags_list([])
        assert item.get_tags_list() == []

    def test_increment_views(self, make_product):
        item = make_product()
        before = item.views or 0
        item.increment_views()
        assert item.views == before + 1
