#!/usr/bin/env bash

set -Eeuo pipefail

# shellcheck source=common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

load_env_file
require_deploy_files
set_image_vars "${DEFAULT_VERSION}"

log "Checking Docker and Compose."
require_command docker
require_command curl
docker compose version >/dev/null
docker info >/dev/null

log "Checking production env values."
check_env_values

log "Creating persistent directories under ${QUORVEX_DATA_ROOT}."
create_data_dirs

log "Checking disk space."
check_disk_space

log "Checking required app ports."
check_required_ports_available

log "Rendering Compose config without starting services."
render_compose

log "Checking GHCR image registry access using ${QUORVEX_IMAGE_NAMESPACE}."
if [ "${QUORVEX_SKIP_REGISTRY_CHECK:-false}" != "true" ]; then
  if ! docker manifest inspect "$(image_for backend "${QUORVEX_REGISTRY_CHECK_VERSION:-${DEFAULT_VERSION}}")" >/dev/null 2>&1; then
    log "Registry check could not find ${QUORVEX_REGISTRY_CHECK_VERSION:-${DEFAULT_VERSION}}."
    log "Set QUORVEX_REGISTRY_CHECK_VERSION to an existing tag, or QUORVEX_SKIP_REGISTRY_CHECK=true for bootstrap-only validation."
  else
    log "Registry access verified."
  fi
fi

log "Reverse proxy template:"
log "  ${REVERSE_PROXY_FILE}"
log "Install it into your nginx sites-enabled path after verifying certificate paths."

log "Bootstrap checks completed. Run: ./scripts/deploy.sh --dry-run v1.2.3"
