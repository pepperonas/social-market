-- Migration: Add session_version to users
-- Purpose: Part of the Flask-Login identifier ("<uuid>:<session_version>").
--          Raising it ends every session AND every remember-me cookie of a
--          user at once -- on password change and on "sign out everywhere".
--          Existing sessions carry the old bare-uuid identifier and are
--          refused once after deploy: everybody logs in again.
-- Date: 2026-11-06

BEGIN;

ALTER TABLE users
ADD COLUMN IF NOT EXISTS session_version INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN users.session_version IS
    'Bumped to invalidate all sessions and remember-me cookies of the user';

COMMIT;
