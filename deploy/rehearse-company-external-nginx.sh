#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${QUORVEX_REHEARSAL_HOST:-quorvex.test.internal}"
HTTPS_PORT="${QUORVEX_REHEARSAL_HTTPS_PORT:-9443}"
HTTP_PORT="${QUORVEX_REHEARSAL_HTTP_PORT:-9080}"
FRONTEND_URL="${QUORVEX_FRONTEND_URL:-http://localhost:3000}"
BACKEND_URL="${QUORVEX_BACKEND_URL:-http://localhost:8001}"
FRONTEND_TARGET="${QUORVEX_REHEARSAL_FRONTEND_TARGET:-host.docker.internal:3000}"
VNC_TARGET="${QUORVEX_REHEARSAL_VNC_TARGET:-host.docker.internal:6080}"
CONTAINER_NAME="${QUORVEX_REHEARSAL_CONTAINER:-quorvex-company-nginx-rehearsal}"
START_APP="${QUORVEX_REHEARSAL_START_APP:-true}"
KEEP_NGINX="${QUORVEX_REHEARSAL_KEEP_NGINX:-false}"
TMP_DIR="${QUORVEX_REHEARSAL_TMP_DIR:-$(mktemp -d /tmp/quorvex-company-rehearsal.XXXXXX)}"
ENV_FILE="${QUORVEX_REHEARSAL_ENV_FILE:-${QUORVEX_ENV_FILE:-${ROOT_DIR}/.env.prod}}"

log() {
  printf '[company-rehearsal] %s\n' "$*"
}

die() {
  printf '[company-rehearsal] ERROR: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  if [ "${KEEP_NGINX}" != "true" ]; then
    docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
  else
    log "Keeping nginx rehearsal container: ${CONTAINER_NAME}"
  fi
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

url_ok() {
  curl -fsS --max-time 5 "$1" >/dev/null 2>&1
}

wait_for_url() {
  local name="$1"
  local url="$2"
  local attempts="${3:-60}"
  local i
  for ((i = 1; i <= attempts; i++)); do
    if url_ok "${url}"; then
      log "${name} ready: ${url}"
      return 0
    fi
    sleep 2
  done
  die "${name} did not become ready: ${url}"
}

ensure_app_runtime() {
  if url_ok "${FRONTEND_URL}" && url_ok "${BACKEND_URL}/health"; then
    log "Existing app runtime is ready."
    return
  fi

  [ "${START_APP}" = "true" ] || die "App runtime is not ready. Run 'make start' first or set QUORVEX_REHEARSAL_START_APP=true."
  log "App runtime is not ready; running make start."
  (cd "${ROOT_DIR}" && make start)
  wait_for_url frontend "${FRONTEND_URL}" 60
  wait_for_url backend "${BACKEND_URL}/health" 60
}

write_nginx_config() {
  mkdir -p "${TMP_DIR}/certs" "${TMP_DIR}/nginx"
  openssl req -x509 -newkey rsa:2048 -sha256 -days 2 -nodes \
    -keyout "${TMP_DIR}/certs/key.pem" \
    -out "${TMP_DIR}/certs/cert.pem" \
    -subj "/CN=${HOST}" \
    -addext "subjectAltName=DNS:${HOST}" >/dev/null 2>&1

  cat > "${TMP_DIR}/nginx/default.conf" <<EOF
map \$http_upgrade \$connection_upgrade {
    default upgrade;
    ''      '';
}

upstream quorvex_frontend_rehearsal {
    server ${FRONTEND_TARGET};
    keepalive 16;
}

upstream quorvex_websockify_rehearsal {
    server ${VNC_TARGET};
    keepalive 16;
}

server {
    listen 80;
    server_name ${HOST};
    return 301 https://\$host:${HTTPS_PORT}\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name ${HOST};

    ssl_certificate /etc/nginx/certs/cert.pem;
    ssl_certificate_key /etc/nginx/certs/key.pem;

    client_max_body_size 50m;

    location /websockify {
        proxy_pass http://quorvex_websockify_rehearsal/websockify;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_connect_timeout 60s;
        proxy_send_timeout 3600s;
        proxy_read_timeout 3600s;
    }

    location / {
        proxy_pass http://quorvex_frontend_rehearsal;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_connect_timeout 60s;
        proxy_send_timeout 600s;
        proxy_read_timeout 600s;
    }
}
EOF
}

start_nginx() {
  docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
  docker run -d \
    --name "${CONTAINER_NAME}" \
    --add-host=host.docker.internal:host-gateway \
    -p "127.0.0.1:${HTTP_PORT}:80" \
    -p "127.0.0.1:${HTTPS_PORT}:443" \
    -v "${TMP_DIR}/nginx/default.conf:/etc/nginx/conf.d/default.conf:ro" \
    -v "${TMP_DIR}/certs:/etc/nginx/certs:ro" \
    nginx:alpine >/dev/null

  docker exec "${CONTAINER_NAME}" nginx -t >/dev/null
  for _ in $(seq 1 30); do
    if curl -kfsS --resolve "${HOST}:${HTTPS_PORT}:127.0.0.1" "https://${HOST}:${HTTPS_PORT}/login" >/dev/null 2>&1; then
      log "Temporary company nginx ready: https://${HOST}:${HTTPS_PORT}"
      return
    fi
    sleep 2
  done
  docker logs "${CONTAINER_NAME}" >&2 || true
  die "Temporary company nginx did not become ready."
}

run_smoke() {
  local base_url="https://${HOST}:${HTTPS_PORT}"
  log "Running Playwright company edge smoke against ${base_url}."
  (
    cd "${ROOT_DIR}"
    BASE_URL="${base_url}" \
    PLAYWRIGHT_COMPANY_EDGE_SMOKE=true \
    PLAYWRIGHT_IGNORE_HTTPS_ERRORS=true \
    PLAYWRIGHT_HOST_RESOLVER_RULES="MAP ${HOST} 127.0.0.1" \
    PLAYWRIGHT_WORKERS=1 \
    PLAYWRIGHT_OUTPUT_DIR="${TMP_DIR}/playwright-results" \
    npx playwright test tests/e2e/company-external-nginx.spec.ts --project=chromium
  )
}

main() {
  trap cleanup EXIT
  require_command curl
  require_command docker
  require_command openssl
  require_command npx

  ensure_app_runtime
  python3 "${ROOT_DIR}/scripts/deploy_check.py" --env-file "${ENV_FILE}"
  write_nginx_config
  start_nginx
  run_smoke
  log "Company external-nginx rehearsal passed. Artifacts: ${TMP_DIR}"
}

main "$@"
