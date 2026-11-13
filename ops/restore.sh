#!/usr/bin/env bash
# Nakeeb AI - Encrypted Restore from Google Drive
# Verifies SHA256 manifest. Does NOT overwrite existing files without confirmation.
# Run: ./ops/restore.sh <backup-name>

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMP_DIR=$(mktemp -d)

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${GREEN}[RESTORE]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
info() { echo -e "${BLUE}[INFO]${NC} $*"; }

# Cleanup on exit
cleanup() {
    log "Cleaning up..."
    rm -rf "${TEMP_DIR}"
}
trap cleanup EXIT

# Check arguments
if [ $# -ne 1 ]; then
    error "Usage: $0 <backup-name>"
    error "Example: $0 nakeeb-backup-20261113_120000"
    exit 1
fi

BACKUP_NAME="$1"
CRYPT_REMOTE="drive-crypt"

# Check rclone config
if ! rclone listremotes | grep -q "${CRYPT_REMOTE}:"; then
    error "Crypt remote '${CRYPT_REMOTE}' not configured."
    exit 1
fi

log "Restoring backup: ${BACKUP_NAME}"

# Download backup
log "Downloading from Google Drive..."
rclone copy "${CRYPT_REMOTE}:${BACKUP_NAME}" "${TEMP_DIR}/${BACKUP_NAME}" \
    --progress \
    --checksum \
    --transfers 4

# Verify manifest
MANIFEST="${TEMP_DIR}/${BACKUP_NAME}/MANIFEST.sha256"
if [ ! -f "${MANIFEST}" ]; then
    error "MANIFEST.sha256 not found in backup!"
    exit 1
fi

log "Verifying SHA256 manifest..."
cd "${TEMP_DIR}/${BACKUP_NAME}"
if ! sha256sum -c "${MANIFEST}"; then
    error "❌ Manifest verification FAILED! Backup corrupted or tampered."
    exit 1
fi

log "✅ Manifest verification PASSED"

# Show backup info
if [ -f "${TEMP_DIR}/${BACKUP_NAME}/COMMIT_SHA" ]; then
    COMMIT=$(cat "${TEMP_DIR}/${BACKUP_NAME}/COMMIT_SHA")
    info "Backup commit: ${COMMIT}"
fi

# List files to restore
info "Files in backup:"
find "${TEMP_DIR}/${BACKUP_NAME}" -type f | sed "s|${TEMP_DIR}/${BACKUP_NAME}/||" | sort

# Confirm before restoring
echo
warn "This will restore files to the repository."
warn "Existing files will NOT be overwritten without explicit confirmation."
read -p "Continue? (yes/no): " CONFIRM

if [ "${CONFIRM}" != "yes" ]; then
    log "Restore cancelled."
    exit 0
fi

# Restore files
log "Restoring files..."
cd "${REPO_ROOT}"

# Restore index/events.jsonl
if [ -f "${TEMP_DIR}/${BACKUP_NAME}/index/events.jsonl" ]; then
    if [ -f "index/events.jsonl" ]; then
        read -p "index/events.jsonl exists. Overwrite? (yes/no): " OVERWRITE
        if [ "${OVERWRITE}" = "yes" ]; then
            cp "${TEMP_DIR}/${BACKUP_NAME}/index/events.jsonl" "index/events.jsonl"
            log "Restored index/events.jsonl"
        else
            log "Skipped index/events.jsonl"
        fi
    else
        cp "${TEMP_DIR}/${BACKUP_NAME}/index/events.jsonl" "index/events.jsonl"
        log "Restored index/events.jsonl"
    fi
fi

# Restore reports
if [ -d "${TEMP_DIR}/${BACKUP_NAME}/reports" ]; then
    cp -r "${TEMP_DIR}/${BACKUP_NAME}/reports"/* "reports/" 2>/dev/null || true
    log "Restored reports/"
fi

# Restore config
if [ -d "${TEMP_DIR}/${BACKUP_NAME}/config" ]; then
    if [ -d "config" ]; then
        read -p "config/ exists. Overwrite? (yes/no): " OVERWRITE
        if [ "${OVERWRITE}" = "yes" ]; then
            cp -r "${TEMP_DIR}/${BACKUP_NAME}/config"/* "config/"
            log "Restored config/"
        else
            log "Skipped config/"
        fi
    else
        cp -r "${TEMP_DIR}/${BACKUP_NAME}/config" .
        log "Restored config/"
    fi
fi

# Rebuild database
log "Rebuilding database from events..."
python -m src.rebuild_db

log "✅ Restore completed successfully!"
info "Verify the restored data before committing."