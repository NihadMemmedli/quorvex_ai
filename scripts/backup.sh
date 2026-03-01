#!/bin/bash
#
# PostgreSQL Backup Script for Playwright Agent
#
# Usage:
#   ./scripts/backup.sh                    # Daily backup with rotation
#   ./scripts/backup.sh --manual           # Manual backup (no rotation)
#   ./scripts/backup.sh --restore <file>   # Restore from backup
#
# Configuration via environment variables:
#   POSTGRES_USER     - Database user (default: playwright)
#   POSTGRES_PASSWORD - Database password (required)
#   POSTGRES_DB       - Database name (default: playwright_agent)
#   POSTGRES_HOST     - Database host (default: localhost)
#   POSTGRES_PORT     - Database port (default: 5432)
#   BACKUP_DIR        - Backup directory (default: /backups)
#   BACKUP_RETENTION  - Days to keep backups (default: 30)
#

set -euo pipefail

# Configuration with defaults
POSTGRES_USER="${POSTGRES_USER:-playwright}"
POSTGRES_DB="${POSTGRES_DB:-playwright_agent}"
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_RETENTION="${BACKUP_RETENTION:-30}"

# Ensure password is set
if [ -z "${POSTGRES_PASSWORD:-}" ]; then
    echo "ERROR: POSTGRES_PASSWORD environment variable is required"
    exit 1
fi

# Export password for pg_dump/pg_restore
export PGPASSWORD="$POSTGRES_PASSWORD"

# Timestamp for backup filename
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/backup_${TIMESTAMP}.sql.gz"

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Function to perform backup
perform_backup() {
    local backup_type="$1"

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting $backup_type backup..."

    # Perform backup with custom format (supports parallel restore)
    pg_dump \
        -h "$POSTGRES_HOST" \
        -p "$POSTGRES_PORT" \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        --verbose \
        --no-owner \
        --no-privileges \
        2>&1 | gzip > "$BACKUP_FILE"

    # Check if backup was successful
    if [ -f "$BACKUP_FILE" ] && [ -s "$BACKUP_FILE" ]; then
        BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup completed: $BACKUP_FILE ($BACKUP_SIZE)"

        # Create latest symlink
        ln -sf "$BACKUP_FILE" "${BACKUP_DIR}/latest.sql.gz"

        return 0
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Backup failed or file is empty"
        rm -f "$BACKUP_FILE"
        return 1
    fi
}

# Function to rotate old backups
rotate_backups() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Rotating backups older than $BACKUP_RETENTION days..."

    # Find and delete old backups
    local deleted_count=0
    while IFS= read -r -d '' file; do
        rm -f "$file"
        deleted_count=$((deleted_count + 1))
        echo "  Deleted: $(basename "$file")"
    done < <(find "$BACKUP_DIR" -name "backup_*.sql.gz" -type f -mtime +$BACKUP_RETENTION -print0 2>/dev/null || true)

    if [ $deleted_count -eq 0 ]; then
        echo "  No old backups to delete"
    else
        echo "  Deleted $deleted_count old backup(s)"
    fi

    # List remaining backups
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Current backups:"
    ls -lh "${BACKUP_DIR}"/backup_*.sql.gz 2>/dev/null | tail -10 || echo "  No backups found"
}

# Function to restore from backup
restore_backup() {
    local restore_file="$1"

    if [ ! -f "$restore_file" ]; then
        echo "ERROR: Backup file not found: $restore_file"
        exit 1
    fi

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: This will overwrite the current database!"
    echo "Restoring from: $restore_file"
    read -p "Are you sure? (type 'yes' to confirm): " confirm

    if [ "$confirm" != "yes" ]; then
        echo "Restore cancelled"
        exit 0
    fi

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting restore..."

    # Drop and recreate database
    psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres \
        -c "DROP DATABASE IF EXISTS ${POSTGRES_DB};"
    psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres \
        -c "CREATE DATABASE ${POSTGRES_DB};"

    # Restore from backup
    gunzip -c "$restore_file" | psql \
        -h "$POSTGRES_HOST" \
        -p "$POSTGRES_PORT" \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        --quiet

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restore completed successfully"
}

# Function to show backup status
show_status() {
    echo "=== Backup Status ==="
    echo "Backup directory: $BACKUP_DIR"
    echo "Retention period: $BACKUP_RETENTION days"
    echo ""
    echo "Recent backups:"
    ls -lht "${BACKUP_DIR}"/backup_*.sql.gz 2>/dev/null | head -10 || echo "  No backups found"
    echo ""
    echo "Total backup size:"
    du -sh "$BACKUP_DIR" 2>/dev/null || echo "  N/A"
}

# Main script logic
case "${1:-}" in
    --manual)
        perform_backup "manual"
        ;;
    --restore)
        if [ -z "${2:-}" ]; then
            echo "Usage: $0 --restore <backup_file>"
            exit 1
        fi
        restore_backup "$2"
        ;;
    --status)
        show_status
        ;;
    --rotate)
        rotate_backups
        ;;
    ""|--daily)
        perform_backup "daily"
        rotate_backups
        ;;
    --help|-h)
        echo "Usage: $0 [--manual|--daily|--restore <file>|--status|--rotate|--help]"
        echo ""
        echo "Commands:"
        echo "  (default)     Daily backup with rotation"
        echo "  --manual      Manual backup without rotation"
        echo "  --daily       Daily backup with rotation"
        echo "  --restore     Restore from backup file"
        echo "  --status      Show backup status"
        echo "  --rotate      Rotate old backups"
        echo "  --help        Show this help"
        ;;
    *)
        echo "Unknown option: $1"
        echo "Use --help for usage information"
        exit 1
        ;;
esac
