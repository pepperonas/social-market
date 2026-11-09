"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Improvement plan 2026-11, step 6 (C3): route coverage for the admin user
management and the vendor product editing.

admin.py stood at 61-66 %, vendor.py at 63-69 %: unlocking an account,
approving a vendor, the audit-log viewer, the system-health page, the vendor's
order detail and the product edit/delete forms were never requested by any
test. Every test here goes through HTTP and checks what changed in the
database, not only the status code.
"""

import json
import uuid
from collections import namedtuple
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from tests.test_order_lifecycle import (  # noqa: F401 (people, shop, other_vendor are fixtures)
    BUYER_PW, buy_now, fresh, login, other_vendor, people, shop,
)


def _admin_actions(action, target):
    """admin_actions rows for one target (the table is not emptied between tests)."""
    from app import db
    return db.session.execute(
        text('SELECT target_id, before_state, after_state FROM admin_actions '
             'WHERE action = :a AND target_id = :t'),
        {'a': action, 't': str(target.id)}).fetchall()


def _user(user_id):
    from app.models.user import User
    return fresh(User, user_id)


@pytest.fixture
def pending_vendor(app):
    from app import db
    from app.models.user import User

    suffix = uuid.uuid4().hex[:8]
    vendor = User(id=uuid.uuid4(), username=f'newvendor_{suffix}', email=f'nv_{suffix}@test.local',
                  role='vendor', is_active=True, is_verified=True, is_vendor_approved=False)
    vendor.set_password(BUYER_PW)
    db.session.add(vendor)
    db.session.commit()
    return vendor


# =============================================================================
# Admin: user management
# =============================================================================

class TestUnlock:
    def _lock(self, user):
        from app import db
        from app.models.user import User
        from app.timeutil import utcnow

        u = db.session.get(User, user.id)
        u.failed_login_attempts = 5
        u.account_locked_until = utcnow() + timedelta(minutes=30)
        db.session.commit()

    def test_admin_unlocks_a_locked_account(self, people, sample_user):
        self._lock(sample_user)

        r = people['admin'].post(f'/admin/user/{sample_user.id}/unlock')

        assert r.status_code == 302
        u = _user(sample_user.id)
        assert u.failed_login_attempts == 0
        assert u.account_locked_until is None
        rows = _admin_actions('unlock_account', sample_user)
        assert [str(r.target_id) for r in rows] == [str(sample_user.id)]
        before = rows[0].before_state  # JSONB on PostgreSQL, text on SQLite
        before = json.loads(before) if isinstance(before, str) else before
        assert before['failed_login_attempts'] == 5

    def test_unlocked_user_can_log_in_again(self, app, people, sample_user):
        self._lock(sample_user)
        people['admin'].post(f'/admin/user/{sample_user.id}/unlock')

        login(app, sample_user)  # asserts the redirect of a successful login

    def test_unlocking_an_account_that_is_not_locked_changes_and_logs_nothing(
            self, people, sample_user):
        r = people['admin'].post(f'/admin/user/{sample_user.id}/unlock', follow_redirects=True)

        assert b'is not locked' in r.data
        assert _admin_actions('unlock_account', sample_user) == []

    def test_a_buyer_cannot_unlock(self, people, sample_user, sample_vendor):
        self._lock(sample_vendor)

        people['buyer'].post(f'/admin/user/{sample_vendor.id}/unlock')

        assert _user(sample_vendor.id).failed_login_attempts == 5

    def test_detail_page_offers_unlock_only_for_a_locked_account(self, people, sample_user):
        url = f'/admin/user/{sample_user.id}'
        action = f'/admin/user/{sample_user.id}/unlock'.encode()
        assert action not in people['admin'].get(url).data

        self._lock(sample_user)
        assert action in people['admin'].get(url).data


class TestApproveVendor:
    def test_admin_approves_a_vendor(self, people, pending_vendor):
        from app.models.notification import Notification

        r = people['admin'].post(f'/admin/user/{pending_vendor.id}/approve-vendor')

        assert r.status_code == 302
        assert _user(pending_vendor.id).is_vendor_approved is True
        assert [str(r.target_id) for r in _admin_actions('approve_vendor', pending_vendor)] == [str(pending_vendor.id)]
        notes = Notification.query.filter_by(user_id=pending_vendor.id).all()
        assert [n.title for n in notes] == ['Vendor Account Approved']

    def test_approving_twice_notifies_once(self, people, pending_vendor):
        from app.models.notification import Notification

        people['admin'].post(f'/admin/user/{pending_vendor.id}/approve-vendor')
        r = people['admin'].post(f'/admin/user/{pending_vendor.id}/approve-vendor',
                                 follow_redirects=True)

        assert b'already approved' in r.data
        assert Notification.query.filter_by(user_id=pending_vendor.id).count() == 1
        assert len(_admin_actions('approve_vendor', pending_vendor)) == 1

    def test_a_buyer_account_is_not_made_a_vendor(self, people, sample_user):
        r = people['admin'].post(f'/admin/user/{sample_user.id}/approve-vendor',
                                 follow_redirects=True)

        assert b'is not a vendor' in r.data
        u = _user(sample_user.id)
        assert u.role == 'buyer' and not u.is_vendor_approved
        assert _admin_actions('approve_vendor', sample_user) == []

    def test_a_vendor_cannot_approve_another_vendor(self, people, pending_vendor):
        people['vendor'].post(f'/admin/user/{pending_vendor.id}/approve-vendor')

        assert _user(pending_vendor.id).is_vendor_approved is False

    def test_unapproved_vendor_cannot_add_products_until_approved(
            self, app, people, pending_vendor):
        client = login(app, pending_vendor)
        assert client.get('/vendor/add-product').status_code == 302

        people['admin'].post(f'/admin/user/{pending_vendor.id}/approve-vendor')

        assert client.get('/vendor/add-product').status_code == 200


class TestUserDetail:
    def test_vendor_detail_counts_products_and_orders(self, people, shop, sample_vendor):
        product = shop()
        shop()
        buy_now(people['buyer'], product)

        r = people['admin'].get(f'/admin/user/{sample_vendor.id}')

        assert r.status_code == 200
        assert sample_vendor.username.encode() in r.data
        page = r.data.decode()
        assert _stat(page, 'Products') == '2'
        assert _stat(page, 'Orders') == '1'

    def test_buyer_detail_counts_their_orders(self, people, shop, sample_user):
        buy_now(people['buyer'], shop())
        buy_now(people['buyer'], shop())

        page = people['admin'].get(f'/admin/user/{sample_user.id}').data.decode()

        assert _stat(page, 'Orders') == '2'

    def test_unknown_user_is_404(self, people):
        assert people['admin'].get(f'/admin/user/{uuid.uuid4()}').status_code == 404

    def test_non_admin_is_turned_away(self, people, sample_user):
        r = people['vendor'].get(f'/admin/user/{sample_user.id}')

        assert r.status_code == 302
        assert '/admin/' not in r.headers['Location']


def _stat(page, label):
    """The number shown next to a statistics label on the user detail page."""
    import re
    m = re.search(rf'{label}[^<]*</[^>]+>\s*(?:<[^>]+>\s*)*(\d+)', page)
    assert m, f'no {label} statistic on the page'
    return m.group(1)


# =============================================================================
# Admin: audit-log viewer and system health
# =============================================================================

class TestAuditLogViewer:
    def test_admin_tab_lists_admin_actions(self, people, pending_vendor):
        people['admin'].post(f'/admin/user/{pending_vendor.id}/approve-vendor')

        r = people['admin'].get('/admin/audit-logs?type=admin')

        assert r.status_code == 200
        assert b'approve_vendor' in r.data

    @pytest.mark.parametrize('log_type, table, row', [
        ('auth', 'auth_log',
         "INSERT INTO auth_log (username, action, ip_address) VALUES ('probe_user', 'login_failed', '10.0.0.9')"),
        ('security', 'security_events',
         "INSERT INTO security_events (event_type, severity, description, ip_address) "
         "VALUES ('probe_event', 'low', 'probe', '10.0.0.9')"),
        ('audit', 'audit_log',
         "INSERT INTO audit_log (action, table_name, status, severity) "
         "VALUES ('probe_action', 'probe_table', 'success', 'info')"),
    ])
    def test_each_tab_reads_its_own_table(self, people, log_type, table, row):
        from app import db
        db.session.execute(text(row))
        db.session.commit()
        marker = row.split("'")[1].encode()

        own = people['admin'].get(f'/admin/audit-logs?type={log_type}')
        other = people['admin'].get('/admin/audit-logs?type=admin')

        assert own.status_code == 200
        assert marker in own.data
        assert marker not in other.data

    def test_pages_past_the_end_are_empty_not_an_error(self, people, pending_vendor):
        people['admin'].post(f'/admin/user/{pending_vendor.id}/approve-vendor')

        r = people['admin'].get('/admin/audit-logs?type=admin&page=99')

        assert r.status_code == 200
        assert b'approve_vendor' not in r.data

    def test_unknown_type_shows_nothing(self, people, pending_vendor):
        people['admin'].post(f'/admin/user/{pending_vendor.id}/approve-vendor')

        r = people['admin'].get('/admin/audit-logs?type=bogus')

        assert r.status_code == 200
        assert b'approve_vendor' not in r.data

    def test_non_admin_cannot_read_logs(self, people):
        assert people['buyer'].get('/admin/audit-logs?type=admin').status_code == 302


Usage = namedtuple('Usage', 'percent free available')


class TestSystemHealth:
    @pytest.fixture
    def machine(self, monkeypatch):
        """Set disk and memory usage seen by the health page."""
        import psutil

        def set_usage(disk, memory):
            gb = 1024 ** 3
            monkeypatch.setattr(psutil, 'disk_usage', lambda path: Usage(disk, 10 * gb, 0))
            monkeypatch.setattr(psutil, 'virtual_memory', lambda: Usage(memory, 0, 4 * gb))
        return set_usage

    @pytest.mark.parametrize('disk, expected', [(50, 'healthy'), (85, 'warning'), (95, 'critical')])
    def test_disk_thresholds(self, people, machine, disk, expected, monkeypatch):
        import app.routes.admin as admin_routes
        captured = {}
        real = admin_routes.render_template

        def spy(template, **ctx):
            captured.update(ctx)
            return real(template, **ctx)

        monkeypatch.setattr(admin_routes, 'render_template', spy)
        machine(disk=disk, memory=50)

        r = people['admin'].get('/admin/system-health')

        assert r.status_code == 200
        assert captured['health']['disk']['status'] == expected
        assert captured['health']['disk']['usage'] == disk
        assert captured['health']['memory']['status'] == 'healthy'
        assert captured['health']['database']['status'] in ('healthy', 'degraded')

    def test_memory_critical_lowers_the_score(self, people, machine, monkeypatch):
        import app.routes.admin as admin_routes
        scores = []
        real = admin_routes.render_template

        def spy(template, **ctx):
            scores.append(ctx['health_score'])
            return real(template, **ctx)

        monkeypatch.setattr(admin_routes, 'render_template', spy)
        machine(disk=10, memory=10)
        people['admin'].get('/admin/system-health')
        machine(disk=10, memory=95)
        people['admin'].get('/admin/system-health')

        assert scores[1] < scores[0]

    def test_unreachable_redis_is_shown_not_a_500(self, people, machine, monkeypatch):
        """The page must render the failure it exists to report. A healthy check
        has no `error` key and an unhealthy one no `latency` -- the template read
        both unconditionally, which StrictUndefined turned into a 500."""
        import redis

        def refuse(url):
            raise redis.ConnectionError('connection refused by probe')

        monkeypatch.setattr(redis, 'from_url', refuse)
        machine(disk=10, memory=10)

        r = people['admin'].get('/admin/system-health')

        assert r.status_code == 200
        assert b'connection refused by probe' in r.data
        assert b'UNHEALTHY' in r.data

    def test_non_admin_is_turned_away(self, people):
        assert people['vendor'].get('/admin/system-health').status_code == 302


# =============================================================================
# Vendor: order detail, product edit and delete
# =============================================================================

class TestVendorOrderDetail:
    def test_vendor_sees_their_order(self, people, shop):
        product = shop()
        order = buy_now(people['buyer'], product)

        r = people['vendor'].get(f'/vendor/order/{order.id}')

        assert r.status_code == 200
        assert product.title.encode() in r.data

    def test_another_vendor_is_turned_away(self, app, people, shop, other_vendor):
        product = shop()
        order = buy_now(people['buyer'], product)
        intruder = login(app, other_vendor)

        r = intruder.get(f'/vendor/order/{order.id}')

        assert r.status_code == 302
        assert r.headers['Location'].endswith('/vendor/orders')

    def test_unknown_order_is_404(self, people):
        assert people['vendor'].get(f'/vendor/order/{uuid.uuid4()}').status_code == 404


class TestEditProduct:
    def _form(self, product, **overrides):
        form = {'title': product.title, 'description': product.description,
                'price': str(product.price), 'quantity': str(product.quantity),
                'category_id': str(product.category_id), 'tags': ''}
        form.update(overrides)
        return form

    def _product(self, product):
        from app.models.product import Product
        return fresh(Product, product.id)

    def test_form_renders_with_current_values(self, people, shop):
        product = shop()

        r = people['vendor'].get(f'/vendor/product/{product.id}/edit')

        assert r.status_code == 200
        assert product.title.encode() in r.data

    def test_stock_change_keeps_the_approval(self, people, shop):
        product = shop(stock=5)

        r = people['vendor'].post(f'/vendor/product/{product.id}/edit',
                                  data=self._form(product, quantity='9'))

        assert r.status_code == 302
        p = self._product(product)
        assert p.quantity == 9
        assert p.is_approved is True

    def test_content_change_goes_back_to_review(self, people, shop):
        product = shop()

        people['vendor'].post(f'/vendor/product/{product.id}/edit',
                              data=self._form(product, title='A completely new title'))

        p = self._product(product)
        assert p.title == 'A completely new title'
        assert p.is_approved is False

    @pytest.mark.parametrize('field, value', [
        ('title', 'ab'),
        ('description', 'short'),
        ('price', '-1'),
        ('price', 'free'),
        ('quantity', '-3'),
    ])
    def test_rejected_input_changes_nothing(self, people, shop, field, value):
        product = shop(price='20.00', stock=5)
        before = (product.title, product.description, product.price, product.quantity)

        r = people['vendor'].post(f'/vendor/product/{product.id}/edit',
                                  data=self._form(product, **{field: value}))

        assert r.status_code == 302
        assert r.headers['Location'].endswith(f'/vendor/product/{product.id}/edit')
        p = self._product(product)
        assert (p.title, p.description, p.price, p.quantity) == before
        assert p.is_approved is True

    def test_another_vendor_cannot_edit(self, app, shop, other_vendor):
        product = shop(price='20.00')
        intruder = login(app, other_vendor)

        assert intruder.get(f'/vendor/product/{product.id}/edit').status_code == 302
        intruder.post(f'/vendor/product/{product.id}/edit',
                      data=self._form(product, price='0.01', title='Hijacked listing'))

        p = self._product(product)
        assert p.price == Decimal('20.00')
        assert p.title != 'Hijacked listing'


class TestDeleteProduct:
    def test_vendor_deletes_their_product(self, people, shop):
        from app.models.product import Product
        product = shop()

        r = people['vendor'].post(f'/vendor/product/{product.id}/delete')

        assert r.status_code == 302
        assert fresh(Product, product.id) is None

    def test_another_vendor_cannot_delete(self, app, shop, other_vendor):
        from app.models.product import Product
        product = shop()

        login(app, other_vendor).post(f'/vendor/product/{product.id}/delete')

        assert fresh(Product, product.id) is not None

    def test_a_buyer_cannot_delete(self, people, shop):
        from app.models.product import Product
        product = shop()

        people['buyer'].post(f'/vendor/product/{product.id}/delete')

        assert fresh(Product, product.id) is not None
