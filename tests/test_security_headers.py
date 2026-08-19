"""
Tests for the defensive HTTP layer: security headers, CSP, request IDs.

Blue team relevance: these headers are the browser-side controls that turn a
reflected-input bug into a non-event. They are also the first thing an attacker
checks, and the easiest thing to lose silently during a refactor.
"""

import pytest


@pytest.fixture
def response(client):
    return client.get('/health')


class TestSecurityHeaders:
    def test_health_endpoint_reachable(self, response):
        assert response.status_code == 200

    def test_content_type_options_nosniff(self, response):
        assert response.headers.get('X-Content-Type-Options') == 'nosniff'

    def test_frame_options_set(self, response):
        """Clickjacking defence."""
        assert response.headers.get('X-Frame-Options') in ('DENY', 'SAMEORIGIN')

    def test_csp_present(self, response):
        assert 'Content-Security-Policy' in response.headers

    def test_csp_restricts_default_src_to_self(self, response):
        assert "default-src 'self'" in response.headers['Content-Security-Policy']

    def test_csp_script_src_has_no_unsafe_inline(self, response):
        """
        Inline script must be nonce-gated, never blanket-allowed -- otherwise
        the CSP provides no XSS protection at all.
        """
        csp = response.headers['Content-Security-Policy']
        script_src = [p for p in csp.split(';') if p.strip().startswith('script-src')]
        assert script_src, 'script-src must be declared explicitly'
        assert "'unsafe-inline'" not in script_src[0]

    def test_csp_uses_nonce_for_scripts(self, response):
        script_src = [p for p in response.headers['Content-Security-Policy'].split(';')
                      if p.strip().startswith('script-src')][0]
        assert 'nonce-' in script_src

    def test_referrer_policy_is_strict(self, response):
        assert response.headers.get('Referrer-Policy') == 'no-referrer'

    def test_hsts_sent_over_https(self, client):
        """
        Talisman deliberately omits HSTS on plain HTTP (announcing it there is
        meaningless), so this must be asserted against an HTTPS request.
        """
        secure = client.get('/health', base_url='https://localhost')
        hsts = secure.headers.get('Strict-Transport-Security')

        assert hsts is not None
        assert 'max-age=' in hsts

    def test_hsts_absent_over_plain_http(self, response):
        assert 'Strict-Transport-Security' not in response.headers


class TestRequestId:
    def test_request_id_is_returned(self, client):
        assert client.get('/health').headers.get('X-Request-ID')

    def test_supplied_request_id_is_propagated(self, client):
        """Lets a reverse proxy correlate its access log with the app log."""
        supplied = 'test-request-id-123'
        got = client.get('/health', headers={'X-Request-ID': supplied})
        assert got.headers.get('X-Request-ID') == supplied

    def test_generated_ids_are_unique(self, client):
        a = client.get('/health').headers.get('X-Request-ID')
        b = client.get('/health').headers.get('X-Request-ID')
        assert a != b


class TestErrorHandling:
    def test_unknown_route_returns_404_not_500(self, client):
        assert client.get('/definitely-not-a-route').status_code == 404

    def test_health_reports_training_environment(self, client):
        """The disclaimer must survive refactors -- it is the legal framing."""
        payload = client.get('/health').get_json()
        assert payload['environment'] == 'training'
        assert 'disclaimer' in payload
