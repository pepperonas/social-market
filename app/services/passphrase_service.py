"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Passphrase Generator
Purpose: Suggest passwords whose strength can be stated as a number

Why a wordlist instead of "Xk9#mQ2!vL":
    Random character strings are strong but people do not use them -- they get
    written down, reused, or replaced with something memorable that is not
    random. A passphrase drawn from a known wordlist gives measurable entropy
    AND survives contact with a human.

Why the strength claim is honest here:
    Entropy is log2(list_size) per word ONLY IF each word is chosen uniformly at
    random by the machine. 2048 words = exactly 11 bits per word. This is the
    number the UI shows. It assumes the attacker knows the wordlist and the
    scheme -- Kerckhoffs's principle. Secrecy lives in the dice, not the method.
"""

import math
import secrets
from pathlib import Path

WORDLIST_PATH = Path(__file__).resolve().parent.parent / 'data' / 'bip39_english.txt'

# Separators that survive copy/paste and shells without quoting surprises
SEPARATORS = ('-', '.', '_')

DEFAULT_WORDS = 6
MIN_WORDS = 4
MAX_WORDS = 12


class PassphraseService:
    """Generates wordlist passphrases with a stated entropy in bits."""

    def __init__(self, wordlist_path=None):
        self._path = Path(wordlist_path) if wordlist_path else WORDLIST_PATH
        self._words = None

    @property
    def words(self):
        """Wordlist, loaded once."""
        if self._words is None:
            raw = self._path.read_text(encoding='utf-8').split()
            # Duplicates would silently reduce entropy below the advertised value
            unique = sorted(set(raw))
            if len(unique) != len(raw):
                raise ValueError(
                    f'wordlist has duplicates: {len(raw)} entries, {len(unique)} unique'
                )
            self._words = unique
        return self._words

    def bits_per_word(self):
        """Entropy contributed by one word, in bits."""
        return math.log2(len(self.words))

    def entropy_bits(self, word_count):
        """
        Entropy of a passphrase of ``word_count`` words.

        Deliberately counts ONLY the words. The capitalisation, digit and symbol
        added below satisfy composition rules; they add essentially nothing an
        attacker has to guess, because their placement is predictable. Claiming
        credit for them would be the exact overstatement that makes strength
        meters useless.
        """
        return word_count * self.bits_per_word()

    def generate(self, word_count=DEFAULT_WORDS, separator=None, policy_safe=True):
        """
        Generate one passphrase.

        Args:
            word_count: Number of words (clamped to [MIN_WORDS, MAX_WORDS])
            separator: Character between words; random from SEPARATORS if None
            policy_safe: Append the upper/digit/symbol the password policy wants

        Returns:
            dict: passphrase, entropy_bits, word_count, wordlist_size
        """
        word_count = max(MIN_WORDS, min(MAX_WORDS, int(word_count)))
        sep = separator if separator in SEPARATORS else secrets.choice(SEPARATORS)

        # secrets.choice, not random.choice: the latter is a Mersenne Twister and
        # is trivially predictable from a handful of outputs.
        chosen = [secrets.choice(self.words) for _ in range(word_count)]

        if policy_safe:
            # Capitalise one random word rather than always the first: it costs
            # the attacker log2(word_count) bits instead of nothing, and it stops
            # every generated passphrase from looking identical in shape.
            idx = secrets.randbelow(word_count)
            chosen[idx] = chosen[idx].capitalize()
            phrase = sep.join(chosen) + sep + str(secrets.randbelow(10)) + secrets.choice('!?#$%&*+')
        else:
            phrase = sep.join(chosen)

        return {
            'passphrase': phrase,
            'entropy_bits': round(self.entropy_bits(word_count), 1),
            'word_count': word_count,
            'wordlist_size': len(self.words),
        }

    def generate_many(self, count=3, **kwargs):
        """Generate several distinct suggestions."""
        count = max(1, min(10, int(count)))
        return [self.generate(**kwargs) for _ in range(count)]

    @staticmethod
    def crack_time_estimate(entropy_bits, guesses_per_second=1e12):
        """
        Rough offline-cracking estimate, as a human-readable string.

        1e12 guesses/s is a deliberately pessimistic stand-in for a GPU rig
        against a *fast* hash. Against this application's Argon2id (64 MB,
        t=3) the real rate is many orders of magnitude lower -- which is the
        point of a memory-hard KDF, and worth saying out loud.
        """
        seconds = (2 ** (entropy_bits - 1)) / guesses_per_second

        if seconds < 1:
            return 'less than a second'

        for limit, name, divisor in (
            (60, 'second', 1),
            (3600, 'minute', 60),
            (86400, 'hour', 3600),
            (31536000, 'day', 86400),
            (31536000 * 1000, 'year', 31536000),
        ):
            if seconds < limit:
                value = seconds / divisor
                return f'{value:.0f} {name}' + ('' if 0.5 <= value < 1.5 else 's')

        return f'{seconds / 31536000:.2e} years'


_service = None


def get_passphrase_service():
    """Passphrase service singleton."""
    global _service
    if _service is None:
        _service = PassphraseService()
    return _service
