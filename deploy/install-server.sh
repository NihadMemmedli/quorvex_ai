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
COMMIT_ENV="${QUORVEX_COMMIT_ENV:-false}"

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
  else
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

  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
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
    *replace-with*|your-*|example-*|placeholder-*)
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
  local example_file="${DEPLOY_DIR}/env/quorvex.prod.env.example"
  local generated_file="${DEPLOY_DIR}/.state/generated-secrets.txt"

  if [ ! -f "${env_file}" ]; then
    log "Creating private env file at ${env_file}."
    cp "${example_file}" "${env_file}"
  fi

  mkdir -p "${DEPLOY_DIR}/.state"
  chmod 700 "${DEPLOY_DIR}/.state"

  replace_or_append_env QUORVEX_SOURCE_DIR "${SOURCE_DIR}" "${env_file}"
  replace_or_append_env QUORVEX_DATA_ROOT "${DATA_ROOT}" "${env_file}"
  replace_or_append_env QUORVEX_IMAGE_NAMESPACE "${IMAGE_NAMESPACE}" "${env_file}"
  replace_or_append_env QUORVEX_PUBLIC_URL "https://${DOMAIN}" "${env_file}"
  replace_or_append_env ALLOWED_ORIGINS "https://${DOMAIN}" "${env_file}"
  replace_or_append_env TEMPORAL_CORS_ORIGINS "https://${DOMAIN}" "${env_file}"
  replace_or_append_env VNC_PUBLIC_WS_URL "wss://${DOMAIN}/websockify" "${env_file}"

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
    local admin_password="${INITIAL_ADMIN_PASSWORD:-$(random_secret)}"
    replace_or_append_env INITIAL_ADMIN_PASSWORD "${admin_password}" "${env_file}"
    {
      printf 'INITIAL_ADMIN_EMAIL=%s\n' "$(grep '^INITIAL_ADMIN_EMAIL=' "${env_file}" | cut -d= -f2-)"
      printf 'INITIAL_ADMIN_PASSWORD=%s\n' "${admin_password}"
    } > "${generated_file}"
    chmod 600 "${generated_file}"
    log "Generated initial admin password stored at ${generated_file}."
  fi

  configure_llm_provider_env "${env_file}"
}

commit_private_env_if_requested() {
  if [ "${COMMIT_ENV}" != "true" ]; then
    return
  fi

  log "Committing private env file because QUORVEX_COMMIT_ENV=true."
  (
    cd "${DEPLOY_DIR}"
    git add env/quorvex.prod.env
    if git diff --cached --quiet; then
      log "No private env changes to commit."
      exit 0
    fi
    git commit -m "Update production env"
    git push origin HEAD
  )
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
  ensure_private_env
  commit_private_env_if_requested

  log "Running bootstrap checks."
  (
    cd "${DEPLOY_DIR}"
    QUORVEX_SKIP_REGISTRY_CHECK="${QUORVEX_SKIP_REGISTRY_CHECK:-true}" ./scripts/bootstrap.sh
  )

  if [ -n "${VERSION}" ]; then
    log "Running deploy dry-run for ${VERSION}."
    (cd "${DEPLOY_DIR}" && ./scripts/deploy.sh --dry-run "${VERSION}")

    if [ "${CONFIRM_DEPLOY}" = "true" ]; then
      log "Deploying ${VERSION} because QUORVEX_CONFIRM_DEPLOY=true."
      (cd "${DEPLOY_DIR}" && ./scripts/deploy.sh "${VERSION}")
    else
      log "Dry-run complete. Set QUORVEX_CONFIRM_DEPLOY=true to deploy ${VERSION} in the same command."
    fi
  fi

  log "Install complete. Private deploy repo: ${DEPLOY_DIR}"
  log "Runtime data root: ${DATA_ROOT}"
}

main "$@"
