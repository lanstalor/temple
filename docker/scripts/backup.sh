#!/bin/bash
# Temple backup script - backs up ChromaDB, Kuzu, and audit logs
# Usage: bash docker/scripts/backup.sh [BACKUP_DIR]
#   BACKUP_DIR defaults to /home/lans/temple/backups
set -euo pipefail

BACKUP_DIR="${1:-/home/lans/temple/backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_PATH="${BACKUP_DIR}/temple_${TIMESTAMP}"
DATA_DIR="/home/lans/temple/data"

echo "=== Temple Backup ==="
echo "Timestamp: ${TIMESTAMP}"
echo "Backup to: ${BACKUP_PATH}"

mkdir -p "${BACKUP_PATH}"

# Backup ChromaDB data
if [ -d "${DATA_DIR}/chromadb" ]; then
    echo "Backing up ChromaDB..."
    cp -r "${DATA_DIR}/chromadb" "${BACKUP_PATH}/chromadb"
fi

# Backup Kuzu graph data (file + WAL + any legacy backup JSONs)
if [ -d "${DATA_DIR}/graph" ]; then
    echo "Backing up graph data..."
    mkdir -p "${BACKUP_PATH}/graph"
    cp -a "${DATA_DIR}/graph/"* "${BACKUP_PATH}/graph/" 2>/dev/null || true
fi

# Backup audit logs
if [ -d "${DATA_DIR}/audit" ]; then
    echo "Backing up audit logs..."
    cp -r "${DATA_DIR}/audit" "${BACKUP_PATH}/audit"
fi

# Verify backup contents
echo ""
echo "Backup contents:"
ITEMS=0
for component in chromadb graph audit; do
    if [ -e "${BACKUP_PATH}/${component}" ]; then
        SIZE=$(du -sh "${BACKUP_PATH}/${component}" | cut -f1)
        echo "  ${component}: ${SIZE}"
        ITEMS=$((ITEMS + 1))
    fi
done

if [ "$ITEMS" -eq 0 ]; then
    echo "  WARNING: No data found to back up!"
    rm -rf "${BACKUP_PATH}"
    exit 1
fi

# Compress
echo ""
echo "Compressing..."
cd "${BACKUP_DIR}"
tar -czf "temple_${TIMESTAMP}.tar.gz" "temple_${TIMESTAMP}"
rm -rf "temple_${TIMESTAMP}"

ARCHIVE="${BACKUP_DIR}/temple_${TIMESTAMP}.tar.gz"
echo "Backup complete: ${ARCHIVE}"
echo "Size: $(du -h "${ARCHIVE}" | cut -f1)"
