#!/bin/bash
# Temple restore script - restores from a backup archive
# Usage: bash docker/scripts/restore.sh <BACKUP_ARCHIVE>
#
# WARNING: This replaces current data. Stop the Temple stack first:
#   docker compose -f docker/docker-compose.yml down
#
# After restore, restart:
#   docker compose -f docker/docker-compose.yml up -d --build
set -euo pipefail

ARCHIVE="${1:-}"
DATA_DIR="/home/lans/temple/data"

if [ -z "$ARCHIVE" ]; then
    echo "Usage: bash docker/scripts/restore.sh <BACKUP_ARCHIVE.tar.gz>"
    echo ""
    echo "Available backups:"
    ls -lh /home/lans/temple/backups/temple_*.tar.gz 2>/dev/null || echo "  (none found in /home/lans/temple/backups/)"
    exit 1
fi

if [ ! -f "$ARCHIVE" ]; then
    echo "ERROR: Archive not found: $ARCHIVE"
    exit 1
fi

# Check if containers are running
if docker ps --filter "name=temple" --format '{{.Names}}' 2>/dev/null | grep -q temple; then
    echo "ERROR: Temple containers are still running. Stop them first:"
    echo "  docker compose -f docker/docker-compose.yml down"
    exit 1
fi

echo "=== Temple Restore ==="
echo "Archive: $ARCHIVE"
echo "Target:  $DATA_DIR"
echo ""

# Extract to temp directory
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

echo "Extracting archive..."
tar -xzf "$ARCHIVE" -C "$TEMP_DIR"

# Find the extracted directory (temple_YYYYMMDD_HHMMSS)
EXTRACTED=$(find "$TEMP_DIR" -maxdepth 1 -type d -name 'temple_*' | head -1)
if [ -z "$EXTRACTED" ]; then
    echo "ERROR: Archive does not contain expected temple_* directory"
    exit 1
fi

echo "Extracted: $(basename "$EXTRACTED")"
echo ""

# Verify backup contents
echo "Backup contents:"
ITEMS=0
for component in chromadb graph audit; do
    if [ -e "${EXTRACTED}/${component}" ]; then
        SIZE=$(du -sh "${EXTRACTED}/${component}" | cut -f1)
        echo "  ${component}: ${SIZE}"
        ITEMS=$((ITEMS + 1))
    else
        echo "  ${component}: (not in backup)"
    fi
done

if [ "$ITEMS" -eq 0 ]; then
    echo ""
    echo "ERROR: Backup archive contains no data components"
    exit 1
fi

echo ""
echo "This will REPLACE current data in: $DATA_DIR"
read -p "Continue? [y/N] " confirm
if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "Aborted."
    exit 0
fi

# Restore each component
if [ -e "${EXTRACTED}/chromadb" ]; then
    echo "Restoring ChromaDB..."
    rm -rf "${DATA_DIR}/chromadb"
    cp -r "${EXTRACTED}/chromadb" "${DATA_DIR}/chromadb"
fi

if [ -e "${EXTRACTED}/graph" ]; then
    echo "Restoring graph data..."
    rm -rf "${DATA_DIR}/graph"
    mkdir -p "${DATA_DIR}/graph"
    cp -a "${EXTRACTED}/graph/"* "${DATA_DIR}/graph/" 2>/dev/null || true
fi

if [ -e "${EXTRACTED}/audit" ]; then
    echo "Restoring audit logs..."
    rm -rf "${DATA_DIR}/audit"
    cp -r "${EXTRACTED}/audit" "${DATA_DIR}/audit"
fi

# Verify restored files
echo ""
echo "Restored data:"
for component in chromadb graph audit; do
    if [ -e "${DATA_DIR}/${component}" ]; then
        SIZE=$(du -sh "${DATA_DIR}/${component}" | cut -f1)
        echo "  ${component}: ${SIZE}"
    fi
done

echo ""
echo "Restore complete. Start Temple:"
echo "  docker compose -f docker/docker-compose.yml up -d --build"
echo ""
echo "Then verify with smoke test:"
echo "  bash docker/scripts/smoke-test.sh"
