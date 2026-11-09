"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Improvement plan 2026-11, step 6 (C5): one browser run through the whole shop.

The HTTP tests post form fields directly. They cannot see what only a browser
sees: a button that is not rendered, a form without its CSRF token, a script
the Content-Security-Policy blocks. Review round 3 found exactly that kind of
defect (K1: the payment step existed in the code but no page offered it).

This test starts the application on a local port and clicks through it in
headless Chromium, with CSRF protection switched ON:

    register -> log in -> order -> pay -> vendor ships -> buyer confirms
    delivery -> buyer completes

and fails on any CSP violation, any uncaught page error and any console error
on the way.

Opt-in, because it needs a browser:
    pip install playwright && python -m playwright install chromium
    BROWSER_TESTS=1 pytest tests/test_browser_smoke.py
"""

import os
import threading
import uuid

import pytest

if os.environ.get('BROWSER_TESTS') != '1':
    pytest.skip('browser smoke test: set BROWSER_TESTS=1', allow_module_level=True)

sync_playwright = pytest.importorskip('playwright.sync_api').sync_playwright

from tests.test_order_lifecycle import BUYER_PW, fresh, shop  # noqa: E402,F401 (shop is a fixture)

BUYER_NEW_PW = 'Smoke-Test-Passphrase-2026!'

# Recorded before any page script runs. Playwright injects init scripts through
# the DevTools protocol, so the page's own CSP does not apply to this one.
RECORD_CSP = """
window.__csp = [];
document.addEventListener('securitypolicyviolation', e => {
  window.__csp.push(e.violatedDirective + ' ' + (e.blockedURI || 'inline'));
});
"""


@pytest.fixture
def shop_url(app, monkeypatch):  # not `live_server`: pytest-flask owns that name
    """The test application on a free local port, CSRF protection on."""
    from werkzeug.serving import make_server

    server = make_server('127.0.0.1', 0, app, threaded=False)
    port = server.server_port
    # Routing matches the Host header against SERVER_NAME, port included.
    monkeypatch.setitem(app.config, 'SERVER_NAME', f'localhost:{port}')
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://localhost:{port}'
    finally:
        server.shutdown()
        thread.join(5)


class Watched:
    """A page whose CSP violations, page errors and console errors are kept."""

    def __init__(self, context, name):
        self.name = name
        self.page = context.new_page()
        self.problems = []
        self.page.on('pageerror', lambda e: self.problems.append(f'{name} pageerror: {e}'))
        self.page.on('console', self._console)

    def _console(self, msg):
        # The browser asks for /favicon.ico on its own; the app has none.
        if msg.type == 'error' and 'favicon' not in msg.text:
            self.problems.append(f'{self.name} console: {msg.text}')

    def check(self):
        """Collect the CSP violations of the page currently shown."""
        for v in self.page.evaluate('window.__csp || []'):
            self.problems.append(f'{self.name} CSP on {self.page.url}: {v}')
        self.page.evaluate('window.__csp = []')

    def goto(self, url):
        response = self.page.goto(url)
        assert response.status == 200, f'{self.name}: {url} -> {response.status}'
        self.check()

    def submit(self, button):
        """Click a submit button and wait for the page it leads to."""
        with self.page.expect_navigation():
            self.page.locator(button).click()
        self.check()

    def flash(self):
        return self.page.locator('.alert').all_inner_texts()


def _order_of(username):
    from app.models.order import Order
    from app.models.user import User

    buyer = User.query.filter_by(username=username).one()
    return Order.query.filter_by(buyer_id=buyer.id).one()


def _status(order):
    from app.models.order import Order
    return fresh(Order, order.id).status


def test_register_order_pay_ship_complete(shop_url, shop, sample_vendor):
    product = shop(price='12.50', stock=3)
    username = f'smoke_{uuid.uuid4().hex[:8]}'

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            buyer_ctx = browser.new_context()
            vendor_ctx = browser.new_context()
            for ctx in (buyer_ctx, vendor_ctx):
                ctx.add_init_script(RECORD_CSP)
            buyer = Watched(buyer_ctx, 'buyer')
            vendor = Watched(vendor_ctx, 'vendor')
            b = buyer.page

            # Register through the form, the honeypot field left empty.
            buyer.goto(f'{shop_url}/auth/register')
            b.fill('#username', username)
            b.fill('#email', f'{username}@smoke.local')
            b.fill('#password', BUYER_NEW_PW)
            b.fill('#password_confirm', BUYER_NEW_PW)
            b.select_option('#role', 'buyer')
            b.check('#terms_accepted')
            buyer.submit('button:has-text("Register")')
            assert '/auth/login' in b.url, buyer.flash()

            b.fill('#username', username)
            b.fill('#password', BUYER_NEW_PW)
            buyer.submit('button:has-text("Login")')
            assert '/auth/login' not in b.url, buyer.flash()

            # Order from the product page.
            buyer.goto(f'{shop_url}/product/{product.id}')
            buyer.submit('button:has-text("Place Order")')
            order = _order_of(username)
            assert _status(order) == 'pending'

            # The order page offers the payment step (K1).
            buyer.goto(f'{shop_url}/buyer/order/{order.id}')
            buyer.submit(f'form[action$="/order/{order.id}/pay"] button[type=submit]')
            assert _status(order) == 'paid', buyer.flash()

            # The vendor ships it.
            vendor.goto(f'{shop_url}/auth/login')
            vendor.page.fill('#username', sample_vendor.username)
            vendor.page.fill('#password', BUYER_PW)
            vendor.submit('button:has-text("Login")')
            vendor.goto(f'{shop_url}/vendor/order/{order.id}')
            vendor.page.fill('#tracking_number', 'SMOKE-TRACK-1')
            vendor.submit(f'form[action$="/order/{order.id}/ship"] button[type=submit]')
            assert _status(order) == 'shipped', vendor.flash()

            # The buyer confirms delivery, then completes.
            buyer.goto(f'{shop_url}/buyer/order/{order.id}')
            buyer.submit(f'form[action$="/order/{order.id}/confirm-delivery"] button[type=submit]')
            assert _status(order) == 'delivered', buyer.flash()
            buyer.submit(f'form[action$="/order/{order.id}/complete"] button[type=submit]')
            assert _status(order) == 'completed', buyer.flash()

            problems = buyer.problems + vendor.problems
        finally:
            browser.close()

    assert problems == []


# =============================================================================
# The things the CSP blocked (found by the run above, see test_templates_csp.py)
# =============================================================================

@pytest.fixture
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        try:
            yield b
        finally:
            b.close()


def _logged_in(browser, base, user, password, name):
    ctx = browser.new_context(accept_downloads=True)
    ctx.add_init_script(RECORD_CSP)
    w = Watched(ctx, name)
    w.goto(f'{base}/auth/login')
    w.page.fill('#username', user.username)
    w.page.fill('#password', password)
    w.submit('button:has-text("Login")')
    assert '/auth/login' not in w.page.url, w.flash()
    return w


def test_password_can_be_changed_in_the_browser(shop_url, browser, sample_user):
    """The submit button starts disabled; only the page script enables it."""
    from app.models.user import User
    w = _logged_in(browser, shop_url, sample_user, BUYER_PW, 'buyer')
    new = 'Another-Smoke-Passphrase-77!'

    w.goto(f'{shop_url}/account/change-password')
    w.page.fill('#current_password', BUYER_PW)
    w.page.fill('#new_password', new)
    w.page.fill('#confirm_password', new)
    assert w.page.locator('#submitBtn').is_enabled(), 'button stays disabled: the page script did not run'
    w.submit('#submitBtn')

    assert fresh(User, sample_user.id).check_password(new), w.flash()
    assert w.problems == []


def test_password_toggle_reveals_the_field(shop_url, browser, sample_user):
    w = _logged_in(browser, shop_url, sample_user, BUYER_PW, 'buyer')
    w.goto(f'{shop_url}/account/change-password')

    w.page.locator('[data-toggle-password="current_password"]').click()

    assert w.page.locator('#current_password').get_attribute('type') == 'text'
    assert w.problems == []


@pytest.mark.parametrize('answer, survives', [('dismiss', True), ('accept', False)])
def test_deleting_a_product_asks_first(shop_url, browser, shop, sample_vendor, answer, survives):
    from app.models.product import Product
    product = shop()
    w = _logged_in(browser, shop_url, sample_vendor, BUYER_PW, 'vendor')
    asked = []

    def on_dialog(dialog):
        asked.append(dialog.message)
        getattr(dialog, answer)()

    w.page.on('dialog', on_dialog)
    w.goto(f'{shop_url}/vendor/products')
    button = w.page.locator(f'form[action$="/product/{product.id}/delete"] button[type=submit]')
    if survives:
        button.click()
        w.page.wait_for_timeout(300)  # a submit would navigate; give it the chance
    else:
        with w.page.expect_navigation():
            button.click()

    assert asked, 'no confirmation dialog: the handler did not run'
    assert (fresh(Product, product.id) is not None) is survives
    assert w.problems == []


def test_export_my_data_link_downloads(shop_url, browser, sample_user):
    w = _logged_in(browser, shop_url, sample_user, BUYER_PW, 'buyer')
    w.goto(f'{shop_url}/account/security')

    with w.page.expect_download(timeout=5000) as dl:
        w.page.locator('a:has-text("Export My Data")').click()

    assert dl.value.suggested_filename.startswith('data_export_')
    assert w.problems == []


def test_cart_quantity_submits_on_change(shop_url, browser, shop, sample_user):
    from app.models.cart import Cart
    from app.models.user import User
    product = shop(stock=10)
    w = _logged_in(browser, shop_url, sample_user, BUYER_PW, 'buyer')
    # No page offers "add to cart" (an open finding, see the plan), so the item
    # is put in directly; the quantity field on the cart page is what is tested.
    from app import db
    Cart.get_or_create(sample_user.id).add_item(product.id, 1)
    db.session.commit()
    w.goto(f'{shop_url}/cart/')

    field = w.page.locator('input[name=quantity][data-autosubmit]').first
    with w.page.expect_navigation():
        field.fill('3')
        field.dispatch_event('change')

    cart = Cart.query.filter_by(user_id=fresh(User, sample_user.id).id).one()
    assert [item.quantity for item in cart.items] == [3], w.flash()
    assert w.problems == []
