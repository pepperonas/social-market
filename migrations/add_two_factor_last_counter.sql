-- Migration: Add TOTP replay protection to users table
-- Purpose: Remember the highest TOTP counter already accepted, so a code that
--          is still inside its validity window (+/- 30s) cannot be replayed.
-- Date: 2026-08-19

BEGIN;

ALTER TABLE users
ADD COLUMN IF NOT EXISTS two_factor_last_counter BIGINT;

COMMENT ON COLUMN users.two_factor_last_counter IS
    'Highest accepted TOTP time counter; codes at or below this are rejected as replays';

COMMIT;
