"""
Code blocks must stay readable while selected, and key passphrases must be
suggestible.

The selection bug: `<pre class="bg-dark text-white">` renders white text, and
the browser's default selection highlight is light grey. Selecting a command --
the only reason those blocks exist -- turned it white-on-light-grey. Forcing a
text colour without declaring a selection colour is the whole failure.
"""

import pathlib
import re

import pytest

TEMPLATES = pathlib.Path('app/templates')
BASE = TEMPLATES / 'base.html'


class TestSelectionIsReadable:
    def test_selection_colours_are_declared(self):
        css = BASE.read_text()
        assert '::selection' in css, (
            'a forced text colour needs a matching ::selection rule, '
            'otherwise selected text can land on an unreadable background'
        )

    def test_selection_sets_both_background_and_colour(self):
        """Setting only one of the two is what produces the unreadable pair."""
        css = BASE.read_text()
        block = re.search(r'::selection\s*\{([^}]*)\}', css)

        assert block, 'no ::selection rule found'
        body = block.group(1)
        assert 'background' in body
        assert 'color' in body

    def test_no_template_still_uses_the_broken_pair(self):
        """`bg-dark text-white` on a <pre> is the exact combination that broke."""
        offenders = []
        for path in TEMPLATES.rglob('*.html'):
            for tag in re.findall(r'<pre[^>]*>', path.read_text()):
                if 'bg-dark' in tag and 'text-white' in tag:
                    offenders.append(f'{path.name}: {tag}')

        assert not offenders, (
            'use .code-block, which declares its own selection colours: '
            f'{offenders}'
        )

    def test_code_blocks_use_the_shared_class(self):
        used = sum(
            path.read_text().count('class="code-block"')
            for path in TEMPLATES.rglob('*.html')
        )
        assert used >= 2, 'the GPG import instructions should use .code-block'

    def test_forced_colors_fallback_exists(self):
        """High-contrast mode overrides backgrounds; hand it back to the OS."""
        assert 'forced-colors: active' in BASE.read_text()


class TestCopyButton:
    """A copy button removes the need to select the text at all."""

    def test_copy_script_is_present(self):
        assert 'code-copy' in BASE.read_text()

    def test_copy_script_carries_a_csp_nonce(self):
        """Inline script without the nonce is silently blocked by the CSP."""
        html = BASE.read_text()
        for tag in re.findall(r'<script(?![^>]*\bsrc=)[^>]*>', html):
            assert 'csp_nonce()' in tag, f'inline script without nonce: {tag}'

    def test_copy_uses_textcontent_not_innerhtml(self):
        """Round-tripping page content through innerHTML invites injection."""
        html = BASE.read_text()
        script = html[html.index('code-copy'):]
        assert 'innerHTML' not in script

    def test_has_insecure_context_fallback(self):
        """navigator.clipboard is unavailable over plain HTTP."""
        assert 'isSecureContext' in BASE.read_text()


class TestPgpPassphraseSuggestions:
    @pytest.fixture
    def html(self):
        return (TEMPLATES / 'auth' / 'pgp_keys.html').read_text()

    def test_suggest_button_exists(self, html):
        assert 'pgp-suggest' in html

    def test_uses_the_shared_generator_endpoint(self, html):
        assert '/auth/suggest-passphrase' in html

    def test_requests_more_words_than_account_passwords(self, html):
        """
        A private key file is attacked offline: no lockout, no rate limit. It
        deserves more entropy than a login, which the server can throttle.
        """
        words = int(re.search(r'suggest-passphrase\?words=(\d+)', html).group(1))
        register = (TEMPLATES / 'auth' / 'register.html').read_text()
        register_words = int(re.search(r'suggest-passphrase\?words=(\d+)', register).group(1))

        assert words > register_words, (
            f'key passphrase uses {words} words, account password {register_words}'
        )

    def test_warns_that_the_passphrase_is_unrecoverable(self, html):
        assert 'cannot be recovered' in html

    def test_says_what_the_passphrase_protects(self, html):
        assert 'private key' in html.lower()


class TestGeneratorServesBothForms:
    """One generator, two call sites -- the key form must get real entropy too."""

    def test_eight_word_suggestions_are_stronger(self, client):
        six = client.get('/auth/suggest-passphrase?words=6').get_json()
        eight = client.get('/auth/suggest-passphrase?words=8').get_json()

        assert eight['suggestions'][0]['entropy_bits'] > six['suggestions'][0]['entropy_bits']

    def test_eight_words_reach_88_bits(self, client):
        item = client.get('/auth/suggest-passphrase?words=8').get_json()['suggestions'][0]
        assert item['entropy_bits'] == pytest.approx(88.0)


class TestCodeBlockLayout:
    """
    The copy button used to sit inside the code area, immediately beside the
    first line, which made that line read as indented even though it was not
    (measured: both lines start at the same x). Perceived misalignment is still
    misalignment. The button now lives in its own bar above the code.
    """

    def test_wrapper_and_bar_are_created(self):
        js = BASE.read_text()
        assert 'code-figure' in js
        assert 'code-bar' in js

    def test_padding_is_symmetric(self):
        """
        Asymmetric right padding existed only to dodge the button. With the
        button in the bar, a one-value padding keeps every line evenly inset.

        Matched against comment-free CSS: the comment above that very rule
        contains the word "padding:", and a naive search swallows it -- the
        trap CONTRIBUTING.md warns about, walked into while writing this test.
        """
        css = re.sub(r'/\*.*?\*/', '', BASE.read_text(), flags=re.S)
        rule = re.search(r'\.code-block\s*\{([^}]*)\}', css).group(1)
        padding = re.search(r'padding:\s*([^;]+);', rule)

        assert padding, '.code-block should declare padding'
        values = padding.group(1).split()
        assert len(set(values)) == 1, f'padding should be uniform, got {values}'

    def test_wrapping_is_idempotent(self):
        """The script may run again (e.g. after a partial render)."""
        js = BASE.read_text()
        assert "classList.contains('code-figure')" in js, (
            'must skip blocks that are already wrapped'
        )

    def test_bar_has_a_label(self):
        assert 'code-bar-label' in BASE.read_text()

    def test_button_is_reachable_by_keyboard(self):
        """It is a real <button>, and it shows a focus ring."""
        css = BASE.read_text()
        assert '.code-copy:focus-visible' in css
        assert "createElement('button')" in css
