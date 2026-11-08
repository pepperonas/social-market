-- EDUCATIONAL SECURITY TRAINING ENVIRONMENT
-- Migration: audit indexes that never got created (improvement plan 2026-11, C1)
-- Date: 2026-11-08
--
-- postgres/audit-logging.sql had an index whose predicate called NOW(). An
-- index predicate must be IMMUTABLE, so the script stopped there on every fresh
-- database ("functions in index predicate must be marked IMMUTABLE"). On the
-- live server that left the rate_limit_log cleanup index and every index of
-- admin_actions, transaction_audit and message_audit missing. Found by the first
-- PostgreSQL test run, which builds its schema from that script.
--
-- Idempotent (IF NOT EXISTS): a no-op where the corrected script already ran.
-- Run as the postgres superuser.

BEGIN;

CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_table_name ON audit_log(table_name);
CREATE INDEX IF NOT EXISTS idx_audit_log_severity ON audit_log(severity);
CREATE INDEX IF NOT EXISTS idx_audit_log_status ON audit_log(status);
CREATE INDEX IF NOT EXISTS idx_auth_log_timestamp ON auth_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_auth_log_user_id ON auth_log(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_log_username ON auth_log(username);
CREATE INDEX IF NOT EXISTS idx_auth_log_action ON auth_log(action);
CREATE INDEX IF NOT EXISTS idx_auth_log_ip ON auth_log(ip_address);
CREATE INDEX IF NOT EXISTS idx_security_events_timestamp ON security_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_security_events_type ON security_events(event_type);
CREATE INDEX IF NOT EXISTS idx_security_events_severity ON security_events(severity);
CREATE INDEX IF NOT EXISTS idx_security_events_resolved ON security_events(resolved);
CREATE INDEX IF NOT EXISTS idx_rate_limit_log_key ON rate_limit_log(key, attempted_at DESC);
CREATE INDEX IF NOT EXISTS idx_rate_limit_log_ip ON rate_limit_log(ip_address);
CREATE INDEX IF NOT EXISTS idx_rate_limit_log_cleanup ON rate_limit_log(attempted_at);
CREATE INDEX IF NOT EXISTS idx_admin_actions_timestamp ON admin_actions(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_admin_actions_admin ON admin_actions(admin_user_id);
CREATE INDEX IF NOT EXISTS idx_admin_actions_action ON admin_actions(action);
CREATE INDEX IF NOT EXISTS idx_admin_actions_target ON admin_actions(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_transaction_audit_timestamp ON transaction_audit(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_transaction_audit_transaction_id ON transaction_audit(transaction_id);
CREATE INDEX IF NOT EXISTS idx_transaction_audit_buyer ON transaction_audit(buyer_id);
CREATE INDEX IF NOT EXISTS idx_transaction_audit_vendor ON transaction_audit(vendor_id);
CREATE INDEX IF NOT EXISTS idx_message_audit_timestamp ON message_audit(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_message_audit_message_id ON message_audit(message_id);
CREATE INDEX IF NOT EXISTS idx_message_audit_sender ON message_audit(sender_id);
CREATE INDEX IF NOT EXISTS idx_message_audit_recipient ON message_audit(recipient_id);

COMMIT;
