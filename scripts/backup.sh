#!/bin/bash
# EDUCATIONAL SECURITY TRAINING ENVIRONMENT
# Encrypted Backup Script
# Purpose: Create GPG-encrypted backups of database and critical files

set -e

echo "=========================================="
echo "Secure Marketplace - Backup Script"
echo "=========================================="

# Configuration
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/backups"
TEMP_DIR="/tmp/backup_${DATE}"
BACKUP_NAME="backup_${DATE}.tar.gz.gpg"
PASSPHRASE="${BACKUP_ENCRYPTION_PASSPHRASE:-change-me}"
RETENTION_DAYS=7

# Create directories
mkdir -p "${BACKUP_DIR}"
mkdir -p "${TEMP_DIR}"

echo "[*] Starting backup: ${DATE}"

# Backup PostgreSQL database
echo "[*] Backing up database..."
PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump \
    -h "${POSTGRES_HOST:-postgres}" \
    -U "${POSTGRES_USER:-marketplace}" \
    -d "${POSTGRES_DB:-marketplace}" \
    > "${TEMP_DIR}/database.sql"

echo "[+] Database backup complete"

# Backup application files
echo "[*] Backing up application files..."
cp -r /app "${TEMP_DIR}/app" 2>/dev/null || true

# Backup configuration
echo "[*] Backing up configuration..."
mkdir -p "${TEMP_DIR}/config"
cp /app/.env "${TEMP_DIR}/config/.env" 2>/dev/null || true

# Create tarball
echo "[*] Creating archive..."
tar -czf "${TEMP_DIR}/backup.tar.gz" -C "${TEMP_DIR}" .

# Encrypt with GPG
echo "[*] Encrypting backup..."
echo "${PASSPHRASE}" | gpg \
    --batch \
    --yes \
    --passphrase-fd 0 \
    --symmetric \
    --cipher-algo AES256 \
    --output "${BACKUP_DIR}/${BACKUP_NAME}" \
    "${TEMP_DIR}/backup.tar.gz"

# Secure delete temporary files
echo "[*] Cleaning up temporary files..."
rm -rf "${TEMP_DIR}"

# Calculate backup size
BACKUP_SIZE=$(du -h "${BACKUP_DIR}/${BACKUP_NAME}" | cut -f1)
echo "[+] Backup created: ${BACKUP_NAME} (${BACKUP_SIZE})"

# Cleanup old backups
echo "[*] Cleaning up old backups (retention: ${RETENTION_DAYS} days)..."
find "${BACKUP_DIR}" -name "backup_*.tar.gz.gpg" -type f -mtime +${RETENTION_DAYS} -delete
REMAINING=$(ls -1 "${BACKUP_DIR}"/backup_*.tar.gz.gpg | wc -l)
echo "[+] Remaining backups: ${REMAINING}"

# Verify backup
echo "[*] Verifying backup..."
if [ -f "${BACKUP_DIR}/${BACKUP_NAME}" ]; then
    echo "[+] Backup verification passed"
    echo ""
    echo "=========================================="
    echo "Backup completed successfully"
    echo "Location: ${BACKUP_DIR}/${BACKUP_NAME}"
    echo "Size: ${BACKUP_SIZE}"
    echo "=========================================="
else
    echo "[!] Backup verification failed!"
    exit 1
fi
