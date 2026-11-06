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
set -euo pipefail

HOST="${DEPLOY_HOST:-root@69.62.121.168}"
DEST="${DEPLOY_DEST:-/opt/socialmarket}"
URL="${DEPLOY_URL:-https://socialmarket.celox.io/auth/login}"
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

if [[ "${1:-}" != "--go" ]]; then
  echo "Dry run (pass --go to deploy). Changes on $HOST:$DEST:"
  rsync -az --delete --delete-excluded --dry-run --itemize-changes "${FILTERS[@]}" ./ "$HOST:$DEST/"
  exit 0
fi

rsync -az --delete --delete-excluded "${FILTERS[@]}" ./ "$HOST:$DEST/"
ssh "$HOST" "cd $DEST && ./venv/bin/pip -q install -r app/requirements.txt \
  && systemctl restart socialmarket && sleep 3 && systemctl is-active socialmarket"
code=$(curl -s -o /dev/null -w '%{http_code}' "$URL")
echo "health: $URL -> $code"
[[ "$code" == "200" ]]
