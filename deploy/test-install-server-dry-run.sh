#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d /tmp/quorvex-install-test.XXXXXX)"
FAKE_BIN="${TMP_DIR}/bin"
PUBLIC_REPO="${TMP_DIR}/public-repo"
PRIVATE_SOURCE="${TMP_DIR}/private-source"
SOURCE_DIR="${TMP_DIR}/install-public"
DEPLOY_DIR="${TMP_DIR}/install-private"
LOG_FILE="${TMP_DIR}/installer.log"

log() {
  printf '[install-test] %s\n' "$*"
}

pick_port() {
  local port
  for port in $(seq 31000 33000); do
    if [[ " ${USED_TEST_PORTS:-} " == *" ${port} "* ]]; then
      continue
    fi
    if ! lsof -iTCP:"${port}" -sTCP:LISTEN -Pn >/dev/null 2>&1; then
      USED_TEST_PORTS="${USED_TEST_PORTS:-} ${port}"
      printf '%s' "${port}"
      return
    fi
  done
  printf 'No free test port found.\n' >&2
  exit 1
}

FRONTEND_PORT="$(pick_port)"
BACKEND_PORT="$(pick_port)"
VNC_PORT="$(pick_port)"

make_git_repo() {
  local dir="$1"
  (
    cd "${dir}"
    git init -q
    git config user.email test@example.com
    git config user.name "Quorvex Test"
    git add .
    git commit -q -m "Initial test repo"
  )
}

mkdir -p "${FAKE_BIN}" "${PUBLIC_REPO}" "${PRIVATE_SOURCE}/env" "${PRIVATE_SOURCE}/compose" "${PRIVATE_SOURCE}/reverse-proxy" "${PRIVATE_SOURCE}/scripts"

cat > "${FAKE_BIN}/docker" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail

case "${1:-}" in
  compose)
    shift
    if [ "${1:-}" = "version" ]; then
      printf 'Docker Compose version v2.99.0\n'
      exit 0
    fi
    if [ "$#" -gt 0 ] && [ "${@: -1}" = "config" ]; then
      exit 0
    fi
    printf 'fake docker compose only supports version and config\n' >&2
    exit 2
    ;;
  info)
    printf 'fake docker info\n'
    ;;
  manifest)
    exit 1
    ;;
  pull)
    printf 'fake docker pull %s\n' "${2:-}"
    ;;
  *)
    printf 'fake docker only supports compose/info/manifest/pull\n' >&2
    exit 2
    ;;
esac
EOF
chmod +x "${FAKE_BIN}/docker"

log "Creating local public repo fixture."
cp -R "${ROOT_DIR}/deploy" "${PUBLIC_REPO}/deploy"
cp "${ROOT_DIR}/docker-compose.prod.yml" "${PUBLIC_REPO}/docker-compose.prod.yml"
make_git_repo "${PUBLIC_REPO}"

log "Creating sparse private repo fixture with missing deploy files."
cat > "${PRIVATE_SOURCE}/README.md" <<'EOF'
# Test private deploy repo
EOF
cp "${ROOT_DIR}/deploy/private-repo-template/compose/docker-compose.mytest.example.yml" "${PRIVATE_SOURCE}/compose/docker-compose.company.yml"
sed -i.bak '/HERMES_CONTAINER_NAME/d' "${PRIVATE_SOURCE}/compose/docker-compose.company.yml"
sed -i.bak 's/^    ports: !override$/    ports:/' "${PRIVATE_SOURCE}/compose/docker-compose.company.yml"
rm -f "${PRIVATE_SOURCE}/compose/docker-compose.company.yml.bak"
make_git_repo "${PRIVATE_SOURCE}"

log "Running installer dry-run against local repos."
PATH="${FAKE_BIN}:${PATH}" \
QUORVEX_PUBLIC_REPO="${PUBLIC_REPO}" \
QUORVEX_DEPLOY_REPO="${PRIVATE_SOURCE}" \
QUORVEX_SOURCE_DIR="${SOURCE_DIR}" \
QUORVEX_DEPLOY_DIR="${DEPLOY_DIR}" \
QUORVEX_DATA_ROOT="${TMP_DIR}/data" \
QUORVEX_DOMAIN="quorvex.test.internal" \
QUORVEX_SITE="company" \
QUORVEX_IMAGE_NAMESPACE="ghcr.io/test-org/quorvex-ai" \
QUORVEX_VERSION="v1.2.3" \
QUORVEX_ACTIVE_LLM_PROVIDER="zai" \
ZAI_API_KEY="test-zai-key" \
FRONTEND_BIND="127.0.0.1:${FRONTEND_PORT}" \
BACKEND_BIND="127.0.0.1:${BACKEND_PORT}" \
VNC_BIND="127.0.0.1:${VNC_PORT}" \
HERMES_CONTAINER_NAME="quorvex-test-hermes" \
QUORVEX_MIN_FREE_GB=0 \
QUORVEX_SKIP_REGISTRY_CHECK=true \
QUORVEX_SKIP_PUBLIC_CHECK=true \
bash "${ROOT_DIR}/deploy/install-server.sh" 2>&1 | tee "${LOG_FILE}"

log "Checking installer reported and created missing files."
grep -q "Private env file missing: ${DEPLOY_DIR}/env/quorvex.prod.env" "${LOG_FILE}"
grep -q "Created private env file" "${LOG_FILE}"
grep -q "Private compose overlay present: ${DEPLOY_DIR}/compose/docker-compose.company.yml" "${LOG_FILE}"
grep -q "Added Hermes container-name override to private compose overlay" "${LOG_FILE}"
grep -q "Added private compose port-list overrides" "${LOG_FILE}"
grep -q "Private reverse proxy config missing: ${DEPLOY_DIR}/reverse-proxy/quorvex.test.internal.conf" "${LOG_FILE}"
grep -q "Created private reverse proxy config from template" "${LOG_FILE}"
grep -q "Running deploy dry-run for v1.2.3" "${LOG_FILE}"
grep -q "Dry-run complete. Set QUORVEX_CONFIRM_DEPLOY=true" "${LOG_FILE}"

test -f "${DEPLOY_DIR}/env/quorvex.prod.env"
test -f "${DEPLOY_DIR}/compose/docker-compose.company.yml"
test -f "${DEPLOY_DIR}/reverse-proxy/quorvex.test.internal.conf"
test -x "${DEPLOY_DIR}/scripts/bootstrap.sh"
test -x "${DEPLOY_DIR}/scripts/deploy.sh"

log "Checking generated settings."
grep -q '^QUORVEX_PUBLIC_API_URL=$' "${DEPLOY_DIR}/env/quorvex.prod.env"
grep -q '^NEXT_PUBLIC_API_URL=$' "${DEPLOY_DIR}/env/quorvex.prod.env"
grep -q '^INTERNAL_API_URL=http://backend:8001$' "${DEPLOY_DIR}/env/quorvex.prod.env"
grep -q '^VNC_PUBLIC_WS_URL=wss://quorvex.test.internal/websockify$' "${DEPLOY_DIR}/env/quorvex.prod.env"
grep -q '^RECORDER_BROWSER_URL=$' "${DEPLOY_DIR}/env/quorvex.prod.env"
grep -q '^QUORVEX_OVERLAY_FILE='"${DEPLOY_DIR}"'/compose/docker-compose.company.yml$' "${DEPLOY_DIR}/env/quorvex.prod.env"
grep -q '^HERMES_CONTAINER_NAME=quorvex-test-hermes$' "${DEPLOY_DIR}/env/quorvex.prod.env"
grep -q 'container_name: ${HERMES_CONTAINER_NAME:-quorvex-hermes}' "${DEPLOY_DIR}/compose/docker-compose.company.yml"
grep -q 'ports: !override' "${DEPLOY_DIR}/compose/docker-compose.company.yml"
grep -q 'server_name quorvex.test.internal;' "${DEPLOY_DIR}/reverse-proxy/quorvex.test.internal.conf"

if grep -q 'replace-with-at-least-32-random-bytes\|replace-with-strong-postgres-password\|replace-with-strong-minio-password\|replace-with-strong-initial-admin-password' "${DEPLOY_DIR}/env/quorvex.prod.env"; then
  printf 'Installer left generated-secret placeholders in private env.\n' >&2
  exit 1
fi

log "Installer dry-run test passed."
