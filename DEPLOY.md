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
rsync -az --delete \
  --exclude '.git' --exclude '__pycache__' --exclude 'venv' \
  --exclude '.env' --exclude 'app/uploads/*' \
  ./ root@<host>:/opt/socialmarket/

ssh root@<host> 'cd /opt/socialmarket && ./venv/bin/pip -q install -r app/requirements.txt \
  && systemctl restart socialmarket && systemctl is-active socialmarket'
```

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
  `LOGIN_CREDENTIALS.md`. It lives in `/root/.socialmarket-adminpw`.
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
