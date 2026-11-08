"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Crypto Service
Purpose: Centralized cryptographic operations
"""

import secrets
from cryptography.fernet import Fernet, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from flask import current_app


class CryptoService:
    """
    Cryptographic service for application-level encryption
    Uses Fernet (symmetric encryption) for application data
    """

    @staticmethod
    def generate_key():
        """Generate a new Fernet key"""
        return Fernet.generate_key()

    @staticmethod
    def get_fernet():
        """Get Fernet instance with application key"""
        key = current_app.config['SECRET_KEY'].encode()[:32]
        # Pad or truncate to 32 bytes
        key = key.ljust(32, b'0')[:32]

        # Derive key using PBKDF2
        # NOTE: the class is PBKDF2HMAC. This module previously imported a
        # non-existent `PBKDF2`, so every call raised ImportError -- unnoticed
        # because nothing in the app called CryptoService.
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'marketplace_salt',  # In production, use random salt
            iterations=100000,
        )
        derived_key = kdf.derive(key)

        # Base64 encode for Fernet
        import base64
        fernet_key = base64.urlsafe_b64encode(derived_key)

        return Fernet(fernet_key)

    @staticmethod
    def encrypt(data):
        """
        Encrypt data

        Args:
            data: String or bytes to encrypt

        Returns:
            bytes: Encrypted data
        """
        if isinstance(data, str):
            data = data.encode('utf-8')

        f = CryptoService.get_fernet()
        return f.encrypt(data)

    @staticmethod
    def decrypt(encrypted_data):
        """
        Decrypt data

        Args:
            encrypted_data: Encrypted bytes

        Returns:
            str: Decrypted string
        """
        f = CryptoService.get_fernet()
        decrypted = f.decrypt(encrypted_data)
        return decrypted.decode('utf-8')

    # =========================================================================
    # TOTP seeds at rest (improvement plan 2026-11, A1)
    # =========================================================================

    @staticmethod
    def _totp_keys(value):
        return [k.strip() for k in (value or '').split(',') if k.strip()]

    @staticmethod
    def totp_key_is_usable(value):
        """True if every comma-separated entry is a valid Fernet key."""
        keys = CryptoService._totp_keys(value)
        if not keys:
            return False
        try:
            for key in keys:
                Fernet(key)
        except (ValueError, TypeError):
            return False
        return True

    @staticmethod
    def totp_fernet():
        """
        MultiFernet over TOTP_ENCRYPTION_KEY: encrypts with the first key,
        decrypts with any of them. Its own key, not SECRET_KEY -- see config.py.
        """
        keys = CryptoService._totp_keys(current_app.config.get('TOTP_ENCRYPTION_KEY'))
        return MultiFernet([Fernet(k) for k in keys])

    @staticmethod
    def encrypt_totp_secret(secret):
        return CryptoService.totp_fernet().encrypt(secret.encode('ascii'))

    @staticmethod
    def decrypt_totp_secret(token):
        """Raises InvalidToken on a wrong key: fail closed, never 'no 2FA'."""
        return CryptoService.totp_fernet().decrypt(bytes(token)).decode('ascii')

    @staticmethod
    def rotate_totp_secret(token):
        """Re-encrypt under the current first key."""
        return CryptoService.totp_fernet().rotate(bytes(token))

    @staticmethod
    def generate_token(length=32):
        """
        Generate secure random token

        Args:
            length: Token length in bytes

        Returns:
            str: Hex-encoded token
        """
        return secrets.token_hex(length)

    @staticmethod
    def hash_data(data):
        """
        Hash data with SHA-256

        Args:
            data: Data to hash

        Returns:
            str: Hex-encoded hash
        """
        import hashlib

        if isinstance(data, str):
            data = data.encode('utf-8')

        return hashlib.sha256(data).hexdigest()
