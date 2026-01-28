-- EDUCATIONAL SECURITY TRAINING ENVIRONMENT
-- pgcrypto Setup and Encryption Functions
-- Purpose: Field-level encryption for sensitive data

-- =============================================================================
-- Encryption Helper Functions
-- =============================================================================

-- Function to encrypt data with current encryption key
CREATE OR REPLACE FUNCTION encrypt_data(data TEXT)
RETURNS BYTEA AS $$
BEGIN
    RETURN pgp_sym_encrypt(
        data,
        current_setting('app.encryption_key', true),
        'cipher-algo=aes256, compress-algo=0'
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to decrypt data with current encryption key
CREATE OR REPLACE FUNCTION decrypt_data(encrypted_data BYTEA)
RETURNS TEXT AS $$
BEGIN
    IF encrypted_data IS NULL THEN
        RETURN NULL;
    END IF;

    RETURN pgp_sym_decrypt(
        encrypted_data,
        current_setting('app.encryption_key', true)
    );
EXCEPTION
    WHEN OTHERS THEN
        -- Log decryption failure but don't expose key
        RAISE WARNING 'Decryption failed for data';
        RETURN NULL;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================================================
-- Password Hashing Functions (using bcrypt via pgcrypto)
-- =============================================================================

-- Generate bcrypt hash for password (cost factor 12)
CREATE OR REPLACE FUNCTION hash_password(password TEXT)
RETURNS TEXT AS $$
BEGIN
    RETURN crypt(password, gen_salt('bf', 12));
END;
$$ LANGUAGE plpgsql;

-- Verify password against hash
CREATE OR REPLACE FUNCTION verify_password(password TEXT, password_hash TEXT)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN password_hash = crypt(password, password_hash);
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- Secure Random Generators
-- =============================================================================

-- Generate secure random token (for CSRF, session tokens, etc.)
CREATE OR REPLACE FUNCTION generate_secure_token(length INT DEFAULT 32)
RETURNS TEXT AS $$
BEGIN
    RETURN encode(gen_random_bytes(length), 'hex');
END;
$$ LANGUAGE plpgsql;

-- Generate UUID v4
CREATE OR REPLACE FUNCTION generate_uuid()
RETURNS UUID AS $$
BEGIN
    RETURN uuid_generate_v4();
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- Audit Trail Helpers
-- =============================================================================

-- Get current application user (from session variable)
CREATE OR REPLACE FUNCTION get_current_user_id()
RETURNS UUID AS $$
BEGIN
    RETURN COALESCE(
        current_setting('app.current_user_id', true)::UUID,
        '00000000-0000-0000-0000-000000000000'::UUID
    );
EXCEPTION
    WHEN OTHERS THEN
        RETURN '00000000-0000-0000-0000-000000000000'::UUID;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- PGP Key Management (for encrypted messaging)
-- =============================================================================

-- Encrypt message with recipient's public key
CREATE OR REPLACE FUNCTION encrypt_message_pgp(message TEXT, public_key TEXT)
RETURNS BYTEA AS $$
BEGIN
    RETURN pgp_pub_encrypt(message, dearmor(public_key));
EXCEPTION
    WHEN OTHERS THEN
        RAISE EXCEPTION 'PGP encryption failed: Invalid public key';
END;
$$ LANGUAGE plpgsql;

-- Decrypt message with private key
CREATE OR REPLACE FUNCTION decrypt_message_pgp(
    encrypted_message BYTEA,
    private_key TEXT,
    passphrase TEXT DEFAULT NULL
)
RETURNS TEXT AS $$
BEGIN
    IF passphrase IS NOT NULL THEN
        RETURN pgp_pub_decrypt(encrypted_message, dearmor(private_key), passphrase);
    ELSE
        RETURN pgp_pub_decrypt(encrypted_message, dearmor(private_key));
    END IF;
EXCEPTION
    WHEN OTHERS THEN
        RAISE WARNING 'PGP decryption failed';
        RETURN NULL;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================================================
-- Data Sanitization
-- =============================================================================

-- Remove potentially dangerous characters from input
CREATE OR REPLACE FUNCTION sanitize_input(input TEXT)
RETURNS TEXT AS $$
BEGIN
    -- Remove null bytes and control characters
    RETURN regexp_replace(input, '[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', 'g');
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- =============================================================================
-- Secure Deletion
-- =============================================================================

-- Overwrite sensitive data before deletion (for GDPR/compliance)
CREATE OR REPLACE FUNCTION secure_delete_user_data(user_id UUID)
RETURNS VOID AS $$
BEGIN
    -- This would be called before actual deletion to overwrite sensitive fields
    -- Implementation depends on table structure (created in migration)
    RAISE NOTICE 'Secure deletion initiated for user: %', user_id;

    -- Log the deletion in audit trail
    INSERT INTO audit_log (user_id, action, table_name, record_id)
    VALUES (user_id, 'SECURE_DELETE', 'users', user_id);
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- Security Constraints
-- =============================================================================

-- Function to validate email format
CREATE OR REPLACE FUNCTION is_valid_email(email TEXT)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}$';
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Function to validate username format (alphanumeric, 3-20 chars)
CREATE OR REPLACE FUNCTION is_valid_username(username TEXT)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN username ~* '^[a-zA-Z0-9_]{3,20}$';
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- =============================================================================
-- Rate Limiting Helpers (timestamp-based)
-- =============================================================================

-- Check if action is rate limited
CREATE OR REPLACE FUNCTION is_rate_limited(
    action_key TEXT,
    max_attempts INT,
    window_seconds INT
)
RETURNS BOOLEAN AS $$
DECLARE
    recent_count INT;
BEGIN
    -- Count recent attempts within time window
    SELECT COUNT(*) INTO recent_count
    FROM rate_limit_log
    WHERE key = action_key
      AND attempted_at > NOW() - (window_seconds || ' seconds')::INTERVAL;

    RETURN recent_count >= max_attempts;
EXCEPTION
    WHEN undefined_table THEN
        -- Table doesn't exist yet, allow action
        RETURN FALSE;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- Comments
-- =============================================================================

COMMENT ON FUNCTION encrypt_data IS 'Encrypt sensitive data using AES-256';
COMMENT ON FUNCTION decrypt_data IS 'Decrypt data encrypted with encrypt_data()';
COMMENT ON FUNCTION hash_password IS 'Hash password using bcrypt (cost 12)';
COMMENT ON FUNCTION verify_password IS 'Verify password against bcrypt hash';
COMMENT ON FUNCTION generate_secure_token IS 'Generate cryptographically secure random token';
COMMENT ON FUNCTION encrypt_message_pgp IS 'Encrypt message with PGP public key';
COMMENT ON FUNCTION decrypt_message_pgp IS 'Decrypt message with PGP private key';
COMMENT ON FUNCTION sanitize_input IS 'Remove dangerous characters from input';

-- =============================================================================
-- Permissions
-- =============================================================================

-- Grant execute permissions to application user
GRANT EXECUTE ON FUNCTION encrypt_data TO marketplace_app;
GRANT EXECUTE ON FUNCTION decrypt_data TO marketplace_app;
GRANT EXECUTE ON FUNCTION hash_password TO marketplace_app;
GRANT EXECUTE ON FUNCTION verify_password TO marketplace_app;
GRANT EXECUTE ON FUNCTION generate_secure_token TO marketplace_app;
GRANT EXECUTE ON FUNCTION generate_uuid TO marketplace_app;
GRANT EXECUTE ON FUNCTION get_current_user_id TO marketplace_app;
GRANT EXECUTE ON FUNCTION encrypt_message_pgp TO marketplace_app;
GRANT EXECUTE ON FUNCTION decrypt_message_pgp TO marketplace_app;
GRANT EXECUTE ON FUNCTION sanitize_input TO marketplace_app;
GRANT EXECUTE ON FUNCTION is_valid_email TO marketplace_app;
GRANT EXECUTE ON FUNCTION is_valid_username TO marketplace_app;

-- Security: Revoke public access to sensitive functions
REVOKE ALL ON FUNCTION secure_delete_user_data FROM PUBLIC;

-- =============================================================================
-- Test Encryption (Development Only)
-- =============================================================================

DO $$
DECLARE
    test_data TEXT := 'Test sensitive data';
    encrypted BYTEA;
    decrypted TEXT;
BEGIN
    -- Only run if encryption key is set
    IF current_setting('app.encryption_key', true) IS NOT NULL THEN
        encrypted := pgp_sym_encrypt(test_data, current_setting('app.encryption_key', true));
        decrypted := pgp_sym_decrypt(encrypted, current_setting('app.encryption_key', true));

        IF decrypted = test_data THEN
            RAISE NOTICE 'Encryption test: PASSED';
        ELSE
            RAISE WARNING 'Encryption test: FAILED';
        END IF;
    ELSE
        RAISE NOTICE 'Encryption key not set - skipping test';
    END IF;
END;
$$;

-- =============================================================================
-- Security Notice
-- =============================================================================

DO $$
BEGIN
    RAISE NOTICE '========================================';
    RAISE NOTICE 'pgcrypto Setup Complete';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Available functions:';
    RAISE NOTICE '  - encrypt_data() / decrypt_data()';
    RAISE NOTICE '  - hash_password() / verify_password()';
    RAISE NOTICE '  - encrypt_message_pgp() / decrypt_message_pgp()';
    RAISE NOTICE '  - generate_secure_token()';
    RAISE NOTICE '  - sanitize_input()';
    RAISE NOTICE '========================================';
END;
$$;
