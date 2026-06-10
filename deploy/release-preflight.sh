#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-${VERSION:-}}"
DEFAULT_IMAGE_NAMESPACE="ghcr.io/nihadmemmedli/quorvex-ai"
DEPLOY_DIR="${QUORVEX_DEPLOY_DIR:-/opt/quorvex-deploy-private}"
REQUIRE_PRIVATE_DEPLOY="${QUORVEX_PREFLIGHT_REQUIRE_PRIVATE_DEPLOY:-false}"
PULL_ONLY="${QUORVEX_PREFLIGHT_PULL:-false}"
IMAGE_NAMESPACE=""

log() {
  printf '[release-preflight] %s\n' "$*"
}

die() {
  printf '[release-preflight] ERROR: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

validate_version() {
  [[ "${VERSION}" =~ ^v[0-9]+[.][0-9]+[.][0-9]+([-+][0-9A-Za-z.-]+)?$ ]] \
    || die "VERSION must look like v1.2.3; got '${VERSION:-}'"
}

image_for() {
  printf '%s/%s:%s' "${IMAGE_NAMESPACE}" "$1" "${VERSION}"
}

load_private_env_if_available() {
  local env_file="${QUORVEX_ENV_FILE:-${DEPLOY_DIR}/env/quorvex.prod.env}"
  if [ -f "${env_file}" ]; then
    log "Loading deploy env for preflight: ${env_file}"
    set -a
    # shellcheck disable=SC1090
    . "${env_file}"
    set +a
  elif [ "${REQUIRE_PRIVATE_DEPLOY}" = "true" ]; then
    die "Private deploy env file not found: ${env_file}"
  fi

  IMAGE_NAMESPACE="${QUORVEX_IMAGE_NAMESPACE:-${DEFAULT_IMAGE_NAMESPACE}}"
}

inspect_image() {
  local image="$1"
  if docker manifest inspect "${image}" >/dev/null 2>&1; then
    log "Image available: ${image}"
    return 0
  fi
  printf '[release-preflight] Missing image: %s\n' "${image}" >&2
  return 1
}

run_private_dry_run() {
  if [ -x "${DEPLOY_DIR}/scripts/deploy.sh" ]; then
    log "Running private deploy dry-run in ${DEPLOY_DIR}."
    (cd "${DEPLOY_DIR}" && ./scripts/deploy.sh --dry-run "${VERSION}")
    return
  fi

  if [ "${REQUIRE_PRIVATE_DEPLOY}" = "true" ]; then
    die "Private deploy repo not found or deploy script is not executable: ${DEPLOY_DIR}"
  fi

  log "Private deploy repo not available at ${DEPLOY_DIR}; validating public template instead."
  "${ROOT_DIR}/deploy/test-private-deploy-template.sh"
}

print_server_state() {
  if [ -d "${DEPLOY_DIR}/.state" ]; then
    if [ -f "${DEPLOY_DIR}/.state/current-version" ]; then
      log "Current deployed version: $(cat "${DEPLOY_DIR}/.state/current-version")"
    else
      log "No current deployed version recorded."
    fi
    if [ -f "${DEPLOY_DIR}/.state/previous-version" ]; then
      log "Previous deployed version: $(cat "${DEPLOY_DIR}/.state/previous-version")"
    fi
  fi

  if [ -d "${DEPLOY_DIR}" ]; then
    df -h "${DEPLOY_DIR}" | awk 'NR == 1 || NR == 2 { print "[release-preflight] disk " $0 }'
  fi
}

main() {
  validate_version
  require_command docker
  docker compose version >/dev/null
  load_private_env_if_available

  log "Checking release ${VERSION} in ${IMAGE_NAMESPACE}."
  local failures=0
  for name in backend backend-slim frontend browser-worker k6-worker; do
    inspect_image "$(image_for "${name}")" || failures=$((failures + 1))
  done
  [ "${failures}" -eq 0 ] || die "Release ${VERSION} is not deployable; ${failures} image(s) are missing."

  run_private_dry_run

  if [ "${PULL_ONLY}" = "true" ]; then
    [ -x "${DEPLOY_DIR}/scripts/deploy.sh" ] || die "QUORVEX_PREFLIGHT_PULL=true requires a private deploy repo at ${DEPLOY_DIR}."
    log "Pulling release images through private deploy script."
    (cd "${DEPLOY_DIR}" && ./scripts/deploy.sh --pull-only "${VERSION}")
  fi

  print_server_state
  log "Release preflight passed for ${VERSION}."
}

main "$@"
