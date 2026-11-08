-- EDUCATIONAL SECURITY TRAINING ENVIRONMENT
-- Migration: TOTP seeds encrypted at rest (improvement plan 2026-11, A1)
-- Purpose: users.two_factor_secret held the base32 seed in plaintext, so a
--          database dump yielded every user's current code. The seed now lives
--          Fernet-encrypted in two_factor_secret_enc (key TOTP_ENCRYPTION_KEY,
--          application side -- the database never sees the key).
--
-- Order of operations (lossless, nobody has to enrol 2FA again):
--   1. this file          adds the column; the old column stays and is read
--   2. deploy the code    reads both columns, writes only the encrypted one
--   3. flask encrypt-totp-secrets   moves the remaining plaintext rows
--   4. later, separately  drop users.two_factor_secret (not part of this file:
--                         keeping it until step 3 is verified IS the rollback)
-- Date: 2026-11-08

BEGIN;

ALTER TABLE users
ADD COLUMN IF NOT EXISTS two_factor_secret_enc BYTEA;

COMMENT ON COLUMN users.two_factor_secret_enc IS
    'TOTP seed, Fernet-encrypted under TOTP_ENCRYPTION_KEY (MultiFernet, newest key first)';
COMMENT ON COLUMN users.two_factor_secret IS
    'DEPRECATED plaintext TOTP seed; read only during the transition, emptied by every write';

COMMIT;
