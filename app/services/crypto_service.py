"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Crypto Service
Purpose: Centralized cryptographic operations
"""

import os
import secrets
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
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
        kdf = PBKDF2(
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
