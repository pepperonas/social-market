"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Contract tests for deploy/deploy.sh (review round 3 follow-up, 2026-11-08).

The script is not run here -- it needs the live host. What is pinned is its
order of operations, read from the comment-free source (the comments in the
script quote the old failures and would satisfy a naive substring check).

* Preflight runs before anything changes, in the dry run as well. A log file
  owned by root and an uploads root owned by the Mac user (uid 501) both went
  unnoticed until they happened to matter.
* A backup is taken before rsync touches the server, with umask 077, outside
  /root, and only the newest few are kept. The hand-made backups had landed in
  /root as a world-readable database dump and were never cleaned up.
"""

import pathlib
import re

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / 'deploy' / 'deploy.sh'


def code():
    lines = []
    for line in SCRIPT.read_text().splitlines():
        stripped = line.lstrip()
        if stripped.startswith('#'):
            continue
        lines.append(re.sub(r"\s+#\s.*$", '', line))
    return '\n'.join(lines)


def body_of(name, src):
    match = re.search(rf'^{name}\(\) {{\n(.*?)^}}', src, re.S | re.M)
    assert match, f'{name}() missing'
    return match.group(1)


def main_part(src):
    """Everything after the function definitions: the actual control flow."""
    return src[src.rindex('\n}\n'):]


def test_preflight_checks_every_path_the_service_writes():
    body = body_of('preflight', code())

    assert '/var/log/socialmarket' in body
    assert '$DEST/app/uploads' in body
    assert '! -user $SERVICE_USER' in body
    assert 'exit 1' in body


def test_preflight_runs_before_the_dry_run_and_before_any_rsync():
    flow = main_part(code())

    preflight = flow.find('\npreflight\n')
    assert preflight > -1, 'preflight is never called'
    assert preflight < flow.find('--dry-run'), 'the dry run must not hide an ownership problem'
    assert preflight < flow.find('rsync -az --delete --delete-excluded "${FILTERS[@]}" ./')


def test_backup_is_taken_before_the_real_rsync():
    flow = main_part(code())
    real_rsync = flow.rfind('rsync -az --delete --delete-excluded "${FILTERS[@]}" ./')

    backup = flow.find('\nbackup\n')
    assert backup > -1, 'backup is never called'
    assert backup < real_rsync


def test_backup_is_private_outside_root_and_rotated():
    src = code()
    body = body_of('backup', src)

    assert 'umask 077' in body
    assert 'chmod 700 $BACKUP_DIR' in body
    assert 'pg_dump' in body
    assert '--exclude=./.env' in body, 'the backup must not become another copy of the secrets'
    assert 'tail -n +$((KEEP_BACKUPS + 1))' in body

    default = re.search(r'BACKUP_DIR="\$\{DEPLOY_BACKUP_DIR:-([^}]+)\}"', src).group(1)
    assert not default.startswith('/root'), default
