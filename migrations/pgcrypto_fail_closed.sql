-- EDUCATIONAL SECURITY TRAINING ENVIRONMENT
-- Migration: encrypt_data()/decrypt_data() fail closed (improvement plan 2026-11, C1)
-- Date: 2026-11-08
--
-- Found by the first test run against PostgreSQL: encrypt_data() read
-- app.encryption_key, which nothing ever set. pgp_sym_encrypt() with a NULL key
-- returns NULL, so checkout stored every shipping name and address as NULL,
-- silently. decrypt_data() swallowed every error and returned NULL as well.
--
-- Order: apply this file, then deploy the code that passes DB_ENCRYPTION_KEY as
-- app.encryption_key in the connection options. In between, checkout of a
-- physical product fails loudly instead of losing the address. Same bodies as
-- postgres/pgcrypto-setup.sql.
--
-- Run as the postgres superuser (the functions are SECURITY DEFINER).

BEGIN;

-- Function to encrypt data with the session's encryption key.
-- The key is app.encryption_key, set by the application in the connection's
-- startup options (app/__init__.py, _pass_db_encryption_key). Fails closed: with
-- no key, pgp_sym_encrypt() would return NULL and the caller would store NULL --
-- exactly what happened to every shipping address until 2026-11-08.
CREATE OR REPLACE FUNCTION encrypt_data(data TEXT)
RETURNS BYTEA AS $$
DECLARE
    key TEXT := current_setting('app.encryption_key', true);
BEGIN
    IF data IS NULL THEN
        RETURN NULL;
    END IF;
    IF key IS NULL OR key = '' THEN
        RAISE EXCEPTION 'encrypt_data: no encryption key in this session (app.encryption_key)';
    END IF;
    RETURN pgp_sym_encrypt(data, key, 'cipher-algo=aes256, compress-algo=0');
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

-- Function to decrypt data encrypted with encrypt_data(). Fails closed too: a
-- missing or wrong key raises instead of returning NULL, which a caller would
-- read as "nothing on file". The error carries no key material.
CREATE OR REPLACE FUNCTION decrypt_data(encrypted_data BYTEA)
RETURNS TEXT AS $$
DECLARE
    key TEXT := current_setting('app.encryption_key', true);
BEGIN
    IF encrypted_data IS NULL THEN
        RETURN NULL;
    END IF;
    IF key IS NULL OR key = '' THEN
        RAISE EXCEPTION 'decrypt_data: no encryption key in this session (app.encryption_key)';
    END IF;
    RETURN pgp_sym_decrypt(encrypted_data, key);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

COMMIT;
