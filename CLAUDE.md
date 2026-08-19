# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Context

Educational IT security training environment, part of the **celox.io** security
training programme. A Flask marketplace built to be *read*: defence-in-depth
written out in full, published together with its own security audit and the
mistakes left visible on purpose.

**Blue team only.** No exploit code, no offensive tooling, no features that
serve illegal activity. New files carry the educational disclaimer.

The most important convention in this repository: **when something was wrong,
fix it AND leave the explanation.** The failures are the curriculum. A commit
message or docstring that says "fixed bug" throws away the teaching value.

## Commands

```bash
# Tests: SQLite in-memory, no Docker, no Postgres, no Redis needed
pytest tests/ -v
pytest tests/test_auth.py -v
pytest tests/ --cov=app --cov-report=term-missing

# Lint (settings live in .flake8 so CI and local cannot drift)
flake8 app/ tests/
bandit -r app/ -ll --skip B101
pip-audit -r app/requirements.txt --desc

# Docker (local full stack)
docker-compose up -d --build
docker exec marketplace_app flask init-db
docker exec marketplace_app flask init-admin
docker exec marketplace_app flask seed-data
docker restart marketplace_app          # templates are cached; restart after edits

# SQL migrations are plain files, not Alembic
docker exec marketplace_postgres psql -U marketplace -d marketplace -f /migrations/<file>.sql
```

Container names use underscores: `marketplace_app`, `marketplace_postgres`,
`marketplace_redis`, `marketplace_nginx`. App at http://localhost:8080.

**Deployment** (systemd + nginx, not docker-compose) is documented in
[DEPLOY.md](DEPLOY.md). Live at https://socialmarket.celox.io.

## Architecture

```
nginx (TLS) → gunicorn → Flask
                           ↓
              SecurityHeadersMiddleware (X-Request-ID)
                           ↓
              Flask-Talisman (nonce CSP, HSTS)
                           ↓
              Blueprint → service layer → PostgreSQL / Redis
```

`app/__init__.py` → `create_app(config_name=None)`.

### Config selection

`config.py` exports a `config` **dict**; there is no module attribute per name.
`create_app` looks the name up in that dict, and falls back to the `APP_CONFIG`
environment variable when called without arguments (gunicorn calls the factory
bare). Opt-in on purpose: `ProductionConfig` also switches on
`WTF_CSRF_SSL_STRICT`, which needs HTTPS end to end.

### Blueprints

| Blueprint | Prefix | Access | File |
|---|---|---|---|
| `marketplace_bp` | `/` | login-gated storefront | `routes/marketplace.py` |
| `auth_bp` | `/auth` | public + auth | `routes/auth.py` |
| `vendor_bp` | `/vendor` | `@vendor_required` | `routes/vendor.py` |
| `buyer_bp` | `/buyer` | `@login_required` | `routes/buyer.py` |
| `admin_bp` | `/admin` | `@admin_required` | `routes/admin.py` |
| `messages_bp` | `/messages` | auth | `routes/messages.py` |
| `cart_bp` | `/cart` | auth | `routes/cart.py` |
| `account_bp` | `/account` | auth | `routes/account.py` |
| `notifications_bp` | `/notifications` | auth | `routes/notifications.py` |

The storefront (`/`) is deliberately behind login — a closed marketplace, which
is what makes the role separation worth studying.

### Service layer

Security logic lives in `app/services/`, never inline in a route:

| Service | Responsibility |
|---|---|
| `password_service.py` | Argon2id + pepper, **and** the password policy (`validate_policy`) |
| `passphrase_service.py` | BIP-39 passphrase suggestions with honest entropy |
| `cover_service.py` | Deterministic generated product covers |
| `crypto_service.py` | Fernet application-level encryption |
| `pgp_service.py` | RSA-4096 keypairs, encrypt/decrypt |
| `image_service.py` | Upload validation, EXIF stripping, thumbnails |
| `audit_service.py` | PostgreSQL stored procedures |
| `security_service.py` | IP blocking, canary tokens, honeypots |
| `escrow_service.py` | Escrow lifecycle |

### Database

PostgreSQL with pgcrypto. UUID primary keys throughout, via
`app/models/types.py` — portable types that render **identical DDL** on
PostgreSQL and still work on SQLite, so the test suite needs no database server.
Encrypted columns are `LargeBinary` written through the `encrypt_data()` /
`decrypt_data()` stored functions.

Audit tables (`auth_log`, `audit_log`, `security_events`, `message_audit`,
`transaction_audit`, `admin_actions`) are defined in `postgres/audit-logging.sql`,
**not** in the models — `db.create_all()` does not create them.

## Conventions

- POST forms: `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>`
- Inline scripts: `nonce="{{ csp_nonce() }}"` — the CSP blocks anything else, silently
- Code samples in templates: `<pre class="code-block">`, which gets a header bar and copy button
- Money is `Decimal` end to end; never multiply it by a float
- Rate limits: `@limiter.limit("20 per minute")` on login, `3 per hour` on PGP generation.
  Static media is `@limiter.exempt` — see gotchas.

### Tests

`tests/` runs on SQLite in-memory. `conftest.py` provides:

- `app` (session) + an autouse **per-test app context** — Flask reuses an active
  context for requests, and `g` lives there, so a session-wide context leaks
  `current_user` between tests
- `sample_user` / `sample_vendor` / `sample_admin` — **unique usernames per test**
- `reload_user(id)` — re-read in the current context; a fixture object is stale
  after an HTTP request
- `query_counter` — counts SQL statements, for N+1 budgets
- `mock_audit` — stubs the stored-procedure calls
- SQLite implementations of `encrypt_data`, `decrypt_data` and `NOW()`

**House rule: every new regression test must be seen to fail.** Reintroduce the
bug, watch it go red, then fix it again. Match against comment-free source —
the docs here quote removed code verbatim, and a naive `in source` check passes
against the very thing it forbids. (That trap has caught this project twice.)

### CI

`.github/workflows/ci.yml` — four jobs, all required:

| Job | What it does |
|---|---|
| Lint | flake8 (`.flake8`) + bandit |
| Test | pytest with PostgreSQL + Redis services available |
| Security Scan | `pip-audit`, **no `\|\| true`** |
| Secret Scan | gitleaks over the **full history** |

## Gotchas

Every one of these cost real debugging time here.

### Application

- **Order of checks is a security boundary.** `if two_factor_enabled` used to be
  evaluated before `if is_active`, so deactivating an account did not deactivate it.
- **Enabling 2FA must require proof.** Switching it on while rendering the QR code
  locks out anyone who abandons the page.
- **`Decimal * float` raises `TypeError`.** It sat in an order insert listener, so
  every checkout failed. Convert percentages with `Decimal(str(x))`.
- **Template field names must match what the route reads.** `name="terms"` versus
  `request.form.get('terms_accepted')` made registration impossible for months.
- **A checkbox submits the string `'on'`,** not a bool. Boolean columns reject it.
- **Never echo a password back into HTML** when re-rendering a rejected form.
- **Nullable audit fields.** `user_agent[:50]` 500s: rows written by the model
  event listeners carry no user agent.
- **Rate limiting static media is self-harm.** The default 10/s throttled the app's
  own product covers — a listing page renders 20 of them, half came back 429.
- **`::selection` must be declared whenever text colour is forced.** White text plus
  the default light-grey selection is unreadable exactly when someone copies it.
- **Do not render ORM objects in templates.** `{{ product.category }}` prints a repr.
- **Jinja renders an unknown name as an empty string.** `product.active`,
  `order.status_color` and five dashboard variables all shipped broken and invisible.
  `create_app` switches to `StrictUndefined` under `TESTING`; production keeps the
  lenient default so a stray reference cannot 500 a page for a visitor.
- **Bind ids and money as `str()` in raw SQL.** psycopg2 adapts `uuid.UUID` and
  `Decimal`; sqlite3 does not, so a listener that works in production explodes in tests.
- **During a flush, a relationship may not be populated.** The escrow audit listener
  read `target.order` and bound NULL into a NOT NULL column, failing every order.
  Set the relationship (`Escrow(order=order, ...)`), not just the foreign key.
- **Availability checks belong on the model.** `product.can_purchase(qty)` covers active,
  approved and stock in one place; re-implementing it in a route is how `product.active`
  got past review.

### The test schema must not be looser than production

`transaction_audit.transaction_id` was nullable in the SQLite test DDL and
`NOT NULL` in PostgreSQL, so the suite accepted exactly the write the real
database rejects — and every order failed in production while the tests were
green. When mirroring `postgres/*.sql` into `conftest.py`, carry the constraints
across, not just the column names. A test schema that is more permissive than
production does not merely miss bugs; it certifies them.

### Infrastructure

- **Docker Compose does not expand `${VAR}` inside `.env` values.** Write them out.
- **`EnvironmentFile` is read at process start,** not on `systemctl reload`.
- **gunicorn ≥ 26 opens a control socket** whose default path is the working
  directory — read-only under `ProtectSystem=strict`. Use `RuntimeDirectory`.
- **nginx 1.24 needs `listen 443 ssl http2;`**; `http2 on;` requires 1.25+.
- **Do not `proxy_hide_header` the security headers** unless nginx sets its own.
- **Grant privileges after loading the SQL layer** as the postgres superuser, or
  the app hits `permission denied for table auth_log`.
- **Behind a proxy, `remote_addr` is the proxy.** ProxyFix is opt-in via
  `TRUSTED_PROXY_COUNT`; trusting `X-Forwarded-For` blindly allows IP spoofing.
- **Rate limits cannot be judged from sequential curl calls** — they spread over
  more than a second. Test in parallel with `xargs -P`.

### Audit service

`log_security_event` parameter order is
`(event_type, severity, 'application', description, user_id, ip_address, metadata)`
and must match the signature in `postgres/audit-logging.sql`.

## Where the teaching material lives

| Document | Contents |
|---|---|
| [`docs/BUGFIX-PLAN.md`](docs/BUGFIX-PLAN.md) | The full security review: findings, severity, fixes |
| [`docs/PASSWORD_SECURITY.md`](docs/PASSWORD_SECURITY.md) | Argon2id, pepper, and a real secret that leaked through documentation |
| [`SECURITY.md`](SECURITY.md) | Which properties are intentional — read before reporting |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | The mutation-testing house rule |
| [`DEPLOY.md`](DEPLOY.md) | systemd + nginx topology and its gotchas |
