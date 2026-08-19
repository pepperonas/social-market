"""
Unit tests for CryptoService (Fernet-based application-level encryption).

This module was entirely non-functional until 2026-08-19: it imported a class
name that does not exist in `cryptography`. Nothing called it, so nothing
failed. These tests make sure it stays callable.
"""

import pytest


class TestEncryptDecrypt:
    def test_roundtrip_str(self, app):
        from app.services.crypto_service import CryptoService

        assert CryptoService.decrypt(CryptoService.encrypt('hello')) == 'hello'

    def test_roundtrip_bytes_input(self, app):
        from app.services.crypto_service import CryptoService

        assert CryptoService.decrypt(CryptoService.encrypt(b'hello')) == 'hello'

    def test_roundtrip_unicode(self, app):
        from app.services.crypto_service import CryptoService

        text = 'Straße 42, Köln — 🔐'
        assert CryptoService.decrypt(CryptoService.encrypt(text)) == text

    def test_ciphertext_does_not_contain_plaintext(self, app):
        from app.services.crypto_service import CryptoService

        assert b'topsecret' not in CryptoService.encrypt('topsecret')

    def test_same_plaintext_yields_different_ciphertext(self, app):
        """Fernet includes a random IV; identical inputs must not collide."""
        from app.services.crypto_service import CryptoService

        assert CryptoService.encrypt('same') != CryptoService.encrypt('same')

    def test_tampered_ciphertext_is_rejected(self, app):
        """Fernet is authenticated: flipping a byte must fail, not decrypt."""
        from cryptography.fernet import InvalidToken
        from app.services.crypto_service import CryptoService

        token = bytearray(CryptoService.encrypt('important'))
        token[-1] ^= 0x01

        with pytest.raises(InvalidToken):
            CryptoService.decrypt(bytes(token))

    def test_foreign_key_cannot_decrypt(self, app):
        """A token from an unrelated key must not be accepted."""
        from cryptography.fernet import Fernet, InvalidToken
        from app.services.crypto_service import CryptoService

        foreign = Fernet(Fernet.generate_key()).encrypt(b'secret')
        with pytest.raises(InvalidToken):
            CryptoService.decrypt(foreign)


class TestTokens:
    def test_generate_token_is_unique(self, app):
        from app.services.crypto_service import CryptoService

        tokens = {CryptoService.generate_token() for _ in range(50)}
        assert len(tokens) == 50

    def test_generate_token_length_scales(self, app):
        from app.services.crypto_service import CryptoService

        short, long = CryptoService.generate_token(8), CryptoService.generate_token(32)
        assert len(long) > len(short)


class TestHashing:
    def test_hash_is_deterministic(self, app):
        from app.services.crypto_service import CryptoService

        assert CryptoService.hash_data('abc') == CryptoService.hash_data('abc')

    def test_hash_differs_for_different_input(self, app):
        from app.services.crypto_service import CryptoService

        assert CryptoService.hash_data('abc') != CryptoService.hash_data('abd')

    def test_hash_is_hex_sha256(self, app):
        from app.services.crypto_service import CryptoService

        digest = CryptoService.hash_data('abc')
        assert len(digest) == 64
        assert all(c in '0123456789abcdef' for c in digest)
