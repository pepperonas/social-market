-- EDUCATIONAL SECURITY TRAINING ENVIRONMENT
-- Migration: product moderation trail (improvement plan 2026-11, B1)
-- Date: 2026-11-08
--
-- products.is_approved existed from the start, with the comment "Admin approval
-- required" -- and vendor.py set it to True itself. There was no queue, no
-- admin decision, no record of who approved what. These columns hold the
-- decision: why a listing was rejected, when, and by which admin.
--
-- Additive and nullable: the running code ignores them, so apply this BEFORE
-- deploying the code that reads them. Existing rows keep their is_approved
-- value; a NULL moderated_by on an approved row means "approved before the
-- queue existed".

BEGIN;

ALTER TABLE products ADD COLUMN IF NOT EXISTS rejection_reason TEXT;
ALTER TABLE products ADD COLUMN IF NOT EXISTS moderated_at TIMESTAMP;
ALTER TABLE products ADD COLUMN IF NOT EXISTS moderated_by UUID REFERENCES users(id);

COMMIT;
