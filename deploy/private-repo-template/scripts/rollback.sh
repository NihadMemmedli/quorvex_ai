#!/usr/bin/env bash

set -Eeuo pipefail

# shellcheck source=common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

load_env_file
require_deploy_files

[ -f "${STATE_DIR}/previous-version" ] || die "No previous successful version recorded."

PREVIOUS_VERSION="$(cat "${STATE_DIR}/previous-version")"
CURRENT_VERSION=""
if [ -f "${STATE_DIR}/current-version" ]; then
  CURRENT_VERSION="$(cat "${STATE_DIR}/current-version")"
fi

validate_version "${PREVIOUS_VERSION}"
set_image_vars "${PREVIOUS_VERSION}"

require_command docker
require_command curl
docker compose version >/dev/null

log "Rolling back from ${CURRENT_VERSION:-unknown} to ${PREVIOUS_VERSION}."
log "Image plan:"
print_images

log "Checking production env values."
check_env_values

create_data_dirs
check_disk_space

log "Rendering Compose config."
render_compose

log "Pulling rollback images."
pull_images

log "Applying rollback deployment."
compose "${QUORVEX_COMPOSE_PROFILES}" up -d --remove-orphans

log "Waiting for service health."
health_checks

if [ -n "${CURRENT_VERSION}" ]; then
  printf '%s\n' "${CURRENT_VERSION}" > "${STATE_DIR}/failed-version"
fi
printf '%s\n' "${PREVIOUS_VERSION}" > "${STATE_DIR}/current-version"
write_image_env "${PREVIOUS_VERSION}"
append_audit "rollback to=${PREVIOUS_VERSION} failed=${CURRENT_VERSION:-unknown}"

log "Rollback complete: ${PREVIOUS_VERSION}"
