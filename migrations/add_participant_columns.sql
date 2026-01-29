-- Migration: Add participant_1_id and participant_2_id to message_threads
-- Purpose: Enable flexible communication (Admin, Vendor, Buyer)
-- Date: 2026-01-29

BEGIN;

-- Add new columns (nullable first to avoid errors)
ALTER TABLE message_threads
ADD COLUMN IF NOT EXISTS participant_1_id UUID,
ADD COLUMN IF NOT EXISTS participant_2_id UUID;

-- Migrate existing data: buyer_id -> participant_1_id, vendor_id -> participant_2_id
-- Ensure participant_1_id is always the "lower" UUID for consistency
UPDATE message_threads
SET
  participant_1_id = CASE
    WHEN buyer_id < vendor_id THEN buyer_id
    ELSE vendor_id
  END,
  participant_2_id = CASE
    WHEN buyer_id < vendor_id THEN vendor_id
    ELSE buyer_id
  END
WHERE participant_1_id IS NULL AND participant_2_id IS NULL;

-- Make new columns NOT NULL now that data is migrated
ALTER TABLE message_threads
ALTER COLUMN participant_1_id SET NOT NULL,
ALTER COLUMN participant_2_id SET NOT NULL;

-- Make old columns nullable (keep for backward compatibility)
ALTER TABLE message_threads
ALTER COLUMN buyer_id DROP NOT NULL,
ALTER COLUMN vendor_id DROP NOT NULL;

-- Add indexes for new columns
CREATE INDEX IF NOT EXISTS idx_thread_participant_1 ON message_threads(participant_1_id);
CREATE INDEX IF NOT EXISTS idx_thread_participant_2 ON message_threads(participant_2_id);

-- Update unique constraint to use new columns
-- First drop old constraint
ALTER TABLE message_threads DROP CONSTRAINT IF EXISTS uq_thread_participants_order;

-- Add new constraint for participant-based uniqueness
-- Only one thread per pair of participants (order_id can be null for general messaging)
CREATE UNIQUE INDEX IF NOT EXISTS uq_thread_participants_order_new
ON message_threads(
  LEAST(participant_1_id, participant_2_id),
  GREATEST(participant_1_id, participant_2_id),
  COALESCE(order_id, '00000000-0000-0000-0000-000000000000'::UUID)
);

-- Add foreign keys for new columns
ALTER TABLE message_threads
ADD CONSTRAINT message_threads_participant_1_fkey
  FOREIGN KEY (participant_1_id) REFERENCES users(id),
ADD CONSTRAINT message_threads_participant_2_fkey
  FOREIGN KEY (participant_2_id) REFERENCES users(id);

COMMIT;

-- Verification query (run separately to check):
-- SELECT id, buyer_id, vendor_id, participant_1_id, participant_2_id FROM message_threads LIMIT 10;
