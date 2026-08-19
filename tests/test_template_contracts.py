"""
Templates must only reference names the route actually provides.

Jinja's default Undefined renders a missing name as an empty string. That is
convenient and it is why several features shipped broken and invisible:

  * `product.active` -- the column is `is_active`, so every product showed
    "Inactive"
  * `order.status_color` -- never defined, so every badge rendered as bare "bg-"
  * `recent_users`, `recent_orders`, `security_alerts`, `stats.active_products`,
    `stats.pending_orders` -- dashboard panels that silently stayed empty
  * `product.shipping_info` -- a block that could never display

None of these raised. The pages looked fine; they were just missing their data.
The application keeps the lenient default (a stray reference should not 500 a
visitor), but `create_app` switches Jinja to StrictUndefined under TESTING, so
the suite refuses to let one through.
"""

import pathlib
import re

import pytest

TEMPLATES = pathlib.Path('app/templates')


def _login(client, user, password='TestPassword123!'):
    response = client.post('/auth/login',
                           data={'username': user.username, 'password': password},
                           follow_redirects=False)
    assert response.status_code in (302, 303)


class TestStrictUndefinedIsActive:
    def test_testing_uses_strict_undefined(self, app):
        from jinja2 import StrictUndefined

        assert app.jinja_env.undefined is StrictUndefined, (
            'tests must fail on undefined template names, not render them blank'
        )

    def test_strict_undefined_is_gated_on_testing(self):
        """
        Production must keep the lenient default.

        Checked at the source rather than by building a non-testing app:
        config.py reads DATABASE_URL when the class body runs, so a test cannot
        point a second app at SQLite after import -- the same import-time trap
        that TRUSTED_PROXY_COUNT hit. Asserting the guard exists is the honest
        thing this test can actually prove.
        """
        import re

        source = pathlib.Path('app/__init__.py').read_text()
        source = re.sub(r'#.*', '', source)  # comments here mention the setting

        match = re.search(
            r"if app\.config\.get\('TESTING'\):\s*\n\s*from jinja2 import StrictUndefined"
            r"\s*\n\s*app\.jinja_env\.undefined = StrictUndefined",
            source,
        )
        assert match, (
            'StrictUndefined must be applied only under TESTING; a stray '
            'reference should not 500 a page for a visitor'
        )

    def test_a_missing_name_really_raises(self, app):
        from jinja2 import UndefinedError

        with pytest.raises(UndefinedError):
            app.jinja_env.from_string('{{ nope.attribute }}').render()


class TestDashboardsRenderCompletely:
    """Each of these panels was blank because its variable was never passed."""

    def test_admin_dashboard(self, client, sample_admin):
        _login(client, sample_admin, 'AdminPassword123!')
        assert client.get('/admin/dashboard').status_code == 200

    def test_vendor_dashboard(self, client, sample_vendor):
        _login(client, sample_vendor)
        assert client.get('/vendor/dashboard').status_code == 200

    def test_vendor_products(self, client, sample_vendor):
        _login(client, sample_vendor)
        assert client.get('/vendor/products').status_code == 200

    def test_vendor_orders(self, client, sample_vendor):
        _login(client, sample_vendor)
        assert client.get('/vendor/orders').status_code == 200

    def test_buyer_orders(self, client, sample_user):
        _login(client, sample_user)
        assert client.get('/buyer/orders').status_code == 200

    def test_marketplace_and_search(self, client, sample_user):
        _login(client, sample_user)
        assert client.get('/').status_code == 200
        assert client.get('/search').status_code == 200

    def test_account_pages(self, client, sample_user):
        _login(client, sample_user)
        assert client.get('/account/security').status_code == 200

    def test_messages_inbox(self, client, sample_user):
        _login(client, sample_user)
        assert client.get('/messages/').status_code == 200


class TestNoKnownBadReferences:
    """Static guards for the specific typos found, so they cannot return."""

    @pytest.mark.parametrize('bad,good', [
        ('product.active', 'product.is_active'),
        ('product.approved', 'product.is_approved'),
        ('product.shipping_info', '(does not exist)'),
        ('product.images[0]', 'product.primary_image_url'),
    ])
    def test_reference_is_gone(self, bad, good):
        offenders = []
        for path in TEMPLATES.rglob('*.html'):
            # Strip Jinja comments: this project documents removed code verbatim
            text = re.sub(r'\{#.*?#\}', '', path.read_text(), flags=re.S)
            if bad in text:
                offenders.append(path.name)

        assert not offenders, f'{bad} still used in {offenders} -- use {good}'

    def test_status_color_exists_on_the_model(self):
        """The templates render bg-{{ order.status_color }}."""
        from app.models.order import Order

        assert isinstance(getattr(Order, 'status_color', None), property)

    @pytest.mark.parametrize('status,expected', [
        ('pending', 'secondary'),
        ('completed', 'success'),
        ('disputed', 'warning'),
        ('refunded', 'danger'),
    ])
    def test_status_color_values(self, status, expected):
        from app.models.order import Order

        order = Order()
        order.status = status
        assert order.status_color == expected

    def test_unknown_status_falls_back(self):
        from app.models.order import Order

        order = Order()
        order.status = 'something-new'
        assert order.status_color == 'secondary', 'must not render a bare bg- class'
