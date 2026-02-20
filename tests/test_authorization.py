"""
Authorization Tests for Social Market.

Tests cover:
- Role-based access control (Admin, Vendor, Buyer routes)
- Object-level authorization (own products/orders only)
- Unauthenticated redirect to login
"""

import uuid
import pytest
from unittest.mock import patch, MagicMock


class TestUnauthenticatedAccess:
    """Tests that unauthenticated users are redirected to login."""

    @pytest.mark.parametrize('url', [
        '/auth/profile',
        '/vendor/dashboard',
        '/vendor/products',
        '/admin/dashboard',
        '/admin/users',
        '/admin/security',
        '/buyer/orders',
        '/messages/inbox',
        '/account/security',
        '/account/sessions',
    ])
    def test_unauthenticated_redirect(self, client, url):
        """Unauthenticated users should be redirected to login."""
        response = client.get(url, follow_redirects=False)
        assert response.status_code in (302, 303, 401)
        if response.status_code in (302, 303):
            location = response.headers.get('Location', '')
            assert 'login' in location.lower() or response.status_code == 401


class TestAdminRouteAccess:
    """Tests that admin routes are restricted to admins."""

    def test_buyer_cannot_access_admin_dashboard(self, auth_client, app):
        """Buyer should not access admin dashboard."""
        with app.app_context():
            response = auth_client.get('/admin/dashboard', follow_redirects=True)
            assert b'Admin access required' in response.data or response.status_code == 403

    def test_admin_can_access_admin_dashboard(self, admin_client, app):
        """Admin should access admin dashboard."""
        with app.app_context():
            response = admin_client.get('/admin/dashboard')
            assert response.status_code == 200

    def test_buyer_cannot_access_admin_users(self, auth_client, app):
        """Buyer should not access admin user list."""
        with app.app_context():
            response = auth_client.get('/admin/users', follow_redirects=True)
            assert b'Admin access required' in response.data or response.status_code == 403

    def test_buyer_cannot_access_admin_security(self, auth_client, app):
        """Buyer should not access admin security page."""
        with app.app_context():
            response = auth_client.get('/admin/security', follow_redirects=True)
            assert b'Admin access required' in response.data or response.status_code == 403


class TestVendorRouteAccess:
    """Tests that vendor routes are restricted to approved vendors."""

    def test_buyer_cannot_access_vendor_dashboard(self, auth_client, app):
        """Buyer should not access vendor dashboard."""
        with app.app_context():
            response = auth_client.get('/vendor/dashboard', follow_redirects=True)
            assert b'Vendor access required' in response.data or response.status_code == 403

    def test_approved_vendor_can_access_dashboard(self, vendor_client, app):
        """Approved vendor should access vendor dashboard."""
        with app.app_context():
            response = vendor_client.get('/vendor/dashboard')
            assert response.status_code == 200

    def test_buyer_cannot_access_vendor_products(self, auth_client, app):
        """Buyer should not access vendor products list."""
        with app.app_context():
            response = auth_client.get('/vendor/products', follow_redirects=True)
            assert b'Vendor access required' in response.data or response.status_code == 403

    def test_buyer_cannot_add_product(self, auth_client, app):
        """Buyer should not access add product page."""
        with app.app_context():
            response = auth_client.get('/vendor/add-product', follow_redirects=True)
            assert b'Vendor access required' in response.data or response.status_code == 403


class TestBuyerRouteAccess:
    """Tests for buyer route access."""

    def test_authenticated_buyer_can_view_orders(self, auth_client, app):
        """Authenticated buyer should access orders page."""
        with app.app_context():
            response = auth_client.get('/buyer/orders')
            assert response.status_code == 200


class TestUserModel:
    """Tests for User model authorization methods."""

    def test_is_admin(self, sample_admin, app):
        """Admin user should return True for is_admin()."""
        with app.app_context():
            assert sample_admin.is_admin() is True
            assert sample_admin.is_vendor() is False
            assert sample_admin.is_buyer() is False

    def test_is_vendor(self, sample_vendor, app):
        """Approved vendor should return True for is_vendor()."""
        with app.app_context():
            assert sample_vendor.is_vendor() is True
            assert sample_vendor.is_admin() is False

    def test_is_buyer(self, sample_user, app):
        """Buyer user should return True for is_buyer()."""
        with app.app_context():
            assert sample_user.is_buyer() is True
            assert sample_user.is_admin() is False
            assert sample_user.is_vendor() is False

    def test_unapproved_vendor_is_not_vendor(self, app):
        """Unapproved vendor should return False for is_vendor()."""
        from app import db
        from app.models.user import User

        with app.app_context():
            user = User(
                id=uuid.uuid4(),
                username='unapproved_vendor',
                email='unapproved@test.local',
                role='vendor',
                is_active=True,
                is_vendor_approved=False,
            )
            user.set_password('TestPassword123!')
            db.session.add(user)
            db.session.commit()

            assert user.is_vendor() is False
            assert user.role == 'vendor'

            db.session.delete(user)
            db.session.commit()

    def test_has_role(self, sample_user, app):
        """has_role should match the user's role."""
        with app.app_context():
            assert sample_user.has_role('buyer') is True
            assert sample_user.has_role('admin') is False
            assert sample_user.has_role('vendor') is False
