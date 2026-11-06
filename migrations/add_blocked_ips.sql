-- Migration: manual IP blocking (review round 3, step 5 / P1-24)
-- Date: 2026-11-06
--
-- SecurityService has had block_ip / is_ip_blocked since the beginning, and a
-- test suite for them -- but the table existed only in the SQLite test schema
-- and in an unused SECURITY_TABLES_SQL string. Nothing called the service, so
-- nothing failed. Now a before_request hook checks every request.
--
-- expires_at / created_at are naive UTC like every model column; the app binds
-- its own "now" instead of NOW(), which in this database's session time zone
-- (Europe/Berlin) would expire blocks one or two hours early.
--
-- Canary tokens and honeypots are NOT created here: they stay unwired.

BEGIN;

CREATE TABLE IF NOT EXISTS blocked_ips (
    id SERIAL PRIMARY KEY,
    ip_address INET NOT NULL UNIQUE,
    reason TEXT NOT NULL,
    blocked_by VARCHAR(100) DEFAULT 'system',
    expires_at TIMESTAMP,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_blocked_ips_expires ON blocked_ips(expires_at);

COMMIT;
