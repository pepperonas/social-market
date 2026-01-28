"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Password Hashing Service
Purpose: Secure password hashing with Argon2id + pepper
"""

import os
import secrets
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHash
from flask import current_app


class PasswordService:
    """
    Secure password hashing using Argon2id with pepper

    Security Features:
    - Argon2id: Winner of Password Hashing Competition (2015)
    - Memory-hard algorithm: Resistant to GPU/ASIC attacks
    - Time-cost parameter: Configurable iteration count
    - Parallelism: Multi-threaded hashing
    - Pepper: Secret server-side value added to password
    - Salt: Random per-password salt (automatic)

    Hash Format: Argon2id(password + pepper, salt)
    """

    def __init__(self):
        """
        Initialize Argon2 hasher with secure parameters

        Parameters (OWASP recommendations):
        - time_cost: 3 iterations (minimum recommended)
        - memory_cost: 65536 KB = 64 MB (recommended for web apps)
        - parallelism: 4 threads (balanced for server performance)
        - hash_len: 32 bytes (256 bits)
        - salt_len: 16 bytes (128 bits)
        - type: Argon2id (hybrid of Argon2i and Argon2d)
        """
        self.hasher = PasswordHasher(
            time_cost=3,           # Number of iterations
            memory_cost=65536,     # 64 MB memory
            parallelism=4,         # 4 parallel threads
            hash_len=32,           # 256-bit hash output
            salt_len=16,           # 128-bit salt
            encoding='utf-8'       # String encoding
        )

    def _get_pepper(self):
        """
        Get pepper from environment variable

        Returns:
            bytes: Pepper value

        Raises:
            RuntimeError: If pepper not configured
        """
        pepper = current_app.config.get('PASSWORD_PEPPER')

        if not pepper:
            raise RuntimeError(
                'PASSWORD_PEPPER not configured! Set PASSWORD_PEPPER in environment.'
            )

        # Convert to bytes if string
        if isinstance(pepper, str):
            pepper = pepper.encode('utf-8')

        # Validate pepper length (minimum 32 bytes recommended)
        if len(pepper) < 32:
            current_app.logger.warning(
                f'PASSWORD_PEPPER is only {len(pepper)} bytes. '
                'Recommended minimum: 32 bytes for security.'
            )

        return pepper

    def hash_password(self, password):
        """
        Hash password using Argon2id with pepper

        Process:
        1. Get pepper from config
        2. Concatenate password + pepper
        3. Hash with Argon2id (salt generated automatically)
        4. Return hash string

        Args:
            password (str): Plain text password

        Returns:
            str: Argon2id hash string (includes salt and parameters)

        Raises:
            ValueError: If password is empty or too short
            RuntimeError: If pepper not configured

        Example:
            >>> service = PasswordService()
            >>> hash_str = service.hash_password("MySecurePassword123!")
            >>> print(hash_str)
            $argon2id$v=19$m=65536,t=3,p=4$...
        """
        # Validate password
        if not password:
            raise ValueError('Password cannot be empty')

        if len(password) < 8:
            raise ValueError('Password must be at least 8 characters')

        # Get pepper
        pepper = self._get_pepper()

        # Combine password with pepper
        peppered_password = password.encode('utf-8') + pepper

        # Hash with Argon2id
        # Note: Salt is generated automatically by argon2-cffi
        hash_str = self.hasher.hash(peppered_password)

        return hash_str

    def verify_password(self, password, hash_str):
        """
        Verify password against Argon2id hash

        Process:
        1. Get pepper from config
        2. Concatenate password + pepper
        3. Verify against hash

        Args:
            password (str): Plain text password to verify
            hash_str (str): Argon2id hash string

        Returns:
            bool: True if password matches, False otherwise

        Raises:
            RuntimeError: If pepper not configured
        """
        if not password or not hash_str:
            return False

        try:
            # Get pepper
            pepper = self._get_pepper()

            # Combine password with pepper
            peppered_password = password.encode('utf-8') + pepper

            # Verify against hash
            # Will raise VerifyMismatchError if password doesn't match
            self.hasher.verify(hash_str, peppered_password)

            # If we get here, password is correct
            return True

        except VerifyMismatchError:
            # Password doesn't match
            return False
        except (VerificationError, InvalidHash) as e:
            # Invalid hash format or verification error
            current_app.logger.error(f'Password verification error: {e}')
            return False
        except Exception as e:
            # Unexpected error
            current_app.logger.error(f'Unexpected error during password verification: {e}')
            return False

    def needs_rehash(self, hash_str):
        """
        Check if password hash needs to be rehashed

        Use case: If Argon2 parameters are updated in code,
        old hashes should be rehashed on next login

        Args:
            hash_str (str): Argon2id hash string

        Returns:
            bool: True if hash should be regenerated

        Example:
            >>> if service.needs_rehash(user.password_hash):
            >>>     user.password_hash = service.hash_password(password)
            >>>     db.session.commit()
        """
        try:
            return self.hasher.check_needs_rehash(hash_str)
        except (InvalidHash, Exception):
            # Invalid hash or error - should be rehashed
            return True

    def generate_pepper(self, length=32):
        """
        Generate a cryptographically secure random pepper

        Use this to generate pepper for .env file during setup

        Args:
            length (int): Length in bytes (default 32 = 256 bits)

        Returns:
            str: Hex-encoded random pepper

        Example:
            >>> service = PasswordService()
            >>> pepper = service.generate_pepper()
            >>> print(f"PASSWORD_PEPPER={pepper}")
            PASSWORD_PEPPER=a1b2c3d4...
        """
        return secrets.token_hex(length)

    def get_hash_info(self, hash_str):
        """
        Extract information from Argon2id hash string

        Args:
            hash_str (str): Argon2id hash string

        Returns:
            dict: Hash parameters or None if invalid

        Example:
            >>> info = service.get_hash_info(hash_str)
            >>> print(info)
            {'version': 19, 'memory_cost': 65536, 'time_cost': 3, 'parallelism': 4}
        """
        try:
            # Parse hash string
            # Format: $argon2id$v=19$m=65536,t=3,p=4$salt$hash
            parts = hash_str.split('$')

            if len(parts) < 5 or parts[1] != 'argon2id':
                return None

            version = int(parts[2].split('=')[1])
            params = parts[3].split(',')

            memory_cost = int(params[0].split('=')[1])
            time_cost = int(params[1].split('=')[1])
            parallelism = int(params[2].split('=')[1])

            return {
                'algorithm': 'argon2id',
                'version': version,
                'memory_cost': memory_cost,
                'memory_cost_mb': memory_cost / 1024,
                'time_cost': time_cost,
                'parallelism': parallelism
            }

        except (IndexError, ValueError, Exception) as e:
            current_app.logger.error(f'Failed to parse hash info: {e}')
            return None


# Singleton instance
_password_service = None


def get_password_service():
    """Get password service singleton instance"""
    global _password_service
    if _password_service is None:
        _password_service = PasswordService()
    return _password_service
