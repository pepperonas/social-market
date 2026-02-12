# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a **local, isolated training environment** for IT security education demonstrating secure marketplace architecture. It is NOT production code and NOT intended for deployment beyond authorized educational use.

**Critical Context:**
- Educational Purpose: IT security training, architecture study, defensive security research
- Legal Context: Authorized security education material (CloudCommand IT Security Training)
- Blue Team Focus: Defensive security perspective, identifying vulnerabilities for protection
- All security features include comprehensive logging and audit trails

## Development Environment

### Quick Start

```bash
# Start all services
docker-compose up -d

# Initialize database (first time only)
docker-compose exec app flask db upgrade
docker-compose exec app flask init-db

# Access application
open http://localhost:8080
```

### Container Names

The container naming is inconsistent due to historical docker-compose versions:
- **App**: `marketplace_app` (not `marketplace-app`)
- **Database**: `marketplace_postgres`
- **Redis**: `marketplace_redis`
- **Nginx**: `marketplace_nginx`

Always use `marketplace_app` when executing commands.

### Common Commands

```bash
# Access Flask shell
docker exec marketplace_app flask shell

# Run Flask CLI commands
docker exec marketplace_app flask <command>

# View application logs
docker logs marketplace_app -f

# Restart application (after code/template changes)
docker restart marketplace_app

# Execute SQL migrations
docker exec marketplace_postgres psql -U marketplace -d marketplace -f /migrations/migration_file.sql

# Access PostgreSQL
docker exec -it marketplace_postgres psql -U marketplace

# Access Redis CLI
docker exec -it marketplace_redis redis-cli -a <password>

# Rebuild after dependency changes
docker-compose down
docker-compose up -d --build
```

### Flask CLI Commands

```bash
# Database initialization
flask init-db              # Create tables and default categories
flask init-admin           # Create default admin user

# User management
flask create-user          # Interactive user creation
flask reset-password       # Reset user password

# PGP key management
flask generate-pgp-keys    # Generate RSA-4096 keypair for user
flask upload-pgp-key       # Upload existing PGP public key
flask show-pgp-audit       # View PGP key audit log

# Data management
flask seed-data            # Seed test data (buyers, vendors, products)
flask cleanup-old-data     # Clean up old messages, sessions

# Security
flask security-check       # Run security validation checks
flask generate-secret      # Generate secure random secrets

# Backup
flask backup-now           # Create encrypted backup
```

## Architecture Overview

### Application Factory Pattern

The app uses Flask's application factory pattern (`app/__init__.py`):

```python
from app import create_app, db

app = create_app()  # Creates configured Flask app
with app.app_context():
    # All database operations must be in app context
    user = User.query.first()
```

### Key Extensions Initialized

- **SQLAlchemy** (`db`): ORM for PostgreSQL
- **Flask-Login** (`login_manager`): User session management
- **Flask-Session** (`session`): Redis-backed sessions
- **Flask-Limiter** (`limiter`): Rate limiting with Redis storage
- **Flask-Talisman** (`Talisman`): Security headers, CSP with nonce support
- **CSRFProtect** (`csrf`): CSRF token validation
- **Celery** (`celery`): Background tasks

### Service Layer Architecture

All business logic lives in `app/services/`:

- **`password_service.py`**: Argon2id password hashing with pepper (64MB memory-hard)
- **`pgp_service.py`**: RSA-4096 PGP key generation, encryption/decryption
- **`audit_service.py`**: Comprehensive audit logging for security events
- **`crypto_service.py`**: General cryptographic utilities
- **`escrow_service.py`**: Multi-signature escrow simulation
- **`security_service.py`**: Security validation, threat detection
- **`image_service.py`**: Image metadata stripping, validation

**Important:** Always use service layer functions rather than implementing crypto/security logic directly in routes.

### Database Architecture

#### UUID Primary Keys

All models use UUID primary keys (not auto-increment integers):

```python
from uuid import uuid4

# Creating new records
user = User(
    id=uuid4(),  # Always generate UUID explicitly
    username='test'
)
```

#### Audit Logging

Every security-critical operation must be logged via `audit_service.py`:

```python
from app.services.audit_service import log_pgp_key_event

log_pgp_key_event(
    user_id=user.id,
    action='pgp_key_generated',
    key_fingerprint=fingerprint,
    created_by='user',  # or 'cli', 'admin'
    source='generated',  # or 'uploaded', 'imported'
    metadata={'username': user.username}
)
```

Audit logs include:
- `user_id`, `action`, `table_name`, `record_id`
- `old_values`, `new_values` (JSONB)
- `ip_address`, `user_agent`
- `status` ('success', 'failure'), `severity` ('info', 'warning', 'critical')
- `metadata` (JSONB for custom fields)

#### Field-Level Encryption

Sensitive fields are encrypted with pgcrypto:

```sql
-- Encrypt on insert
INSERT INTO messages (content_encrypted)
VALUES (pgp_sym_encrypt('message text', current_setting('app.encryption_key')));

-- Decrypt on read
SELECT pgp_sym_decrypt(content_encrypted, current_setting('app.encryption_key'))
FROM messages;
```

In Python models, encrypted fields are stored as `LargeBinary`.

## Security-Critical Features

### CSRF Protection

**All forms MUST include CSRF token:**

```html
<form method="POST">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
    <!-- form fields -->
</form>
```

Missing CSRF tokens cause 400 Bad Request errors with no detailed message (by design).

### Content Security Policy (CSP)

The app uses **nonce-based CSP** for inline scripts:

```html
<script nonce="{{ csp_nonce() }}">
    // Inline JavaScript here
</script>
```

**Never use inline scripts without the nonce** - they will be blocked by CSP.

CSP configuration in `app/__init__.py`:
- `script-src: 'self'` (allows nonce-based inline scripts)
- `style-src: 'self' 'unsafe-inline'` (Bootstrap requires inline styles)
- `frame-ancestors: 'none'` (prevents clickjacking)

### Rate Limiting

Routes have different rate limits based on sensitivity:

```python
@limiter.limit("10 per hour")  # Login attempts
@limiter.limit("3 per hour")   # PGP key generation (expensive)
@limiter.limit("20 per hour")  # Message sending
```

Rate limiting uses Redis storage. 429 errors indicate limit exceeded.

### Password Hashing (Argon2id)

**Always use `password_service.py` for password operations:**

```python
from app.services.password_service import PasswordService

pwd_service = PasswordService()

# Hash password (with pepper)
hashed = pwd_service.hash_password('plaintext')
user.password_hash = hashed

# Verify password
is_valid = pwd_service.verify_password('plaintext', user.password_hash)
```

Configuration (in `app/config.py`):
- Memory cost: 64 MB (65536 KB)
- Time cost: 3 iterations
- Parallelism: 4 threads
- Pepper: Server-side secret salt from `PASSWORD_PEPPER` env var

### PGP Encryption System

The messaging system uses **mandatory PGP encryption**:

#### Two Encryption Modes

1. **Auto-encrypt**: System encrypts with recipient's public key
   - Requires recipient to have `pgp_public_key` in database
   - User provides plaintext, system encrypts before storage
   - Validates message is NOT already PGP-encrypted

2. **Manual**: User provides pre-encrypted PGP message
   - User encrypted externally with recipient's public key
   - Validates message starts with `-----BEGIN PGP MESSAGE-----`
   - Validates message ends with `-----END PGP MESSAGE-----`

#### Zero-Knowledge Architecture

- Private keys are NEVER stored on server
- Messages stored encrypted in database (`content_encrypted` bytea field)
- Decryption requires user to provide private key + passphrase via AJAX
- Server performs decryption but never stores the key

#### Key Generation

Users can generate RSA-4096 keys via web UI (`/auth/pgp-keys`) or CLI:

```bash
# Generate new keypair
docker exec marketplace_app flask generate-pgp-keys --username buyer1

# Upload existing public key
docker exec marketplace_app flask upload-pgp-key --username buyer1 --key-file /path/to/key.asc
```

All key operations are logged with timestamps in `users` table and `audit_log`.

## Message Threading Architecture

Messages use a **flexible participant model** (not fixed buyer/vendor):

### Database Schema

```sql
CREATE TABLE message_threads (
    id UUID PRIMARY KEY,
    participant_1_id UUID NOT NULL,  -- First participant (sorted by UUID)
    participant_2_id UUID NOT NULL,  -- Second participant (sorted by UUID)
    buyer_id UUID,                    -- Legacy, nullable
    vendor_id UUID,                   -- Legacy, nullable
    subject VARCHAR(200),
    last_message_at TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE messages (
    id UUID PRIMARY KEY,
    thread_id UUID REFERENCES message_threads(id),
    sender_id UUID REFERENCES users(id),
    recipient_id UUID REFERENCES users(id),
    content_encrypted BYTEA NOT NULL,  -- PGP-encrypted content
    is_encrypted BOOLEAN DEFAULT TRUE,
    is_deleted_by_sender BOOLEAN DEFAULT FALSE,
    is_deleted_by_recipient BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Communication Matrix

- **Admin** ↔ All users (support, moderation)
- **Vendor** ↔ Buyers (customer service)
- **Buyers** ↔ Vendors (purchase inquiries)
- **Users** ↔ Admin (support requests)

Thread participants are sorted by UUID to ensure consistent ordering regardless of who initiates.

## Common Development Tasks

### Adding a New Route

1. Create route in appropriate blueprint (`app/routes/`)
2. Add CSRF token to all POST forms
3. Add rate limiting decorator for sensitive operations
4. Log security events to audit log
5. Restart app container: `docker restart marketplace_app`

### Adding a New Model

1. Create model in `app/models/`
2. Use UUID primary key: `id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid4)`
3. Add `created_at` and `updated_at` timestamps
4. Import in `app/models/__init__.py`
5. Create database migration if needed
6. Run migration: `docker exec marketplace_postgres psql ...`

### Database Migrations

This project uses **SQL migrations** (not Alembic):

1. Create SQL file in `migrations/` directory:
   ```sql
   -- migrations/add_new_column.sql
   ALTER TABLE users ADD COLUMN new_field VARCHAR(100);
   ```

2. Execute migration:
   ```bash
   docker exec marketplace_postgres psql -U marketplace -d marketplace -f /migrations/add_new_column.sql
   ```

3. Verify migration:
   ```bash
   docker exec marketplace_postgres psql -U marketplace -c "\d users"
   ```

### Template Updates

Templates are in `app/templates/` with Jinja2 inheritance:

- **Base template**: `base.html` (navbar, footer, flash messages, CSP nonce)
- **Auth**: `auth/` (login, register, profile, pgp_keys)
- **Messages**: `messages/` (inbox, thread, new_thread)
- **Marketplace**: `marketplace/` (index, product detail)
- **Admin**: `admin/` (dashboard, users, audit logs)

**After template changes**: `docker restart marketplace_app`

**Remember**: All inline scripts need `nonce="{{ csp_nonce() }}"`.

### Environment Variables

Critical environment variables in `.env`:

```bash
# Security (MUST be changed from defaults)
SECRET_KEY=                 # Flask secret key (64 hex chars)
DB_ENCRYPTION_KEY=          # Database field encryption (64 hex chars)
PASSWORD_PEPPER=            # Argon2id pepper (64 hex chars)

# Database
POSTGRES_PASSWORD=          # PostgreSQL password
REDIS_PASSWORD=             # Redis password

# Redis URLs (must expand nested variables for Docker)
REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0  # ❌ WRONG (Docker doesn't expand)
REDIS_URL=redis://:actual_password@redis:6379/0    # ✅ CORRECT

# Rate limiting
RATELIMIT_STORAGE_URL=redis://:${REDIS_PASSWORD}@redis:6379/1  # Must be fully expanded
```

**Important**: Docker Compose does NOT expand nested environment variables like `${REDIS_PASSWORD}`. Always use the actual values in Redis URLs.

## Testing

### Security Header Verification

```bash
# Check CSP, HSTS, X-Frame-Options
curl -I http://localhost:8080 | grep -E "Content-Security-Policy|Strict-Transport|X-Frame"
```

### Rate Limiting Verification

```bash
# Test login rate limit (should 429 after limit)
for i in {1..10}; do
    curl -X POST http://localhost:8080/auth/login \
         -d "username=test&password=test" \
         -o /dev/null -w "%{http_code}\n"
done
```

### Database Encryption Test

```bash
docker exec marketplace_postgres psql -U marketplace -d marketplace -c \
  "SELECT pgp_sym_encrypt('test', current_setting('app.encryption_key'));"
```

## Troubleshooting

### "Bad Request" on Form Submission

**Cause**: Missing CSRF token in form.

**Fix**: Add `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>` to form.

### "CSP Violation: script-src 'none'"

**Cause**: Inline script missing nonce attribute.

**Fix**: Add `nonce="{{ csp_nonce() }}"` to `<script>` tag.

### Redis Authentication Errors

**Cause**: Environment variables not expanded in `.env`.

**Fix**: Replace `${REDIS_PASSWORD}` with actual password value in all Redis URLs.

### Container Name Errors

**Cause**: Using wrong container name (e.g., `marketplace-app` instead of `marketplace_app`).

**Fix**: Always use underscore: `docker exec marketplace_app flask ...`

### PGP Key Has Fingerprint = None

**Cause**: Key uploaded without proper fingerprint extraction.

**Fix**: Regenerate key using CLI:
```bash
docker exec marketplace_app flask generate-pgp-keys --username <username>
```

## Documentation References

- **`docs/PASSWORD_SECURITY.md`**: Argon2id implementation details, threat model
- **`docs/PGP_KEYS.md`**: RSA-4096 key generation, client integration
- **`docs/MESSAGING.md`**: Encrypted messaging architecture, API endpoints
- **`docs/ARCHITECTURE.md`**: System architecture, security layers
- **`docs/SECURITY.md`**: Threat model, security controls, hardening checklist
- **`LOGIN_CREDENTIALS.md`**: Default user accounts

## Legal and Ethical Guidelines

When working in this codebase:

1. **Always include educational disclaimers** in new files
2. **Never implement features for illegal activities** (enforce legal product categories)
3. **Focus on defensive security** (blue team perspective)
4. **Document security rationale** for all security-critical code
5. **Maintain audit logging** for all security operations
6. **Test security controls** before committing changes

This is an educational security training environment. All features should enhance understanding of secure system architecture and defensive security practices.
