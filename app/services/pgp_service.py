"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
PGP Service
Purpose: PGP encryption/decryption for messaging
"""

import gnupg
from flask import current_app


class PGPService:
    """PGP encryption service using python-gnupg"""

    def __init__(self):
        self.gpg = gnupg.GPG()

    def import_public_key(self, public_key_armor):
        """
        Import PGP public key

        Args:
            public_key_armor: ASCII armored public key

        Returns:
            tuple: (success, fingerprint or error_message)
        """
        try:
            import_result = self.gpg.import_keys(public_key_armor)

            if import_result.count == 0:
                return False, "Failed to import key - invalid format"

            fingerprint = import_result.fingerprints[0]
            return True, fingerprint

        except Exception as e:
            return False, str(e)

    def verify_key_format(self, public_key_armor):
        """
        Verify PGP key format without importing

        Args:
            public_key_armor: ASCII armored public key

        Returns:
            bool: True if valid format
        """
        if not public_key_armor:
            return False

        # Check for PGP headers
        if '-----BEGIN PGP PUBLIC KEY BLOCK-----' not in public_key_armor:
            return False

        if '-----END PGP PUBLIC KEY BLOCK-----' not in public_key_armor:
            return False

        return True

    def encrypt_message(self, message, recipient_public_key):
        """
        Encrypt message with recipient's public key

        Args:
            message: Plain text message
            recipient_public_key: Recipient's ASCII armored public key

        Returns:
            tuple: (success, encrypted_message or error_message)
        """
        try:
            # Import recipient's key temporarily
            import_result = self.gpg.import_keys(recipient_public_key)

            if import_result.count == 0:
                return False, "Invalid recipient public key"

            # Get key fingerprint
            fingerprint = import_result.fingerprints[0]

            # Encrypt message
            encrypted = self.gpg.encrypt(message, fingerprint, always_trust=True)

            if not encrypted.ok:
                return False, f"Encryption failed: {encrypted.status}"

            return True, str(encrypted)

        except Exception as e:
            return False, str(e)

    def decrypt_message(self, encrypted_message, private_key, passphrase=None):
        """
        Decrypt message with private key

        Args:
            encrypted_message: PGP encrypted message
            private_key: ASCII armored private key
            passphrase: Private key passphrase (optional)

        Returns:
            tuple: (success, decrypted_message or error_message)
        """
        try:
            # Import private key
            import_result = self.gpg.import_keys(private_key)

            if import_result.count == 0:
                return False, "Invalid private key"

            # Decrypt message
            decrypted = self.gpg.decrypt(
                encrypted_message,
                passphrase=passphrase
            )

            if not decrypted.ok:
                return False, f"Decryption failed: {decrypted.status}"

            return True, str(decrypted)

        except Exception as e:
            return False, str(e)

    def generate_keypair(self, name, email, passphrase=None, key_length=2048):
        """
        Generate PGP keypair (for testing purposes)

        Args:
            name: Key owner name
            email: Key owner email
            passphrase: Private key passphrase (optional)
            key_length: Key length in bits (default 2048)

        Returns:
            tuple: (public_key, private_key)
        """
        try:
            input_data = self.gpg.gen_key_input(
                name_real=name,
                name_email=email,
                passphrase=passphrase,
                key_length=key_length
            )

            key = self.gpg.gen_key(input_data)

            if not key:
                return None, None

            # Export keys
            public_key = self.gpg.export_keys(str(key))
            private_key = self.gpg.export_keys(str(key), secret=True, passphrase=passphrase)

            return public_key, private_key

        except Exception as e:
            current_app.logger.error(f'Failed to generate keypair: {e}')
            return None, None

    def get_key_info(self, public_key_armor):
        """
        Get information about a PGP key

        Args:
            public_key_armor: ASCII armored public key

        Returns:
            dict: Key information
        """
        try:
            import_result = self.gpg.import_keys(public_key_armor)

            if import_result.count == 0:
                return None

            fingerprint = import_result.fingerprints[0]
            keys = self.gpg.list_keys()

            for key in keys:
                if key['fingerprint'] == fingerprint:
                    return {
                        'fingerprint': key['fingerprint'],
                        'keyid': key['keyid'],
                        'uids': key['uids'],
                        'length': key['length'],
                        'algo': key['algo'],
                        'created': key['date']
                    }

            return None

        except Exception as e:
            current_app.logger.error(f'Failed to get key info: {e}')
            return None


# Singleton instance
_pgp_service = None


def get_pgp_service():
    """Get PGP service instance"""
    global _pgp_service
    if _pgp_service is None:
        _pgp_service = PGPService()
    return _pgp_service
