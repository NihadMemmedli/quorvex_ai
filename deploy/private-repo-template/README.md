# Quorvex Private Deployment Template

Copy this directory into a private deployment repository on the production
server. The private repo owns domain configuration, secrets, deployment state,
backups, and rollback.

Expected one-time layout after copying:

```text
.
├── .gitignore
├── Makefile
├── compose/docker-compose.mytest.yml
├── env/quorvex.prod.env.example
├── reverse-proxy/mytest.idda.az.conf
└── scripts/
    ├── bootstrap.sh
    ├── deploy.sh
    ├── doctor.sh
    └── rollback.sh
```

Keep the public Quorvex source checkout on the same server and point
`QUORVEX_SOURCE_DIR` at it from `env/quorvex.prod.env`.

Track only safe deploy files in this private repo: compose overlays, scripts,
reverse proxy config, README, `.gitignore`, and
`env/quorvex.prod.env.example`. Do not track `env/quorvex.prod.env`, `.state/`,
generated passwords, provider API keys, backups, or runtime data.

## First Setup With The Installer

```bash
GITHUB_TOKEN=... \
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

The installer clones or updates both repos, reports missing private files,
creates missing files from these templates, writes provided real secrets into
the server-local private env file, generates local app secrets only when
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
cd /opt/quorvex-deploy-private
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
make release-preflight VERSION=v1.2.3
make deploy VERSION=v1.2.3
make deploy-check
make rollback
make status
make logs
```

`make release-preflight` verifies that all expected GHCR images for the tag are
available and then runs the private deploy dry-run. `make deploy-check` calls
the public checkout's deployment checker using this repo's private env file.

The scripts never publish to YouTube, mutate GitHub releases, or create public
cloud resources. They only manage the server-local Docker Compose deployment.
