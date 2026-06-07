#!/usr/bin/env bash

set -Eeuo pipefail

# shellcheck source=common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

STATUS_ONLY=false
LOGS=false

case "${1:-}" in
  --status-only)
    STATUS_ONLY=true
    ;;
  --logs)
    LOGS=true
    ;;
  "")
    ;;
  *)
    die "Usage: $0 [--status-only|--logs]"
    ;;
esac

load_env_file
require_deploy_files
set_image_vars "${QUORVEX_DEPLOYED_VERSION:-${DEFAULT_VERSION}}"
load_image_state

if [ "${LOGS}" = true ]; then
  compose "${QUORVEX_COMPOSE_PROFILES}" logs -f backend frontend db redis minio temporal
  exit 0
fi

if [ "${STATUS_ONLY}" = true ]; then
  compose "${QUORVEX_COMPOSE_PROFILES}" ps
  exit 0
fi

log "Checking local tooling."
require_command docker
require_command curl
docker compose version >/dev/null

log "Checking deployment files."
check_env_values
create_data_dirs
check_disk_space

log "Rendering Docker Compose config."
render_compose

log "Current image plan:"
print_images

if [ -f "${STATE_DIR}/current-version" ]; then
  log "Current deployed version: $(cat "${STATE_DIR}/current-version")"
else
  log "No current deployed version recorded yet."
fi

log "Service status:"
compose "${QUORVEX_COMPOSE_PROFILES}" ps || true

log "Doctor checks passed."
