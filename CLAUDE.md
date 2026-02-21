# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Context

Educational IT security training environment (CloudCommand). Flask-based marketplace demonstrating defense-in-depth architecture. Blue team / defensive security focus. All new files must include educational disclaimers. Never implement features for illegal activities.

## Commands

```bash
# Build & run
docker-compose up -d
docker-compose up -d --build          # after dependency changes

# Restart after code/template changes
docker restart marketplace_app

# Database init (first time)
docker exec marketplace_app flask init-db
docker exec marketplace_app flask init-admin
docker exec marketplace_app flask seed-data

# SQL migrations (not Alembic)
docker exec marketplace_postgres psql -U marketplace -d marketplace -f /migrations/<file>.sql

# Tests (SQLite in-memory, no Docker needed)
pytest tests/ -v
pytest tests/test_auth.py -v                          # single file
pytest tests/ -v --cov=app --cov-report=term-missing  # with coverage

# Security scan
./scripts/security-scan.sh

# Access services
docker exec marketplace_app flask shell
docker exec -it marketplace_postgres psql -U marketplace
```

**Container names use underscores**: `marketplace_app`, `marketplace_postgres`, `marketplace_redis`, `marketplace_nginx`.

App at http://localhost:8080. Default creds in `LOGIN_CREDENTIALS.md`.

## Architecture

### Request Flow

```
Nginx (:8080) → Gunicorn → Flask App → PostgreSQL + Redis
                              ↓
                     SecurityHeadersMiddleware (X-Request-ID)
                              ↓
                     Flask-Talisman (CSP with nonce, HSTS)
                              ↓
                     Blueprint routes → Service layer → DB
```

### Application Factory

`app/__init__.py` → `create_app()`. Extensions initialized: SQLAlchemy (`db`), Flask-Login, Flask-Session (Redis), Flask-Limiter (Redis), Flask-Talisman (nonce-based CSP), CSRFProtect (`csrf`), Celery.

### Blueprint → Route Mapping

| Blueprint | Prefix | Access | Key file |
|-----------|--------|--------|----------|
| `marketplace_bp` | `/` | Public | `routes/marketplace.py` |
| `auth_bp` | `/auth` | Public/Auth | `routes/auth.py` |
| `vendor_bp` | `/vendor` | `@vendor_required` | `routes/vendor.py` |
| `buyer_bp` | `/buyer` | `@login_required` | `routes/buyer.py` |
| `admin_bp` | `/admin` | `@admin_required` | `routes/admin.py` |
| `messages_bp` | `/messages` | Auth | `routes/messages.py` |
| `cart_bp` | `/cart` | Auth | `routes/cart.py` |
| `account_bp` | `/account` | Auth | `routes/account.py` |

### Service Layer

All crypto/security logic lives in `app/services/` — never implement directly in routes:

- **`password_service.py`**: Argon2id hashing with pepper. Use `get_password_service()` singleton. User model's `set_password()`/`check_password()` call this internally.
- **`audit_service.py`**: Calls PostgreSQL stored procedures (`log_auth_event`, `log_security_event`, `log_admin_action`). Parameter order must match SQL signatures in `postgres/audit-logging.sql`.
- **`image_service.py`**: EXIF stripping, validation, thumbnails. Use `get_image_service()`.
- **`pgp_service.py`**: RSA-4096 key generation, encrypt/decrypt.

### Database

- **PostgreSQL** with pgcrypto extension. All models use **UUID primary keys**.
- Stored procedures for audit logging (see `postgres/audit-logging.sql`).
- Encrypted fields stored as `LargeBinary` (pgcrypto `pgp_sym_encrypt`).
- SSL connections enabled (`sslmode: prefer` in `config.py`).

### Session Management

Redis-backed sessions (Flask-Session). Session invalidation on password change scans Redis keys matching `SESSION_KEY_PREFIX` and deletes sessions belonging to the user (see `_invalidate_other_sessions` in `routes/account.py`).

### Security Middleware

`app/middleware/security_headers.py`: WSGI middleware that generates/propagates `X-Request-ID` (from Nginx or auto-generated UUID), stored in `g.request_id` via `before_request`.

## Conventions

### Forms & Templates

- All POST forms: `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>`
- All inline scripts: `nonce="{{ csp_nonce() }}"`
- CSP violations report to `POST /admin/csp-report-uri` (CSRF-exempt)
- Base template: `app/templates/base.html`

### Rate Limiting

```python
@limiter.limit("20 per minute")  # Login
@limiter.limit("3 per hour")     # PGP key generation
@limiter.limit("1 per day")      # Data export
```

### Adding a Route

1. Add to appropriate blueprint in `app/routes/`
2. Use `@admin_required` or `@vendor_required` decorators for role-gated routes
3. Add CSRF token to POST forms
4. Log security events via `audit_service.py`
5. `docker restart marketplace_app`

### User Roles

`User.role` field: `buyer`, `vendor`, `admin`. Vendors must also have `is_vendor_approved=True` — `user.is_vendor()` checks both. Unapproved vendors return `False` for `is_vendor()`.

### Testing

Tests in `tests/` use SQLite in-memory (configured in `conftest.py`). PostgreSQL stored procedures are not available — audit service calls should be mocked via the `mock_audit` fixture. Test fixtures provide `sample_user`, `sample_vendor`, `sample_admin`, and pre-authenticated clients (`auth_client`, `vendor_client`, `admin_client`).

### CI/CD

`.github/workflows/ci.yml`: 3 jobs — Lint (flake8 + bandit), Test (pytest with PostgreSQL + Redis services), Security (pip-audit).

## Gotchas

- **Docker Compose does NOT expand nested env vars** like `${REDIS_PASSWORD}` in `.env`. Use literal values in Redis URLs.
- **Audit `log_security_event` parameter order**: `(event_type, severity, 'application', description, user_id, ip_address, metadata)` — must match `postgres/audit-logging.sql`.
- **400 on POST with no message** = missing CSRF token.
- **Login `next` parameter**: validated by `_is_safe_url()` in `routes/auth.py` to prevent open redirects.
