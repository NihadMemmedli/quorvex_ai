#!/usr/bin/env bash

set -Eeuo pipefail

# shellcheck source=common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

DRY_RUN=false
PULL_ONLY=false
VERSION=""

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --pull-only)
      PULL_ONLY=true
      shift
      ;;
    -h|--help)
      printf 'Usage: %s [--dry-run|--pull-only] v1.2.3\n' "$0"
      exit 0
      ;;
    *)
      VERSION="$1"
      shift
      ;;
  esac
done

validate_version "${VERSION}"
load_env_file
require_deploy_files
set_image_vars "${VERSION}"

require_command docker
require_command curl
docker compose version >/dev/null

log "Deploying Quorvex ${VERSION}."
log "Image plan:"
print_images

log "Checking production env values."
check_env_values

create_data_dirs
check_disk_space

log "Rendering Compose config."
render_compose

if [ "${DRY_RUN}" = true ]; then
  log "Dry run complete. No images pulled, backups run, or services changed."
  exit 0
fi

log "Pulling release images."
pull_images

if [ "${PULL_ONLY}" = true ]; then
  log "Pull-only mode complete."
  exit 0
fi

CURRENT_VERSION=""
if [ -f "${STATE_DIR}/current-version" ]; then
  CURRENT_VERSION="$(cat "${STATE_DIR}/current-version")"
fi

if [ "${QUORVEX_SKIP_BACKUP:-false}" != "true" ]; then
  log "Running pre-deploy backup."
  compose "backup-full" run --rm backup-full
else
  log "Skipping backup because QUORVEX_SKIP_BACKUP=true."
fi

log "Applying Compose deployment."
compose "${QUORVEX_COMPOSE_PROFILES}" up -d --remove-orphans

log "Waiting for service health."
health_checks

if [ -n "${CURRENT_VERSION}" ] && [ "${CURRENT_VERSION}" != "${VERSION}" ]; then
  printf '%s\n' "${CURRENT_VERSION}" > "${STATE_DIR}/previous-version"
fi
printf '%s\n' "${VERSION}" > "${STATE_DIR}/current-version"
write_image_env "${VERSION}"
append_audit "deployed version=${VERSION} previous=${CURRENT_VERSION:-none}"

log "Deployment complete: ${VERSION}"
