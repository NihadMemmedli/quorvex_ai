#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

ENV_FILE="${QUORVEX_ENV_FILE:-${DEPLOY_ROOT}/env/quorvex.prod.env}"
OVERLAY_FILE="${QUORVEX_OVERLAY_FILE:-${DEPLOY_ROOT}/compose/docker-compose.mytest.yml}"
STATE_DIR="${QUORVEX_STATE_DIR:-${DEPLOY_ROOT}/.state}"
PUBLIC_URL="${QUORVEX_PUBLIC_URL:-https://mytest.idda.az}"
DEFAULT_VERSION="${QUORVEX_BOOTSTRAP_VERSION:-v0.0.0}"

log() {
  printf '[quorvex] %s\n' "$*"
}

die() {
  printf '[quorvex] ERROR: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

load_env_file() {
  [ -f "${ENV_FILE}" ] || die "Missing env file: ${ENV_FILE}"
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a

  QUORVEX_SOURCE_DIR="${QUORVEX_SOURCE_DIR:-/opt/quorvex_ai}"
  QUORVEX_IMAGE_NAMESPACE="${QUORVEX_IMAGE_NAMESPACE:-ghcr.io/example-org/quorvex-ai}"
  QUORVEX_DATA_ROOT="${QUORVEX_DATA_ROOT:-${DEPLOY_ROOT}/data}"
  QUORVEX_PRIVATE_CONTENT_DIR="${QUORVEX_PRIVATE_CONTENT_DIR:-${DEPLOY_ROOT}}"
  SPECS_DIR="${SPECS_DIR:-${QUORVEX_PRIVATE_CONTENT_DIR}/specs}"
  TESTS_DIR="${TESTS_DIR:-${QUORVEX_PRIVATE_CONTENT_DIR}/tests}"
  PRDS_DIR="${PRDS_DIR:-${QUORVEX_PRIVATE_CONTENT_DIR}/prds}"
  QUORVEX_COMPOSE_PROFILES="${QUORVEX_COMPOSE_PROFILES:-standard}"
  OVERLAY_FILE="${QUORVEX_OVERLAY_FILE:-${OVERLAY_FILE}}"
  REVERSE_PROXY_FILE="${QUORVEX_REVERSE_PROXY_FILE:-${DEPLOY_ROOT}/reverse-proxy/mytest.idda.az.conf}"
  PUBLIC_URL="${QUORVEX_PUBLIC_URL:-${PUBLIC_URL}}"
  BASE_COMPOSE_FILE="${QUORVEX_BASE_COMPOSE_FILE:-${QUORVEX_SOURCE_DIR}/docker-compose.prod.yml}"
  export QUORVEX_SOURCE_DIR QUORVEX_IMAGE_NAMESPACE QUORVEX_DATA_ROOT
  export QUORVEX_PRIVATE_CONTENT_DIR SPECS_DIR TESTS_DIR PRDS_DIR
  export QUORVEX_COMPOSE_PROFILES OVERLAY_FILE REVERSE_PROXY_FILE PUBLIC_URL BASE_COMPOSE_FILE
  apply_llm_provider_mapping
}

require_deploy_files() {
  [ -f "${ENV_FILE}" ] || die "Missing env file: ${ENV_FILE}"
  [ -f "${OVERLAY_FILE}" ] || die "Missing compose overlay: ${OVERLAY_FILE}"
  [ -f "${BASE_COMPOSE_FILE}" ] || die "Missing public compose file: ${BASE_COMPOSE_FILE}"
}

validate_version() {
  local version="${1:-}"
  [[ "${version}" =~ ^v[0-9]+[.][0-9]+[.][0-9]+([-+][0-9A-Za-z.-]+)?$ ]] \
    || die "Version must look like v1.2.3; got '${version}'"
}

image_for() {
  local name="$1"
  local version="$2"
  printf '%s/%s:%s' "${QUORVEX_IMAGE_NAMESPACE}" "${name}" "${version}"
}

set_image_vars() {
  local version="$1"
  export QUORVEX_BACKEND_IMAGE
  export QUORVEX_BACKEND_SLIM_IMAGE
  export QUORVEX_FRONTEND_IMAGE
  export QUORVEX_BROWSER_WORKER_IMAGE
  export QUORVEX_K6_WORKER_IMAGE
  QUORVEX_BACKEND_IMAGE="$(image_for backend "${version}")"
  QUORVEX_BACKEND_SLIM_IMAGE="$(image_for backend-slim "${version}")"
  QUORVEX_FRONTEND_IMAGE="$(image_for frontend "${version}")"
  QUORVEX_BROWSER_WORKER_IMAGE="$(image_for browser-worker "${version}")"
  QUORVEX_K6_WORKER_IMAGE="$(image_for k6-worker "${version}")"
}

write_image_env() {
  local version="$1"
  mkdir -p "${STATE_DIR}"
  cat > "${STATE_DIR}/images.env" <<EOF
QUORVEX_BACKEND_IMAGE=${QUORVEX_BACKEND_IMAGE}
QUORVEX_BACKEND_SLIM_IMAGE=${QUORVEX_BACKEND_SLIM_IMAGE}
QUORVEX_FRONTEND_IMAGE=${QUORVEX_FRONTEND_IMAGE}
QUORVEX_BROWSER_WORKER_IMAGE=${QUORVEX_BROWSER_WORKER_IMAGE}
QUORVEX_K6_WORKER_IMAGE=${QUORVEX_K6_WORKER_IMAGE}
QUORVEX_DEPLOYED_VERSION=${version}
EOF
}

load_image_state() {
  if [ -f "${STATE_DIR}/images.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "${STATE_DIR}/images.env"
    set +a
  fi
}

compose_profiles_args() {
  local profiles="${1:-${QUORVEX_COMPOSE_PROFILES}}"
  local args=()
  local profile
  for profile in ${profiles}; do
    args+=(--profile "${profile}")
  done
  printf '%s\0' "${args[@]}"
}

compose() {
  local profiles="${1:-${QUORVEX_COMPOSE_PROFILES}}"
  shift || true
  local args=()
  while IFS= read -r -d '' arg; do
    args+=("${arg}")
  done < <(compose_profiles_args "${profiles}")

  docker compose \
    --env-file "${ENV_FILE}" \
    -f "${BASE_COMPOSE_FILE}" \
    -f "${OVERLAY_FILE}" \
    "${args[@]}" \
    "$@"
}

required_env_keys() {
  printf '%s\n' \
    QUORVEX_SOURCE_DIR \
    QUORVEX_IMAGE_NAMESPACE \
    QUORVEX_DATA_ROOT \
    QUORVEX_PRIVATE_CONTENT_DIR \
    SPECS_DIR \
    TESTS_DIR \
    PRDS_DIR \
    QUORVEX_PUBLIC_URL \
    ALLOWED_ORIGINS \
    VNC_PUBLIC_WS_URL \
    JWT_SECRET_KEY \
    POSTGRES_PASSWORD \
    MINIO_ROOT_PASSWORD \
    INITIAL_ADMIN_EMAIL \
    INITIAL_ADMIN_PASSWORD
}

env_value() {
  local key="$1"
  local value="${!key-}"
  printf '%s' "${value}"
}

has_real_env_value() {
  local value="${1:-}"
  [ -n "${value}" ] || return 1
  case "${value}" in
    *replace-with*|your-*|example-*|*example-org*|placeholder-*)
      return 1
      ;;
  esac
  return 0
}

normalize_llm_provider() {
  local provider="${1:-zai}"
  provider="$(printf '%s' "${provider}" | tr '[:upper:]' '[:lower:]')"
  case "${provider}" in
    zai|z-ai|z_ai|glm)
      printf 'zai'
      ;;
    openrouter|open-router|open_router)
      printf 'openrouter'
      ;;
    openai|open-ai|open_ai)
      printf 'openai'
      ;;
    anthropic|anthropic_compatible|anthropic-compatible|claude)
      printf 'anthropic'
      ;;
    hermes|hermes_agent|hermes-agent)
      printf 'hermes'
      ;;
    *)
      die "QUORVEX_ACTIVE_LLM_PROVIDER must be one of: zai, openrouter, openai, anthropic, hermes."
      ;;
  esac
}

set_env_value() {
  local key="$1"
  local value="$2"
  export "${key}=${value}"
}

set_if_missing_or_placeholder() {
  local key="$1"
  local value="$2"
  local current="${!key-}"
  if ! has_real_env_value "${current}"; then
    set_env_value "${key}" "${value}"
  fi
}

apply_anthropic_compatible_provider() {
  local provider_key="$1"
  local base_url="$2"
  local light_model="$3"
  local standard_model="$4"
  local deep_model="$5"
  local chat_model="$6"
  local api_key="${!provider_key-}"

  set_env_value QUORVEX_LLM_PROVIDER "anthropic_compatible"
  set_env_value QUORVEX_LLM_BASE_URL "${base_url}"
  set_env_value ANTHROPIC_BASE_URL "${base_url}"
  set_env_value QUORVEX_LLM_LIGHT_MODEL "${light_model}"
  set_env_value QUORVEX_LLM_STANDARD_MODEL "${standard_model}"
  set_env_value QUORVEX_LLM_DEEP_MODEL "${deep_model}"
  set_env_value QUORVEX_LLM_TOOL_DEEP_MODEL "${deep_model}"
  set_env_value QUORVEX_LLM_CHAT_MODEL "${chat_model}"
  set_env_value QUORVEX_EMBEDDING_MODEL "text-embedding-3-small"
  set_env_value ANTHROPIC_MODEL "${deep_model}"
  set_env_value ANTHROPIC_DEFAULT_OPUS_MODEL "${deep_model}"
  set_env_value ANTHROPIC_DEFAULT_SONNET_MODEL "${standard_model}"
  set_env_value ANTHROPIC_DEFAULT_HAIKU_MODEL "${light_model}"
  set_env_value ANTHROPIC_CHAT_MODEL "${chat_model}"
  set_env_value ANTHROPIC_ENABLE_CHAT_THINKING "${ANTHROPIC_ENABLE_CHAT_THINKING:-false}"
  set_env_value API_TIMEOUT_MS "${API_TIMEOUT_MS:-3000000}"

  if has_real_env_value "${api_key}"; then
    set_env_value QUORVEX_LLM_API_KEY "${api_key}"
    set_env_value ANTHROPIC_AUTH_TOKEN "${api_key}"
    if [ "${provider_key}" = "ANTHROPIC_API_KEY" ]; then
      set_env_value ANTHROPIC_API_KEY "${api_key}"
    fi
    if [ "${provider_key}" = "ZAI_API_KEY" ]; then
      set_env_value GLM_API_KEY "${api_key}"
    fi
  else
    set_env_value QUORVEX_LLM_API_KEY ""
    set_env_value ANTHROPIC_AUTH_TOKEN ""
    if [ "${provider_key}" = "ANTHROPIC_API_KEY" ]; then
      set_env_value ANTHROPIC_API_KEY ""
    fi
  fi
}

apply_openai_provider() {
  local api_key="${OPENAI_API_KEY:-}"

  set_env_value QUORVEX_LLM_PROVIDER "openai"
  set_env_value QUORVEX_LLM_BASE_URL "https://api.openai.com/v1"
  set_env_value OPENAI_BASE_URL "https://api.openai.com/v1"
  set_env_value QUORVEX_LLM_LIGHT_MODEL "gpt-4o-mini"
  set_env_value QUORVEX_LLM_STANDARD_MODEL "gpt-4o-mini"
  set_env_value QUORVEX_LLM_DEEP_MODEL "gpt-4o"
  set_env_value QUORVEX_LLM_TOOL_DEEP_MODEL "gpt-4o"
  set_env_value QUORVEX_LLM_CHAT_MODEL "gpt-4o-mini"
  set_env_value QUORVEX_EMBEDDING_MODEL "text-embedding-3-small"
  set_env_value OPENAI_CHAT_MODEL "gpt-4o-mini"

  if has_real_env_value "${api_key}"; then
    set_env_value QUORVEX_LLM_API_KEY "${api_key}"
  else
    set_env_value QUORVEX_LLM_API_KEY ""
  fi
  set_env_value ANTHROPIC_AUTH_TOKEN ""
  set_env_value ANTHROPIC_API_KEY ""
}

apply_named_llm_provider() {
  local provider="$1"
  case "${provider}" in
    zai)
      apply_anthropic_compatible_provider \
        ZAI_API_KEY \
        "https://api.z.ai/api/anthropic" \
        "glm-4.5-air" \
        "glm-5-turbo" \
        "glm-5.1" \
        "glm-5-turbo"
      ;;
    openrouter)
      apply_anthropic_compatible_provider \
        OPENROUTER_API_KEY \
        "https://openrouter.ai/api" \
        "anthropic/claude-3.5-haiku" \
        "anthropic/claude-sonnet-4" \
        "anthropic/claude-opus-4" \
        "anthropic/claude-sonnet-4"
      ;;
    openai)
      apply_openai_provider
      ;;
    anthropic)
      apply_anthropic_compatible_provider \
        ANTHROPIC_API_KEY \
        "https://api.anthropic.com" \
        "claude-3-5-haiku-latest" \
        "claude-sonnet-4-20250514" \
        "claude-opus-4-20250514" \
        "claude-sonnet-4-20250514"
      ;;
    *)
      die "Unsupported upstream LLM provider: ${provider}"
      ;;
  esac
}

apply_llm_provider_mapping() {
  local active_provider upstream_provider
  active_provider="$(normalize_llm_provider "${QUORVEX_ACTIVE_LLM_PROVIDER:-zai}")"
  set_env_value QUORVEX_ACTIVE_LLM_PROVIDER "${active_provider}"

  if [ "${active_provider}" = "hermes" ]; then
    upstream_provider="$(normalize_llm_provider "${HERMES_UPSTREAM_PROVIDER:-zai}")"
    [ "${upstream_provider}" != "hermes" ] || die "HERMES_UPSTREAM_PROVIDER cannot be hermes."
    apply_named_llm_provider "${upstream_provider}"
    set_env_value HERMES_UPSTREAM_PROVIDER "${upstream_provider}"
    set_env_value QUORVEX_AGENT_RUNTIME "hermes"
    set_env_value HERMES_ENABLED "true"
    set_env_value HERMES_API_URL "${HERMES_API_URL:-http://hermes:8642}"
    set_env_value HERMES_MODEL "${HERMES_MODEL:-hermes-agent}"
    return
  fi

  apply_named_llm_provider "${active_provider}"
  set_env_value QUORVEX_AGENT_RUNTIME "claude_sdk"
  set_env_value HERMES_ENABLED "false"
}

check_llm_provider_values() {
  local active_provider key_name key_value upstream_provider
  active_provider="$(normalize_llm_provider "${QUORVEX_ACTIVE_LLM_PROVIDER:-zai}")"

  case "${active_provider}" in
    zai)
      key_name=ZAI_API_KEY
      ;;
    openrouter)
      key_name=OPENROUTER_API_KEY
      ;;
    openai)
      key_name=OPENAI_API_KEY
      ;;
    anthropic)
      key_name=ANTHROPIC_API_KEY
      ;;
    hermes)
      upstream_provider="$(normalize_llm_provider "${HERMES_UPSTREAM_PROVIDER:-zai}")"
      case "${upstream_provider}" in
        zai) key_name=ZAI_API_KEY ;;
        openrouter) key_name=OPENROUTER_API_KEY ;;
        openai) key_name=OPENAI_API_KEY ;;
        anthropic) key_name=ANTHROPIC_API_KEY ;;
        *) die "Unsupported Hermes upstream provider: ${upstream_provider}" ;;
      esac
      ;;
    *)
      die "Unsupported active LLM provider: ${active_provider}"
      ;;
  esac

  key_value="$(env_value "${key_name}")"
  if ! has_real_env_value "${key_value}"; then
    printf '[quorvex] missing or placeholder env value for active LLM provider %s: %s\n' "${active_provider}" "${key_name}" >&2
    return 1
  fi

  if ! has_real_env_value "${QUORVEX_LLM_API_KEY:-}"; then
    printf '[quorvex] active LLM provider %s did not map to QUORVEX_LLM_API_KEY\n' "${active_provider}" >&2
    return 1
  fi

  return 0
}

check_env_values() {
  local failures=0
  local key value
  while IFS= read -r key; do
    value="$(env_value "${key}")"
    if [ -z "${value}" ]; then
      printf '[quorvex] missing env value: %s\n' "${key}" >&2
      failures=$((failures + 1))
    elif ! has_real_env_value "${value}"; then
      printf '[quorvex] placeholder env value: %s\n' "${key}" >&2
      failures=$((failures + 1))
    fi
  done < <(required_env_keys)
  check_llm_provider_values || failures=$((failures + 1))
  [ "${failures}" -eq 0 ] || die "Fix env placeholders before deploying."
}

create_data_dirs() {
  mkdir -p \
    "${QUORVEX_DATA_ROOT}/app-data" \
    "${QUORVEX_DATA_ROOT}/backups" \
    "${QUORVEX_DATA_ROOT}/generated-scripts" \
    "${QUORVEX_DATA_ROOT}/logs" \
    "${QUORVEX_DATA_ROOT}/minio" \
    "${QUORVEX_DATA_ROOT}/postgres" \
    "${QUORVEX_DATA_ROOT}/redis" \
    "${QUORVEX_DATA_ROOT}/runs" \
    "${QUORVEX_DATA_ROOT}/test-results" \
    "${SPECS_DIR}" \
    "${TESTS_DIR}" \
    "${PRDS_DIR}" \
    "${STATE_DIR}"
}

port_from_bind() {
  local bind="$1"
  printf '%s' "${bind##*:}"
}

url_from_bind() {
  local bind="$1"
  local path="${2:-}"
  local host port

  port="$(port_from_bind "${bind}")"
  if [ "${bind}" = "${port}" ]; then
    host="127.0.0.1"
  else
    host="${bind%:*}"
  fi
  case "${host}" in
    ""|"0.0.0.0"|"[::]"|"::")
      host="127.0.0.1"
      ;;
  esac

  printf 'http://%s:%s%s' "${host}" "${port}" "${path}"
}

check_port_available() {
  local label="$1"
  local bind="$2"
  local port
  port="$(port_from_bind "${bind}")"
  if command -v lsof >/dev/null 2>&1; then
    if lsof -iTCP:"${port}" -sTCP:LISTEN -Pn >/dev/null 2>&1; then
      printf '[quorvex] port in use for %s: %s\n' "${label}" "${bind}" >&2
      return 1
    fi
  elif command -v ss >/dev/null 2>&1; then
    if ss -ltn "( sport = :${port} )" | grep -q ":${port}"; then
      printf '[quorvex] port in use for %s: %s\n' "${label}" "${bind}" >&2
      return 1
    fi
  fi
  return 0
}

check_required_ports_available() {
  local failures=0
  check_port_available frontend "${FRONTEND_BIND:-127.0.0.1:3000}" || failures=$((failures + 1))
  check_port_available backend "${BACKEND_BIND:-127.0.0.1:8001}" || failures=$((failures + 1))
  check_port_available websockify "${VNC_BIND:-127.0.0.1:6080}" || failures=$((failures + 1))
  check_port_available minio-api "${MINIO_API_BIND:-127.0.0.1:9000}" || failures=$((failures + 1))
  check_port_available minio-console "${MINIO_CONSOLE_BIND:-127.0.0.1:9001}" || failures=$((failures + 1))
  check_port_available temporal "${TEMPORAL_BIND:-127.0.0.1:7233}" || failures=$((failures + 1))
  check_port_available temporal-ui "${TEMPORAL_UI_BIND:-127.0.0.1:8233}" || failures=$((failures + 1))
  check_port_available hermes-api "${HERMES_API_BIND:-127.0.0.1:8642}" || failures=$((failures + 1))
  check_port_available hermes-dashboard "${HERMES_DASHBOARD_BIND:-127.0.0.1:9119}" || failures=$((failures + 1))
  check_port_available zap "${ZAP_BIND:-127.0.0.1:8090}" || failures=$((failures + 1))
  [ "${failures}" -eq 0 ] || die "Required app ports are already in use."
}

check_disk_space() {
  local root="${QUORVEX_DATA_ROOT}"
  local min_gb="${QUORVEX_MIN_FREE_GB:-20}"
  local available_kb
  mkdir -p "${root}"
  available_kb="$(df -Pk "${root}" | awk 'NR==2 {print $4}')"
  if [ "${available_kb}" -lt $((min_gb * 1024 * 1024)) ]; then
    die "Less than ${min_gb}GB free for ${root}."
  fi
}

render_compose() {
  compose "${QUORVEX_COMPOSE_PROFILES}" config >/dev/null
}

pull_images() {
  docker pull "${QUORVEX_BACKEND_IMAGE}"
  docker pull "${QUORVEX_BACKEND_SLIM_IMAGE}"
  docker pull "${QUORVEX_FRONTEND_IMAGE}"
  docker pull "${QUORVEX_BROWSER_WORKER_IMAGE}"
  docker pull "${QUORVEX_K6_WORKER_IMAGE}"
}

print_images() {
  printf '%s\n' \
    "${QUORVEX_BACKEND_IMAGE}" \
    "${QUORVEX_BACKEND_SLIM_IMAGE}" \
    "${QUORVEX_FRONTEND_IMAGE}" \
    "${QUORVEX_BROWSER_WORKER_IMAGE}" \
    "${QUORVEX_K6_WORKER_IMAGE}"
}

wait_for_url() {
  local name="$1"
  local url="$2"
  local attempts="${3:-60}"
  local sleep_seconds="${4:-5}"
  local i

  for ((i = 1; i <= attempts; i++)); do
    if curl -fsS --max-time 10 "${url}" >/dev/null 2>&1; then
      log "${name} is ready: ${url}"
      return 0
    fi
    sleep "${sleep_seconds}"
  done

  die "${name} did not become ready: ${url}"
}

health_checks() {
  wait_for_url backend "${QUORVEX_BACKEND_HEALTH_URL:-$(url_from_bind "${BACKEND_BIND:-127.0.0.1:8001}" "/health")}" "${QUORVEX_HEALTH_ATTEMPTS:-60}" 5
  wait_for_url frontend "${QUORVEX_FRONTEND_HEALTH_URL:-$(url_from_bind "${FRONTEND_BIND:-127.0.0.1:3000}")}" "${QUORVEX_HEALTH_ATTEMPTS:-60}" 5

  if [ "${QUORVEX_SKIP_PUBLIC_CHECK:-false}" != "true" ]; then
    wait_for_url public "${PUBLIC_URL}" "${QUORVEX_PUBLIC_HEALTH_ATTEMPTS:-24}" 5
    wait_for_url login "${PUBLIC_URL}/login" "${QUORVEX_PUBLIC_HEALTH_ATTEMPTS:-24}" 5
  else
    log "Skipping public URL checks because QUORVEX_SKIP_PUBLIC_CHECK=true."
  fi
}

append_audit() {
  local message="$1"
  mkdir -p "${STATE_DIR}"
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${message}" >> "${STATE_DIR}/deploy-audit.log"
}
