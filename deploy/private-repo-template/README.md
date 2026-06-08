# Quorvex Private Deployment Template

Copy this directory into a private deployment repository on the production
server. The private repo owns domain configuration, secrets, deployment state,
backups, and rollback.

Expected one-time layout after copying:

```text
.
├── Makefile
├── compose/docker-compose.mytest.yml
├── env/quorvex.prod.env
├── reverse-proxy/mytest.idda.az.conf
└── scripts/
    ├── bootstrap.sh
    ├── deploy.sh
    ├── doctor.sh
    └── rollback.sh
```

Keep the public Quorvex source checkout on the same server and point
`QUORVEX_SOURCE_DIR` at it from `env/quorvex.prod.env`.

## First Setup With The Installer

```bash
GITHUB_TOKEN=... \
QUORVEX_DEPLOY_REPO=<owner>/<private-deploy-repo> \
QUORVEX_DOMAIN=mytest.idda.az \
QUORVEX_VERSION=v1.2.3 \
bash -c "$(curl -fsSL https://raw.githubusercontent.com/NihadMemmedli/quorvex_ai/main/deploy/install-server.sh)"
```

The installer clones or updates both repos, reports missing private files,
creates missing files from these templates, generates local app secrets when
placeholders remain, runs `./scripts/bootstrap.sh`, and runs
`./scripts/deploy.sh --dry-run v1.2.3`. It does not start or replace containers
unless `QUORVEX_CONFIRM_DEPLOY=true` is passed.

Set `QUORVEX_ACTIVE_LLM_PROVIDER` in `env/quorvex.prod.env` to one of
`zai`, `openrouter`, `openai`, `anthropic`, or `hermes`, then fill the matching
provider key (`ZAI_API_KEY`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, or
`ANTHROPIC_API_KEY`). The scripts derive `QUORVEX_LLM_API_KEY` and SDK aliases
from the active provider before rendering Docker Compose.

If the provider key is not already in the private env file, pass it to the
installer command, for example `ZAI_API_KEY=...`. Secret values are not printed.

For company nginx mode, keep `QUORVEX_PUBLIC_API_URL` and
`NEXT_PUBLIC_API_URL` blank, keep `INTERNAL_API_URL=http://backend:8001`, and
set `VNC_PUBLIC_WS_URL=wss://<domain>/websockify`. Leave
`RECORDER_BROWSER_URL` blank unless nginx also exposes `/vnc.html` and noVNC
assets.

## Release Deploy

After the public repository tag has published GHCR images:

```bash
./scripts/deploy.sh --dry-run v1.2.3
./scripts/deploy.sh v1.2.3
```

## Rollback

```bash
./scripts/rollback.sh
```

Equivalent Makefile commands:

```bash
make bootstrap
make deploy VERSION=v1.2.3
make rollback
make status
make logs
```

The scripts never publish to YouTube, mutate GitHub releases, or create public
cloud resources. They only manage the server-local Docker Compose deployment.
