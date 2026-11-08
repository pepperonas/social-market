"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Improvement plan 2026-11, A1: the TOTP secret is encrypted at rest.

`users.two_factor_secret` held the base32 seed in plaintext. Anyone with a
database dump (a backup, a leaked pg_dump, an SQL injection) could compute
every user's current code -- the second factor collapsed into the first.

Now the seed lives in `two_factor_secret_enc` (Fernet, own key
TOTP_ENCRYPTION_KEY, independent of SECRET_KEY). The plaintext column is only
read during the transition: rows written before the change keep working, and
`flask encrypt-totp-secrets` moves them over without anyone having to enrol
again.
"""

import pyotp
import pytest
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text

KEY_A = Fernet.generate_key().decode()
KEY_B = Fernet.generate_key().decode()


def _raw(username):
    from app import db
    return db.session.execute(
        text('SELECT two_factor_secret, two_factor_secret_enc FROM users WHERE username = :u'),
        {'u': username}).one()


def _set_legacy_plaintext(user, secret):
    """What a row written before A1 looks like: plaintext only."""
    from app import db
    db.session.execute(
        text('UPDATE users SET two_factor_secret = :s, two_factor_secret_enc = NULL '
             'WHERE username = :u'), {'s': secret, 'u': user.username})
    db.session.commit()
    db.session.expire(user)


@pytest.fixture
def totp_key(app):
    saved = app.config.get('TOTP_ENCRYPTION_KEY')
    app.config['TOTP_ENCRYPTION_KEY'] = KEY_A
    yield
    app.config['TOTP_ENCRYPTION_KEY'] = saved


class TestStorage:
    def test_secret_is_stored_encrypted_not_in_plaintext(self, app, sample_user, totp_key):
        from app import db
        secret = pyotp.random_base32()
        sample_user.two_factor_secret = secret
        db.session.commit()

        plain, enc = _raw(sample_user.username)
        assert plain is None
        assert enc is not None and secret.encode() not in bytes(enc)

    def test_secret_reads_back(self, app, sample_user, totp_key):
        from app import db
        secret = pyotp.random_base32()
        sample_user.two_factor_secret = secret
        db.session.commit()
        db.session.expire(sample_user)

        assert sample_user.two_factor_secret == secret

    def test_clearing_removes_both_columns(self, app, sample_user, totp_key):
        from app import db
        sample_user.two_factor_secret = pyotp.random_base32()
        db.session.commit()
        sample_user.two_factor_secret = None
        db.session.commit()

        assert tuple(_raw(sample_user.username)) == (None, None)

    def test_survives_a_new_secret_key(self, app, sample_user, totp_key):
        """Rotating the session key must not lock 2FA users out."""
        from app import db
        secret = pyotp.random_base32()
        sample_user.two_factor_secret = secret
        db.session.commit()
        db.session.expire(sample_user)

        saved = app.config['SECRET_KEY']
        app.config['SECRET_KEY'] = 'another-session-key-entirely-' + 'x' * 20
        try:
            assert sample_user.two_factor_secret == secret
        finally:
            app.config['SECRET_KEY'] = saved

    def test_wrong_key_fails_closed(self, app, sample_user, totp_key):
        """A wrong key must not read as 'no 2FA configured'."""
        from app import db
        sample_user.two_factor_secret = pyotp.random_base32()
        db.session.commit()
        db.session.expire(sample_user)

        app.config['TOTP_ENCRYPTION_KEY'] = KEY_B
        with pytest.raises(InvalidToken):
            _ = sample_user.two_factor_secret


class TestTransition:
    def test_legacy_plaintext_row_still_works(self, app, sample_user, totp_key):
        secret = pyotp.random_base32()
        _set_legacy_plaintext(sample_user, secret)

        assert sample_user.two_factor_secret == secret

    def test_migration_command_encrypts_legacy_rows_losslessly(self, app, sample_user, totp_key):
        from app import db
        from app.cli import encrypt_totp_secrets
        secret = pyotp.random_base32()
        _set_legacy_plaintext(sample_user, secret)
        sample_user.two_factor_enabled = True
        db.session.commit()

        result = app.test_cli_runner().invoke(encrypt_totp_secrets)
        assert result.exit_code == 0, result.output

        db.session.expire(sample_user)
        plain, enc = _raw(sample_user.username)
        assert plain is None and enc is not None
        assert sample_user.two_factor_secret == secret
        assert sample_user.verify_totp(pyotp.TOTP(secret).now())

    def test_migration_command_is_idempotent(self, app, sample_user, totp_key):
        from app.cli import encrypt_totp_secrets
        secret = pyotp.random_base32()
        _set_legacy_plaintext(sample_user, secret)

        runner = app.test_cli_runner()
        assert runner.invoke(encrypt_totp_secrets).exit_code == 0
        second = runner.invoke(encrypt_totp_secrets)
        assert second.exit_code == 0, second.output
        assert sample_user.two_factor_secret == secret


class TestKeyRotation:
    def test_old_key_still_decrypts_after_rotation(self, app, sample_user, totp_key):
        from app import db
        secret = pyotp.random_base32()
        sample_user.two_factor_secret = secret
        db.session.commit()
        db.session.expire(sample_user)

        app.config['TOTP_ENCRYPTION_KEY'] = f'{KEY_B},{KEY_A}'
        assert sample_user.two_factor_secret == secret

    def test_command_reencrypts_under_the_new_key(self, app, sample_user, totp_key):
        from app import db
        from app.cli import encrypt_totp_secrets
        secret = pyotp.random_base32()
        sample_user.two_factor_secret = secret
        db.session.commit()

        app.config['TOTP_ENCRYPTION_KEY'] = f'{KEY_B},{KEY_A}'
        assert app.test_cli_runner().invoke(encrypt_totp_secrets).exit_code == 0

        db.session.expire(sample_user)
        app.config['TOTP_ENCRYPTION_KEY'] = KEY_B
        assert sample_user.two_factor_secret == secret


class TestProductionGuard:
    def test_development_key_stops_startup(self):
        from app import refuse_development_secrets, DEVELOPMENT_SECRETS
        config = {k: 'x' * 40 for k in DEVELOPMENT_SECRETS if k != 'TOTP_ENCRYPTION_KEY'}
        config['TOTP_ENCRYPTION_KEY'] = DEVELOPMENT_SECRETS['TOTP_ENCRYPTION_KEY']
        with pytest.raises(RuntimeError, match='TOTP_ENCRYPTION_KEY'):
            refuse_development_secrets(config)

    @pytest.mark.parametrize('value', ['', 'not-a-fernet-key', f'{KEY_A},garbage'])
    def test_unusable_key_stops_startup(self, value):
        from app import refuse_development_secrets, DEVELOPMENT_SECRETS
        config = {k: 'x' * 40 for k in DEVELOPMENT_SECRETS if k != 'TOTP_ENCRYPTION_KEY'}
        config['TOTP_ENCRYPTION_KEY'] = value
        with pytest.raises(RuntimeError, match='TOTP_ENCRYPTION_KEY'):
            refuse_development_secrets(config)

    def test_real_key_passes(self):
        from app import refuse_development_secrets, DEVELOPMENT_SECRETS
        config = {k: 'x' * 40 for k in DEVELOPMENT_SECRETS if k != 'TOTP_ENCRYPTION_KEY'}
        config['TOTP_ENCRYPTION_KEY'] = f'{KEY_A},{KEY_B}'
        refuse_development_secrets(config)
