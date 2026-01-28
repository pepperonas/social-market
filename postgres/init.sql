-- EDUCATIONAL SECURITY TRAINING ENVIRONMENT
-- PostgreSQL Initialization Script
-- Purpose: Database setup for secure marketplace training

-- =============================================================================
-- Database Configuration
-- =============================================================================

-- Set timezone
SET timezone = 'UTC';

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enable pgcrypto for encryption
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =============================================================================
-- Application User (Least Privilege)
-- =============================================================================

-- Create restricted application user
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'marketplace_app') THEN
        CREATE ROLE marketplace_app WITH LOGIN PASSWORD :'APP_USER_PASSWORD';
    END IF;
END
$$;

-- Grant minimal permissions
GRANT CONNECT ON DATABASE marketplace TO marketplace_app;
GRANT USAGE ON SCHEMA public TO marketplace_app;

-- Note: Table-specific permissions granted after table creation

-- =============================================================================
-- Audit User (Read-only for audit logs)
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'marketplace_audit') THEN
        CREATE ROLE marketplace_audit WITH LOGIN PASSWORD :'AUDIT_USER_PASSWORD';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE marketplace TO marketplace_audit;
GRANT USAGE ON SCHEMA public TO marketplace_audit;

-- =============================================================================
-- Security Settings
-- =============================================================================

-- Set statement timeout (prevent long-running queries)
ALTER DATABASE marketplace SET statement_timeout = '30s';

-- Set lock timeout
ALTER DATABASE marketplace SET lock_timeout = '10s';

-- Set idle session timeout
ALTER DATABASE marketplace SET idle_in_transaction_session_timeout = '5min';

-- =============================================================================
-- Application Configuration Table
-- =============================================================================

CREATE TABLE IF NOT EXISTS app_config (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Store encryption key reference (key itself in environment)
INSERT INTO app_config (key, value, description) VALUES
    ('encryption_enabled', 'true', 'Whether database encryption is enabled'),
    ('version', '1.0.0', 'Application version'),
    ('maintenance_mode', 'false', 'Whether maintenance mode is enabled');

-- =============================================================================
-- Comments
-- =============================================================================

COMMENT ON DATABASE marketplace IS 'Educational security training environment - NOT FOR PRODUCTION USE';
COMMENT ON EXTENSION "uuid-ossp" IS 'UUID generation functions';
COMMENT ON EXTENSION "pgcrypto" IS 'Cryptographic functions for data encryption';

-- =============================================================================
-- Security Notice
-- =============================================================================

DO $$
BEGIN
    RAISE NOTICE '========================================';
    RAISE NOTICE 'EDUCATIONAL SECURITY TRAINING ENVIRONMENT';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Database initialized successfully';
    RAISE NOTICE 'Extensions enabled: uuid-ossp, pgcrypto';
    RAISE NOTICE 'Security features: Statement timeout, lock timeout';
    RAISE NOTICE 'Least privilege user: marketplace_app';
    RAISE NOTICE '========================================';
END
$$;
