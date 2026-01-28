-- EDUCATIONAL SECURITY TRAINING ENVIRONMENT
-- Audit Logging Setup
-- Purpose: Complete audit trail for security monitoring

-- =============================================================================
-- Audit Log Table
-- =============================================================================

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    user_id UUID,
    session_id VARCHAR(255),
    ip_address INET,
    user_agent TEXT,
    action VARCHAR(50) NOT NULL,
    table_name VARCHAR(100),
    record_id UUID,
    old_values JSONB,
    new_values JSONB,
    query TEXT,
    status VARCHAR(20) DEFAULT 'success',
    error_message TEXT,
    severity VARCHAR(20) DEFAULT 'info',
    metadata JSONB
);

-- Indexes for fast querying
CREATE INDEX idx_audit_log_timestamp ON audit_log(timestamp DESC);
CREATE INDEX idx_audit_log_user_id ON audit_log(user_id);
CREATE INDEX idx_audit_log_action ON audit_log(action);
CREATE INDEX idx_audit_log_table_name ON audit_log(table_name);
CREATE INDEX idx_audit_log_severity ON audit_log(severity);
CREATE INDEX idx_audit_log_status ON audit_log(status);

-- Partition by month for better performance (optional, for large deployments)
-- CREATE TABLE audit_log_2025_01 PARTITION OF audit_log
--     FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');

-- =============================================================================
-- Authentication Audit Log
-- =============================================================================

CREATE TABLE IF NOT EXISTS auth_log (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    username VARCHAR(255),
    user_id UUID,
    action VARCHAR(50) NOT NULL,  -- login_success, login_failed, logout, 2fa_success, 2fa_failed, etc.
    ip_address INET,
    user_agent TEXT,
    session_id VARCHAR(255),
    failure_reason VARCHAR(255),
    metadata JSONB
);

-- Indexes
CREATE INDEX idx_auth_log_timestamp ON auth_log(timestamp DESC);
CREATE INDEX idx_auth_log_user_id ON auth_log(user_id);
CREATE INDEX idx_auth_log_username ON auth_log(username);
CREATE INDEX idx_auth_log_action ON auth_log(action);
CREATE INDEX idx_auth_log_ip ON auth_log(ip_address);

-- =============================================================================
-- Security Events Log
-- =============================================================================

CREATE TABLE IF NOT EXISTS security_events (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    event_type VARCHAR(100) NOT NULL,  -- rate_limit_exceeded, suspicious_activity, etc.
    severity VARCHAR(20) NOT NULL,     -- critical, high, medium, low, info
    source VARCHAR(100),               -- component that detected the event
    user_id UUID,
    ip_address INET,
    description TEXT NOT NULL,
    metadata JSONB,
    resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMPTZ,
    resolved_by UUID
);

-- Indexes
CREATE INDEX idx_security_events_timestamp ON security_events(timestamp DESC);
CREATE INDEX idx_security_events_type ON security_events(event_type);
CREATE INDEX idx_security_events_severity ON security_events(severity);
CREATE INDEX idx_security_events_resolved ON security_events(resolved);

-- =============================================================================
-- Rate Limiting Log
-- =============================================================================

CREATE TABLE IF NOT EXISTS rate_limit_log (
    id BIGSERIAL PRIMARY KEY,
    key VARCHAR(255) NOT NULL,         -- e.g., "login:192.168.1.1"
    attempted_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    ip_address INET,
    user_id UUID,
    action VARCHAR(100)
);

-- Indexes
CREATE INDEX idx_rate_limit_log_key ON rate_limit_log(key, attempted_at DESC);
CREATE INDEX idx_rate_limit_log_ip ON rate_limit_log(ip_address);

-- Auto-cleanup old rate limit logs (keep 24 hours)
CREATE INDEX idx_rate_limit_log_cleanup ON rate_limit_log(attempted_at)
    WHERE attempted_at < NOW() - INTERVAL '24 hours';

-- =============================================================================
-- Admin Actions Log
-- =============================================================================

CREATE TABLE IF NOT EXISTS admin_actions (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    admin_user_id UUID NOT NULL,
    action VARCHAR(100) NOT NULL,
    target_type VARCHAR(50),          -- user, product, transaction, etc.
    target_id UUID,
    before_state JSONB,
    after_state JSONB,
    reason TEXT,
    ip_address INET,
    session_id VARCHAR(255)
);

-- Indexes
CREATE INDEX idx_admin_actions_timestamp ON admin_actions(timestamp DESC);
CREATE INDEX idx_admin_actions_admin ON admin_actions(admin_user_id);
CREATE INDEX idx_admin_actions_action ON admin_actions(action);
CREATE INDEX idx_admin_actions_target ON admin_actions(target_type, target_id);

-- =============================================================================
-- Transaction Audit Log
-- =============================================================================

CREATE TABLE IF NOT EXISTS transaction_audit (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    transaction_id UUID NOT NULL,
    buyer_id UUID NOT NULL,
    vendor_id UUID NOT NULL,
    product_id UUID NOT NULL,
    action VARCHAR(50) NOT NULL,      -- created, paid, shipped, completed, disputed, refunded, etc.
    amount DECIMAL(12, 2),
    status VARCHAR(50),
    metadata JSONB
);

-- Indexes
CREATE INDEX idx_transaction_audit_timestamp ON transaction_audit(timestamp DESC);
CREATE INDEX idx_transaction_audit_transaction_id ON transaction_audit(transaction_id);
CREATE INDEX idx_transaction_audit_buyer ON transaction_audit(buyer_id);
CREATE INDEX idx_transaction_audit_vendor ON transaction_audit(vendor_id);

-- =============================================================================
-- Message Audit Log (for encrypted messages)
-- =============================================================================

CREATE TABLE IF NOT EXISTS message_audit (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    message_id UUID NOT NULL,
    sender_id UUID NOT NULL,
    recipient_id UUID NOT NULL,
    action VARCHAR(50) NOT NULL,      -- sent, read, deleted
    encrypted BOOLEAN DEFAULT TRUE,
    metadata JSONB
);

-- Indexes
CREATE INDEX idx_message_audit_timestamp ON message_audit(timestamp DESC);
CREATE INDEX idx_message_audit_message_id ON message_audit(message_id);
CREATE INDEX idx_message_audit_sender ON message_audit(sender_id);
CREATE INDEX idx_message_audit_recipient ON message_audit(recipient_id);

-- =============================================================================
-- Audit Trigger Function
-- =============================================================================

-- Generic audit trigger function for tables
CREATE OR REPLACE FUNCTION audit_trigger_func()
RETURNS TRIGGER AS $$
DECLARE
    audit_user_id UUID;
    audit_session_id TEXT;
BEGIN
    -- Get current user from session
    audit_user_id := get_current_user_id();
    audit_session_id := current_setting('app.session_id', true);

    IF TG_OP = 'INSERT' THEN
        INSERT INTO audit_log (
            user_id, session_id, action, table_name, record_id, new_values
        ) VALUES (
            audit_user_id,
            audit_session_id,
            'INSERT',
            TG_TABLE_NAME,
            NEW.id,
            to_jsonb(NEW)
        );
        RETURN NEW;

    ELSIF TG_OP = 'UPDATE' THEN
        INSERT INTO audit_log (
            user_id, session_id, action, table_name, record_id, old_values, new_values
        ) VALUES (
            audit_user_id,
            audit_session_id,
            'UPDATE',
            TG_TABLE_NAME,
            NEW.id,
            to_jsonb(OLD),
            to_jsonb(NEW)
        );
        RETURN NEW;

    ELSIF TG_OP = 'DELETE' THEN
        INSERT INTO audit_log (
            user_id, session_id, action, table_name, record_id, old_values
        ) VALUES (
            audit_user_id,
            audit_session_id,
            'DELETE',
            TG_TABLE_NAME,
            OLD.id,
            to_jsonb(OLD)
        );
        RETURN OLD;
    END IF;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================================================
-- Helper Functions
-- =============================================================================

-- Log authentication event
CREATE OR REPLACE FUNCTION log_auth_event(
    p_username VARCHAR,
    p_user_id UUID,
    p_action VARCHAR,
    p_ip_address INET,
    p_user_agent TEXT,
    p_session_id VARCHAR DEFAULT NULL,
    p_failure_reason VARCHAR DEFAULT NULL,
    p_metadata JSONB DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    INSERT INTO auth_log (
        username, user_id, action, ip_address, user_agent,
        session_id, failure_reason, metadata
    ) VALUES (
        p_username, p_user_id, p_action, p_ip_address, p_user_agent,
        p_session_id, p_failure_reason, p_metadata
    );
END;
$$ LANGUAGE plpgsql;

-- Log security event
CREATE OR REPLACE FUNCTION log_security_event(
    p_event_type VARCHAR,
    p_severity VARCHAR,
    p_source VARCHAR,
    p_description TEXT,
    p_user_id UUID DEFAULT NULL,
    p_ip_address INET DEFAULT NULL,
    p_metadata JSONB DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    INSERT INTO security_events (
        event_type, severity, source, user_id, ip_address, description, metadata
    ) VALUES (
        p_event_type, p_severity, p_source, p_user_id, p_ip_address, p_description, p_metadata
    );

    -- Auto-alert on critical events
    IF p_severity = 'critical' THEN
        RAISE WARNING 'CRITICAL SECURITY EVENT: % - %', p_event_type, p_description;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Log rate limit attempt
CREATE OR REPLACE FUNCTION log_rate_limit(
    p_key VARCHAR,
    p_ip_address INET,
    p_user_id UUID DEFAULT NULL,
    p_action VARCHAR DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    INSERT INTO rate_limit_log (key, ip_address, user_id, action)
    VALUES (p_key, p_ip_address, p_user_id, p_action);
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- Cleanup Functions
-- =============================================================================

-- Clean up old rate limit logs (called by scheduled task)
CREATE OR REPLACE FUNCTION cleanup_rate_limit_logs()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM rate_limit_log
    WHERE attempted_at < NOW() - INTERVAL '24 hours';

    GET DIAGNOSTICS deleted_count = ROW_COUNT;

    RAISE NOTICE 'Cleaned up % old rate limit log entries', deleted_count;

    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Archive old audit logs (move to archive table or delete based on policy)
CREATE OR REPLACE FUNCTION archive_audit_logs(retention_days INTEGER DEFAULT 365)
RETURNS INTEGER AS $$
DECLARE
    archived_count INTEGER;
BEGIN
    -- For educational purposes, we just delete
    -- In production, would move to archive table or external storage

    DELETE FROM audit_log
    WHERE timestamp < NOW() - (retention_days || ' days')::INTERVAL;

    GET DIAGNOSTICS archived_count = ROW_COUNT;

    RAISE NOTICE 'Archived % audit log entries older than % days', archived_count, retention_days;

    RETURN archived_count;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- Audit Query Helpers
-- =============================================================================

-- Get recent failed login attempts for user
CREATE OR REPLACE FUNCTION get_failed_login_attempts(
    p_username VARCHAR,
    p_minutes INTEGER DEFAULT 15
)
RETURNS INTEGER AS $$
DECLARE
    attempt_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO attempt_count
    FROM auth_log
    WHERE username = p_username
      AND action = 'login_failed'
      AND timestamp > NOW() - (p_minutes || ' minutes')::INTERVAL;

    RETURN attempt_count;
END;
$$ LANGUAGE plpgsql;

-- Get recent suspicious activities
CREATE OR REPLACE FUNCTION get_recent_security_events(
    p_hours INTEGER DEFAULT 24,
    p_severity VARCHAR DEFAULT NULL
)
RETURNS TABLE (
    event_type VARCHAR,
    severity VARCHAR,
    count BIGINT,
    last_seen TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        e.event_type,
        e.severity,
        COUNT(*) as count,
        MAX(e.timestamp) as last_seen
    FROM security_events e
    WHERE e.timestamp > NOW() - (p_hours || ' hours')::INTERVAL
      AND (p_severity IS NULL OR e.severity = p_severity)
    GROUP BY e.event_type, e.severity
    ORDER BY count DESC, last_seen DESC;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- Permissions
-- =============================================================================

-- Grant permissions to application user
GRANT SELECT, INSERT ON audit_log TO marketplace_app;
GRANT SELECT, INSERT ON auth_log TO marketplace_app;
GRANT SELECT, INSERT ON security_events TO marketplace_app;
GRANT SELECT, INSERT, DELETE ON rate_limit_log TO marketplace_app;
GRANT SELECT, INSERT ON admin_actions TO marketplace_app;
GRANT SELECT, INSERT ON transaction_audit TO marketplace_app;
GRANT SELECT, INSERT ON message_audit TO marketplace_app;

-- Grant execute permissions on functions
GRANT EXECUTE ON FUNCTION log_auth_event TO marketplace_app;
GRANT EXECUTE ON FUNCTION log_security_event TO marketplace_app;
GRANT EXECUTE ON FUNCTION log_rate_limit TO marketplace_app;
GRANT EXECUTE ON FUNCTION get_failed_login_attempts TO marketplace_app;

-- Grant read-only access to audit user
GRANT SELECT ON audit_log TO marketplace_audit;
GRANT SELECT ON auth_log TO marketplace_audit;
GRANT SELECT ON security_events TO marketplace_audit;
GRANT SELECT ON admin_actions TO marketplace_audit;

-- Sequence permissions
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO marketplace_app;

-- =============================================================================
-- Comments
-- =============================================================================

COMMENT ON TABLE audit_log IS 'Complete audit trail of all database operations';
COMMENT ON TABLE auth_log IS 'Authentication and authorization events';
COMMENT ON TABLE security_events IS 'Security-related events and alerts';
COMMENT ON TABLE rate_limit_log IS 'Rate limiting attempts (24h retention)';
COMMENT ON TABLE admin_actions IS 'Administrative actions for accountability';
COMMENT ON TABLE transaction_audit IS 'Transaction lifecycle audit trail';
COMMENT ON TABLE message_audit IS 'Encrypted message audit trail';

COMMENT ON FUNCTION audit_trigger_func IS 'Generic trigger function for auditing table changes';
COMMENT ON FUNCTION log_auth_event IS 'Log authentication event';
COMMENT ON FUNCTION log_security_event IS 'Log security event with auto-alerting';
COMMENT ON FUNCTION log_rate_limit IS 'Log rate limit attempt';
COMMENT ON FUNCTION cleanup_rate_limit_logs IS 'Clean up rate limit logs older than 24h';
COMMENT ON FUNCTION archive_audit_logs IS 'Archive/delete audit logs based on retention policy';

-- =============================================================================
-- Security Notice
-- =============================================================================

DO $$
BEGIN
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Audit Logging Setup Complete';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Audit tables created:';
    RAISE NOTICE '  - audit_log (general audit trail)';
    RAISE NOTICE '  - auth_log (authentication events)';
    RAISE NOTICE '  - security_events (security alerts)';
    RAISE NOTICE '  - rate_limit_log (rate limiting)';
    RAISE NOTICE '  - admin_actions (admin accountability)';
    RAISE NOTICE '  - transaction_audit (transaction trail)';
    RAISE NOTICE '  - message_audit (message audit)';
    RAISE NOTICE '========================================';
END;
$$;
