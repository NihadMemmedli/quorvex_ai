# Deployment Templates

This directory contains safe templates for private production deployment repos.
Do not put real domains, secrets, server paths, or deployment state in the
public repository.

Use `private-repo-template/` for the private deployment repo flow:

```bash
./scripts/bootstrap.sh
./scripts/deploy.sh v1.2.3
./scripts/rollback.sh
```

For first server setup, `install-server.sh` can clone or update the public
source repo and private deploy repo, report missing private deployment files,
create missing files from templates, run bootstrap, and optionally run a deploy
dry-run:

```bash
curl -fsSL https://raw.githubusercontent.com/NihadMemmedli/quorvex_ai/main/deploy/install-server.sh | bash
```

Because the deploy repo is private, the server must already have `gh auth login`
or a `GITHUB_TOKEN` with repo read access. For the company test deployment,
pass real values once to the installer so it writes them into the server-local
private env file:

```bash
GITHUB_TOKEN=<real-github-token> \
QUORVEX_DEPLOY_REPO=NihadMemmedli/quorvex-idda-tests \
QUORVEX_DOMAIN=mytest.idda.az \
QUORVEX_SITE=mytest \
QUORVEX_VERSION=v1.2.3 \
QUORVEX_ACTIVE_LLM_PROVIDER=zai \
ZAI_API_KEY=<real-zai-key> \
INITIAL_ADMIN_EMAIL=<real-admin-email> \
INITIAL_ADMIN_PASSWORD=<real-admin-password> \
POSTGRES_PASSWORD=<real-postgres-password> \
MINIO_ROOT_PASSWORD=<real-minio-password> \
JWT_SECRET_KEY=<real-64-char-or-longer-secret> \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/NihadMemmedli/quorvex_ai/main/deploy/install-server.sh)"
```

The installer dry-runs by default. In this context, deploy means the
runtime-changing path: pull tagged GHCR images, run the configured backup, and
apply `docker compose up -d` through the private repo scripts. To deploy in the
same command, pass `QUORVEX_CONFIRM_DEPLOY=true` and the provider-specific key
for the selected active runtime provider:

```bash
GITHUB_TOKEN=... \
QUORVEX_VERSION=v1.2.3 \
QUORVEX_ACTIVE_LLM_PROVIDER=zai \
ZAI_API_KEY=... \
QUORVEX_CONFIRM_DEPLOY=true \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/NihadMemmedli/quorvex_ai/main/deploy/install-server.sh)"
```

Supported active providers are `zai`, `openrouter`, `openai`, and
`anthropic`. The installer maps the selected provider key into
`QUORVEX_LLM_API_KEY` for the app runtime.

Missing private files are created from templates and logged before creation.
Generated local secrets are not printed; generated notes are stored under the
private repo `.state/` directory with private permissions. The installer never
commits generated env or deployment files.

The public repository still owns source code, local development, and tagged
GHCR image releases. The private deployment repo owns production env files,
compose overlays, reverse proxy config, company specs/tests/fixtures/PRDs,
backups, and rollback state. The private repo should track only safe files such
as scripts, compose overlays, reverse proxy config, README, `.gitignore`,
`env/quorvex.prod.env.example`, `specs/`, `tests/`, `fixtures/`, and `prds/`;
it must not track `env/quorvex.prod.env`, `.state/`, generated passwords,
provider API keys, backups, test results, or runtime data.

For company-network deployments, keep browser-facing API URLs blank so the
frontend uses same-origin `/backend-proxy`; set
`VNC_PUBLIC_WS_URL=wss://<domain>/websockify`; and leave
`RECORDER_BROWSER_URL` blank unless the company edge also proxies `/vnc.html`
and the noVNC assets.

After the installer dry-run passes, deploy from the private repo:

```bash
cd /opt/quorvex-deploy-private
./scripts/deploy.sh --dry-run v1.2.3
./scripts/deploy.sh v1.2.3
```

For local or server-side confidence checks around the external-nginx runtime:

```bash
# Start the same app runtime that company nginx proxies to.
make start

# Verify backend, frontend, storage/backup health, same-origin proxy, and agent readiness.
make deploy-check

# Without company server access, simulate company nginx locally with HTTPS and /websockify.
make company-rehearsal
```

Before updating a real server to a tagged release, make the exact release tag a
hard gate:

```bash
make release-preflight VERSION=v1.2.3
make server-upgrade VERSION=v1.2.3
```

From a local development machine, the preferred production handoff is:

```bash
VERSION=v1.2.3 QUORVEX_SERVER_HOST=user@production-host make release-to-server
```

That command pushes the public branch and release tag, waits for GHCR images,
then runs `make server-upgrade` over SSH on the production server. On the
server, `release-preflight` verifies all tagged GHCR images exist and runs the
private deploy dry-run; `server-upgrade` also pulls the images before it deploys
through the private repo and runs post-deploy checks.

`examples/` contains smaller generic snippets. Prefer the full
`private-repo-template/` when setting up a real production server.
