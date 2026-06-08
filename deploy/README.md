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
or a `GITHUB_TOKEN` with repo read access:

```bash
GITHUB_TOKEN=... QUORVEX_VERSION=v1.2.3 \
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

Supported active providers are `zai`, `openrouter`, `openai`, `anthropic`, and
`hermes`. The installer maps the selected provider key into
`QUORVEX_LLM_API_KEY` for the app runtime.

Missing private files are created from templates and logged before creation.
Generated local secrets are not printed; generated notes are stored under the
private repo `.state/` directory with private permissions. The installer never
commits generated env or deployment files.

The public repository still owns source code, local development, and tagged
GHCR image releases. The private deployment repo owns production env files,
compose overlays, reverse proxy config, backups, and rollback state.

For company-network deployments, keep browser-facing API URLs blank so the
frontend uses same-origin `/backend-proxy`; set
`VNC_PUBLIC_WS_URL=wss://<domain>/websockify`; and leave
`RECORDER_BROWSER_URL` blank unless the company edge also proxies `/vnc.html`
and the noVNC assets.

`examples/` contains smaller generic snippets. Prefer the full
`private-repo-template/` when setting up a real production server.
