#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-${VERSION:-}}"
DEPLOY_DIR="${QUORVEX_DEPLOY_DIR:-/opt/quorvex-deploy-private}"
PUBLIC_URL="${QUORVEX_PUBLIC_URL:-${QUORVEX_DOMAIN:+https://${QUORVEX_DOMAIN}}}"
ENV_FILE="${QUORVEX_ENV_FILE:-${DEPLOY_DIR}/env/quorvex.prod.env}"

log() {
  printf '[server-upgrade] %s\n' "$*"
}

die() {
  printf '[server-upgrade] ERROR: %s\n' "$*" >&2
  exit 1
}

validate_version() {
  [[ "${VERSION}" =~ ^v[0-9]+[.][0-9]+[.][0-9]+([-+][0-9A-Za-z.-]+)?$ ]] \
    || die "VERSION must look like v1.2.3; got '${VERSION:-}'"
}

current_version() {
  if [ -f "${DEPLOY_DIR}/.state/current-version" ]; then
    cat "${DEPLOY_DIR}/.state/current-version"
  fi
}

load_private_env() {
  [ -f "${ENV_FILE}" ] || die "Private deploy env file not found: ${ENV_FILE}"
  set -a
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
  set +a
  PUBLIC_URL="${QUORVEX_PUBLIC_URL:-${QUORVEX_DOMAIN:+https://${QUORVEX_DOMAIN}}}"
}

main() {
  validate_version
  [ -x "${DEPLOY_DIR}/scripts/deploy.sh" ] || die "Private deploy script not found: ${DEPLOY_DIR}/scripts/deploy.sh"
  load_private_env

  local before=""
  before="$(current_version || true)"

  log "Preflighting ${VERSION}."
  QUORVEX_PREFLIGHT_REQUIRE_PRIVATE_DEPLOY=true bash "${ROOT_DIR}/deploy/release-preflight.sh" "${VERSION}"

  log "Deploying ${VERSION} with private deploy script."
  (cd "${DEPLOY_DIR}" && ./scripts/deploy.sh "${VERSION}")

  log "Running local post-deploy checks."
  python3 "${ROOT_DIR}/scripts/deploy_check.py" --env-file "${ENV_FILE}"

  log "Upgrade complete: ${before:-none} -> ${VERSION}"
  if [ -n "${PUBLIC_URL}" ]; then
    log "Final company-workstation validation still required:"
    log "  open ${PUBLIC_URL}"
    log "  confirm login, dashboard API calls, and live browser via ${PUBLIC_URL}/websockify"
  else
    log "Set QUORVEX_PUBLIC_URL or QUORVEX_DOMAIN to print the exact company validation URL."
  fi
}

main "$@"
