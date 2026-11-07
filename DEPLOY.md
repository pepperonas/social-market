# Deployment

The public teaching demo runs at **https://socialmarket.celox.io**.

This is deliberately *not* the `docker-compose.yml` topology: the host already
runs nginx, PostgreSQL and Redis, so the app is a plain systemd service behind
the existing reverse proxy.

## Layout

| Piece | Value |
|---|---|
| Code | `/opt/socialmarket` |
| Service | `socialmarket.service` (gunicorn, 3 workers) |
| Port | `127.0.0.1:4264` (loopback only) |
| User | `socialmarket` (system user, no shell) |
| Database | PostgreSQL `socialmarket` + `pgcrypto` |
| Redis | DBs 11–14 |
| Secrets | `/opt/socialmarket/.env` (`640 root:socialmarket`) |
| TLS | Let's Encrypt, `renew_hook = systemctl reload nginx` |

## Deploying an update

```bash
deploy/deploy.sh          # dry run: lists every change on the server
deploy/deploy.sh --go     # sync, pip install, restart, health check (non-zero exit on failure)
```

An **allow list** of what the service needs (`app/`, `migrations/`, `postgres/`, `deploy/`,
`celery_worker.py`, licence and security notes); `--delete-excluded` removes everything else from
the server, protect rules keep the venv, `.env`, uploads and `__pycache__`. Until November 2026
this was an rsync of the whole working tree with a few excludes: 92 old test sessions,
`LOGIN_CREDENTIALS.md`, `tests/`, `docs/` and a local `.env.bak` with development secrets all
ended up on the server. A deny list fails open -- every new file is published until someone
remembers to exclude it.

Database migrations (`migrations/*.sql`) are applied by hand as `postgres` **before** `--go`,
followed by `GRANT ... TO socialmarket` for new tables (see Gotchas).

The service runs with `APP_CONFIG=production` (since November 2026): CSRF referrer checks on,
and it refuses to start if `SECRET_KEY`, `PASSWORD_PEPPER` or `DB_ENCRYPTION_KEY` fall back to
the development values in `config.py`.

## Latest verified deployment

On **2026-11-07**, implementation commit **`2ec9235`** was deployed with the script above;
no database migration was needed. Last restart: 02:13:47 CET. The web service and both job
timers are active, and `APP_CONFIG=production` remains set. Login and authenticated
notification, account and inbox pages passed HTTPS checks; the affected runtime files match
the repository by SHA-256. See the [step 7 live checks](docs/REVIEW-2026-11.md#live-deploy-von-schritt-7-2026-11-07)
for the scope and limits of verification.

## Background jobs

The unit files are versioned in [`deploy/systemd/`](deploy/systemd/) (the web service too).
Jobs run as oneshots under the same user and sandbox, through one command:

```bash
flask run-job --list                       # what exists, and on which schedule
flask run-job auto-finalize-orders ...     # run by name; non-zero exit if any failed
```

| Timer | Jobs |
|---|---|
| `socialmarket-jobs-hourly.timer` (:07) | auto-finalize-orders, expire-unpaid-orders, security-scan |
| `socialmarket-jobs-daily.timer` (03:17) | purge-expired-messages, purge-expired-notifications |

```bash
# install / update the units
scp deploy/systemd/socialmarket-jobs-* root@<host>:/etc/systemd/system/
ssh root@<host> 'systemctl daemon-reload && systemctl enable --now socialmarket-jobs-hourly.timer socialmarket-jobs-daily.timer'
ssh root@<host> 'systemctl list-timers "socialmarket-*"; journalctl -u socialmarket-jobs-hourly -n 20'
```

`tests/test_jobs.py` checks that every job in `app/jobs.py` appears in the unit for its
schedule. Until November 2026 no job ran here at all (see `docs/REVIEW-2026-11.md`, K2).

## Gotchas

- **The application log must be writable by the service user.** During the step 7 deploy,
  `/var/log/socialmarket/app.log` was owned by `root:root` (0644), so Flask fell back to
  stderr/journald. Fixed with `chown socialmarket:socialmarket /var/log/socialmarket/app.log`
  and `chmod 640 /var/log/socialmarket/app.log`, then a restart; no warning remained.
  Run maintenance CLI commands as the service user so a newly created log file has the
  right owner. Keep `/var/log/socialmarket` in the unit's `ReadWritePaths`.

- **nginx 1.24 does not accept `http2 on;`** — that directive needs 1.25+. Use
  `listen 443 ssl http2;`.
- **Do not `proxy_hide_header` the security headers.** nginx adds none of its own
  for this vhost, so hiding them just strips the ones Flask-Talisman sets. This
  was caught by checking the live response, not the config.
- **Grant privileges after loading the SQL layer.** `postgres/audit-logging.sql`
  is applied as the `postgres` superuser, so the tables end up owned by
  `postgres` and the app role gets `permission denied for table auth_log` until
  `GRANT ... ON ALL TABLES` (plus `ALTER DEFAULT PRIVILEGES`) is run.
- **The admin password is generated at deploy time**, not the one in
  `LOGIN_CREDENTIALS.md`. It lives in `/root/.socialmarket-adminpw`. (In November 2026 it no
  longer matched the account -- nobody could log in as admin. Reset to the file's value.)
  `flask init-admin` has no default any more: without `ADMIN_PASSWORD` it generates one.
- **`Referrer-Policy: no-referrer` and `WTF_CSRF_SSL_STRICT` cannot coexist.** Strict CSRF
  rejects every HTTPS POST without a same-origin `Referer`; `no-referrer` tells browsers never
  to send one. The policy is `same-origin`.
- **Rotating `PASSWORD_PEPPER` invalidates every existing password hash.** That
  is the point of a pepper; plan a re-seed, do not "fix" it by reverting.
- **gunicorn >= 26 opens a control socket.** Its default path lands in the
  working directory, which `ProtectSystem=strict` makes read-only, so the master
  logs `Control server error: Read-only file system`. Fixed with
  `RuntimeDirectory=socialmarket` plus `--control-socket /run/socialmarket/...`.
- **`systemctl enable` does not start a timer** -- use `enable --now`, or the first run is
  silently skipped until the next boot.
- **`EnvironmentFile` is read at process start, not on reload.** `systemctl
  reload` sends HUP, which recycles workers but keeps the master's environment.
  New variables in `.env` need a full `restart`.
- **Do not conclude "the rate limiter is broken" from sequential curl calls.**
  Fourteen requests issued one after another are spread over more than a second
  and stay under a 10/s limit. Test it in parallel:
  `seq 1 25 | xargs -P 25 -I{} curl -s -o /dev/null -w '%{http_code}\n' <url>`

## Deliberate demo posture

- Buyer/vendor demo accounts use the documented password — being able to log in
  and look around is the teaching value.
- The admin account does not, so the admin surface is not open to the internet.
- `X-Robots-Tag: noindex, nofollow` and a `robots.txt` that disallows everything.
- Data is disposable; there is nothing real to protect.
