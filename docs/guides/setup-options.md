# How to Choose a Setup Path

![Quorvex dashboard overview after setup is complete](../assets/ui/dashboard-overview.png)

<p class="caption">Quorvex dashboard overview after setup is complete.</p>


Choose the smallest setup that matches what you need to prove. You can move from one path to another later without changing how specs are written.

## Setup Matrix

| Path | Use when | Database | Main command | Trade-off |
|------|----------|----------|--------------|-----------|
| Minimal Docker | You want a quick demo on a laptop or small VM | SQLite | `docker compose -f docker-compose.minimal.yml up -d` | No Redis, MinIO, VNC, or distributed workers |
| Full Docker dev | You want the dashboard, queues, storage, VNC, and scanners locally | PostgreSQL | `make prod-dev` | More RAM and disk usage |
| Local native dev | You are changing backend or frontend code | SQLite or PostgreSQL | `make setup && make dev` | More host dependency setup |
| Production single host | You are running Quorvex for a team | PostgreSQL | `make prod-up` | Requires real secrets, backups, and operational care |
| Browser worker mode | You need more isolated or concurrent browser execution | PostgreSQL | `make workers-up` | More containers to monitor |
| Kubernetes | You need enterprise scheduling, scaling, and cluster operations | PostgreSQL | `make k8s-deploy` | Requires Kubernetes ownership |

## Recommended Defaults

Start with **Minimal Docker** if you only want to evaluate the product flow. It is the fastest route to a running dashboard and keeps optional infrastructure out of the way.

Start with **Full Docker dev** if you need to evaluate security scanning, backup storage, VNC live browser viewing, Redis-backed queues, or multi-user behavior.

Use **Local native dev** only when you are contributing code or debugging backend/frontend behavior closely. It is the most flexible path, but it asks more of your host machine.

Use **Production single host** for the first real team deployment. Move to browser workers or Kubernetes when concurrency and isolation become the constraint.

## Prerequisites by Path

| Path | Required |
|------|----------|
| Minimal Docker | Docker Compose v2, `.env` with `ANTHROPIC_AUTH_TOKEN` |
| Full Docker dev | Docker Compose v2, `.env.prod`, 8 GB+ available Docker memory |
| Local native dev | Python 3.10+, Node.js 20+, Playwright browsers, optional Docker for PostgreSQL |
| Production single host | Docker Compose v2, `.env.prod` with rotated secrets, backup location, TLS or trusted network |
| Kubernetes | `kubectl`, cluster storage classes, ingress/TLS plan, namespace permissions |

## Upgrade Path

1. Evaluate with Minimal Docker.
2. Switch to Full Docker dev when you need queues, storage, VNC, or scanners.
3. Use Production single host for a team deployment.
4. Add browser workers when browser slot contention becomes visible.
5. Move to Kubernetes when cluster-level scheduling, policy, or autoscaling is required.

## Verification

After starting any setup:

```bash
make check-env
make health-check
```

Then open the dashboard at [http://localhost:3000](http://localhost:3000) and run a small spec from `specs/examples/hello-world.md`.

## Related

- [Getting Started](../tutorials/getting-started.md)
- [Deployment](deployment.md)
- [On-Premises Deployment](company-deployment.md)
- [Troubleshooting](troubleshooting.md)
