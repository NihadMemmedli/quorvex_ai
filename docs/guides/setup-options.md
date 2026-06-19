# How to Choose a Setup Path

![Quorvex dashboard overview after setup is complete](../assets/ui/dashboard-overview.png)

<p class="caption">Quorvex dashboard overview after setup is complete.</p>


Choose the smallest setup that matches what you need to prove. You can move from one path to another later without changing how specs are written.

## Setup Matrix

| Path | Use when | Database | Main command | Trade-off |
|------|----------|----------|--------------|-----------|
| Evaluator demo | You want the fastest local product trial | SQLite | `docker compose -f docker-compose.minimal.yml up -d` | Local-only and unsupported for company deployment |
| Contributor dev | You want the dashboard, queues, storage, VNC, and frontend hot reload locally | PostgreSQL | `make dev` | More RAM and disk usage |
| Production/company | You are running behind company DNS/TLS/nginx in external-nginx mode | PostgreSQL | `make start` | Requires real secrets, backups, and operational care |
| Repo-managed nginx | You explicitly need the legacy single-host nginx container | PostgreSQL | `QUORVEX_ENABLE_REPO_NGINX=1 make prod-up` | Guarded; not used for company deployment |
| Browser worker mode | You need more isolated or concurrent browser execution | PostgreSQL | `make workers-up` | More containers to monitor |
| Kubernetes | You need enterprise scheduling, scaling, and cluster operations | PostgreSQL | `make k8s-deploy` | Requires Kubernetes ownership |

## Recommended Defaults

Start with **Evaluator demo** if you only want to evaluate the product flow. It is the fastest route to a running dashboard and keeps optional infrastructure out of the way.

Start with **Contributor dev** if you need to evaluate security scanning, backup storage, VNC live browser viewing, Redis-backed queues, multi-user behavior, or source changes.

Use **Local native dev** only when you are contributing code or debugging backend/frontend behavior closely. It is the most flexible path, but it asks more of your host machine.

Use **Production/company** for the first real team deployment. Company deployments are external-nginx mode: company DNS/TLS/nginx proxies to the Compose app, `make start` starts the app runtime, and the repo-managed nginx container stays disabled unless explicitly requested.

## Prerequisites by Path

| Path | Required |
|------|----------|
| Evaluator demo | Docker Compose v2, `.env` with AI provider credentials |
| Contributor dev | Docker Compose v2, 8 GB+ available Docker memory. `make dev` can create `.env.prod` from `.env.prod.example` for local evaluation; edit it with your provider token before real use. |
| Local native dev | Python 3.10+, Node.js 20+, Playwright browsers, optional Docker for PostgreSQL |
| Production/company | Docker Compose v2, `.env.prod` with rotated secrets, backup location, company nginx/TLS, same-origin browser API routing |
| Kubernetes | `kubectl`, cluster storage classes, ingress/TLS plan, namespace permissions |

## Upgrade Path

1. Evaluate with the Minimal Docker evaluator path.
2. Switch to Contributor dev when you need queues, storage, VNC, scanners, or source changes.
3. Use Production/company external-nginx mode for a team deployment.
4. Add browser workers when browser slot contention becomes visible.
5. Move to Kubernetes when cluster-level scheduling, policy, or autoscaling is required.

## Verification

After starting any setup:

```bash
make check-env
make health-check
```

Then open the dashboard at [http://localhost:3000](http://localhost:3000) and run a small spec from `specs/examples/hello-world.md`.

For company deployments, also verify that `QUORVEX_PUBLIC_API_URL=` and `NEXT_PUBLIC_API_URL=` are blank, `VNC_PUBLIC_WS_URL` points to the company `/websockify` route, and direct `3000`, `8001`, and `6080` ports are private to the app server or trusted network.

## Related

- [Getting Started](../tutorials/getting-started.md)
- [Deployment](deployment.md)
- [On-Premises Deployment](company-deployment.md)
- [Troubleshooting](troubleshooting.md)
