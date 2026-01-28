#!/bin/bash
# EDUCATIONAL SECURITY TRAINING ENVIRONMENT
# Restore from Encrypted Backup
# Purpose: Restore database and files from GPG-encrypted backup

set -e

echo "=========================================="
echo "Secure Marketplace - Restore Script"
echo "=========================================="

if [ -z "$1" ]; then
    echo "Usage: $0 <backup_file.tar.gz.gpg>"
    echo ""
    echo "Available backups:"
    ls -lh /backups/backup_*.tar.gz.gpg 2>/dev/null || echo "  No backups found"
    exit 1
fi

BACKUP_FILE="$1"
PASSPHRASE="${BACKUP_ENCRYPTION_PASSPHRASE:-change-me}"
TEMP_DIR="/tmp/restore_$(date +%s)"

if [ ! -f "${BACKUP_FILE}" ]; then
    echo "[!] Backup file not found: ${BACKUP_FILE}"
    exit 1
fi

echo "[*] Restoring from: ${BACKUP_FILE}"

# Create temp directory
mkdir -p "${TEMP_DIR}"

# Decrypt backup
echo "[*] Decrypting backup..."
echo "${PASSPHRASE}" | gpg \
    --batch \
    --yes \
    --passphrase-fd 0 \
    --decrypt \
    --output "${TEMP_DIR}/backup.tar.gz" \
    "${BACKUP_FILE}"

# Extract tarball
echo "[*] Extracting backup..."
tar -xzf "${TEMP_DIR}/backup.tar.gz" -C "${TEMP_DIR}"

# Restore database
echo "[*] Restoring database..."
echo "[!] WARNING: This will overwrite the current database!"
read -p "Continue? (yes/no): " CONFIRM

if [ "${CONFIRM}" != "yes" ]; then
    echo "[*] Restore cancelled"
    rm -rf "${TEMP_DIR}"
    exit 0
fi

PGPASSWORD="${POSTGRES_PASSWORD}" psql \
    -h "${POSTGRES_HOST:-postgres}" \
    -U "${POSTGRES_USER:-marketplace}" \
    -d "${POSTGRES_DB:-marketplace}" \
    < "${TEMP_DIR}/database.sql"

echo "[+] Database restored"

# Cleanup
echo "[*] Cleaning up..."
rm -rf "${TEMP_DIR}"

echo ""
echo "=========================================="
echo "Restore completed successfully"
echo "=========================================="
