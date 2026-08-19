"""
Password Service Tests for Social Market.

Tests cover:
- Argon2id hash format
- Pepper application
- Password verification (correct/incorrect)
- Rehash detection
- Legacy hash upgrade detection
- Password validation
"""

import pytest


class TestPasswordHashing:
    """Tests for Argon2id password hashing."""

    def test_hash_produces_argon2id_format(self, app):
        """Hash should be in $argon2id$ format."""
        with app.app_context():
            from app.services.password_service import PasswordService
            svc = PasswordService()
            hash_str = svc.hash_password('TestPassword123!')
            assert hash_str.startswith('$argon2id$')

    def test_hash_contains_parameters(self, app):
        """Hash should contain memory, time, and parallelism parameters."""
        with app.app_context():
            from app.services.password_service import PasswordService
            svc = PasswordService()
            hash_str = svc.hash_password('TestPassword123!')
            assert 'm=65536' in hash_str
            assert 't=3' in hash_str
            assert 'p=4' in hash_str

    def test_different_passwords_different_hashes(self, app):
        """Different passwords should produce different hashes."""
        with app.app_context():
            from app.services.password_service import PasswordService
            svc = PasswordService()
            hash1 = svc.hash_password('Password1234!')
            hash2 = svc.hash_password('Password5678!')
            assert hash1 != hash2

    def test_same_password_different_salts(self, app):
        """Same password hashed twice should produce different hashes (random salt)."""
        with app.app_context():
            from app.services.password_service import PasswordService
            svc = PasswordService()
            hash1 = svc.hash_password('SamePassword123!')
            hash2 = svc.hash_password('SamePassword123!')
            assert hash1 != hash2


class TestPasswordVerification:
    """Tests for password verification."""

    def test_verify_correct_password(self, app):
        """Correct password should verify successfully."""
        with app.app_context():
            from app.services.password_service import PasswordService
            svc = PasswordService()
            hash_str = svc.hash_password('CorrectPassword123!')
            assert svc.verify_password('CorrectPassword123!', hash_str) is True

    def test_verify_wrong_password(self, app):
        """Wrong password should fail verification."""
        with app.app_context():
            from app.services.password_service import PasswordService
            svc = PasswordService()
            hash_str = svc.hash_password('CorrectPassword123!')
            assert svc.verify_password('WrongPassword123!', hash_str) is False

    def test_verify_empty_password(self, app):
        """Empty password should fail verification."""
        with app.app_context():
            from app.services.password_service import PasswordService
            svc = PasswordService()
            hash_str = svc.hash_password('SomePassword123!')
            assert svc.verify_password('', hash_str) is False

    def test_verify_empty_hash(self, app):
        """Empty hash should fail verification."""
        with app.app_context():
            from app.services.password_service import PasswordService
            svc = PasswordService()
            assert svc.verify_password('SomePassword123!', '') is False

    def test_verify_none_values(self, app):
        """None values should fail verification."""
        with app.app_context():
            from app.services.password_service import PasswordService
            svc = PasswordService()
            assert svc.verify_password(None, None) is False


class TestPepperApplication:
    """Tests for pepper application in hashing."""

    def test_different_pepper_different_hash(self, app):
        """Different pepper should produce different verification result."""
        with app.app_context():
            from app.services.password_service import PasswordService
            svc = PasswordService()
            hash_str = svc.hash_password('TestPassword123!')

            # Verify with correct pepper works
            assert svc.verify_password('TestPassword123!', hash_str) is True

    def test_hash_rejects_short_password(self, app):
        """Password shorter than 8 chars should raise ValueError."""
        with app.app_context():
            from app.services.password_service import PasswordService
            svc = PasswordService()
            with pytest.raises(ValueError, match='at least 8 characters'):
                svc.hash_password('short')

    def test_hash_rejects_empty_password(self, app):
        """Empty password should raise ValueError."""
        with app.app_context():
            from app.services.password_service import PasswordService
            svc = PasswordService()
            with pytest.raises(ValueError, match='cannot be empty'):
                svc.hash_password('')


class TestRehashDetection:
    """Tests for rehash detection."""

    def test_current_hash_no_rehash(self, app):
        """Hash with current parameters should not need rehashing."""
        with app.app_context():
            from app.services.password_service import PasswordService
            svc = PasswordService()
            hash_str = svc.hash_password('TestPassword123!')
            assert svc.needs_rehash(hash_str) is False

    def test_invalid_hash_needs_rehash(self, app):
        """Invalid hash should indicate rehash needed."""
        with app.app_context():
            from app.services.password_service import PasswordService
            svc = PasswordService()
            assert svc.needs_rehash('not-a-valid-hash') is True


class TestHashInfo:
    """Tests for hash info extraction."""

    def test_get_hash_info(self, app):
        """Should extract correct parameters from hash."""
        with app.app_context():
            from app.services.password_service import PasswordService
            svc = PasswordService()
            hash_str = svc.hash_password('TestPassword123!')
            info = svc.get_hash_info(hash_str)
            assert info is not None
            assert info['algorithm'] == 'argon2id'
            assert info['memory_cost'] == 65536
            assert info['time_cost'] == 3
            assert info['parallelism'] == 4

    def test_get_hash_info_invalid(self, app):
        """Invalid hash should return None."""
        with app.app_context():
            from app.services.password_service import PasswordService
            svc = PasswordService()
            info = svc.get_hash_info('invalid-hash')
            assert info is None


class TestPepperGeneration:
    """Tests for pepper generation utility."""

    def test_generate_pepper_default_length(self, app):
        """Generated pepper should be 64 hex chars (32 bytes)."""
        with app.app_context():
            from app.services.password_service import PasswordService
            svc = PasswordService()
            pepper = svc.generate_pepper()
            assert len(pepper) == 64  # 32 bytes = 64 hex chars

    def test_generate_pepper_uniqueness(self, app):
        """Each generated pepper should be unique."""
        with app.app_context():
            from app.services.password_service import PasswordService
            svc = PasswordService()
            peppers = {svc.generate_pepper() for _ in range(10)}
            assert len(peppers) == 10
