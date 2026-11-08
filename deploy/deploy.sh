#!/usr/bin/env bash
# EDUCATIONAL SECURITY TRAINING ENVIRONMENT
# Deploy to the live server: an ALLOW list, not a deny list.
#
# The old command (DEPLOY.md) synced the whole working tree minus a few
# excludes. Everything else went along: 92 test sessions from flask_session/,
# LOGIN_CREDENTIALS.md, tests/, docs/, coverage data -- whatever happened to be
# lying around locally. A deny list fails open: a new file is published until
# someone remembers to exclude it. Here, only what the service needs is sent;
# --delete-excluded removes the rest from the server. Protect (P) rules keep
# what belongs to the server and is not in the repo: the venv, .env, uploads.
#
# Usage:  deploy/deploy.sh            # dry run: shows what would change
#         deploy/deploy.sh --go       # deploy, install requirements, restart, check
# Database migrations (migrations/*.sql) are applied by hand, before --go.
#
# Two additions after round 3 (2026-11-08):
# * Preflight. /var/log/socialmarket/app.log once belonged to root, so the
#   service could not write its log and fell back to the journal unnoticed; the
#   uploads root belonged to the Mac user (uid 501) that ran the first rsync.
#   Both only showed up by accident. Now any path the service writes to must
#   belong to the service user, or the deploy stops before changing anything.
# * Backup before --go. The backups used to be made by hand, landed in /root
#   with mode 0644 (a readable database dump under a 0711 /root) and were never
#   cleaned up. Now: one directory per deploy under BACKUP_DIR, umask 077,
#   code without venv/.env/uploads plus a pg_dump, newest KEEP_BACKUPS kept.
set -euo pipefail

HOST="${DEPLOY_HOST:-root@69.62.121.168}"
DEST="${DEPLOY_DEST:-/opt/socialmarket}"
URL="${DEPLOY_URL:-https://socialmarket.celox.io/auth/login}"
SERVICE_USER="${DEPLOY_SERVICE_USER:-socialmarket}"
DB_NAME="${DEPLOY_DB:-socialmarket}"
BACKUP_DIR="${DEPLOY_BACKUP_DIR:-/var/backups/socialmarket-deploy}"
KEEP_BACKUPS="${DEPLOY_KEEP_BACKUPS:-2}"
cd "$(dirname "$0")/.."

FILTERS=(
  --filter='P /venv/'
  --filter='P /.env'
  --filter='P /app/uploads/'
  --filter='P __pycache__/'   # the service cannot write them under ProtectSystem=strict
  --exclude='__pycache__/' --exclude='*.pyc' --exclude='.DS_Store'
  --exclude='/app/uploads/'
  --include='/app/***'
  --include='/migrations/***'
  --include='/postgres/***'
  --include='/deploy/***'
  --include='/celery_worker.py'
  --include='/LICENSE' --include='/README.md' --include='/SECURITY.md'
  --exclude='*'
)

# Paths the service writes to (ReadWritePaths in the unit). Anything below them
# not owned by the service user is reported; the deploy stops.
preflight() {
  ssh "$HOST" "bad=\$(find /var/log/socialmarket $DEST/app/uploads ! -user $SERVICE_USER -print 2>&1); \
    if [ -n \"\$bad\" ]; then echo 'Preflight failed, not owned by $SERVICE_USER:' >&2; \
    echo \"\$bad\" | head -20 >&2; echo 'Fix: chown -R $SERVICE_USER:$SERVICE_USER <path>' >&2; exit 1; fi"
}

backup() {
  local ts; ts=$(date +%Y%m%d-%H%M%S)
  ssh "$HOST" "set -e; umask 077; mkdir -p $BACKUP_DIR; chmod 700 $BACKUP_DIR; d=$BACKUP_DIR/$ts; mkdir \$d; \
    tar -C $DEST --exclude=./venv --exclude=./.env --exclude=./app/uploads --exclude='*/__pycache__' \
      -czf \$d/code.tar.gz .; \
    sudo -u postgres pg_dump -Fc $DB_NAME > \$d/db.dump; \
    ls -1dt $BACKUP_DIR/*/ | tail -n +$((KEEP_BACKUPS + 1)) | xargs -r rm -rf; \
    echo \"backup: \$d\"; ls -1d $BACKUP_DIR/*/"
}

preflight

if [[ "${1:-}" != "--go" ]]; then
  echo "Dry run (pass --go to deploy). Changes on $HOST:$DEST:"
  rsync -az --delete --delete-excluded --dry-run --itemize-changes "${FILTERS[@]}" ./ "$HOST:$DEST/"
  exit 0
fi

backup
rsync -az --delete --delete-excluded "${FILTERS[@]}" ./ "$HOST:$DEST/"
ssh "$HOST" "cd $DEST && ./venv/bin/pip -q install -r app/requirements.txt \
  && systemctl restart socialmarket && sleep 3 && systemctl is-active socialmarket"
code=$(curl -s -o /dev/null -w '%{http_code}' "$URL")
echo "health: $URL -> $code"
[[ "$code" == "200" ]]
