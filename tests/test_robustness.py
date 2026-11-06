"""
Review round 3 (2026-11), step 6: P2 robustness and hygiene.

Each class pins one finding from docs/REVIEW-2026-11.md, section P2.
"""

import re
import uuid
from unittest.mock import patch

import pyotp

USER_PW = 'TestPassword123!'
ADMIN_PW = 'AdminPassword123!'


def login(app, user, password=USER_PW, **query):
    client = app.test_client()
    url = '/auth/login' + (f"?next={query['next']}" if 'next' in query else '')
    return client, client.post(url, data={'username': user.username, 'password': password})


class TestInvalidUuidsFindNothing:
    """
    A non-UUID string reached PostgreSQL as is: DataError, a 500, for
    ?category=abc or a tampered product_id. SQLite compares strings and never
    showed it, so the type itself is what is checked.
    """

    def test_bind_param_turns_garbage_into_the_nil_uuid(self):
        from app.models.types import UUID

        bind = UUID().process_bind_param
        assert bind('abc', None) == uuid.UUID(int=0)
        assert bind('../../etc', None) == uuid.UUID(int=0)

    def test_real_values_pass_through(self):
        from app.models.types import UUID

        value = uuid.uuid4()
        bind = UUID().process_bind_param
        assert bind(value, None) == value
        assert bind(str(value), None) == value
        assert bind(None, None) is None

    def test_search_with_garbage_category_is_fine(self, app, sample_user):
        client, _ = login(app, sample_user)

        assert client.get('/search?category=abc').status_code == 200


class TestInternalErrorsStayInternal:
    """f'Error ...: {str(e)}' put database messages -- SQL, constraint names -- on the page."""

    def test_buyer_route_shows_a_generic_message(self, app, sample_user, sample_vendor,
                                                 monkeypatch):
        from decimal import Decimal

        from app import db
        from app.models.order import Order
        from app.models.product import Product, ProductCategory

        cat = ProductCategory(id=uuid.uuid4(), name=f'r{uuid.uuid4().hex[:6]}',
                              slug=f'r{uuid.uuid4().hex[:6]}')
        db.session.add(cat)
        db.session.flush()
        product = Product(id=uuid.uuid4(), vendor_id=sample_vendor.id, category_id=cat.id,
                          title='t', description='d' * 12, price=Decimal('5'), quantity=5,
                          is_active=True, is_approved=True)
        order = Order(id=uuid.uuid4(), buyer_id=sample_user.id, vendor_id=sample_vendor.id,
                      product_id=product.id, quantity=1, unit_price=Decimal('5'), status='paid')
        db.session.add_all([product, order])
        db.session.commit()

        def boom(self, *a, **kw):
            raise RuntimeError('relation "orders" violates constraint secret_internal_name')
        monkeypatch.setattr(Order, 'open_dispute', boom)

        client, _ = login(app, sample_user)
        html = client.post(f'/buyer/order/{order.id}/dispute', data={'reason': 'x'},
                           follow_redirects=True).get_data(as_text=True)

        assert 'secret_internal_name' not in html
        assert 'Something went wrong while opening the dispute' in html


class TestAuditLogPaging:
    def test_page_below_one_never_gives_a_negative_offset(self, app, sample_admin):
        """SQLite accepts a negative OFFSET; PostgreSQL raises. So the bound value is checked."""
        from app import db

        offsets = []
        real = db.session.execute

        def spy(statement, params=None, *a, **kw):
            if params and 'offset' in params:
                offsets.append(params['offset'])
            return real(statement, params, *a, **kw)

        client, _ = login(app, sample_admin, ADMIN_PW)
        with patch.object(db.session, 'execute', side_effect=spy):
            client.get('/admin/audit-logs?page=-3')

        assert offsets and min(offsets) >= 0


class TestHeaders:
    def test_no_invalid_cors_value_and_no_duplicate_nosniff(self, client):
        response = client.get('/auth/login')

        assert response.headers.get('Access-Control-Allow-Origin') != 'self'
        assert response.headers.getlist('X-Content-Type-Options') == ['nosniff']

    def test_client_cannot_choose_the_request_id(self, client):
        forged = 'x\r\nSet-Cookie: evil=1'
        response = client.get('/auth/login', headers={'X-Request-ID': forged[:1] + 'abc$%'})

        assert re.fullmatch(r'[0-9a-f]{32}', response.headers['X-Request-ID'])

    def test_upstream_request_id_is_kept(self, client):
        rid = uuid.uuid4().hex
        assert client.get('/auth/login', headers={'X-Request-ID': rid}).headers['X-Request-ID'] == rid


class TestLogout:
    def test_logout_by_get_is_not_possible(self, app, sample_user):
        """An <img src="/auth/logout"> on any page used to log the visitor out."""
        client, _ = login(app, sample_user)

        assert client.get('/auth/logout').status_code == 405
        assert client.get('/auth/profile').status_code == 200

    def test_logout_by_post_works(self, app, sample_user):
        client, _ = login(app, sample_user)
        client.post('/auth/logout')

        assert client.get('/auth/profile').status_code == 302

    def test_cancel_on_the_2fa_page_clears_the_pending_login(self, app, sample_user):
        from app import db
        from tests.conftest import reload_user

        user = reload_user(sample_user.id)
        user.two_factor_secret = pyotp.random_base32()
        user.two_factor_enabled = True
        db.session.commit()

        client, _ = login(app, sample_user)
        client.post('/auth/logout')

        with client.session_transaction() as sess:
            assert 'pending_2fa_user_id' not in sess


class TestNextSurvivesLogin:
    def test_form_keeps_next(self, client):
        html = client.get('/auth/login?next=/cart/').get_data(as_text=True)

        assert 'action="/auth/login?next=/cart/"' in html

    def test_login_goes_to_next(self, app, sample_user):
        _, response = login(app, sample_user, next='/cart/')

        assert response.headers['Location'].endswith('/cart/')

    def test_next_survives_2fa(self, app, sample_user):
        from app import db
        from tests.conftest import reload_user

        secret = pyotp.random_base32()
        user = reload_user(sample_user.id)
        user.two_factor_secret = secret
        user.two_factor_enabled = True
        db.session.commit()

        client, _ = login(app, sample_user, next='/cart/')
        with patch('app.routes.auth._log_auth_event'):
            response = client.post('/auth/verify-2fa', data={'token': pyotp.TOTP(secret).now()})

        assert response.headers['Location'].endswith('/cart/')

    def test_foreign_next_is_ignored(self, app, sample_user):
        _, response = login(app, sample_user, next='https://evil.example/')

        assert 'evil.example' not in response.headers['Location']


class TestUsernamesIgnoreCase:
    def test_cannot_register_a_case_variant(self, client, sample_user):
        """'Admin' next to 'admin' is a ready-made impersonation."""
        from app.models.user import User

        response = client.post('/auth/register', data={
            'username': sample_user.username.upper(), 'email': f'{uuid.uuid4().hex[:8]}@x.local',
            'password': 'Some-Long-Passw0rd!', 'password_confirm': 'Some-Long-Passw0rd!',
            'role': 'buyer', 'terms_accepted': 'on'})

        assert response.status_code == 400
        assert User.query.filter_by(username=sample_user.username.upper()).count() == 0

    def test_login_ignores_case(self, app, sample_user):
        client = app.test_client()
        response = client.post('/auth/login', data={
            'username': sample_user.username.upper(), 'password': USER_PW})

        assert response.status_code == 302
        assert client.get('/auth/profile').status_code == 200


class TestViewsCountOncePerSession:
    def test_reloading_does_not_inflate_views(self, app, sample_user, sample_vendor):
        from decimal import Decimal

        from app import db
        from app.models.product import Product, ProductCategory

        cat = ProductCategory(id=uuid.uuid4(), name=f'v{uuid.uuid4().hex[:6]}',
                              slug=f'v{uuid.uuid4().hex[:6]}')
        db.session.add(cat)
        db.session.flush()
        product = Product(id=uuid.uuid4(), vendor_id=sample_vendor.id, category_id=cat.id,
                          title='viewed', description='d' * 12, price=Decimal('5'), quantity=5,
                          is_active=True, is_approved=True, views=0)
        db.session.add(product)
        db.session.commit()

        client, _ = login(app, sample_user)
        for _ in range(5):
            client.get(f'/product/{product.id}')

        db.session.expire_all()
        assert db.session.get(Product, product.id).views == 1
