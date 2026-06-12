#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${VERSION:-}"
SERVER_HOST="${QUORVEX_SERVER_HOST:-}"
SERVER_SOURCE_DIR="${QUORVEX_SERVER_SOURCE_DIR:-/opt/quorvex_ai}"
SERVER_DEPLOY_DIR="${QUORVEX_DEPLOY_DIR:-/opt/quorvex-deploy-private}"
REMOTE="${QUORVEX_GIT_REMOTE:-origin}"
BRANCH="${QUORVEX_RELEASE_BRANCH:-main}"
IMAGE_NAMESPACE="${QUORVEX_IMAGE_NAMESPACE:-ghcr.io/nihadmemmedli/quorvex-ai}"
POLL_ATTEMPTS="${QUORVEX_IMAGE_POLL_ATTEMPTS:-60}"
POLL_SECONDS="${QUORVEX_IMAGE_POLL_SECONDS:-15}"
DRY_RUN=true

log() {
  printf '[release-to-server] %s\n' "$*"
}

die() {
  printf '[release-to-server] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: VERSION=v1.2.3 QUORVEX_SERVER_HOST=user@host scripts/release_to_server.sh [--deploy]

Checks the local release state, pushes the branch and tag, waits for GHCR
release images, then runs the production server upgrade over SSH when --deploy
is provided. Without --deploy it prints the remote command and exits after
local/tag/image checks.
EOF
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

validate_version() {
  [[ "${VERSION}" =~ ^v[0-9]+[.][0-9]+[.][0-9]+([-+][0-9A-Za-z.-]+)?$ ]] \
    || die "VERSION must look like v1.2.3; got '${VERSION:-}'"
}

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --deploy)
        DRY_RUN=false
        ;;
      --dry-run)
        DRY_RUN=true
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "Unknown argument: $1"
        ;;
    esac
    shift
  done
}

image_for() {
  printf '%s/%s:%s' "${IMAGE_NAMESPACE}" "$1" "${VERSION}"
}

check_local_git_state() {
  local current_branch
  current_branch="$(git -C "${ROOT_DIR}" branch --show-current)"
  [ "${current_branch}" = "${BRANCH}" ] || die "Expected branch ${BRANCH}; current branch is ${current_branch:-detached}."
  git -C "${ROOT_DIR}" diff --quiet || die "Worktree has unstaged changes."
  git -C "${ROOT_DIR}" diff --cached --quiet || die "Worktree has staged but uncommitted changes."
  git -C "${ROOT_DIR}" fetch "${REMOTE}" --tags
  git -C "${ROOT_DIR}" rev-parse --verify "${REMOTE}/${BRANCH}" >/dev/null
  git -C "${ROOT_DIR}" merge-base --is-ancestor "${REMOTE}/${BRANCH}" HEAD \
    || die "Local ${BRANCH} is behind ${REMOTE}/${BRANCH}."
}

ensure_release_tag() {
  if git -C "${ROOT_DIR}" rev-parse -q --verify "refs/tags/${VERSION}" >/dev/null; then
    local tagged_head
    tagged_head="$(git -C "${ROOT_DIR}" rev-list -n 1 "${VERSION}")"
    [ "${tagged_head}" = "$(git -C "${ROOT_DIR}" rev-parse HEAD)" ] \
      || die "Tag ${VERSION} exists but does not point at HEAD."
  else
    log "Creating annotated tag ${VERSION}."
    git -C "${ROOT_DIR}" tag -a "${VERSION}" -m "Release ${VERSION}"
  fi
}

push_release_refs() {
  log "Pushing ${BRANCH} and ${VERSION} to ${REMOTE}."
  git -C "${ROOT_DIR}" push "${REMOTE}" "${BRANCH}"
  git -C "${ROOT_DIR}" push "${REMOTE}" "${VERSION}"
}

wait_for_images() {
  local attempt image name failures
  require_command docker
  for ((attempt = 1; attempt <= POLL_ATTEMPTS; attempt++)); do
    failures=0
    for name in backend backend-slim frontend browser-worker k6-worker; do
      image="$(image_for "${name}")"
      if ! docker manifest inspect "${image}" >/dev/null 2>&1; then
        failures=$((failures + 1))
      fi
    done
    if [ "${failures}" -eq 0 ]; then
      log "All release images are available in ${IMAGE_NAMESPACE}."
      return
    fi
    log "Waiting for release images (${attempt}/${POLL_ATTEMPTS}); ${failures} missing."
    sleep "${POLL_SECONDS}"
  done
  die "Timed out waiting for release images for ${VERSION}."
}

run_remote_upgrade() {
  [ -n "${SERVER_HOST}" ] || die "Set QUORVEX_SERVER_HOST=user@host."
  local remote_command
  remote_command="set -Eeuo pipefail; git -C '${SERVER_SOURCE_DIR}' pull --ff-only; QUORVEX_DEPLOY_DIR='${SERVER_DEPLOY_DIR}' make -C '${SERVER_SOURCE_DIR}' server-upgrade VERSION='${VERSION}'"
  if [ "${DRY_RUN}" = true ]; then
    log "Dry run complete. Remote command not executed:"
    printf '%s\n' "ssh ${SERVER_HOST} ${remote_command}"
    return
  fi
  require_command ssh
  log "Running server upgrade on ${SERVER_HOST}."
  ssh "${SERVER_HOST}" "${remote_command}"
}

main() {
  parse_args "$@"
  validate_version
  if [ "${DRY_RUN}" = false ] && [ -z "${SERVER_HOST}" ]; then
    die "Set QUORVEX_SERVER_HOST=user@host."
  fi
  require_command git
  check_local_git_state
  ensure_release_tag
  push_release_refs
  wait_for_images
  run_remote_upgrade
}

main "$@"
