#!/bin/bash
#
# Full Backup Script for Playwright Agent
#
# This script creates comprehensive backups including:
# - PostgreSQL database
# - Specs directory (test specifications)
# - Tests directory (generated tests)
# - PRDs directory (PRD documents)
# - ChromaDB data directory (vectors + graph store)
# - Test results (Playwright reports)
#
# All backups are synced to MinIO for off-site storage.
#
# Usage:
#   ./scripts/full_backup.sh                    # Full backup with MinIO sync
#   ./scripts/full_backup.sh --daily            # Daily backup with rotation
#   ./scripts/full_backup.sh --manual           # Manual backup (no rotation)
#   ./scripts/full_backup.sh --no-sync          # Backup without MinIO sync
#   ./scripts/full_backup.sh --restore <ts>     # Restore from backup timestamp
#   ./scripts/full_backup.sh --status           # Show backup status
#
# Configuration via environment variables:
#   POSTGRES_USER       - Database user (default: playwright)
#   POSTGRES_PASSWORD   - Database password (required)
#   POSTGRES_DB         - Database name (default: playwright_agent)
#   POSTGRES_HOST       - Database host (default: db)
#   POSTGRES_PORT       - Database port (default: 5432)
#   BACKUP_DIR          - Local backup directory (default: /backups)
#   BACKUP_RETENTION    - Days to keep backups (default: 30)
#   MINIO_ENDPOINT      - MinIO endpoint (default: http://minio:9000)
#   MINIO_ROOT_USER     - MinIO access key (required for sync)
#   MINIO_ROOT_PASSWORD - MinIO secret key (required for sync)
#   MINIO_BUCKET        - MinIO bucket name (default: playwright-backups)
#

set -euo pipefail

# =============================================================================
# Configuration
# =============================================================================

# PostgreSQL configuration
POSTGRES_USER="${POSTGRES_USER:-playwright}"
POSTGRES_DB="${POSTGRES_DB:-playwright_agent}"
POSTGRES_HOST="${POSTGRES_HOST:-db}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"

# Backup configuration
BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_RETENTION="${BACKUP_RETENTION:-30}"
ARCHIVE_RETENTION="${ARCHIVE_RETENTION:-90}"

# MinIO configuration
MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://minio:9000}"
MINIO_ROOT_USER="${MINIO_ROOT_USER:-}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-}"
MINIO_BUCKET="${MINIO_BUCKET:-playwright-backups}"

# Application directories (inside container)
APP_DIR="${APP_DIR:-/app}"
SPECS_DIR="${APP_DIR}/specs"
TESTS_DIR="${APP_DIR}/tests"
PRDS_DIR="${APP_DIR}/prds"
DATA_DIR="${APP_DIR}/data"
RUNS_DIR="${APP_DIR}/runs"
TEST_RESULTS_DIR="${APP_DIR}/test-results"
SCRIPTS_DIR="${APP_DIR}/scripts"

# Timestamp for backup filename
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_PREFIX="${BACKUP_DIR}/${TIMESTAMP}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# =============================================================================
# Helper Functions
# =============================================================================

log_info() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1"
}

log_error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1" >&2
}

check_required_vars() {
    if [ -z "${POSTGRES_PASSWORD:-}" ]; then
        log_error "POSTGRES_PASSWORD environment variable is required"
        exit 1
    fi
}

check_minio_config() {
    if [ -z "${MINIO_ROOT_USER:-}" ] || [ -z "${MINIO_ROOT_PASSWORD:-}" ]; then
        log_warn "MinIO credentials not configured, skipping sync"
        return 1
    fi
    return 0
}

# Calculate directory size in MB
get_dir_size() {
    local dir="$1"
    if [ -d "$dir" ]; then
        du -sm "$dir" 2>/dev/null | cut -f1
    else
        echo "0"
    fi
}

# =============================================================================
# Backup Functions
# =============================================================================

backup_database() {
    log_info "Backing up PostgreSQL database..."

    export PGPASSWORD="$POSTGRES_PASSWORD"

    local db_backup="${BACKUP_PREFIX}_db.sql.gz"

    pg_dump \
        -h "$POSTGRES_HOST" \
        -p "$POSTGRES_PORT" \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        --no-owner \
        --no-privileges \
        2>/var/log/pg_dump.log | gzip > "$db_backup"

    if [ -f "$db_backup" ] && [ -s "$db_backup" ]; then
        local size=$(du -h "$db_backup" | cut -f1)
        log_info "Database backup completed: $db_backup ($size)"
        return 0
    else
        log_error "Database backup failed or file is empty"
        rm -f "$db_backup"
        return 1
    fi
}

backup_directory() {
    local src_dir="$1"
    local backup_name="$2"
    local backup_file="${BACKUP_PREFIX}_${backup_name}.tar.gz"

    if [ ! -d "$src_dir" ]; then
        log_warn "Directory not found, skipping: $src_dir"
        return 0
    fi

    local src_size=$(get_dir_size "$src_dir")
    if [ "$src_size" -eq 0 ]; then
        log_warn "Directory is empty, skipping: $src_dir"
        return 0
    fi

    log_info "Backing up $backup_name (${src_size}MB)..."

    # Create archive with relative paths
    tar -czf "$backup_file" -C "$(dirname "$src_dir")" "$(basename "$src_dir")" 2>/dev/null || {
        log_warn "Some files could not be archived from $src_dir"
    }

    if [ -f "$backup_file" ]; then
        local size=$(du -h "$backup_file" | cut -f1)
        log_info "$backup_name backup completed: $backup_file ($size)"
        return 0
    else
        log_error "Failed to create backup: $backup_file"
        return 1
    fi
}

backup_specs() {
    backup_directory "$SPECS_DIR" "specs"
}

backup_tests() {
    backup_directory "$TESTS_DIR" "tests"
}

backup_prds() {
    backup_directory "$PRDS_DIR" "prds"
}

backup_data() {
    backup_directory "$DATA_DIR" "data"
}

backup_runs() {
    backup_directory "$RUNS_DIR" "runs"
}

backup_test_results() {
    backup_directory "$TEST_RESULTS_DIR" "test-results"
}


backup_scripts() {
    backup_directory "$SCRIPTS_DIR" "scripts"
}

create_manifest() {
    log_info "Creating backup manifest..."

    local manifest_file="${BACKUP_PREFIX}_manifest.json"

    # Generate checksums for all backup files
    local checksums=()
    local files_found=0

    # Find all backup files with this timestamp
    while IFS= read -r -d '' file; do
        if [ -f "$file" ]; then
            local checksum=$(sha256sum "$file" | cut -d' ' -f1)
            local filename=$(basename "$file")
            local size=$(stat -f%z "$file" 2>/dev/null || stat -c%s "$file" 2>/dev/null || echo "0")
            checksums+=("\"$filename\": {\"sha256\": \"$checksum\", \"size\": $size}")
            files_found=$((files_found + 1))
        fi
    done < <(find "$BACKUP_DIR" -maxdepth 1 -name "${TIMESTAMP}_*" -type f -print0 2>/dev/null)

    # Build JSON manifest
    local files_json=""
    if [ ${#checksums[@]} -gt 0 ]; then
        files_json=$(IFS=,; echo "${checksums[*]}")
    fi

    cat > "$manifest_file" << EOF
{
    "timestamp": "$TIMESTAMP",
    "created_at": "$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S)",
    "version": "1.0",
    "components": {
        "database": "postgresql",
        "database_name": "$POSTGRES_DB",
        "specs_dir": "$SPECS_DIR",
        "tests_dir": "$TESTS_DIR",
        "prds_dir": "$PRDS_DIR",
        "prds_dir": "$PRDS_DIR",
        "data_dir": "$DATA_DIR",
        "scripts_dir": "$SCRIPTS_DIR"
    },
    "files": {
        $files_json
    },
    "retention": {
        "hot_days": $BACKUP_RETENTION,
        "archive_days": $ARCHIVE_RETENTION
    },
    "notes": [
        "CRITICAL: .env file must be backed up separately",
        "Contains JWT_SECRET_KEY required for credential decryption"
    ]
}
EOF

    log_info "Manifest created: $manifest_file ($files_found files tracked)"
}

# =============================================================================
# MinIO Sync Functions
# =============================================================================

setup_minio_client() {
    log_info "Configuring MinIO client..."

    # Check if mc is available
    if ! command -v mc &> /dev/null; then
        log_warn "MinIO client (mc) not found, attempting to download..."

        # Download mc based on architecture
        local arch=$(uname -m)
        local mc_url=""

        case "$arch" in
            x86_64)
                mc_url="https://dl.min.io/client/mc/release/linux-amd64/mc"
                ;;
            aarch64|arm64)
                mc_url="https://dl.min.io/client/mc/release/linux-arm64/mc"
                ;;
            *)
                log_error "Unsupported architecture: $arch"
                return 1
                ;;
        esac

        curl -sL "$mc_url" -o /usr/local/bin/mc && chmod +x /usr/local/bin/mc
    fi

    # Configure mc alias
    mc alias set minio "$MINIO_ENDPOINT" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" --api S3v4 2>/dev/null

    # Create bucket if it doesn't exist
    if ! mc ls minio/"$MINIO_BUCKET" &>/dev/null; then
        log_info "Creating MinIO bucket: $MINIO_BUCKET"
        mc mb minio/"$MINIO_BUCKET" --ignore-existing
    fi

    return 0
}

sync_to_minio() {
    log_info "Syncing backups to MinIO..."

    # Sync all backup files from current timestamp
    local uploaded=0
    while IFS= read -r -d '' file; do
        if [ -f "$file" ]; then
            local filename=$(basename "$file")
            log_info "Uploading: $filename"
            mc cp "$file" "minio/$MINIO_BUCKET/$filename"
            uploaded=$((uploaded + 1))
        fi
    done < <(find "$BACKUP_DIR" -maxdepth 1 -name "${TIMESTAMP}_*" -type f -print0 2>/dev/null)

    log_info "MinIO sync completed ($uploaded files uploaded)"
}

cleanup_minio_old() {
    log_info "Cleaning up old backups in MinIO (older than $ARCHIVE_RETENTION days)..."

    # Calculate cutoff date
    local cutoff_date=$(date -d "-${ARCHIVE_RETENTION} days" +%Y%m%d 2>/dev/null || \
                        date -v-${ARCHIVE_RETENTION}d +%Y%m%d 2>/dev/null)

    if [ -z "$cutoff_date" ]; then
        log_warn "Could not calculate cutoff date, skipping MinIO cleanup"
        return 0
    fi

    # List and remove old files
    mc ls minio/"$MINIO_BUCKET"/ --json 2>/dev/null | while read -r line; do
        local key=$(echo "$line" | jq -r '.key // empty' 2>/dev/null)
        if [ -n "$key" ]; then
            # Extract timestamp from filename (format: YYYYMMDD_HHMMSS)
            local file_date=$(echo "$key" | grep -oE '^[0-9]{8}' || echo "")
            if [ -n "$file_date" ] && [ "$file_date" -lt "$cutoff_date" ]; then
                log_info "Removing old backup: $key"
                mc rm "minio/$MINIO_BUCKET/$key" 2>/dev/null || true
            fi
        fi
    done
}

# =============================================================================
# Rotation Functions
# =============================================================================

rotate_local_backups() {
    log_info "Rotating local backups older than $BACKUP_RETENTION days..."

    local deleted_count=0

    # Find and delete old backups
    while IFS= read -r -d '' file; do
        rm -f "$file"
        deleted_count=$((deleted_count + 1))
        log_info "  Deleted: $(basename "$file")"
    done < <(find "$BACKUP_DIR" -name "*_db.sql.gz" -o -name "*_*.tar.gz" -o -name "*_manifest.json" -type f -mtime +$BACKUP_RETENTION -print0 2>/dev/null || true)

    if [ $deleted_count -eq 0 ]; then
        log_info "  No old backups to delete"
    else
        log_info "  Deleted $deleted_count old file(s)"
    fi
}

# =============================================================================
# Status Functions
# =============================================================================

show_status() {
    echo "=== Full Backup Status ==="
    echo ""
    echo "Configuration:"
    echo "  Backup directory: $BACKUP_DIR"
    echo "  Retention: $BACKUP_RETENTION days (local), $ARCHIVE_RETENTION days (MinIO)"
    echo "  MinIO endpoint: $MINIO_ENDPOINT"
    echo "  MinIO bucket: $MINIO_BUCKET"
    echo ""

    echo "Local Backups:"
    local latest=$(ls -t "${BACKUP_DIR}"/*_manifest.json 2>/dev/null | head -1)
    if [ -n "$latest" ]; then
        echo "  Latest: $(basename "$latest" | sed 's/_manifest.json//')"
        cat "$latest" | jq -r '.created_at // "unknown"' 2>/dev/null | sed 's/^/  Created: /'
    else
        echo "  No backups found"
    fi
    echo ""

    echo "Recent backups:"
    ls -lht "${BACKUP_DIR}"/*_manifest.json 2>/dev/null | head -5 || echo "  None"
    echo ""

    echo "Local backup size:"
    du -sh "$BACKUP_DIR" 2>/dev/null || echo "  N/A"
    echo ""

    # MinIO status
    if check_minio_config; then
        echo "MinIO Status:"
        if setup_minio_client 2>/dev/null; then
            mc ls minio/"$MINIO_BUCKET"/ --summarize 2>/dev/null | tail -3 || echo "  Could not connect"
        else
            echo "  MinIO client not available"
        fi
    else
        echo "MinIO: Not configured"
    fi
}

# =============================================================================
# Full Backup Function
# =============================================================================

perform_full_backup() {
    local backup_type="${1:-full}"
    local sync_enabled="${2:-true}"

    log_info "Starting $backup_type backup..."
    echo ""

    # Create backup directory
    mkdir -p "$BACKUP_DIR"

    # Perform all backups
    local failed=0

    backup_database || failed=1
    backup_specs || true
    backup_tests || true
    backup_prds || true
    backup_data || true
    backup_runs || true
    backup_runs || true
    backup_test_results || true
    backup_scripts || true

    # Create manifest
    create_manifest

    echo ""

    # Sync to MinIO if enabled and configured
    if [ "$sync_enabled" = "true" ] && check_minio_config; then
        if setup_minio_client; then
            sync_to_minio
            cleanup_minio_old
        fi
    fi

    # Show summary
    echo ""
    log_info "=== Backup Summary ==="
    echo ""
    echo "Timestamp: $TIMESTAMP"
    echo "Location: $BACKUP_DIR"
    echo ""
    echo "Files created:"
    ls -lh "${BACKUP_PREFIX}"_* 2>/dev/null | awk '{print "  " $NF " (" $5 ")"}'
    echo ""

    if [ $failed -eq 0 ]; then
        log_info "Backup completed successfully!"
    else
        log_warn "Backup completed with warnings (some components may have failed)"
    fi

    # Create symlink to latest
    ln -sf "${BACKUP_PREFIX}_manifest.json" "${BACKUP_DIR}/latest_manifest.json"

    echo ""
    log_warn "REMINDER: Backup .env file separately - it contains JWT_SECRET_KEY!"
    log_warn "Without JWT_SECRET_KEY, encrypted credentials cannot be decrypted."

    return $failed
}

# =============================================================================
# Main Script Logic
# =============================================================================

case "${1:-}" in
    --manual)
        check_required_vars
        perform_full_backup "manual" "true"
        ;;
    --daily)
        check_required_vars
        perform_full_backup "daily" "true"
        rotate_local_backups
        ;;
    --no-sync)
        check_required_vars
        perform_full_backup "manual" "false"
        ;;
    --status)
        show_status
        ;;
    --rotate)
        rotate_local_backups
        ;;
    --help|-h)
        echo "Usage: $0 [OPTIONS]"
        echo ""
        echo "Options:"
        echo "  (default)     Full backup with MinIO sync"
        echo "  --daily       Daily backup with rotation and MinIO sync"
        echo "  --manual      Manual backup with MinIO sync"
        echo "  --no-sync     Backup without MinIO sync"
        echo "  --status      Show backup status"
        echo "  --rotate      Rotate old local backups"
        echo "  --help        Show this help"
        echo ""
        echo "Backed up components:"
        echo "  - PostgreSQL database"
        echo "  - /app/specs (test specifications)"
        echo "  - /app/tests (generated tests)"
        echo "  - /app/prds (PRD documents)"
        echo "  - /app/data (ChromaDB vectors + graph store)"
        echo "  - /app/runs (run artifacts)"
        echo "  - /app/test-results (Playwright reports)"
        echo ""
        echo "IMPORTANT: .env file must be backed up separately!"
        echo "It contains JWT_SECRET_KEY required for credential decryption."
        ;;
    "")
        check_required_vars
        perform_full_backup "full" "true"
        ;;
    *)
        log_error "Unknown option: $1"
        echo "Use --help for usage information"
        exit 1
        ;;
esac
