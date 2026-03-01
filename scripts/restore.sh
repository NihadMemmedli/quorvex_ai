#!/bin/bash
#
# Full Restore Script for Playwright Agent
#
# This script restores from comprehensive backups including:
# - PostgreSQL database
# - Specs directory (test specifications)
# - Tests directory (generated tests)
# - PRDs directory (PRD documents)
# - ChromaDB data directory (vectors + graph store)
# - Test results (Playwright reports)
#
# Usage:
#   ./scripts/restore.sh <timestamp>              # Restore from specific backup
#   ./scripts/restore.sh --latest                 # Restore from latest backup
#   ./scripts/restore.sh --list                   # List available backups
#   ./scripts/restore.sh --from-minio <timestamp> # Download from MinIO and restore
#   ./scripts/restore.sh --verify <timestamp>     # Verify backup integrity
#
# IMPORTANT: Ensure .env file is restored separately before running this script!
# The .env file contains JWT_SECRET_KEY required for credential decryption.
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

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
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

log_step() {
    echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')] STEP:${NC} $1"
}

check_required_vars() {
    if [ -z "${POSTGRES_PASSWORD:-}" ]; then
        log_error "POSTGRES_PASSWORD environment variable is required"
        exit 1
    fi
}

check_minio_config() {
    if [ -z "${MINIO_ROOT_USER:-}" ] || [ -z "${MINIO_ROOT_PASSWORD:-}" ]; then
        log_warn "MinIO credentials not configured"
        return 1
    fi
    return 0
}

confirm_action() {
    local message="$1"
    echo ""
    echo -e "${YELLOW}$message${NC}"
    read -p "Type 'yes' to confirm: " confirm
    if [ "$confirm" != "yes" ]; then
        log_info "Operation cancelled"
        exit 0
    fi
}

# =============================================================================
# MinIO Functions
# =============================================================================

setup_minio_client() {
    if ! command -v mc &> /dev/null; then
        log_warn "MinIO client (mc) not found, attempting to download..."

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

    mc alias set minio "$MINIO_ENDPOINT" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" --api S3v4 2>/dev/null
    return 0
}

download_from_minio() {
    local timestamp="$1"

    log_info "Downloading backup files from MinIO..."

    # Download all files with matching timestamp
    local files=(
        "${timestamp}_db.sql.gz"
        "${timestamp}_specs.tar.gz"
        "${timestamp}_tests.tar.gz"
        "${timestamp}_prds.tar.gz"
        "${timestamp}_data.tar.gz"
        "${timestamp}_runs.tar.gz"
        "${timestamp}_test-results.tar.gz"
        "${timestamp}_manifest.json"
    )

    mkdir -p "$BACKUP_DIR"

    for file in "${files[@]}"; do
        if mc stat "minio/$MINIO_BUCKET/$file" &>/dev/null; then
            log_info "Downloading: $file"
            mc cp "minio/$MINIO_BUCKET/$file" "$BACKUP_DIR/"
        else
            log_warn "File not found in MinIO: $file"
        fi
    done

    log_info "Download completed"
}

# =============================================================================
# Verification Functions
# =============================================================================

verify_backup() {
    local timestamp="$1"
    local manifest="${BACKUP_DIR}/${timestamp}_manifest.json"

    log_info "Verifying backup integrity..."

    if [ ! -f "$manifest" ]; then
        log_error "Manifest not found: $manifest"
        return 1
    fi

    local failed=0

    # Parse manifest and verify checksums
    while IFS= read -r line; do
        local filename=$(echo "$line" | jq -r '.filename // empty' 2>/dev/null)
        local expected_sha=$(echo "$line" | jq -r '.sha256 // empty' 2>/dev/null)

        if [ -n "$filename" ] && [ -n "$expected_sha" ]; then
            local filepath="${BACKUP_DIR}/${filename}"
            if [ -f "$filepath" ]; then
                local actual_sha=$(sha256sum "$filepath" | cut -d' ' -f1)
                if [ "$actual_sha" = "$expected_sha" ]; then
                    log_info "  ✓ $filename - OK"
                else
                    log_error "  ✗ $filename - CHECKSUM MISMATCH"
                    failed=1
                fi
            else
                log_warn "  - $filename - NOT FOUND"
            fi
        fi
    done < <(jq -c '.files | to_entries[] | {filename: .key, sha256: .value.sha256}' "$manifest" 2>/dev/null)

    if [ $failed -eq 0 ]; then
        log_info "Backup verification passed"
        return 0
    else
        log_error "Backup verification failed"
        return 1
    fi
}

# =============================================================================
# Restore Functions
# =============================================================================

restore_database() {
    local timestamp="$1"
    local db_backup="${BACKUP_DIR}/${timestamp}_db.sql.gz"

    if [ ! -f "$db_backup" ]; then
        log_error "Database backup not found: $db_backup"
        return 1
    fi

    log_step "Restoring PostgreSQL database..."

    export PGPASSWORD="$POSTGRES_PASSWORD"

    # Wait for database to be ready
    log_info "Waiting for database connection..."
    local retries=30
    while [ $retries -gt 0 ]; do
        if pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" &>/dev/null; then
            break
        fi
        sleep 1
        retries=$((retries - 1))
    done

    if [ $retries -eq 0 ]; then
        log_error "Database is not ready"
        return 1
    fi

    # Drop existing database and recreate
    log_info "Dropping existing database..."
    psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres \
        -c "DROP DATABASE IF EXISTS ${POSTGRES_DB};" 2>/dev/null || true

    log_info "Creating new database..."
    psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres \
        -c "CREATE DATABASE ${POSTGRES_DB};"

    # Restore from backup
    log_info "Restoring database from backup..."
    gunzip -c "$db_backup" | psql \
        -h "$POSTGRES_HOST" \
        -p "$POSTGRES_PORT" \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        --quiet 2>/dev/null

    log_info "Database restore completed"
}

restore_directory() {
    local timestamp="$1"
    local backup_name="$2"
    local target_dir="$3"
    local backup_file="${BACKUP_DIR}/${timestamp}_${backup_name}.tar.gz"

    if [ ! -f "$backup_file" ]; then
        log_warn "Backup not found, skipping: $backup_file"
        return 0
    fi

    log_step "Restoring $backup_name to $target_dir..."

    # Create parent directory if needed
    mkdir -p "$(dirname "$target_dir")"

    # Backup existing directory if it exists
    if [ -d "$target_dir" ] && [ "$(ls -A "$target_dir" 2>/dev/null)" ]; then
        local backup_existing="${target_dir}.restore-backup"
        log_info "Backing up existing $target_dir to $backup_existing"
        mv "$target_dir" "$backup_existing"
    fi

    # Extract backup
    tar -xzf "$backup_file" -C "$(dirname "$target_dir")"

    log_info "$backup_name restore completed"
}

restore_specs() {
    local timestamp="$1"
    restore_directory "$timestamp" "specs" "$SPECS_DIR"
}

restore_tests() {
    local timestamp="$1"
    restore_directory "$timestamp" "tests" "$TESTS_DIR"
}

restore_prds() {
    local timestamp="$1"
    restore_directory "$timestamp" "prds" "$PRDS_DIR"
}

restore_data() {
    local timestamp="$1"
    restore_directory "$timestamp" "data" "$DATA_DIR"
}

restore_runs() {
    local timestamp="$1"
    restore_directory "$timestamp" "runs" "$RUNS_DIR"
}

restore_test_results() {
    local timestamp="$1"
    restore_directory "$timestamp" "test-results" "$TEST_RESULTS_DIR"
}

restore_scripts() {
    local timestamp="$1"
    restore_directory "$timestamp" "scripts" "$SCRIPTS_DIR"
}

# =============================================================================
# Main Restore Function
# =============================================================================

perform_full_restore() {
    local timestamp="$1"
    local from_minio="${2:-false}"

    log_info "Starting full restore from backup: $timestamp"
    echo ""

    # Check for .env file warning
    echo ""
    log_warn "========================================"
    log_warn "CRITICAL: Ensure .env file is restored!"
    log_warn "========================================"
    log_warn ""
    log_warn "The .env file contains JWT_SECRET_KEY which is required"
    log_warn "to decrypt stored credentials in the database."
    log_warn ""
    log_warn "If JWT_SECRET_KEY is different from the original backup,"
    log_warn "all encrypted credentials will be UNRECOVERABLE."
    log_warn ""

    confirm_action "WARNING: This will overwrite all existing data. Continue?"

    # Download from MinIO if requested
    if [ "$from_minio" = "true" ]; then
        if ! check_minio_config; then
            log_error "MinIO credentials not configured"
            exit 1
        fi
        setup_minio_client
        download_from_minio "$timestamp"
    fi

    # Verify backup exists
    local manifest="${BACKUP_DIR}/${timestamp}_manifest.json"
    if [ ! -f "$manifest" ]; then
        log_error "Backup manifest not found: $manifest"
        log_error "Available backups:"
        list_backups
        exit 1
    fi

    # Verify backup integrity
    verify_backup "$timestamp" || {
        log_warn "Backup verification failed, some files may be missing or corrupted"
        read -p "Continue anyway? (yes/no): " continue_anyway
        if [ "$continue_anyway" != "yes" ]; then
            exit 1
        fi
    }

    echo ""

    # Perform restore in order
    restore_database "$timestamp"
    restore_specs "$timestamp"
    restore_tests "$timestamp"
    restore_prds "$timestamp"
    restore_data "$timestamp"
    restore_runs "$timestamp"
    restore_runs "$timestamp"
    restore_test_results "$timestamp"
    restore_scripts "$timestamp"

    echo ""
    log_info "=== Restore Summary ==="
    echo ""
    echo "Restored from: $timestamp"
    echo ""

    # Show manifest info
    if [ -f "$manifest" ]; then
        echo "Backup details:"
        jq -r '.created_at // "unknown"' "$manifest" | sed 's/^/  Created: /'
        jq -r '.components.database_name // "unknown"' "$manifest" | sed 's/^/  Database: /'
    fi

    echo ""
    log_info "Full restore completed!"
    echo ""

    log_warn "NEXT STEPS:"
    log_warn "1. Verify .env file has correct JWT_SECRET_KEY"
    log_warn "2. Restart the application: docker-compose restart backend frontend"
    log_warn "3. Test user login to verify JWT tokens work"
    log_warn "4. Test credential decryption (view stored credentials)"
}

# =============================================================================
# List Backups Function
# =============================================================================

list_backups() {
    echo "=== Available Backups ==="
    echo ""

    echo "Local backups ($BACKUP_DIR):"
    if ls "${BACKUP_DIR}"/*_manifest.json &>/dev/null; then
        for manifest in "${BACKUP_DIR}"/*_manifest.json; do
            local timestamp=$(basename "$manifest" | sed 's/_manifest.json//')
            local created=$(jq -r '.created_at // "unknown"' "$manifest" 2>/dev/null)
            echo "  $timestamp (created: $created)"
        done
    else
        echo "  None found"
    fi

    echo ""

    # List MinIO backups if configured
    if check_minio_config && setup_minio_client 2>/dev/null; then
        echo "MinIO backups ($MINIO_BUCKET):"
        mc ls minio/"$MINIO_BUCKET"/ 2>/dev/null | grep "_manifest.json" | while read -r line; do
            local filename=$(echo "$line" | awk '{print $NF}')
            local timestamp=$(echo "$filename" | sed 's/_manifest.json//')
            echo "  $timestamp (in MinIO)"
        done || echo "  None found or MinIO not accessible"
    fi
}

# =============================================================================
# Main Script Logic
# =============================================================================

case "${1:-}" in
    --list)
        list_backups
        ;;
    --latest)
        check_required_vars
        latest=$(ls -t "${BACKUP_DIR}"/*_manifest.json 2>/dev/null | head -1)
        if [ -z "$latest" ]; then
            log_error "No local backups found"
            exit 1
        fi
        timestamp=$(basename "$latest" | sed 's/_manifest.json//')
        perform_full_restore "$timestamp" "false"
        ;;
    --from-minio)
        check_required_vars
        if [ -z "${2:-}" ]; then
            log_error "Timestamp required: $0 --from-minio <timestamp>"
            exit 1
        fi
        perform_full_restore "$2" "true"
        ;;
    --verify)
        if [ -z "${2:-}" ]; then
            log_error "Timestamp required: $0 --verify <timestamp>"
            exit 1
        fi
        verify_backup "$2"
        ;;
    --help|-h)
        echo "Usage: $0 [OPTIONS] [timestamp]"
        echo ""
        echo "Options:"
        echo "  <timestamp>               Restore from specific backup timestamp"
        echo "  --latest                  Restore from latest local backup"
        echo "  --list                    List available backups"
        echo "  --from-minio <timestamp>  Download from MinIO and restore"
        echo "  --verify <timestamp>      Verify backup integrity"
        echo "  --help                    Show this help"
        echo ""
        echo "CRITICAL: Before restoring, ensure .env file is in place!"
        echo "The .env file contains JWT_SECRET_KEY required for credential decryption."
        echo ""
        echo "Example:"
        echo "  $0 20240115_143022           # Restore from specific backup"
        echo "  $0 --from-minio 20240115_143022  # Download and restore from MinIO"
        ;;
    "")
        log_error "Timestamp required. Use --list to see available backups."
        echo "Usage: $0 <timestamp> or $0 --latest"
        exit 1
        ;;
    *)
        # Assume first argument is a timestamp
        check_required_vars
        perform_full_restore "$1" "false"
        ;;
esac
