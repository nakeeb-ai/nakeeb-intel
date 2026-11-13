#!/usr/bin/env bash
# Nakeeb AI - Encrypted Backup to Google Drive
# Uses rclone crypt. Requires rclone config with Drive remote.
# Run: ./ops/backup.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${REPO_ROOT}/backups"
TIMESTAMP=$(date -u +"%Y%m%d_%H%M%S")
BACKUP_NAME="nakeeb-backup-${TIMESTAMP}"
TEMP_DIR=$(mktemp -d)
MANIFEST_FILE="${TEMP_DIR}/MANIFEST.sha256"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[BACKUP]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# Cleanup on exit
cleanup() {
    log "Cleaning up temporary files..."
    rm -rf "${TEMP_DIR}"
}
trap cleanup EXIT

# Check rclone config
if ! rclone listremotes | grep -q "drive:"; then
    error "No 'drive:' remote configured. Run 'rclone config' first."
    exit 1
fi

log "Starting backup: ${BACKUP_NAME}"

# Create backup directory structure
mkdir -p "${TEMP_DIR}/${BACKUP_NAME}/index"
mkdir -p "${TEMP_DIR}/${BACKUP_NAME}/reports"
mkdir -p "${TEMP_DIR}/${BACKUP_NAME}/config"

# Copy files to backup
log "Copying files..."
cp -r "${REPO_ROOT}/index/events.jsonl" "${TEMP_DIR}/${BACKUP_NAME}/index/" 2>/dev/null || true
cp -r "${REPO_ROOT}/reports" "${TEMP_DIR}/${BACKUP_NAME}/" 2>/dev/null || true
cp -r "${REPO_ROOT}/config" "${TEMP_DIR}/${BACKUP_NAME}/" 2>/dev/null || true

# Get current commit SHA
cd "${REPO_ROOT}"
COMMIT_SHA=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
echo "${COMMIT_SHA}" > "${TEMP_DIR}/${BACKUP_NAME}/COMMIT_SHA"

# Generate SHA256 manifest
log "Generating SHA256 manifest..."
cd "${TEMP_DIR}/${BACKUP_NAME}"
find . -type f -name "*.jsonl" -o -name "*.md" -o -name "*.yaml" -o -name "*.yml" -o -name "COMMIT_SHA" | sort | while read -r file; do
    sha256sum "${file}" >> "${MANIFEST_FILE}"
done

# Verify manifest
log "Verifying manifest..."
if ! sha256sum -c "${MANIFEST_FILE}" >/dev/null 2>&1; then
    error "Manifest verification failed!"
    exit 1
fi

# Encrypt and upload using rclone crypt
# Assumes a crypt remote named 'drive-crypt' pointing to drive:backups/nakeeb
CRYPT_REMOTE="drive-crypt"
if ! rclone listremotes | grep -q "${CRYPT_REMOTE}:"; then
    warn "Crypt remote '${CRYPT_REMOTE}' not found. Creating..."
    # This would require interactive setup - skip for now
    error "Please configure rclone crypt remote manually: rclone config"
    exit 1
fi

log "Uploading encrypted backup to Google Drive..."
rclone copy "${TEMP_DIR}/${BACKUP_NAME}" "${CRYPT_REMOTE}:${BACKUP_NAME}" \
    --progress \
    --checksum \
    --transfers 4 \
    --retries 3 \
    --low-level-retries 10

# Verify upload
log "Verifying upload..."
rclone check "${TEMP_DIR}/${BACKUP_NAME}" "${CRYPT_REMOTE}:${BACKUP_NAME}" --one-way

log "✅ Backup completed: ${BACKUP_NAME}"
log "Commit: ${COMMIT_SHA}"
log "Manifest: ${MANIFEST_FILE}"