"""
Tests for the wordlist passphrase generator.

The point of a generator like this is that its strength is a *number you can
defend*, not a colour on a meter. These tests hold that claim to account:
the wordlist must be the size the entropy formula assumes, the words must come
from a CSPRNG, and the advertised bits must not quietly include the decorative
digit and symbol tacked on to satisfy composition rules.
"""

import math
import re

import pytest

from app.services.passphrase_service import (
    MAX_WORDS,
    MIN_WORDS,
    PassphraseService,
    get_passphrase_service,
)


@pytest.fixture
def service():
    return PassphraseService()


class TestWordlist:
    def test_bip39_size(self, service):
        """BIP-39 is exactly 2048 words; 11 bits each depends on that."""
        assert len(service.words) == 2048

    def test_bits_per_word_is_exactly_eleven(self, service):
        assert service.bits_per_word() == pytest.approx(11.0)

    def test_no_duplicates(self, service):
        assert len(service.words) == len(set(service.words))

    def test_all_lowercase_ascii(self, service):
        assert all(re.fullmatch(r'[a-z]+', w) for w in service.words)

    def test_words_are_distinct_in_first_four_letters(self, service):
        """A BIP-39 property: a typo in later letters is still unambiguous."""
        prefixes = [w[:4] for w in service.words]
        assert len(prefixes) == len(set(prefixes))

    def test_duplicate_wordlist_is_rejected(self, tmp_path):
        """A duplicate would silently lower entropy below the advertised value."""
        path = tmp_path / 'dupes.txt'
        path.write_text('alpha\nbravo\nalpha\n')

        with pytest.raises(ValueError, match='duplicates'):
            _ = PassphraseService(path).words


class TestEntropy:
    @pytest.mark.parametrize('words,expected', [(4, 44), (6, 66), (8, 88), (12, 132)])
    def test_entropy_is_eleven_bits_per_word(self, service, words, expected):
        assert service.entropy_bits(words) == pytest.approx(expected)

    def test_reported_entropy_matches_word_count(self, service):
        result = service.generate(7)
        assert result['entropy_bits'] == pytest.approx(77.0)

    def test_entropy_excludes_the_decorative_suffix(self, service):
        """
        The trailing digit and symbol satisfy the policy but are predictable in
        position. Counting them would overstate strength -- the exact dishonesty
        that makes most strength meters worthless.
        """
        plain = service.generate(6, policy_safe=False)['entropy_bits']
        decorated = service.generate(6, policy_safe=True)['entropy_bits']

        assert plain == decorated

    def test_entropy_matches_the_formula(self, service):
        expected = 6 * math.log2(len(service.words))
        assert service.generate(6)['entropy_bits'] == pytest.approx(expected, abs=0.05)


class TestGeneration:
    def test_word_count_is_respected(self, service):
        phrase = service.generate(5, policy_safe=False)['passphrase']
        assert len(re.split(r'[-._]', phrase)) == 5

    def test_word_count_is_clamped_low(self, service):
        assert service.generate(1)['word_count'] == MIN_WORDS

    def test_word_count_is_clamped_high(self, service):
        assert service.generate(999)['word_count'] == MAX_WORDS

    def test_generated_values_are_unique(self, service):
        """A generator that repeats itself is a generator nobody should trust."""
        seen = {service.generate()['passphrase'] for _ in range(200)}
        assert len(seen) == 200

    def test_uses_csprng_not_random_module(self):
        """`random` is a Mersenne Twister: predictable from a few outputs."""
        import pathlib

        source = pathlib.Path('app/services/passphrase_service.py').read_text()
        code = '\n'.join(
            line for line in source.splitlines() if not line.strip().startswith('#')
        )

        assert 'import secrets' in code
        assert not re.search(r'^\s*import random', code, re.M)
        assert 'random.choice' not in code

    def test_generate_many_returns_requested_count(self, service):
        assert len(service.generate_many(5)) == 5

    def test_generate_many_is_bounded(self, service):
        assert len(service.generate_many(500)) <= 10


class TestPolicyCompliance:
    """A suggestion the app itself would reject is worse than no suggestion."""

    @pytest.mark.parametrize('words', [4, 6, 8, 12])
    def test_suggestions_satisfy_the_password_policy(self, app, service, words):
        from app.services.password_service import get_password_service

        policy = get_password_service()
        for _ in range(25):
            phrase = service.generate(words)['passphrase']
            assert policy.validate_policy(phrase) == [], (
                f'generated passphrase violates the policy: {phrase}'
            )

    def test_suggestions_are_actually_settable(self, app, sample_user, service):
        """End to end: the value the UI offers must pass set_password()."""
        sample_user.set_password(service.generate()['passphrase'])
        assert sample_user.password_hash.startswith('$argon2id$')


class TestCrackTimeEstimate:
    def test_more_entropy_means_longer(self, service):
        weak = service.crack_time_estimate(40)
        strong = service.crack_time_estimate(90)
        assert weak != strong

    def test_returns_human_readable_string(self, service):
        assert re.search(r'(second|minute|hour|day|year)', service.crack_time_estimate(66))

    def test_low_entropy_is_reported_as_fast(self, service):
        assert 'less than a second' in service.crack_time_estimate(20)

    def test_singular_is_not_pluralised(self, service):
        """'1 years' reads as a bug and undermines the number next to it."""
        assert '1 years' not in service.crack_time_estimate(66)


class TestSingleton:
    def test_singleton_is_stable(self):
        assert get_passphrase_service() is get_passphrase_service()


class TestEndpoint:
    def test_endpoint_returns_suggestions(self, client):
        payload = client.get('/auth/suggest-passphrase').get_json()

        assert len(payload['suggestions']) == 3
        assert payload['bits_per_word'] == pytest.approx(11.0)

    def test_endpoint_reports_entropy_and_crack_time(self, client):
        item = client.get('/auth/suggest-passphrase').get_json()['suggestions'][0]

        assert item['entropy_bits'] > 0
        assert item['crack_time']

    def test_endpoint_honours_word_count(self, client):
        item = client.get('/auth/suggest-passphrase?words=8').get_json()['suggestions'][0]
        assert item['word_count'] == 8

    def test_endpoint_survives_garbage_input(self, client):
        response = client.get('/auth/suggest-passphrase?words=notanumber')
        assert response.status_code == 200

    def test_endpoint_states_what_the_entropy_covers(self, client):
        """The caveat must travel with the number."""
        assert 'entropy' in client.get('/auth/suggest-passphrase').get_json()['note'].lower()
