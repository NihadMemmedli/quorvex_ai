#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE_DIR="${ROOT_DIR}/deploy/private-repo-template"
TMP_DIR="$(mktemp -d /tmp/quorvex-private-deploy-test.XXXXXX)"

log() {
  printf '[template-test] %s\n' "$*"
}

replace_placeholders() {
  local env_file="$1"
  perl -0pi -e '
    s/replace-with-at-least-32-random-bytes/test-jwt-secret-key-32-bytes-minimum-000/;
    s/replace-with-strong-initial-admin-password/TestAdminPassword123/;
    s/replace-with-strong-postgres-password/TestPostgresPassword123/g;
    s/replace-with-strong-minio-password/TestMinioPassword123/;
    s/replace-with-zai-api-key/test-zai-api-key/g;
    s/replace-with-llm-api-key/test-llm-api-key/g;
    s/replace-with-light-model/test-light-model/g;
    s/replace-with-standard-model/test-standard-model/g;
    s/replace-with-deep-model/test-deep-model/g;
    s/replace-with-chat-model/test-chat-model/g;
  ' "${env_file}"
}

set_test_paths() {
  local env_file="$1"
  perl -0pi -e '
    s|QUORVEX_SOURCE_DIR=/opt/quorvex_ai|QUORVEX_SOURCE_DIR='"${ROOT_DIR}"'|;
    s|QUORVEX_IMAGE_NAMESPACE=ghcr.io/example-org/quorvex-ai|QUORVEX_IMAGE_NAMESPACE=ghcr.io/test-org/quorvex-ai|;
    s|QUORVEX_DATA_ROOT=/srv/quorvex/mytest|QUORVEX_DATA_ROOT='"${TMP_DIR}"'/data|;
    s|QUORVEX_PRIVATE_CONTENT_DIR=/opt/quorvex-deploy-private|QUORVEX_PRIVATE_CONTENT_DIR='"${TMP_DIR}"'|;
    s|SPECS_DIR=/opt/quorvex-deploy-private/specs|SPECS_DIR='"${TMP_DIR}"'/specs|;
    s|TESTS_DIR=/opt/quorvex-deploy-private/tests|TESTS_DIR='"${TMP_DIR}"'/tests|;
    s|PRDS_DIR=/opt/quorvex-deploy-private/prds|PRDS_DIR='"${TMP_DIR}"'/prds|;
    s|COMPOSE_PROJECT_NAME=quorvex-mytest|COMPOSE_PROJECT_NAME=quorvex-template-test|;
  ' "${env_file}"
  {
    printf '\nQUORVEX_MIN_FREE_GB=0\n'
    printf 'QUORVEX_SKIP_PUBLIC_CHECK=true\n'
  } >> "${env_file}"
}

log "Copying private repo template to ${TMP_DIR}."
cp -R "${TEMPLATE_DIR}/." "${TMP_DIR}/"
mv "${TMP_DIR}/env/quorvex.prod.env.example" "${TMP_DIR}/env/quorvex.prod.env"
mv "${TMP_DIR}/compose/docker-compose.mytest.example.yml" "${TMP_DIR}/compose/docker-compose.mytest.yml"
mv "${TMP_DIR}/reverse-proxy/mytest.idda.az.example.conf" "${TMP_DIR}/reverse-proxy/mytest.idda.az.conf"

log "Checking shell syntax."
bash -n "${TMP_DIR}"/scripts/*.sh
test -f "${TMP_DIR}/.gitignore"

log "Pointing copied template at this checkout."
set_test_paths "${TMP_DIR}/env/quorvex.prod.env"

log "Verifying dry-run rejects placeholder env values."
if (cd "${TMP_DIR}" && ./scripts/deploy.sh --dry-run v1.2.3 >/tmp/quorvex-template-placeholder.out 2>&1); then
  printf 'Expected placeholder dry-run to fail.\n' >&2
  exit 1
fi
grep -q 'placeholder env value' /tmp/quorvex-template-placeholder.out

log "Replacing placeholders with deterministic test values."
replace_placeholders "${TMP_DIR}/env/quorvex.prod.env"

log "Checking private env and state are ignored by Git."
(
  cd "${TMP_DIR}"
  git init -q
  git check-ignore -q env/quorvex.prod.env
  git check-ignore -q .state/current-version
  ! git check-ignore -q specs/company-login.md
  ! git check-ignore -q tests/company/login.spec.ts
  ! git check-ignore -q prds/company-login.md
)

log "Verifying deploy dry-run renders Compose without changing services."
(cd "${TMP_DIR}" && ./scripts/deploy.sh --dry-run v1.2.3)

log "Inspecting rendered Compose for release images and same-origin frontend mode."
(
  cd "${TMP_DIR}"
  source scripts/common.sh
  load_env_file
  require_deploy_files
  set_image_vars v1.2.3
  compose "${QUORVEX_COMPOSE_PROFILES}" config > rendered-compose.yml
)

grep -q 'ghcr.io/test-org/quorvex-ai/backend:v1.2.3' "${TMP_DIR}/rendered-compose.yml"
grep -q 'ghcr.io/test-org/quorvex-ai/frontend:v1.2.3' "${TMP_DIR}/rendered-compose.yml"
grep -q 'NEXT_PUBLIC_API_URL: ""' "${TMP_DIR}/rendered-compose.yml"
grep -q 'INTERNAL_API_URL: http://backend:8001' "${TMP_DIR}/rendered-compose.yml"
grep -q 'VNC_PUBLIC_WS_URL: wss://mytest.idda.az/websockify' "${TMP_DIR}/rendered-compose.yml"
grep -q 'RECORDER_BROWSER_URL: ""' "${TMP_DIR}/rendered-compose.yml"
grep -q 'HERMES_API_URL: http://hermes:8642' "${TMP_DIR}/rendered-compose.yml"
grep -q "source: ${TMP_DIR}/specs" "${TMP_DIR}/rendered-compose.yml"
grep -q "source: ${TMP_DIR}/tests" "${TMP_DIR}/rendered-compose.yml"
grep -q "source: ${TMP_DIR}/prds" "${TMP_DIR}/rendered-compose.yml"
if rg -n 'NEXT_PUBLIC_API_URL: .*(localhost|127\.0\.0\.1|host\.docker\.internal|backend:8001|http://)' "${TMP_DIR}/rendered-compose.yml"; then
  printf 'Rendered frontend browser API URL is not company safe.\n' >&2
  exit 1
fi
if rg -n 'VNC_PUBLIC_WS_URL: (""|ws://localhost|ws://127\.0\.0\.1|.*host\.docker\.internal)' "${TMP_DIR}/rendered-compose.yml"; then
  printf 'Rendered VNC websocket URL is not company safe.\n' >&2
  exit 1
fi
if rg -n 'RECORDER_BROWSER_URL: (http://localhost|http://127\.0\.0\.1|.*host\.docker\.internal|.*:6080)' "${TMP_DIR}/rendered-compose.yml"; then
  printf 'Rendered recorder browser URL exposes a direct/local VNC endpoint.\n' >&2
  exit 1
fi
if grep -q "${ROOT_DIR}/specs\\|${ROOT_DIR}/tests\\|${ROOT_DIR}/prds" "${TMP_DIR}/rendered-compose.yml"; then
  printf 'Rendered standard deployment still references public checkout data directories.\n' >&2
  exit 1
fi

log "Inspecting backup/restore profile paths."
(
  cd "${TMP_DIR}"
  source scripts/common.sh
  load_env_file
  require_deploy_files
  set_image_vars v1.2.3
  compose "backup-full restore" config > rendered-backup-compose.yml
)

grep -q "source: ${TMP_DIR}/data/backups" "${TMP_DIR}/rendered-backup-compose.yml"
grep -q "target: /backups" "${TMP_DIR}/rendered-backup-compose.yml"

log "Private deploy template tests passed."
