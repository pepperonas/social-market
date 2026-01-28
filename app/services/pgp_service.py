"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
PGP Service
Purpose: PGP encryption/decryption for messaging with RSA-4096 support
"""

import gnupg
import os
import tempfile
import shutil
from flask import current_app
from datetime import datetime


class PGPService:
    """PGP encryption service using python-gnupg with RSA-4096 support"""

    def __init__(self, use_temp_home=True):
        """
        Initialize PGP service

        Args:
            use_temp_home: Use temporary GPG home directory for isolation (recommended)
        """
        if use_temp_home:
            # Create temporary GPG home directory for better isolation
            self.gnupghome = tempfile.mkdtemp(prefix='gpg_')
            self.gpg = gnupg.GPG(gnupghome=self.gnupghome)
            # Set secure permissions
            os.chmod(self.gnupghome, 0o700)
        else:
            self.gnupghome = None
            self.gpg = gnupg.GPG()

    def __del__(self):
        """Cleanup temporary GPG home directory"""
        if self.gnupghome and os.path.exists(self.gnupghome):
            try:
                shutil.rmtree(self.gnupghome)
            except Exception as e:
                if current_app:
                    current_app.logger.warning(f'Failed to cleanup GPG home: {e}')

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

    def generate_keypair(self, name, email, passphrase, key_length=4096,
                        key_type='RSA', expire_date='0', comment=None):
        """
        Generate secure PGP keypair with RSA-4096

        Args:
            name: Key owner name (real name)
            email: Key owner email
            passphrase: Private key passphrase (REQUIRED for security)
            key_length: Key length in bits (default 4096, minimum 2048)
            key_type: Key algorithm (default RSA)
            expire_date: Expiration date (0 = never, or '1y', '2y', etc.)
            comment: Optional comment for key

        Returns:
            dict: {
                'success': bool,
                'public_key': str,
                'private_key': str,
                'fingerprint': str,
                'keyid': str,
                'error': str (if failed)
            }
        """
        try:
            # Validation
            if not name or len(name) < 3:
                return {
                    'success': False,
                    'error': 'Name must be at least 3 characters'
                }

            if not email or '@' not in email:
                return {
                    'success': False,
                    'error': 'Valid email address required'
                }

            if not passphrase or len(passphrase) < 12:
                return {
                    'success': False,
                    'error': 'Passphrase must be at least 12 characters for security'
                }

            if key_length < 2048:
                return {
                    'success': False,
                    'error': 'Key length must be at least 2048 bits'
                }

            # Security: Limit key length to prevent DoS
            if key_length > 8192:
                return {
                    'success': False,
                    'error': 'Key length cannot exceed 8192 bits'
                }

            # Generate key input
            key_params = {
                'name_real': name,
                'name_email': email,
                'passphrase': passphrase,
                'key_length': key_length,
                'key_type': key_type,
                'expire_date': expire_date
            }

            if comment:
                key_params['name_comment'] = comment

            input_data = self.gpg.gen_key_input(**key_params)

            # Generate key (this may take a while for RSA-4096)
            if current_app:
                current_app.logger.info(f'Generating {key_length}-bit {key_type} keypair for {email}')

            key = self.gpg.gen_key(input_data)

            if not key or not str(key):
                return {
                    'success': False,
                    'error': 'Key generation failed - GPG returned empty key'
                }

            key_str = str(key)

            # Export keys
            public_key = self.gpg.export_keys(key_str)
            private_key = self.gpg.export_keys(key_str, secret=True, passphrase=passphrase)

            if not public_key or not private_key:
                return {
                    'success': False,
                    'error': 'Failed to export generated keys'
                }

            # Get key info
            keys = self.gpg.list_keys()
            key_info = None
            for k in keys:
                if k['keyid'] == key_str or k['fingerprint'].endswith(key_str):
                    key_info = k
                    break

            fingerprint = key_info['fingerprint'] if key_info else key_str
            keyid = key_info['keyid'] if key_info else key_str

            if current_app:
                current_app.logger.info(f'Successfully generated keypair: {fingerprint}')

            return {
                'success': True,
                'public_key': public_key,
                'private_key': private_key,
                'fingerprint': fingerprint,
                'keyid': keyid,
                'key_length': key_length,
                'created_at': datetime.utcnow().isoformat()
            }

        except Exception as e:
            error_msg = f'Failed to generate keypair: {str(e)}'
            if current_app:
                current_app.logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg
            }

    def validate_passphrase_strength(self, passphrase):
        """
        Validate passphrase strength for PGP key generation

        Args:
            passphrase: Passphrase to validate

        Returns:
            dict: {
                'valid': bool,
                'strength': str ('weak', 'medium', 'strong', 'very_strong'),
                'score': int (0-100),
                'feedback': list of str
            }
        """
        feedback = []
        score = 0

        if not passphrase:
            return {
                'valid': False,
                'strength': 'none',
                'score': 0,
                'feedback': ['Passphrase is required']
            }

        length = len(passphrase)

        # Length check
        if length < 12:
            feedback.append('Passphrase must be at least 12 characters')
            return {
                'valid': False,
                'strength': 'weak',
                'score': 10,
                'feedback': feedback
            }

        # Length scoring
        if length >= 12:
            score += 20
        if length >= 16:
            score += 10
        if length >= 20:
            score += 10

        # Character variety
        has_upper = any(c.isupper() for c in passphrase)
        has_lower = any(c.islower() for c in passphrase)
        has_digit = any(c.isdigit() for c in passphrase)
        has_special = any(not c.isalnum() for c in passphrase)

        variety_score = sum([has_upper, has_lower, has_digit, has_special])
        score += variety_score * 15

        # Recommendations
        if not has_upper:
            feedback.append('Add uppercase letters for better security')
        if not has_lower:
            feedback.append('Add lowercase letters for better security')
        if not has_digit:
            feedback.append('Add numbers for better security')
        if not has_special:
            feedback.append('Add special characters for better security')

        # Check for common patterns
        common_weak = ['password', '123456', 'qwerty', 'abc123', 'letmein']
        if any(weak in passphrase.lower() for weak in common_weak):
            score -= 30
            feedback.append('Avoid common words and patterns')

        # Determine strength
        if score < 40:
            strength = 'weak'
            valid = False
            feedback.append('Passphrase is too weak for RSA-4096 key')
        elif score < 60:
            strength = 'medium'
            valid = True
        elif score < 80:
            strength = 'strong'
            valid = True
        else:
            strength = 'very_strong'
            valid = True

        return {
            'valid': valid,
            'strength': strength,
            'score': min(score, 100),
            'feedback': feedback if feedback else ['Passphrase strength is good']
        }

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
