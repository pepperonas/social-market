"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Improvement plan 2026-11, step 4: claims the code made but did not keep.

Every test here goes through HTTP, the way a user or an admin would click.

B4  Opening a dispute froze the escrow without a trace: Escrow._claim moves the
    status with a conditional UPDATE, which bypasses the ORM `after_update`
    listener that writes transaction_audit. fund/release/refund also set other
    columns, so the flush still fired the listener for them; mark_disputed()
    and cancel() change nothing but the status -- no flush, no audit row.
B5  A dispute decided for the buyer refunded the money but never returned the
    stock, even when the goods were never shipped. The admin now decides it
    explicitly in the form.
"""

import pytest
from sqlalchemy import text

from tests.test_order_lifecycle import (  # noqa: F401 (people, shop are fixtures)
    buy_now, fresh, people, shop, status, stock,
)


def _audit_actions(order):
    from app import db
    return [r[0] for r in db.session.execute(
        text('SELECT action FROM transaction_audit WHERE transaction_id = :t ORDER BY id'),
        {'t': str(order.id)})]


def _paid(people, product, quantity=1):
    order = buy_now(people['buyer'], product, quantity)
    people['buyer'].post(f'/buyer/order/{order.id}/pay')
    assert status(order) == 'paid'
    return order


# =============================================================================
# B4 -- every escrow state change leaves an audit row
# =============================================================================

class TestEscrowAuditTrail:
    def test_opening_a_dispute_is_audited(self, people, shop):
        order = _paid(people, shop())

        people['buyer'].post(f'/buyer/order/{order.id}/dispute', data={'reason': 'never arrived'})

        assert status(order) == 'disputed'
        assert 'escrow_disputed' in _audit_actions(order)

    def test_cancelling_an_unpaid_order_audits_the_escrow(self, people, shop):
        order = buy_now(people['buyer'], shop())

        people['buyer'].post(f'/buyer/order/{order.id}/cancel')

        assert status(order) == 'cancelled'
        assert 'escrow_cancelled' in _audit_actions(order)


# =============================================================================
# B5 -- a refund asks whether the stock goes back
# =============================================================================

class TestRefundStock:
    def _disputed(self, people, shop, quantity=2):
        product = shop(stock=5)
        order = _paid(people, product, quantity)
        people['buyer'].post(f'/buyer/order/{order.id}/dispute', data={'reason': 'never arrived'})
        assert stock(product) == 5 - quantity
        return product, order

    def test_refund_with_restock_returns_the_units(self, people, shop):
        product, order = self._disputed(people, shop)

        people['admin'].post(f'/admin/order/{order.id}/resolve',
                             data={'decision': 'refund', 'restock': 'on'})

        assert status(order) == 'refunded'
        assert stock(product) == 5

    def test_refund_without_restock_keeps_the_stock(self, people, shop):
        product, order = self._disputed(people, shop)

        people['admin'].post(f'/admin/order/{order.id}/resolve', data={'decision': 'refund'})

        assert status(order) == 'refunded'
        assert stock(product) == 3

    def test_release_ignores_restock(self, people, shop):
        product, order = self._disputed(people, shop)

        people['admin'].post(f'/admin/order/{order.id}/resolve',
                             data={'decision': 'release', 'restock': 'on'})

        assert status(order) == 'completed'
        assert stock(product) == 3
        from app import db
        after = db.session.execute(text(
            "SELECT after_state FROM admin_actions WHERE target_id = :t "
            "AND action = 'dispute_release'"), {'t': str(order.id)}).scalar()
        assert 'restock' in str(after) and 'false' in str(after).lower()

    def test_the_decision_is_in_the_admin_audit(self, people, shop):
        from app import db
        product, order = self._disputed(people, shop)

        people['admin'].post(f'/admin/order/{order.id}/resolve',
                             data={'decision': 'refund', 'restock': 'on'})

        row = db.session.execute(text(
            "SELECT after_state FROM admin_actions WHERE target_id = :t "
            "AND action = 'dispute_refund'"), {'t': str(order.id)}).scalar()
        assert row is not None and 'restock' in str(row) and 'true' in str(row).lower()

    def test_form_offers_the_choice_checked_for_unshipped_orders(self, people, shop):
        product, order = self._disputed(people, shop)

        html = people['admin'].get('/admin/dashboard').get_data(as_text=True)

        form = html[html.index(f'/admin/order/{order.id}/resolve'):]
        form = form[:form.index('</form>')]
        assert 'name="restock"' in form
        assert 'checked' in form[form.index('name="restock"') - 200:form.index('name="restock"') + 200]


# =============================================================================
# B7 -- the security page lists active blocks and the scan's suggestions
# =============================================================================

SUSPECT_IP = '93.184.216.35'
OTHER_IP = '93.184.216.36'


@pytest.fixture(autouse=True)
def _forget_test_addresses(app):
    """Blocks and scan findings live in the shared test DB; other modules assert an empty block list."""
    yield
    from app import db
    db.session.rollback()
    for table in ('blocked_ips', 'security_events', 'auth_log'):
        db.session.execute(text(f'DELETE FROM {table} WHERE ip_address IN (:a, :b)'),  # nosec B608 -- fixed names
                           {'a': SUSPECT_IP, 'b': OTHER_IP})
    db.session.commit()


def _admin(app, sample_admin):
    from tests.test_order_lifecycle import ADMIN_PW, login
    return login(app, sample_admin, ADMIN_PW)


def _scan_found(ip, hours_ago=0):
    """What security_scan() leaves behind: a suspicious_failed_logins event."""
    from datetime import timedelta
    from app import db
    from tests.conftest import aware_utcnow

    db.session.execute(text(
        "INSERT INTO security_events (timestamp, event_type, severity, source, ip_address, description) "
        "VALUES (:ts, 'suspicious_failed_logins', 'high', 'application', :ip, :d)"),
        {'ts': aware_utcnow() - timedelta(hours=hours_ago), 'ip': ip,
         'd': f'12 failed authentication attempts from {ip} in the last hour'})
    db.session.commit()


def _suggestion_forms(html):
    start = html.index('id="block-suggestions"')
    end = html.index('id="blocked-list"', start)
    return html[start:end]


class TestBlockList:
    def test_list_shows_who_blocked_and_until_when(self, app, sample_admin):
        from datetime import timedelta
        from app.timeutil import utcnow

        client = _admin(app, sample_admin)
        client.post('/admin/ip/block', data={'ip_address': OTHER_IP, 'reason': 'abuse', 'hours': '48'})

        html = client.get('/admin/security').get_data(as_text=True)
        row = html[html.index(f'<code>{OTHER_IP}</code>'):]
        row = row[:row.index('</tr>')]
        assert sample_admin.username in row
        assert (utcnow() + timedelta(hours=48)).strftime('%Y-%m-%d') in row


class TestBlockSuggestions:
    def test_scan_finding_is_offered_but_not_applied(self, app, sample_admin):
        from app.services.security_service import SecurityService

        _scan_found(SUSPECT_IP)
        html = _admin(app, sample_admin).get('/admin/security').get_data(as_text=True)

        forms = _suggestion_forms(html)
        assert f'value="{SUSPECT_IP}"' in forms
        assert 'admin/ip/block' in forms
        assert SecurityService.is_ip_blocked(SUSPECT_IP)[0] is False

    def test_accepting_a_suggestion_blocks(self, app, sample_admin):
        from app.services.security_service import SecurityService

        _scan_found(SUSPECT_IP)
        client = _admin(app, sample_admin)
        client.post('/admin/ip/block', data={'ip_address': SUSPECT_IP, 'hours': '24',
                                             'reason': 'security-scan: failed logins'})

        assert SecurityService.is_ip_blocked(SUSPECT_IP)[0] is True
        html = client.get('/admin/security').get_data(as_text=True)
        assert f'value="{SUSPECT_IP}"' not in _suggestion_forms(html)

    def test_old_findings_are_not_offered(self, app, sample_admin):
        _scan_found(SUSPECT_IP, hours_ago=30)

        html = _admin(app, sample_admin).get('/admin/security').get_data(as_text=True)

        assert SUSPECT_IP not in _suggestion_forms(html)

    def test_own_address_is_never_offered(self, app, sample_admin):
        from tests.test_order_lifecycle import ADMIN_PW

        _scan_found(SUSPECT_IP)
        client = app.test_client()
        client.environ_base['REMOTE_ADDR'] = SUSPECT_IP
        client.post('/auth/login', data={'username': sample_admin.username, 'password': ADMIN_PW})

        html = client.get('/admin/security').get_data(as_text=True)

        assert f'value="{SUSPECT_IP}"' not in _suggestion_forms(html)

    def test_the_scan_job_itself_never_blocks(self, app):
        from app.jobs import security_scan
        from app.services.security_service import SecurityService
        from app import db
        from tests.conftest import aware_utcnow

        for _ in range(15):
            db.session.execute(text(
                "INSERT INTO auth_log (timestamp, username, action, ip_address) "
                "VALUES (:ts, 'x', 'login_failed_password', :ip)"),
                {'ts': aware_utcnow(), 'ip': SUSPECT_IP})
        db.session.commit()

        assert SUSPECT_IP in security_scan()['suspicious_ips']
        assert SecurityService.is_ip_blocked(SUSPECT_IP)[0] is False


# =============================================================================
# B1 -- products are approved by an admin, not by the vendor's own form
# =============================================================================

def _admin_actions(target_id):
    from app import db
    return [r[0] for r in db.session.execute(
        text('SELECT action FROM admin_actions WHERE target_id = :t ORDER BY id'),
        {'t': str(target_id)})]


def _add_product(people, shop):
    import uuid
    from app.models.product import Product

    title = f'Moderated lamp {uuid.uuid4().hex[:8]}'

    people['vendor'].post('/vendor/add-product', data={
        'title': title, 'description': 'a lamp that waits for moderation',
        'price': '12.50', 'category_id': str(shop.category.id), 'quantity': '3'})
    return Product.query.filter_by(title=title).one()


def _moderate(people, product, **data):
    """Post a decision with the fingerprint the moderation page rendered, like the form does."""
    import re
    html = people['admin'].get('/admin/moderation').get_data(as_text=True)
    start = html.find(f'/admin/product/{product.id}/moderate')
    seen = None
    if start >= 0:
        form = html[start:]
        seen = re.search(r'name="fingerprint" value="([0-9a-f]+)"', form[:form.index('</form>')])
    data.setdefault('fingerprint', seen.group(1) if seen else '')
    return people['admin'].post(f'/admin/product/{product.id}/moderate', data=data)


def _set_approved_behind_the_session(product_id, value):
    """
    A commit from "someone else": bulk UPDATE that leaves loaded objects alone.

    Not raw SQL with str(id): SQLite stores these UUIDs as 32 hex digits without
    dashes, so `WHERE id = '<uuid with dashes>'` matched nothing there and the
    first version of the race test ran against a precondition that never held.
    """
    from app import db
    from app.models.product import Product
    db.session.query(Product).filter(Product.id == product_id) \
        .update({Product.is_approved: value}, synchronize_session=False)


def _product(product_id):
    from app.models.product import Product
    return fresh(Product, product_id)


class TestProductApproval:
    def test_new_product_waits_for_an_admin(self, people, shop):
        product = _add_product(people, shop)

        assert product.is_approved is False
        assert people['buyer'].get(f'/product/{product.id}').status_code == 404
        assert product.title not in people['buyer'].get('/').get_data(as_text=True)
        assert product.title in people['admin'].get('/admin/moderation').get_data(as_text=True)

    def test_vendor_and_admin_can_preview_the_pending_product(self, people, shop):
        product = _add_product(people, shop)

        for who in ('vendor', 'admin'):
            response = people[who].get(f'/product/{product.id}')
            assert response.status_code == 200, who
            assert 'not public' in response.get_data(as_text=True).lower()

    def test_pending_product_cannot_be_bought(self, people, shop):
        product = _add_product(people, shop)

        people['buyer'].post('/buyer/create-order',
                             data={'product_id': str(product.id), 'quantity': '1'})

        assert _product(product.id).quantity == 3

    def test_admin_approves(self, people, shop):
        product = _add_product(people, shop)

        _moderate(people, product, decision='approve')

        assert _product(product.id).is_approved is True
        assert people['buyer'].get(f'/product/{product.id}').status_code == 200
        assert 'product_approve' in _admin_actions(product.id)
        assert product.title not in people['admin'].get('/admin/moderation').get_data(as_text=True)

    def test_reject_needs_a_reason(self, people, shop):
        product = _add_product(people, shop)

        _moderate(people, product, decision='reject', reason=' ')

        assert _product(product.id).moderation_state == 'pending'
        assert 'product_reject' not in _admin_actions(product.id)

    def test_rejection_reaches_the_vendor(self, people, shop):
        product = _add_product(people, shop)

        _moderate(people, product, decision='reject', reason='Photos missing')

        assert _product(product.id).moderation_state == 'rejected'
        assert 'product_reject' in _admin_actions(product.id)
        assert 'Photos missing' in people['vendor'].get('/vendor/products').get_data(as_text=True)
        assert people['buyer'].get(f'/product/{product.id}').status_code == 404
        assert product.title not in people['admin'].get('/admin/moderation').get_data(as_text=True)

    def test_vendor_cannot_approve_their_own_product(self, people, shop):
        product = _add_product(people, shop)

        people['vendor'].post(f'/admin/product/{product.id}/moderate', data={'decision': 'approve'})

        assert _product(product.id).is_approved is False

    def _edit(self, people, product, **changes):
        data = {'title': product.title, 'description': product.description,
                'price': str(product.price), 'category_id': str(product.category_id),
                'quantity': str(product.quantity)}
        data.update(changes)
        people['vendor'].post(f'/vendor/product/{product.id}/edit', data=data)

    def test_changing_the_description_sends_it_back_to_review(self, people, shop):
        product = shop()

        self._edit(people, product, description='now something else entirely')

        assert _product(product.id).moderation_state == 'pending'
        assert people['buyer'].get(f'/product/{product.id}').status_code == 404

    def test_changing_only_price_and_stock_keeps_the_approval(self, people, shop):
        product = shop()

        self._edit(people, product, price='21.00', quantity='9')

        assert _product(product.id).moderation_state == 'approved'

    def test_editing_a_rejected_product_resubmits_it(self, people, shop):
        product = _add_product(people, shop)
        _moderate(people, product, decision='reject', reason='Photos missing')

        self._edit(people, _product(product.id), description='now with a better description')

        after = _product(product.id)
        assert after.moderation_state == 'pending'
        assert after.rejection_reason is None


# =============================================================================
# B2 -- reviews are approved by an admin too
# =============================================================================

class TestReviewApproval:
    def _reviewed(self, people, shop):
        from app.models.order import Order
        from app.models.product import ProductReview

        product = shop()
        order = _paid(people, product)
        people['vendor'].post(f'/vendor/order/{order.id}/ship', data={'tracking_number': 'T1'})
        people['buyer'].post(f'/buyer/order/{order.id}/confirm-delivery')
        people['buyer'].post(f'/buyer/order/{order.id}/complete')
        assert fresh(Order, order.id).status == 'completed', fresh(Order, order.id).status
        self.text = f'Review text {order.id}'
        people['buyer'].post(f'/buyer/order/{order.id}/review',
                             data={'rating': '2', 'title': 'Meh', 'review_text': self.text})
        return product, ProductReview.query.filter_by(order_id=order.id).one()

    def test_new_review_is_not_published(self, people, shop):
        product, review = self._reviewed(people, shop)

        assert review.is_approved is False
        assert self.text not in people['buyer'].get(f'/product/{product.id}').get_data(as_text=True)
        assert _product(product.id).rating_count == 0
        assert self.text in people['admin'].get('/admin/moderation').get_data(as_text=True)

    def test_approved_review_is_published_and_counted(self, people, shop):
        product, review = self._reviewed(people, shop)

        people['admin'].post(f'/admin/review/{review.id}/moderate', data={'decision': 'approve'})

        assert self.text in people['buyer'].get(f'/product/{product.id}').get_data(as_text=True)
        assert _product(product.id).rating_count == 1
        assert 'review_approve' in _admin_actions(review.id)

    def test_rejected_review_stays_hidden_and_leaves_the_queue(self, people, shop):
        product, review = self._reviewed(people, shop)

        people['admin'].post(f'/admin/review/{review.id}/moderate',
                             data={'decision': 'reject', 'reason': 'off topic'})

        assert self.text not in people['buyer'].get(f'/product/{product.id}').get_data(as_text=True)
        assert _product(product.id).rating_count == 0
        assert self.text not in people['admin'].get('/admin/moderation').get_data(as_text=True)
        assert 'review_reject' in _admin_actions(review.id)

    def test_buyer_cannot_approve_their_own_review(self, people, shop):
        from app.models.product import ProductReview
        product, review = self._reviewed(people, shop)

        people['buyer'].post(f'/admin/review/{review.id}/moderate', data={'decision': 'approve'})

        assert fresh(ProductReview, review.id).is_approved is False


class TestPublishedReviewPrivacy:
    def test_published_review_does_not_name_the_buyer(self, people, shop, sample_user):
        product, review = TestReviewApproval()._reviewed(people, shop)
        people['admin'].post(f'/admin/review/{review.id}/moderate', data={'decision': 'approve'})

        html = people['vendor'].get(f'/product/{product.id}').get_data(as_text=True)
        reviews = html[html.index('id="reviews"'):]

        assert f'Review text {review.order_id}' in reviews
        assert sample_user.username not in reviews


# =============================================================================
# B1, hardened after the security review of the first version
# =============================================================================

class TestApprovalCoversWhatTheAdminSaw:
    """
    The first version approved whatever the row held at the moment of the
    click. Two ways to get unseen content approved: the vendor edits while the
    admin has the queue open, or swaps the images after approval.
    """

    def test_content_changed_after_the_queue_was_opened_is_not_approved(self, people, shop):
        import re
        product = _add_product(people, shop)
        html = people['admin'].get('/admin/moderation').get_data(as_text=True)
        form = html[html.index(f'/admin/product/{product.id}/moderate'):]
        seen = re.search(r'name="fingerprint" value="([0-9a-f]+)"', form).group(1)

        TestProductApproval()._edit(people, _product(product.id),
                                    description='swapped after the admin looked')
        people['admin'].post(f'/admin/product/{product.id}/moderate',
                             data={'decision': 'approve', 'fingerprint': seen})

        assert _product(product.id).moderation_state == 'pending'
        assert 'product_approve' not in _admin_actions(product.id)

    def test_image_added_after_the_queue_was_opened_is_not_approved(self, people, shop):
        import re
        from tests.test_upload_images import jpeg_with_gps, upload
        product = _add_product(people, shop)
        html = people['admin'].get('/admin/moderation').get_data(as_text=True)
        form = html[html.index(f'/admin/product/{product.id}/moderate'):]
        seen = re.search(r'name="fingerprint" value="([0-9a-f]+)"', form).group(1)

        upload(people['vendor'], product, jpeg_with_gps(), 'late.jpg')
        people['admin'].post(f'/admin/product/{product.id}/moderate',
                             data={'decision': 'approve', 'fingerprint': seen})

        assert _product(product.id).moderation_state == 'pending'

    def test_decision_without_fingerprint_is_refused(self, people, shop):
        product = _add_product(people, shop)

        people['admin'].post(f'/admin/product/{product.id}/moderate', data={'decision': 'approve'})

        assert _product(product.id).moderation_state == 'pending'

    def test_only_pending_products_can_be_decided(self, people, shop):
        product = _add_product(people, shop)
        _moderate(people, product, decision='reject', reason='Photos missing')

        fingerprint = _product(product.id).content_fingerprint()
        people['admin'].post(f'/admin/product/{product.id}/moderate',
                             data={'decision': 'approve', 'fingerprint': fingerprint})

        assert _product(product.id).moderation_state == 'rejected'

    def test_new_image_sends_an_approved_product_back_to_review(self, people, shop):
        from tests.test_upload_images import jpeg_with_gps, upload
        product = shop()

        upload(people['vendor'], product, jpeg_with_gps(), 'swap.jpg')

        assert _product(product.id).moderation_state == 'pending'

    def test_deleting_an_image_sends_it_back_too(self, people, shop):
        from app import db
        from app.models.product import ProductImage
        from tests.test_upload_images import jpeg_with_gps, upload
        product = shop()
        upload(people['vendor'], product, jpeg_with_gps(), 'one.jpg')
        _set_approved_behind_the_session(product.id, True)
        db.session.commit()
        assert _product(product.id).moderation_state == 'approved'
        image = ProductImage.query.filter_by(product_id=product.id).one()

        people['vendor'].post(f'/vendor/product/{product.id}/delete-image/{image.id}')

        assert _product(product.id).moderation_state == 'pending'

    def test_edit_racing_an_approval_ends_pending(self, shop):
        """
        Vendor reads `pending`, admin approves and commits, vendor writes its
        edit. SQLAlchemy writes changed columns only; is_approved=False on an
        object that already believed False is no change -- the approval would
        survive the edit. submit_for_review() must write it regardless.
        """
        from app import db
        from app.models.product import Product

        product = shop()
        _set_approved_behind_the_session(product.id, False)
        db.session.commit()
        vendor_view = fresh(Product, product.id)
        assert vendor_view.is_approved is False

        _set_approved_behind_the_session(product.id, True)  # the admin's commit, unseen by vendor_view
        vendor_view.description = 'edited while the admin approved'
        vendor_view.submit_for_review()
        db.session.commit()

        assert _product(product.id).is_approved is False


class TestFingerprintIsUnambiguous:
    def test_moving_text_between_fields_changes_the_fingerprint(self, shop):
        """The first version joined fields with \\x1f; a vendor could move text across that seam."""
        product = shop()
        product.title, product.description = 'Lamp', 'nice\x1fbright'
        first = product.content_fingerprint()

        product.title, product.description = 'Lamp\x1fnice', 'bright'

        assert product.content_fingerprint() != first
