#!/usr/bin/env bash

set -Eeuo pipefail

PUBLIC_REPO="${QUORVEX_PUBLIC_REPO:-https://github.com/NihadMemmedli/quorvex_ai.git}"
DEPLOY_REPO="${QUORVEX_DEPLOY_REPO:-NihadMemmedli/quorvex-deploy-private}"
SOURCE_DIR="${QUORVEX_SOURCE_DIR:-/opt/quorvex_ai}"
DEPLOY_DIR="${QUORVEX_DEPLOY_DIR:-/opt/quorvex-deploy-private}"
DATA_ROOT="${QUORVEX_DATA_ROOT:-/srv/quorvex/mytest}"
DOMAIN="${QUORVEX_DOMAIN:-mytest.idda.az}"
IMAGE_NAMESPACE="${QUORVEX_IMAGE_NAMESPACE:-ghcr.io/nihadmemmedli/quorvex-ai}"
VERSION="${QUORVEX_VERSION:-}"
CONFIRM_DEPLOY="${QUORVEX_CONFIRM_DEPLOY:-false}"
SITE="${QUORVEX_SITE:-mytest}"
PUBLIC_URL="${QUORVEX_PUBLIC_URL:-https://${DOMAIN}}"
SYNC_PRIVATE_SCRIPTS="${QUORVEX_SYNC_PRIVATE_SCRIPTS:-true}"

log() {
  printf '[quorvex-install] %s\n' "$*"
}

die() {
  printf '[quorvex-install] ERROR: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

sudo_cmd() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif "$@" 2>/dev/null; then
    return 0
  else
    require_command sudo
    sudo "$@"
  fi
}

random_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 64
  fi
}

random_admin_password() {
  printf 'Qvx-%s-Aa1!' "$(random_secret)"
}

clone_or_update_public_repo() {
  if [ -d "${SOURCE_DIR}/.git" ]; then
    log "Updating public source repo at ${SOURCE_DIR}."
    git -C "${SOURCE_DIR}" diff --quiet || die "${SOURCE_DIR} has local changes; commit or clean them before updating."
    git -C "${SOURCE_DIR}" pull --ff-only
    return
  fi

  log "Cloning public source repo into ${SOURCE_DIR}."
  sudo_cmd mkdir -p "${SOURCE_DIR}"
  sudo_cmd chown "$(id -u):$(id -g)" "${SOURCE_DIR}"
  rmdir "${SOURCE_DIR}"
  git clone "${PUBLIC_REPO}" "${SOURCE_DIR}"
}

private_clone_url() {
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    printf 'https://x-access-token:%s@github.com/%s.git' "${GITHUB_TOKEN}" "${DEPLOY_REPO}"
  else
    printf 'https://github.com/%s.git' "${DEPLOY_REPO}"
  fi
}

clone_or_update_private_repo() {
  if [ -d "${DEPLOY_DIR}/.git" ]; then
    log "Updating private deploy repo at ${DEPLOY_DIR}."
    git -C "${DEPLOY_DIR}" diff --quiet || die "${DEPLOY_DIR} has local changes; commit or clean them before updating."
    git -C "${DEPLOY_DIR}" pull --ff-only
    return
  fi

  log "Cloning private deploy repo into ${DEPLOY_DIR}."
  sudo_cmd mkdir -p "${DEPLOY_DIR}"
  sudo_cmd chown "$(id -u):$(id -g)" "${DEPLOY_DIR}"
  rmdir "${DEPLOY_DIR}"

  if [ -d "${DEPLOY_REPO}/.git" ] || [ -f "${DEPLOY_REPO}/HEAD" ]; then
    git clone "${DEPLOY_REPO}" "${DEPLOY_DIR}"
  elif command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    gh repo clone "${DEPLOY_REPO}" "${DEPLOY_DIR}"
  elif [ -n "${GITHUB_TOKEN:-}" ]; then
    git clone "$(private_clone_url)" "${DEPLOY_DIR}"
    git -C "${DEPLOY_DIR}" remote set-url origin "https://github.com/${DEPLOY_REPO}.git"
  else
    die "Cannot clone private repo. Run 'gh auth login' first or provide GITHUB_TOKEN."
  fi
}

replace_or_append_env() {
  local key="$1"
  local value="$2"
  local file="$3"

  if grep -q "^${key}=" "${file}"; then
    sed -i.bak "s|^${key}=.*|${key}=${value}|" "${file}"
  else
    printf '%s=%s\n' "${key}" "${value}" >> "${file}"
  fi
}

copy_template_file() {
  local source="$1"
  local target="$2"
  local mode="${3:-}"

  [ -f "${source}" ] || die "Missing template file: ${source}"
  mkdir -p "$(dirname "${target}")"
  cp "${source}" "${target}"
  if [ -n "${mode}" ]; then
    chmod "${mode}" "${target}"
  fi
}

replace_file_token() {
  local file="$1"
  local pattern="$2"
  local value="$3"

  sed -i.bak "s|${pattern}|${value}|g" "${file}"
  rm -f "${file}.bak"
}

ensure_hermes_container_name_override() {
  local file="$1"

  if grep -q 'HERMES_CONTAINER_NAME' "${file}"; then
    return
  fi

  if grep -q '^  hermes:' "${file}"; then
    sed -i.bak '/^  hermes:$/a\
    container_name: ${HERMES_CONTAINER_NAME:-quorvex-hermes}
' "${file}"
    rm -f "${file}.bak"
    log "Added Hermes container-name override to private compose overlay: ${file}"
  fi
}

ensure_private_overlay_port_overrides() {
  local file="$1"

  if grep -q '^    ports: !override' "${file}"; then
    return
  fi

  if grep -q '^    ports:' "${file}"; then
    sed -i.bak 's/^    ports:$/    ports: !override/' "${file}"
    rm -f "${file}.bak"
    log "Added private compose port-list overrides: ${file}"
  fi
}

report_private_file_state() {
  local label="$1"
  local file="$2"

  if [ -f "${file}" ]; then
    log "Private ${label} present: ${file}"
  else
    log "Private ${label} missing: ${file}"
  fi
}

private_overlay_file() {
  printf '%s' "${QUORVEX_OVERLAY_FILE:-${DEPLOY_DIR}/compose/docker-compose.${SITE}.yml}"
}

ensure_private_repo_scripts() {
  local template_dir="${SOURCE_DIR}/deploy/private-repo-template"
  local script

  [ -d "${template_dir}" ] || die "Missing private repo template in public checkout: ${template_dir}"

  for script in bootstrap common deploy doctor rollback; do
    if [ ! -f "${DEPLOY_DIR}/scripts/${script}.sh" ]; then
      log "Private script missing: ${DEPLOY_DIR}/scripts/${script}.sh"
      copy_template_file "${template_dir}/scripts/${script}.sh" "${DEPLOY_DIR}/scripts/${script}.sh" 755
      log "Created private script from template: ${DEPLOY_DIR}/scripts/${script}.sh"
    elif [ "${SYNC_PRIVATE_SCRIPTS}" = "true" ]; then
      log "Syncing private script from public template: ${DEPLOY_DIR}/scripts/${script}.sh"
      copy_template_file "${template_dir}/scripts/${script}.sh" "${DEPLOY_DIR}/scripts/${script}.sh" 755
    else
      log "Private script present: ${DEPLOY_DIR}/scripts/${script}.sh"
    fi
  done

  if [ ! -f "${DEPLOY_DIR}/Makefile" ]; then
    log "Private Makefile missing: ${DEPLOY_DIR}/Makefile"
    copy_template_file "${template_dir}/Makefile" "${DEPLOY_DIR}/Makefile" 644
    log "Created private Makefile from template: ${DEPLOY_DIR}/Makefile"
  else
    log "Private Makefile present: ${DEPLOY_DIR}/Makefile"
  fi
}

ensure_private_compose_overlay() {
  local template_dir="${SOURCE_DIR}/deploy/private-repo-template"
  local overlay_file
  local example_file="${template_dir}/compose/docker-compose.mytest.example.yml"
  overlay_file="$(private_overlay_file)"

  report_private_file_state "compose overlay" "${overlay_file}"
  if [ ! -f "${overlay_file}" ]; then
    copy_template_file "${example_file}" "${overlay_file}" 644
    log "Created private compose overlay from template: ${overlay_file}"
  fi
  ensure_hermes_container_name_override "${overlay_file}"
  ensure_private_overlay_port_overrides "${overlay_file}"

  if [ "${overlay_file}" != "${DEPLOY_DIR}/compose/docker-compose.mytest.yml" ] && [ -z "${QUORVEX_OVERLAY_FILE:-}" ]; then
    replace_or_append_env QUORVEX_OVERLAY_FILE "${overlay_file}" "${DEPLOY_DIR}/env/quorvex.prod.env"
  fi
}

ensure_private_reverse_proxy() {
  local template_dir="${SOURCE_DIR}/deploy/private-repo-template"
  local proxy_file="${QUORVEX_REVERSE_PROXY_FILE:-${DEPLOY_DIR}/reverse-proxy/${DOMAIN}.conf}"
  local example_file="${template_dir}/reverse-proxy/mytest.idda.az.example.conf"

  report_private_file_state "reverse proxy config" "${proxy_file}"
  if [ ! -f "${proxy_file}" ]; then
    copy_template_file "${example_file}" "${proxy_file}" 644
    replace_file_token "${proxy_file}" "mytest.idda.az" "${DOMAIN}"
    log "Created private reverse proxy config from template: ${proxy_file}"
  fi

  replace_or_append_env QUORVEX_REVERSE_PROXY_FILE "${proxy_file}" "${DEPLOY_DIR}/env/quorvex.prod.env"
}

env_file_value() {
  local key="$1"
  local file="$2"
  local line
  line="$(grep -E "^${key}=" "${file}" | tail -n 1 || true)"
  printf '%s' "${line#*=}"
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

replace_or_append_if_placeholder() {
  local key="$1"
  local value="$2"
  local file="$3"
  local current
  current="$(env_file_value "${key}" "${file}")"

  if ! has_real_env_value "${current}"; then
    replace_or_append_env "${key}" "${value}" "${file}"
  fi
}

replace_or_append_if_env_provided_or_placeholder() {
  local env_key="$1"
  local target_key="$2"
  local value="$3"
  local file="$4"

  if [ -n "${!env_key+x}" ]; then
    replace_or_append_env "${target_key}" "${value}" "${file}"
  else
    replace_or_append_if_placeholder "${target_key}" "${value}" "${file}"
  fi
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

env_or_file_value() {
  local key="$1"
  local file="$2"
  local value="${!key-}"
  if has_real_env_value "${value}"; then
    printf '%s' "${value}"
    return
  fi
  value="$(env_file_value "${key}" "${file}")"
  if has_real_env_value "${value}"; then
    printf '%s' "${value}"
  fi
}

write_if_provided() {
  local key="$1"
  local file="$2"
  local value="${!key-}"
  if [ -n "${value}" ]; then
    replace_or_append_env "${key}" "${value}" "${file}"
  fi
}

write_anthropic_compatible_runtime() {
  local env_file="$1"
  local provider_key="$2"
  local base_url="$3"
  local light_model="$4"
  local standard_model="$5"
  local deep_model="$6"
  local chat_model="$7"
  local api_key
  api_key="$(env_or_file_value "${provider_key}" "${env_file}")"

  replace_or_append_env QUORVEX_LLM_PROVIDER "anthropic_compatible" "${env_file}"
  replace_or_append_env QUORVEX_LLM_BASE_URL "${base_url}" "${env_file}"
  replace_or_append_env ANTHROPIC_BASE_URL "${base_url}" "${env_file}"
  replace_or_append_env QUORVEX_LLM_LIGHT_MODEL "${light_model}" "${env_file}"
  replace_or_append_env QUORVEX_LLM_STANDARD_MODEL "${standard_model}" "${env_file}"
  replace_or_append_env QUORVEX_LLM_DEEP_MODEL "${deep_model}" "${env_file}"
  replace_or_append_env QUORVEX_LLM_TOOL_DEEP_MODEL "${deep_model}" "${env_file}"
  replace_or_append_env QUORVEX_LLM_CHAT_MODEL "${chat_model}" "${env_file}"
  replace_or_append_env QUORVEX_EMBEDDING_MODEL "text-embedding-3-small" "${env_file}"
  replace_or_append_env ANTHROPIC_MODEL "${deep_model}" "${env_file}"
  replace_or_append_env ANTHROPIC_DEFAULT_OPUS_MODEL "${deep_model}" "${env_file}"
  replace_or_append_env ANTHROPIC_DEFAULT_SONNET_MODEL "${standard_model}" "${env_file}"
  replace_or_append_env ANTHROPIC_DEFAULT_HAIKU_MODEL "${light_model}" "${env_file}"
  replace_or_append_env ANTHROPIC_CHAT_MODEL "${chat_model}" "${env_file}"
  replace_or_append_env ANTHROPIC_ENABLE_CHAT_THINKING "${ANTHROPIC_ENABLE_CHAT_THINKING:-false}" "${env_file}"
  replace_or_append_env API_TIMEOUT_MS "${API_TIMEOUT_MS:-3000000}" "${env_file}"

  if has_real_env_value "${api_key}"; then
    replace_or_append_env QUORVEX_LLM_API_KEY "${api_key}" "${env_file}"
    replace_or_append_env ANTHROPIC_AUTH_TOKEN "${api_key}" "${env_file}"
    if [ "${provider_key}" = "ANTHROPIC_API_KEY" ]; then
      replace_or_append_env ANTHROPIC_API_KEY "${api_key}" "${env_file}"
    fi
    if [ "${provider_key}" = "ZAI_API_KEY" ]; then
      replace_or_append_env GLM_API_KEY "${api_key}" "${env_file}"
    fi
  else
    replace_or_append_env QUORVEX_LLM_API_KEY "" "${env_file}"
    replace_or_append_env ANTHROPIC_AUTH_TOKEN "" "${env_file}"
    if [ "${provider_key}" = "ANTHROPIC_API_KEY" ]; then
      replace_or_append_env ANTHROPIC_API_KEY "" "${env_file}"
    fi
  fi
}

write_openai_runtime() {
  local env_file="$1"
  local api_key
  api_key="$(env_or_file_value OPENAI_API_KEY "${env_file}")"

  replace_or_append_env QUORVEX_LLM_PROVIDER "openai" "${env_file}"
  replace_or_append_env QUORVEX_LLM_BASE_URL "https://api.openai.com/v1" "${env_file}"
  replace_or_append_env OPENAI_BASE_URL "https://api.openai.com/v1" "${env_file}"
  replace_or_append_env QUORVEX_LLM_LIGHT_MODEL "gpt-4o-mini" "${env_file}"
  replace_or_append_env QUORVEX_LLM_STANDARD_MODEL "gpt-4o-mini" "${env_file}"
  replace_or_append_env QUORVEX_LLM_DEEP_MODEL "gpt-4o" "${env_file}"
  replace_or_append_env QUORVEX_LLM_TOOL_DEEP_MODEL "gpt-4o" "${env_file}"
  replace_or_append_env QUORVEX_LLM_CHAT_MODEL "gpt-4o-mini" "${env_file}"
  replace_or_append_env QUORVEX_EMBEDDING_MODEL "text-embedding-3-small" "${env_file}"
  replace_or_append_env OPENAI_CHAT_MODEL "gpt-4o-mini" "${env_file}"
  replace_or_append_env ANTHROPIC_AUTH_TOKEN "" "${env_file}"

  if has_real_env_value "${api_key}"; then
    replace_or_append_env QUORVEX_LLM_API_KEY "${api_key}" "${env_file}"
  else
    replace_or_append_env QUORVEX_LLM_API_KEY "" "${env_file}"
  fi
}

write_llm_provider_runtime() {
  local env_file="$1"
  local provider="$2"

  case "${provider}" in
    zai)
      write_anthropic_compatible_runtime "${env_file}" ZAI_API_KEY "https://api.z.ai/api/anthropic" \
        "glm-4.5-air" "glm-5-turbo" "glm-5.1" "glm-5-turbo"
      ;;
    openrouter)
      write_anthropic_compatible_runtime "${env_file}" OPENROUTER_API_KEY "https://openrouter.ai/api" \
        "anthropic/claude-3.5-haiku" "anthropic/claude-sonnet-4" "anthropic/claude-opus-4" "anthropic/claude-sonnet-4"
      ;;
    openai)
      write_openai_runtime "${env_file}"
      ;;
    anthropic)
      write_anthropic_compatible_runtime "${env_file}" ANTHROPIC_API_KEY "https://api.anthropic.com" \
        "claude-3-5-haiku-latest" "claude-sonnet-4-20250514" "claude-opus-4-20250514" "claude-sonnet-4-20250514"
      ;;
    *)
      die "Unsupported LLM provider: ${provider}"
      ;;
  esac
}

configure_llm_provider_env() {
  local env_file="$1"
  local active_provider upstream_provider

  write_if_provided ZAI_API_KEY "${env_file}"
  write_if_provided OPENROUTER_API_KEY "${env_file}"
  write_if_provided OPENAI_API_KEY "${env_file}"
  write_if_provided ANTHROPIC_API_KEY "${env_file}"
  write_if_provided HERMES_API_KEY "${env_file}"

  active_provider="$(normalize_llm_provider "${QUORVEX_ACTIVE_LLM_PROVIDER:-$(env_file_value QUORVEX_ACTIVE_LLM_PROVIDER "${env_file}")}")"
  replace_or_append_env QUORVEX_ACTIVE_LLM_PROVIDER "${active_provider}" "${env_file}"

  if [ "${active_provider}" = "hermes" ]; then
    upstream_provider="$(normalize_llm_provider "${HERMES_UPSTREAM_PROVIDER:-$(env_file_value HERMES_UPSTREAM_PROVIDER "${env_file}")}")"
    [ "${upstream_provider}" != "hermes" ] || die "HERMES_UPSTREAM_PROVIDER cannot be hermes."
    replace_or_append_env HERMES_UPSTREAM_PROVIDER "${upstream_provider}" "${env_file}"
    write_llm_provider_runtime "${env_file}" "${upstream_provider}"
    replace_or_append_env QUORVEX_AGENT_RUNTIME "hermes" "${env_file}"
    replace_or_append_env HERMES_ENABLED "true" "${env_file}"
    replace_or_append_env HERMES_API_URL "${HERMES_API_URL:-http://hermes:8642}" "${env_file}"
    replace_or_append_env HERMES_MODEL "${HERMES_MODEL:-hermes-agent}" "${env_file}"
    return
  fi

  write_llm_provider_runtime "${env_file}" "${active_provider}"
  replace_or_append_env QUORVEX_AGENT_RUNTIME "claude_sdk" "${env_file}"
  replace_or_append_env HERMES_ENABLED "false" "${env_file}"
}

ensure_private_env() {
  local env_file="${DEPLOY_DIR}/env/quorvex.prod.env"
  local example_file="${SOURCE_DIR}/deploy/private-repo-template/env/quorvex.prod.env.example"
  local generated_file="${DEPLOY_DIR}/.state/generated-secrets.txt"
  local public_url_override_key="QUORVEX_PUBLIC_URL"

  report_private_file_state "env file" "${env_file}"
  if [ ! -f "${env_file}" ]; then
    log "Creating private env file at ${env_file}."
    copy_template_file "${example_file}" "${env_file}" 600
    log "Created private env file from template: ${env_file}"
  fi

  mkdir -p "${DEPLOY_DIR}/.state"
  chmod 700 "${DEPLOY_DIR}/.state"

  replace_or_append_if_env_provided_or_placeholder QUORVEX_SOURCE_DIR QUORVEX_SOURCE_DIR "${SOURCE_DIR}" "${env_file}"
  replace_or_append_if_env_provided_or_placeholder QUORVEX_DATA_ROOT QUORVEX_DATA_ROOT "${DATA_ROOT}" "${env_file}"
  replace_or_append_if_env_provided_or_placeholder QUORVEX_IMAGE_NAMESPACE QUORVEX_IMAGE_NAMESPACE "${IMAGE_NAMESPACE}" "${env_file}"
  if [ -z "${QUORVEX_PUBLIC_URL+x}" ] && [ -n "${QUORVEX_DOMAIN+x}" ]; then
    public_url_override_key="QUORVEX_DOMAIN"
  fi

  replace_or_append_if_env_provided_or_placeholder "${public_url_override_key}" QUORVEX_PUBLIC_URL "${PUBLIC_URL}" "${env_file}"
  replace_or_append_if_env_provided_or_placeholder "${public_url_override_key}" ALLOWED_ORIGINS "${PUBLIC_URL}" "${env_file}"
  replace_or_append_if_env_provided_or_placeholder "${public_url_override_key}" TEMPORAL_CORS_ORIGINS "${PUBLIC_URL}" "${env_file}"
  replace_or_append_env QUORVEX_PUBLIC_API_URL "" "${env_file}"
  replace_or_append_env NEXT_PUBLIC_API_URL "" "${env_file}"
  replace_or_append_if_placeholder INTERNAL_API_URL "http://backend:8001" "${env_file}"
  replace_or_append_if_env_provided_or_placeholder "${public_url_override_key}" VNC_PUBLIC_WS_URL "$(printf '%s' "${PUBLIC_URL}" | sed 's|^https://|wss://|; s|^http://|ws://|')/websockify" "${env_file}"
  replace_or_append_if_placeholder RECORDER_BROWSER_URL "" "${env_file}"

  if grep -q 'replace-with-at-least-32-random-bytes' "${env_file}"; then
    replace_or_append_env JWT_SECRET_KEY "${JWT_SECRET_KEY:-$(random_secret)}" "${env_file}"
  fi
  if grep -q 'replace-with-strong-postgres-password' "${env_file}"; then
    local postgres_password="${POSTGRES_PASSWORD:-$(random_secret)}"
    replace_or_append_env POSTGRES_PASSWORD "${postgres_password}" "${env_file}"
    replace_or_append_env DATABASE_URL "postgresql://quorvex:${postgres_password}@db:5432/quorvex" "${env_file}"
  fi
  if grep -q 'replace-with-strong-minio-password' "${env_file}"; then
    replace_or_append_env MINIO_ROOT_PASSWORD "${MINIO_ROOT_PASSWORD:-$(random_secret)}" "${env_file}"
  fi
  if grep -q 'replace-with-strong-initial-admin-password' "${env_file}"; then
    local admin_password="${INITIAL_ADMIN_PASSWORD:-$(random_admin_password)}"
    replace_or_append_env INITIAL_ADMIN_PASSWORD "${admin_password}" "${env_file}"
    {
      printf 'INITIAL_ADMIN_EMAIL=%s\n' "$(grep '^INITIAL_ADMIN_EMAIL=' "${env_file}" | cut -d= -f2-)"
      printf 'INITIAL_ADMIN_PASSWORD=%s\n' "${admin_password}"
    } > "${generated_file}"
    chmod 600 "${generated_file}"
    log "Generated initial admin password stored at ${generated_file}."
  fi

  for key in \
    FRONTEND_BIND \
    BACKEND_BIND \
    VNC_BIND \
    MINIO_API_BIND \
    MINIO_CONSOLE_BIND \
    TEMPORAL_BIND \
    TEMPORAL_UI_BIND \
    HERMES_API_BIND \
    HERMES_DASHBOARD_BIND \
    HERMES_CONTAINER_NAME \
    ZAP_BIND; do
    write_if_provided "${key}" "${env_file}"
  done

  configure_llm_provider_env "${env_file}"
  log "Private env prepared. Secret values were not printed."
}

ensure_private_deploy_files() {
  ensure_private_repo_scripts
  ensure_private_env
  ensure_private_compose_overlay
  ensure_private_reverse_proxy
}

main() {
  require_command git
  require_command curl
  require_command docker

  if [ "$(id -u)" -ne 0 ]; then
    require_command sudo
  fi

  clone_or_update_public_repo
  clone_or_update_private_repo
  ensure_private_deploy_files

  log "Running bootstrap checks."
  (
    cd "${DEPLOY_DIR}"
    QUORVEX_OVERLAY_FILE="$(private_overlay_file)" \
      QUORVEX_SKIP_REGISTRY_CHECK="${QUORVEX_SKIP_REGISTRY_CHECK:-true}" \
      ./scripts/bootstrap.sh
  )

  if [ -n "${VERSION}" ]; then
    log "Running deploy dry-run for ${VERSION}."
    (cd "${DEPLOY_DIR}" && QUORVEX_OVERLAY_FILE="$(private_overlay_file)" ./scripts/deploy.sh --dry-run "${VERSION}")

    if [ "${CONFIRM_DEPLOY}" = "true" ]; then
      log "Deploying ${VERSION} because QUORVEX_CONFIRM_DEPLOY=true."
      (cd "${DEPLOY_DIR}" && QUORVEX_OVERLAY_FILE="$(private_overlay_file)" ./scripts/deploy.sh "${VERSION}")
    else
      log "Dry-run complete. Set QUORVEX_CONFIRM_DEPLOY=true to deploy ${VERSION} in the same command."
    fi
  fi

  log "Install complete. Private deploy repo: ${DEPLOY_DIR}"
  log "Runtime data root: ${DATA_ROOT}"
}

main "$@"
