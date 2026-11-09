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
# Same suite against PostgreSQL (CI runs both). Needs a superuser; the schema
# is rebuilt from postgres/*.sql + db.create_all() + migrations/ every session:
docker run -d --name sm-pgtest -e POSTGRES_USER=marketplace -e POSTGRES_PASSWORD=testpassword \
  -e POSTGRES_DB=marketplace_test -p 127.0.0.1:55432:5432 postgres:16
TEST_DATABASE_URL=postgresql://marketplace:testpassword@127.0.0.1:55432/marketplace_test pytest tests/ -q
pytest tests/test_auth.py -v
pytest tests/ --cov=app --cov-branch --cov-report=term-missing
python -m coverage report --include='app/routes/*' --precision=2 --fail-under=75
# Browser smoke test (opt-in; CI runs it as its own job)
pip install playwright && python -m playwright install chromium
BROWSER_TESTS=1 pytest tests/test_browser_smoke.py -v
# Mutation testing (config in setup.cfg; CI runs it nightly, non-blocking)
pip install mutmut==3.8.1 && mutmut run && mutmut results

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
bare). The live service uses `APP_CONFIG=production`; local HTTP Docker training
keeps the base config. `ProductionConfig` enables `WTF_CSRF_SSL_STRICT` and refuses
the development fallback values for `SECRET_KEY`, `PASSWORD_PEPPER`,
`DB_ENCRYPTION_KEY` and `TOTP_ENCRYPTION_KEY` (the last also when it does not parse as
Fernet keys). Strict HTTPS CSRF needs a same-origin Referer:
`Referrer-Policy` must stay `same-origin`; `no-referrer` would break every form.

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
| `image_service.py` | Upload validation, metadata removal by rebuilding pixels (fail closed), thumbnails |
| `audit_service.py` | PostgreSQL stored procedures |
| `security_service.py` | IP blocking, honeypot traps (report only), block suggestions |
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
- **No inline event handlers** (`onclick=`, `onsubmit=`, `onchange=`) and no `javascript:`
  URLs: the CSP blocks them too. Use the data-* hooks of `static/js/ui.js`:
  `data-confirm="Question?"` (form or submit button), `data-autosubmit`,
  `data-toggle-password="<input id>"`, `data-submit-form="<form id>"`.
  `tests/test_templates_csp.py` rejects anything else.
- Never ship a control that only JavaScript enables (a `disabled` submit button):
  if the script does not run, the form is dead. Disable from the script instead.
- Code samples in templates: `<pre class="code-block">`, which gets a header bar and copy button
- Money is `Decimal` end to end; never multiply it by a float
- Rate limits: `@limiter.limit("20 per minute")` on login, `3 per hour` on PGP generation.
  Static media is `@limiter.exempt` — see gotchas.

### Tests

Measured 2026-11-09 after plan step 6: 900 passing tests on SQLite (914 on
PostgreSQL); line + branch coverage 74 % overall, 78 % for `app/routes/` (admin 87 %, vendor 77 %).
CI enforces the route target of ≥75 %; whole-app branch coverage is reported,
not enforced. Coverage is no proof of PostgreSQL concurrency.

`tests/test_browser_smoke.py` (opt-in, `BROWSER_TESTS=1`) runs the app on a local
port in a thread and clicks through it in headless Chromium with **CSRF on**;
any CSP violation, page error or console error fails it. The fixture is
`shop_url`, not `live_server` -- pytest-flask owns that name. It uses the
in-memory SQLite of the test session, so the server is single-threaded.

`tests/` runs on SQLite in-memory by default, and against PostgreSQL when
`TEST_DATABASE_URL` is a `postgresql://` URL (since 2026-11-08, plan C1/C2):
`_create_pg_schema` builds the schema like production (init scripts, `create_all`,
the files in `PG_MIGRATIONS` -- not the one-shot `order_lifecycle_integrity.sql`)
with the database time zone set to Europe/Berlin. `tests/test_postgres.py` and
`tests/test_concurrency_pg.py` only run there; `REQUIRE_POSTGRES=1` (CI) turns a
fallback to SQLite into an error. A new migration must be added to `PG_MIGRATIONS`.
`conftest.py` provides:

- `app` (session) + an autouse **per-test app context** — Flask reuses an active
  context for requests, and `g` lives there, so a session-wide context leaks
  `current_user` between tests
- `sample_user` / `sample_vendor` / `sample_admin` — **unique usernames per test**
- `reload_user(id)` — re-read in the current context; a fixture object is stale
  after an HTTP request
- `query_counter` — counts SQL statements, for N+1 budgets
- `mock_audit` — stubs the stored-procedure calls
- SQLite implementations of `encrypt_data`, `decrypt_data` and `NOW()`
- `aware_utcnow()` — for writing into the `TIMESTAMPTZ` audit tables; a naive value
  lands an hour early in a Berlin session

**House rule: every new regression test must be seen to fail.** Reintroduce the
bug, watch it go red, then fix it again. Match against comment-free source —
the docs here quote removed code verbatim, and a naive `in source` check passes
against the very thing it forbids. (That trap has caught this project twice.)

### CI

`.github/workflows/ci.yml` — five jobs, all required:

| Job | What it does |
|---|---|
| Lint | flake8 (`.flake8`) + bandit |
| Test | pytest on SQLite (line + branch coverage, routes ≥75 %), then the same suite against the PostgreSQL 16 service |
| Browser smoke test | `tests/test_browser_smoke.py` in headless Chromium |
| Security Scan | `pip-audit`, **no `\|\| true`** |
| Secret Scan | gitleaks over the **full history** |

`.github/workflows/mutation.yml` — mutmut over `app/services/` and
`app/models/order.py`, nightly at 02:30 UTC and on demand. Never blocks: the
survivor list (artifact `mutmut-results`) is the to-do list for new tests.
mutmut 3 copies the project into `./mutants` (gitignored); every directory the
tests read has to be in `also_copy` in `setup.cfg`, or the baseline run fails.
Baseline 2026-11-09: 2758 mutants, 59 % of the reachable ones caught, 832 with
no covering test (420 in `pgp_service`). A full run is ~6 CPU-hours, hence the
240-minute job timeout.

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
- **Products and reviews are approved by an admin** (since 2026-11-08, `/admin/moderation`).
  A content or image change sends a product back (`submit_for_review`, which uses `flag_modified`
  so `is_approved` is always in the UPDATE). The moderation form carries
  `content_fingerprint()`; a decision on changed content is refused. Published reviews show no
  buyer name.
- **Escrow status changes through `_claim()` bypass the audit listener.** A method that changes
  nothing but the status must write its `transaction_audit` row itself (`mark_disputed`, `cancel`).
- **Availability checks belong on the model.** `product.can_purchase(qty)` covers active,
  approved and stock in one place; re-implementing it in a route is how `product.active`
  got past review.

### The test schema must not be looser than production

`transaction_audit.transaction_id` was nullable in the SQLite test DDL and
`NOT NULL` in PostgreSQL, so the suite accepted exactly the write the real
database rejects — and every order failed in production while the tests were
green. When mirroring `postgres/*.sql` into `conftest.py`, carry the constraints
across, not just the column names. A test schema that is more permissive than
production does not merely miss bugs; it certifies them. The opposite drift hides bugs too:
`admin_actions` lacked `ip_address` here until 2026-11-08, so every admin audit write failed
silently on SQLite and no test could see one.

Raw SQL in tests must not compare `str(uuid)` against a **model** table's id: on SQLite the
model type stores these UUIDs as 32 hex digits without dashes, the `WHERE` matches nothing and
the test runs against a precondition that never held. Use an ORM bulk `update()` instead. (The
audit tables are different: the app itself writes them with `str()`, so `str()` matches there.)

### Sessions and the test harness

- **The login identifier is `"<uuid>:<session_version>"`** (`User.get_id`). Bumping
  `session_version` (`end_all_sessions()`, done by `set_password`) kills every session
  *and* remember-me cookie. Rehashing on login uses `_rehash()` so it does not log people out.
  Forged test sessions must use `user.get_id()`, not `str(user.id)`.
- **Within one test, requests share `g`** — Flask-Login's cached user would leak from one
  request (even one client) to the next. `conftest.py` pops `g._login_user` after each
  request; without it, "the other browser is logged out" cannot fail.
- **Flask-Limiter reads `RATELIMIT_ENABLED` once, in `init_app`.** Setting it in
  `app.config` inside a test does nothing. The media regression test uses a separate
  process and an app with the limiter enabled before initialisation; a control route
  must actually return 429 before media exemptions can be trusted.
- **`limiter.limit(...)` counts GET too** unless given `methods=['POST']`; a limit on a
  form page then locks people out for viewing it.

### Transactions and the order lifecycle

- **Models and services do not commit.** `transition_to`, the escrow methods, stock
  reservation, shipping setters and `create_escrow_for_order` leave the commit to the route,
  so a checkout or a payment happens completely or not at all.
- **State changes are claimed with a conditional UPDATE** (`WHERE status = <what I read>`) and
  a rowcount check — never "read status, then write". To test it, keep the object stale with
  `set_committed_value`; `commit()` expires and reloads it otherwise.
- **Audit writes run in a SAVEPOINT** (`audit_service._write`). Order/message events never
  commit; auth/security/admin events do, so call them *after* the caller's own commit.
- **Stock is reserved when an order is placed** (`Product.reserve_stock`, atomic), returned on
  cancel; `record_sale` only counts units, at completion.
- **PostgreSQL sorts NaN above every number** — `CHECK (price > 0)` accepts NaN. Keep the upper
  bound in the constraint.

### Background jobs

- Jobs are plain functions in `app/jobs.py` (registry `JOBS`), run by `flask run-job NAME`.
  Live: systemd timers in `deploy/systemd/`; docker-compose: `app/tasks.py` + `celery_worker.py`.
  A new job needs an entry in `JOBS` **and** in the unit of its schedule (tested).
- Jobs raise on failure; `run-job` exits non-zero. Never return `{'success': False}`.
- **Bind time cutoffs for `TIMESTAMPTZ` columns as aware datetimes.** The live DB session runs
  in Europe/Berlin and reads a naive value as local time. The model columns are naive UTC
  (`app/timeutil.utcnow`); the audit tables are `TIMESTAMPTZ`.

### Raw SQL rows and swallowed errors

- **A caught DB error needs `db.session.rollback()`.** PostgreSQL aborts the transaction after a
  failed statement; SQLite does not, so the suite cannot see a missing rollback. Test the
  rollback call itself.
- **Raw `text()` rows in templates:** psycopg2 returns `datetime`, sqlite3 returns `str`; use the
  `when` filter, never `.strftime()`. Column names come from the SELECT, not from a model —
  `alert.created_at` on a row with `timestamp` broke the live admin dashboard.

### Production and deployment

- Deploy with `deploy/deploy.sh` (dry run) or `deploy/deploy.sh --go`; apply SQL
  migrations separately first. The allow list removes excluded server files;
  protect rules preserve the server `.env`, venv, uploads and bytecode caches.
- Admin credentials are private. `flask init-admin` uses `ADMIN_PASSWORD` if set,
  otherwise generates and prints a passphrase once; there is no built-in default.
- **The TOTP seed is encrypted at rest** (since 2026-11-08): `User.two_factor_secret` is a
  property over `two_factor_secret_enc` (Fernet/MultiFernet under `TOTP_ENCRYPTION_KEY`, never
  `SECRET_KEY`). The old plaintext column is mapped as `_two_factor_secret_plain`, only read for
  pre-migration rows, emptied by every write. `flask encrypt-totp-secrets` migrates leftovers
  and re-encrypts after a key rotation (new key first in the comma list). A wrong key raises
  `InvalidToken` -- fail closed, never "no 2FA". Losing the key makes every 2FA enrolment
  unusable; it lives only in the server `.env` and its backups.
- Manual IP blocks are wired in. **Honeypots are wired in but only report** (since 2026-11-09):
  the hidden `hp_website` field on `/auth/register` (checked before validation, answered like a
  success) and `DECOY_PATHS` (`app/routes/decoys.py`, CSRF-exempt, answer the normal JSON 404).
  Both write `security_events`; `block_suggestions()` counts them per kind (`SUGGESTION_KINDS`)
  for the admin. Never auto-block: behind the Tor hidden service every visitor is 127.0.0.1.
  Decoy de-duplication (`_decoy_seen`) is per worker process -- N workers can log a hit N times.
  The test config turns CSRF off; a test about a CSRF exemption must switch it on itself.
- Canary tokens are NOT in the app: reference code in `examples/canary_tokens.py` (no tables,
  no callers). Do not describe them as active protection.
- **Shipping data goes through pgcrypto** (`encrypt_data`/`decrypt_data`), which read
  `app.encryption_key` from the session. `_pass_db_encryption_key` puts `DB_ENCRYPTION_KEY`
  into the connection's startup `options` -- never into a `SET`/`set_config` statement, which
  statement logs keep. Both functions raise when the key is missing or wrong. Until
  2026-11-08 nothing set the key and every shipping address was stored as NULL.
- **No committing audit call inside a business transaction.** `log_security_event()` commits
  by default; inside a service method pass `commit=False` (see `EscrowService.pay_order`).
- See `docs/REVIEW-2026-11.md` for coverage and open follow-ups. Timezone and
  concurrency behaviour are only covered by the PostgreSQL run.

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
