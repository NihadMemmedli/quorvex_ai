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

## First Setup

```bash
cp env/quorvex.prod.env.example env/quorvex.prod.env
cp compose/docker-compose.mytest.example.yml compose/docker-compose.mytest.yml
cp reverse-proxy/mytest.idda.az.example.conf reverse-proxy/mytest.idda.az.conf

editor env/quorvex.prod.env
editor compose/docker-compose.mytest.yml
editor reverse-proxy/mytest.idda.az.conf

./scripts/bootstrap.sh
```

Set `QUORVEX_ACTIVE_LLM_PROVIDER` in `env/quorvex.prod.env` to one of
`zai`, `openrouter`, `openai`, `anthropic`, or `hermes`, then fill the matching
provider key (`ZAI_API_KEY`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, or
`ANTHROPIC_API_KEY`). The scripts derive `QUORVEX_LLM_API_KEY` and SDK aliases
from the active provider before rendering Docker Compose.

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
