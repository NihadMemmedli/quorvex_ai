# Company Network Deployment Agent Handoff

Use this note when continuing the company-network deployment. The intended topology is:

- Company DNS and company nginx terminate TLS at a dedicated subdomain.
- Company nginx proxies `/` to the app server frontend on `http://<app-server>:3000`.
- Company nginx proxies `/websockify` to the app server live-browser WebSocket on `http://<app-server>:6080/websockify`.
- Recorder browser links stay disabled unless company nginx also proxies `/vnc.html` and the noVNC web assets.
- The repo-managed nginx container is not part of the private deploy path.
- Browser API calls should use same-origin `/backend-proxy`; keep `QUORVEX_PUBLIC_API_URL` and `NEXT_PUBLIC_API_URL` blank.

## Current Repo State

- `deploy/install-server.sh` is the one-line public entrypoint for the two-repo private deployment flow.
- The installer reports missing private deploy files, creates missing files from templates, runs bootstrap, and dry-runs a requested `QUORVEX_VERSION` unless `QUORVEX_CONFIRM_DEPLOY=true`.
- `docker-compose.prod.yml` passes `VNC_PUBLIC_WS_URL` and `VNC_PUBLIC_URL` into the standard backend.
- `web/src/components/LiveBrowserView.tsx` falls back to same-origin `/websockify` on non-local browser hosts.
- `docs/guides/company-deployment.md` documents the external-nginx deployment path.
- `deploy/private-repo-template/` is the full private deployment repo template.

## Remaining Work For The Next Agent

1. Run the one-line installer dry-run against the real private deploy repo.

   ```bash
   GITHUB_TOKEN=... \
   QUORVEX_DEPLOY_REPO=NihadMemmedli/quorvex-idda-tests \
   QUORVEX_DOMAIN=mytest.idda.az \
   QUORVEX_SITE=mytest \
   QUORVEX_VERSION=v1.2.3 \
   QUORVEX_ACTIVE_LLM_PROVIDER=zai \
   ZAI_API_KEY=... \
   INITIAL_ADMIN_EMAIL=... \
   INITIAL_ADMIN_PASSWORD=... \
   POSTGRES_PASSWORD=... \
   MINIO_ROOT_PASSWORD=... \
   JWT_SECRET_KEY=... \
   bash -c "$(curl -fsSL https://raw.githubusercontent.com/NihadMemmedli/quorvex_ai/main/deploy/install-server.sh)"
   ```

   This should clone/update both repos, report present/missing/created private files, run bootstrap, and run `./scripts/deploy.sh --dry-run v1.2.3`.

2. Confirm the private repo env has real values.

   Required values:
   - `POSTGRES_PASSWORD`
   - `MINIO_ROOT_PASSWORD`
   - `JWT_SECRET_KEY`
   - `QUORVEX_ACTIVE_LLM_PROVIDER` and the matching provider key, such as `ZAI_API_KEY`
   - `INITIAL_ADMIN_EMAIL`
   - `INITIAL_ADMIN_PASSWORD`
   - `ALLOWED_ORIGINS=https://<quorvex-company-domain>`
   - `TEMPORAL_CORS_ORIGINS=https://<quorvex-company-domain>`
   - `VNC_PUBLIC_WS_URL=wss://<quorvex-company-domain>/websockify`
   - `RECORDER_BROWSER_URL=` unless nginx also exposes the noVNC page/assets

3. Keep these values blank for company nginx deployments:

   ```env
   QUORVEX_PUBLIC_API_URL=
   NEXT_PUBLIC_API_URL=
   ```

4. Configure outbound proxy only if required by the company network.

   ```env
   # HTTP_PROXY=http://proxy.company.internal:8080
   # HTTPS_PROXY=http://proxy.company.internal:8080
   NO_PROXY=localhost,127.0.0.1,db,redis,minio,zap,backend,frontend,temporal,hermes
   ```

5. Configure company nginx.

   Required behavior:
   - Proxy `https://<quorvex-company-domain>/` to `http://<app-server>:3000`.
   - Proxy `https://<quorvex-company-domain>/websockify` to `http://<app-server>:6080/websockify`.
   - Preserve `Upgrade` and `Connection` headers on `/websockify`.
   - Use timeouts of at least `600s` for frontend/backend requests.
   - Use `client_max_body_size 50m` or larger.
   - If recorder links are needed, also proxy `/vnc.html` and noVNC static assets, then set `RECORDER_BROWSER_URL=https://<quorvex-company-domain>/vnc.html?autoconnect=true&resize=scale`.

6. Restrict direct host ports.

   Normal users should use the company URL. Keep direct `3000`, `8001`, and `6080` private to the app server or trusted network.

## Validation Commands

Run from the private deploy repo before startup:

```bash
./scripts/bootstrap.sh
./scripts/deploy.sh --dry-run v1.2.3
```

Run from the public checkout when a tagged release should become deployable:

```bash
make release-preflight VERSION=v1.2.3
```

Without company server access, rehearse the external-nginx path locally:

```bash
make start
make deploy-check
make company-rehearsal
```

Start or update runtime only after dry-run passes:

```bash
./scripts/deploy.sh v1.2.3
```

For normal tagged server updates from the public checkout:

```bash
make server-upgrade VERSION=v1.2.3
```

App-server checks:

```bash
make deploy-check
curl -f http://localhost:3000
curl -f http://localhost:8001/health
```

Company-workstation checks:

- Open `https://<quorvex-company-domain>`.
- Log in as the initial admin.
- Confirm dashboard API calls work without CORS errors.
- Start a small browser-backed run.
- Confirm live view connects through `wss://<quorvex-company-domain>/websockify`.
- Check browser devtools for failed `localhost`, `127.0.0.1`, or mixed-content requests.

## Known Risks

- If `VNC_PUBLIC_WS_URL` is missing, backend runtime metadata may still point live browser clients at localhost.
- If `RECORDER_BROWSER_URL` points to `localhost`, `127.0.0.1`, or port `6080`, company browsers may hit mixed-content or unreachable direct-port failures.
- If `QUORVEX_PUBLIC_API_URL` or `NEXT_PUBLIC_API_URL` points to localhost or a direct backend URL, company browsers may hit CORS, mixed-content, or unreachable-host failures.
- `docker-compose.swarm.yml`, `docker-compose.minimal.yml`, and `docker-compose.autopilot-stable.yml` are local/non-company-safe unless explicitly hardened for same-origin API and company VNC URLs.
- If old real API keys were ever present in `.env.prod`, rotate them before deploying.
