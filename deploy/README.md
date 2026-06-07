# Deployment Templates

This directory contains safe templates for private production deployment repos.
Do not put real domains, secrets, server paths, or deployment state in the
public repository.

Use `private-repo-template/` for the one-command server flow:

```bash
./scripts/bootstrap.sh
./scripts/deploy.sh v1.2.3
./scripts/rollback.sh
```

For first server setup, `install-server.sh` can clone or update the public
source repo and private deploy repo, create the private env file, run bootstrap,
and optionally run a deploy dry-run:

```bash
curl -fsSL https://raw.githubusercontent.com/NihadMemmedli/quorvex_ai/main/deploy/install-server.sh | bash
```

Because the deploy repo is private, the server must already have `gh auth login`
or a `GITHUB_TOKEN` with repo read access:

```bash
GITHUB_TOKEN=... QUORVEX_VERSION=v1.2.3 \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/NihadMemmedli/quorvex_ai/main/deploy/install-server.sh)"
```

To deploy in the same command, also pass `QUORVEX_CONFIRM_DEPLOY=true` and the
provider-specific key for the selected active runtime provider:

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

The private repo can also track `env/quorvex.prod.env` for fully automated
server rebuilds. To commit generated/env changes during install, pass:

```bash
QUORVEX_COMMIT_ENV=true
```

The public repository still owns source code, local development, and tagged
GHCR image releases. The private deployment repo owns production env files,
compose overlays, reverse proxy config, backups, and rollback state.

`examples/` contains smaller generic snippets. Prefer the full
`private-repo-template/` when setting up a real production server.
