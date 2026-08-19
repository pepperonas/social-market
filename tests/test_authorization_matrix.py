"""
Role x route authorization matrix.

This is the single most valuable defensive test in the suite: it walks every
protected route with every role and asserts who is turned away. Broken access
control is #1 in the OWASP Top 10 precisely because it is invisible in normal
use -- the endpoint works fine for the person who is allowed to reach it.

Adding a route without adding it here is the mistake this file exists to catch.
"""

import pytest

# Routes that must never be reachable without authentication
ANONYMOUS_MUST_BE_REDIRECTED = [
    '/vendor/dashboard',
    '/vendor/products',
    '/vendor/orders',
    '/vendor/add-product',
    '/buyer/orders',
    '/admin/dashboard',
    '/admin/users',
    '/messages/',
    '/cart/',
    '/cart/checkout',
    '/account/security',
    '/auth/profile',
    # The storefront itself is login-gated by design: this is a closed
    # marketplace, not a public shop. Pinned so the gate cannot be dropped.
    '/',
]

# (path, allowed roles) - every other authenticated role must be turned away
ROLE_RESTRICTED = [
    ('/vendor/dashboard', {'vendor'}),
    ('/vendor/products', {'vendor'}),
    ('/vendor/orders', {'vendor'}),
    ('/vendor/add-product', {'vendor'}),
    ('/admin/dashboard', {'admin'}),
    ('/admin/users', {'admin'}),
]

PUBLIC = ['/health', '/auth/login', '/auth/register']


def _login(client, user, password):
    response = client.post('/auth/login',
                           data={'username': user.username, 'password': password},
                           follow_redirects=False)
    assert response.status_code in (302, 303), f'login failed for {user.username}'


@pytest.fixture
def roles(app, sample_user, sample_vendor, sample_admin):
    return {
        'buyer': (sample_user, 'TestPassword123!'),
        'vendor': (sample_vendor, 'TestPassword123!'),
        'admin': (sample_admin, 'AdminPassword123!'),
    }


class TestAnonymousAccess:
    @pytest.mark.parametrize('path', ANONYMOUS_MUST_BE_REDIRECTED)
    def test_anonymous_is_not_served(self, client, path):
        response = client.get(path, follow_redirects=False)
        assert response.status_code in (302, 303, 401), (
            f'{path} served content to an anonymous visitor'
        )

    @pytest.mark.parametrize('path', ANONYMOUS_MUST_BE_REDIRECTED)
    def test_anonymous_is_sent_to_login(self, client, path):
        response = client.get(path, follow_redirects=False)
        location = response.headers.get('Location', '')
        assert 'login' in location, f'{path} redirected to {location!r}, not the login page'

    @pytest.mark.parametrize('path', PUBLIC)
    def test_public_routes_stay_public(self, client, path):
        assert client.get(path).status_code == 200, f'{path} should be public'


class TestRoleSeparation:
    @pytest.mark.parametrize('path,allowed', ROLE_RESTRICTED)
    @pytest.mark.parametrize('role', ['buyer', 'vendor', 'admin'])
    def test_only_allowed_roles_get_through(self, client, roles, path, allowed, role):
        user, password = roles[role]
        _login(client, user, password)

        response = client.get(path, follow_redirects=False)

        if role in allowed:
            assert response.status_code == 200, (
                f'{role} should be able to reach {path} but got {response.status_code}'
            )
        else:
            assert response.status_code in (302, 303, 403), (
                f'{role} reached {path} with {response.status_code} - '
                f'broken access control'
            )


class TestVendorApprovalGate:
    """An unapproved vendor is a vendor on paper only."""

    def test_unapproved_vendor_is_not_a_vendor(self, app, sample_vendor):
        from app import db

        sample_vendor.is_vendor_approved = False
        db.session.commit()

        assert sample_vendor.is_vendor() is False

    def test_unapproved_vendor_cannot_reach_dashboard(self, app, client, sample_vendor):
        from app import db

        sample_vendor.is_vendor_approved = False
        db.session.commit()

        _login(client, sample_vendor, 'TestPassword123!')
        response = client.get('/vendor/dashboard', follow_redirects=False)

        assert response.status_code in (302, 303, 403)

    def test_approved_vendor_can_reach_dashboard(self, app, client, sample_vendor):
        from app import db

        sample_vendor.is_vendor_approved = True
        db.session.commit()

        _login(client, sample_vendor, 'TestPassword123!')
        assert client.get('/vendor/dashboard').status_code == 200


class TestRolePredicates:
    def test_buyer_predicates(self, sample_user):
        assert sample_user.is_buyer() is True
        assert sample_user.is_vendor() is False
        assert sample_user.is_admin() is False

    def test_vendor_predicates(self, sample_vendor):
        assert sample_vendor.is_vendor() is True
        assert sample_vendor.is_admin() is False

    def test_admin_predicates(self, sample_admin):
        assert sample_admin.is_admin() is True
        assert sample_admin.is_vendor() is False

    def test_has_role(self, sample_admin):
        assert sample_admin.has_role('admin') is True
        assert sample_admin.has_role('buyer') is False
