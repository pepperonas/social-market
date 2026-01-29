-- Migration: Add PGP key timestamps to users table
-- Purpose: Track when PGP keys were created/updated for audit purposes
-- Date: 2026-01-29

BEGIN;

-- Add timestamp columns for PGP key tracking
ALTER TABLE users
ADD COLUMN IF NOT EXISTS pgp_key_created_at TIMESTAMP WITHOUT TIME ZONE,
ADD COLUMN IF NOT EXISTS pgp_key_updated_at TIMESTAMP WITHOUT TIME ZONE,
ADD COLUMN IF NOT EXISTS pgp_key_created_by VARCHAR(50),  -- 'user', 'admin', 'cli'
ADD COLUMN IF NOT EXISTS pgp_key_source VARCHAR(50);       -- 'generated', 'uploaded', 'imported'

-- Add index for querying users by key creation date
CREATE INDEX IF NOT EXISTS idx_users_pgp_key_created_at ON users(pgp_key_created_at);

-- Update existing users with keys to set created_at to their account creation date
UPDATE users
SET pgp_key_created_at = created_at
WHERE pgp_public_key IS NOT NULL
  AND pgp_key_created_at IS NULL;

COMMIT;

-- Verification query (run separately to check):
-- SELECT username, pgp_public_key IS NOT NULL as has_key, pgp_key_created_at, pgp_key_updated_at, pgp_key_source FROM users WHERE pgp_public_key IS NOT NULL;
