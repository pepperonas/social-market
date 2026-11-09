"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
The templates have to work under the app's own Content-Security-Policy.

script-src is 'self' plus a per-request nonce. That blocks every inline event
handler (onclick="...", onsubmit="...") and every <script> block without the
nonce. The browser smoke test (step 6, C5) found 18 such handlers in 11
templates and two nonce-less script blocks. None of them ever ran:

* every "Are you sure?" dialog was skipped -- delete, deactivate, clear cart
  went through on the first click;
* the change-password button starts `disabled` and only the blocked script
  enabled it, so a password could not be changed in the browser at all;
* "Export My Data" was a link to "#" whose handler never fired.

This test reads the template sources, so it needs no browser and runs in the
normal suite. The behaviour itself is covered by tests/test_browser_smoke.py.
"""

import re
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parent.parent / 'app' / 'templates'
ALL = sorted(TEMPLATES.rglob('*.html'))

INLINE_HANDLER = re.compile(r'<[^>]*\son[a-z]+\s*=', re.IGNORECASE | re.DOTALL)
SCRIPT_TAG = re.compile(r'<script\b([^>]*)>', re.IGNORECASE)
JS_URL = re.compile(r'(href|src|action)\s*=\s*["\']\s*javascript:', re.IGNORECASE)


def _strip_comments(source):
    return re.sub(r'\{#.*?#\}|<!--.*?-->', '', source, flags=re.DOTALL)


@pytest.mark.parametrize('template', ALL, ids=lambda p: str(p.relative_to(TEMPLATES)))
def test_no_inline_event_handlers(template):
    source = _strip_comments(template.read_text())
    found = [m.group(0)[:80] for m in INLINE_HANDLER.finditer(source)]
    assert found == [], 'blocked by script-src; use data-* + static/js/ui.js'


@pytest.mark.parametrize('template', ALL, ids=lambda p: str(p.relative_to(TEMPLATES)))
def test_every_script_has_the_nonce_or_a_source(template):
    source = _strip_comments(template.read_text())
    bad = [m.group(0) for m in SCRIPT_TAG.finditer(source)
           if 'csp_nonce()' not in m.group(1) and 'src=' not in m.group(1)]
    assert bad == []


@pytest.mark.parametrize('template', ALL, ids=lambda p: str(p.relative_to(TEMPLATES)))
def test_no_javascript_urls(template):
    assert JS_URL.findall(_strip_comments(template.read_text())) == []


def test_the_guard_sees_what_it_is_for():
    """Counter-check: the patterns match the defects they exist to catch."""
    assert INLINE_HANDLER.search('<button type="submit"\n   onclick="return confirm(\'x\')">')
    assert INLINE_HANDLER.search('<input onchange="this.form.submit()">')
    assert not INLINE_HANDLER.search('<button data-confirm="Delete?">')
    tags = [m.group(1) for m in SCRIPT_TAG.finditer('<script>x</script><script nonce="{{ csp_nonce() }}">')]
    assert tags == ['', ' nonce="{{ csp_nonce() }}"']
    assert JS_URL.search('<a href="javascript:void(0)">')


def test_behaviours_used_by_templates_exist_in_ui_js():
    """Every data-* hook a template uses is handled by the shared script."""
    ui = (TEMPLATES.parent / 'static' / 'js' / 'ui.js').read_text()
    used = set()
    for template in ALL:
        used |= set(re.findall(r'\b(data-(?:confirm|autosubmit|toggle-password|submit-form))\b',
                               template.read_text()))
    assert used, 'no template uses the hooks -- the guard above would be pointless'
    for hook in used:
        assert f'[{hook}]' in ui, f'{hook} is used in a template but ui.js does not handle it'


def test_base_template_loads_ui_js():
    base = (TEMPLATES / 'base.html').read_text()
    assert "url_for('static', filename='js/ui.js')" in base
