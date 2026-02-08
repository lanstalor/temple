#!/bin/bash
# Temple backup script - backs up ChromaDB, Kuzu, and audit logs
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

# Backup Kuzu data
if [ -d "${DATA_DIR}/kuzu" ]; then
    echo "Backing up Kuzu..."
    cp -r "${DATA_DIR}/kuzu" "${BACKUP_PATH}/kuzu"
fi

# Backup audit logs
if [ -d "${DATA_DIR}/audit" ]; then
    echo "Backing up audit logs..."
    cp -r "${DATA_DIR}/audit" "${BACKUP_PATH}/audit"
fi

# Compress
echo "Compressing..."
cd "${BACKUP_DIR}"
tar -czf "temple_${TIMESTAMP}.tar.gz" "temple_${TIMESTAMP}"
rm -rf "temple_${TIMESTAMP}"

echo "Backup complete: ${BACKUP_DIR}/temple_${TIMESTAMP}.tar.gz"
echo "Size: $(du -h "${BACKUP_DIR}/temple_${TIMESTAMP}.tar.gz" | cut -f1)"
