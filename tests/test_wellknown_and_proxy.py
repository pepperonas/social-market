"""
Tests for security.txt (RFC 9116), robots.txt, and reverse-proxy handling.

Two real defects motivated this file:

1. The footer linked /.well-known/security.txt from day one and the file never
   existed. A 404 there tells a would-be reporter that nobody is listening.
2. Behind nginx, request.remote_addr was always 127.0.0.1, so the rate limiter
   put every visitor in one bucket and every audit entry recorded the proxy
   rather than the client.
"""

import re

import pytest


class TestSecurityTxt:
    """RFC 9116 requires Contact and Expires; everything else is optional."""

    @pytest.fixture
    def body(self, client):
        response = client.get('/.well-known/security.txt')
        assert response.status_code == 200, 'the footer links here; it must exist'
        return response.get_data(as_text=True)

    def test_is_plain_text(self, client):
        response = client.get('/.well-known/security.txt')
        assert response.mimetype == 'text/plain'

    def test_has_contact_field(self, body):
        assert re.search(r'^Contact:\s*\S+', body, re.M), 'Contact is mandatory (RFC 9116)'

    def test_has_expires_field(self, body):
        assert re.search(r'^Expires:\s*\S+', body, re.M), 'Expires is mandatory (RFC 9116)'

    def test_expires_is_in_the_future(self, body):
        from datetime import datetime, timezone

        raw = re.search(r'^Expires:\s*(\S+)', body, re.M).group(1)
        expires = datetime.fromisoformat(raw.replace('Z', '+00:00'))

        assert expires > datetime.now(timezone.utc), (
            'an expired security.txt is treated as invalid by scanners'
        )

    def test_expires_within_a_year(self, body):
        """RFC 9116 recommends no more than a year out, so it gets revisited."""
        from datetime import datetime, timezone, timedelta

        raw = re.search(r'^Expires:\s*(\S+)', body, re.M).group(1)
        expires = datetime.fromisoformat(raw.replace('Z', '+00:00'))

        assert expires < datetime.now(timezone.utc) + timedelta(days=400)

    def test_points_at_the_security_policy(self, body):
        assert 'SECURITY.md' in body

    def test_states_that_credentials_are_public(self, body):
        """Saves a reporter the trouble of filing 'default credentials'."""
        assert 'public' in body.lower()

    def test_robots_disallows_everything(self, client):
        body = client.get('/robots.txt').get_data(as_text=True)

        assert 'User-agent: *' in body
        assert 'Disallow: /' in body


class TestExternalLinksOpenSafely:
    """
    Links that leave the app open in a new tab -- and must carry rel=noopener,
    otherwise the opened page can reach back via window.opener (tabnabbing).
    """

    def _footer_links(self):
        import pathlib

        html = pathlib.Path('app/templates/base.html').read_text()
        return re.findall(r'<a\s[^>]*>', html)

    def test_blank_targets_exist(self):
        assert any('target="_blank"' in tag for tag in self._footer_links())

    def test_every_blank_target_has_noopener(self):
        offenders = [
            tag for tag in self._footer_links()
            if 'target="_blank"' in tag and 'noopener' not in tag
        ]
        assert not offenders, f'target=_blank without rel=noopener: {offenders}'

    def test_every_external_link_is_blank(self):
        import pathlib

        offenders = []
        for path in pathlib.Path('app/templates').rglob('*.html'):
            for tag in re.findall(r'<a\s[^>]*href="https?://[^"]+"[^>]*>', path.read_text()):
                if 'target="_blank"' not in tag:
                    offenders.append(f'{path.name}: {tag[:70]}')

        assert not offenders, f'external links should open in a new tab: {offenders}'


class TestProxyTrust:
    """
    ProxyFix must be opt-in. X-Forwarded-For is client-controlled, so trusting
    it without a configured hop count would let anyone forge their source IP --
    worse than the bug it fixes.
    """

    def test_disabled_by_default(self, app):
        assert app.config.get('TRUSTED_PROXY_COUNT', 0) == 0

    def test_forwarded_header_ignored_when_untrusted(self, app):
        """With trust disabled, a spoofed header must not change remote_addr."""
        from flask import request

        # A request context, not a new route: the session-scoped app has already
        # served requests, and Flask forbids adding routes after that.
        with app.test_request_context(
            '/', headers={'X-Forwarded-For': '203.0.113.77'}, environ_base={'REMOTE_ADDR': '127.0.0.1'}
        ):
            assert request.remote_addr != '203.0.113.77', (
                'a client-supplied X-Forwarded-For must not be believed by default'
            )

    @staticmethod
    def _middleware_chain(app):
        """Walk the WSGI wrapper chain outermost-first."""
        layers, node, seen = [], app.wsgi_app, 0
        while node is not None and seen < 12:
            layers.append(node)
            node = getattr(node, 'app', None)
            seen += 1
        return layers

    def test_proxyfix_is_wired_when_configured(self, monkeypatch):
        """TRUSTED_PROXY_COUNT > 0 must actually install the middleware."""
        from werkzeug.middleware.proxy_fix import ProxyFix
        from app import create_app

        monkeypatch.setenv('TRUSTED_PROXY_COUNT', '1')
        proxied = create_app('testing')

        # Not the outermost layer: SecurityHeadersMiddleware wraps it afterwards.
        found = [n for n in self._middleware_chain(proxied) if isinstance(n, ProxyFix)]

        assert found, 'ProxyFix should be installed when a trusted hop count is configured'
        assert found[0].x_for == 1

    def test_proxyfix_absent_when_not_configured(self, monkeypatch):
        from werkzeug.middleware.proxy_fix import ProxyFix
        from app import create_app

        monkeypatch.setenv('TRUSTED_PROXY_COUNT', '0')
        plain = create_app('testing')

        assert not [n for n in self._middleware_chain(plain) if isinstance(n, ProxyFix)]

    def test_proxyfix_reads_client_ip_from_header(self):
        """The whole point: the client IP comes from the proxy header."""
        seen = {}

        def probe(environ, start_response):
            seen['addr'] = environ.get('REMOTE_ADDR')
            start_response('200 OK', [('Content-Type', 'text/plain')])
            return [b'ok']

        # Drive ProxyFix directly, wrapping a trivial WSGI app.
        from werkzeug.middleware.proxy_fix import ProxyFix
        from werkzeug.test import Client

        wrapped = ProxyFix(probe, x_for=1, x_proto=1, x_host=1)
        Client(wrapped).get('/', headers={'X-Forwarded-For': '203.0.113.77'})

        assert seen['addr'] == '203.0.113.77'
