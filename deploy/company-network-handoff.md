# Company Network Deployment Agent Handoff

Use this note when continuing the company-network deployment. The intended topology is:

- Company DNS and company nginx terminate TLS at a dedicated subdomain.
- Company nginx proxies `/` to the app server frontend on `http://<app-server>:3000`.
- Company nginx proxies `/websockify` to the app server live-browser WebSocket on `http://<app-server>:6080/websockify`.
- The repo-managed nginx container is not part of the `make start` / `prod-dev` path.
- Browser API calls should use same-origin `/backend-proxy`; keep `QUORVEX_PUBLIC_API_URL` and `NEXT_PUBLIC_API_URL` blank.

## Current Repo State

- `.env.prod.example` has production-safe placeholders and external-nginx defaults.
- `docker-compose.prod.yml` passes `VNC_PUBLIC_WS_URL` and `VNC_PUBLIC_URL` into the standard backend.
- `web/src/components/LiveBrowserView.tsx` falls back to same-origin `/websockify` on non-local browser hosts.
- `docs/guides/company-deployment.md` documents the external-nginx deployment path.
- `deploy/examples/reverse-proxy.example.conf`, `deploy/examples/env.production.example`, and `deploy/examples/docker-compose.private.example.yml` are examples for private deployment repos.

## Remaining Work For The Next Agent

1. Replace placeholders in the real server `.env.prod`.

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

2. Keep these values blank for company nginx deployments:

   ```env
   QUORVEX_PUBLIC_API_URL=
   NEXT_PUBLIC_API_URL=
   ```

3. Configure outbound proxy only if required by the company network.

   ```env
   # HTTP_PROXY=http://proxy.company.internal:8080
   # HTTPS_PROXY=http://proxy.company.internal:8080
   NO_PROXY=localhost,127.0.0.1,db,redis,minio,zap,backend,frontend,temporal,hermes
   ```

4. Configure company nginx.

   Required behavior:
   - Proxy `https://<quorvex-company-domain>/` to `http://<app-server>:3000`.
   - Proxy `https://<quorvex-company-domain>/websockify` to `http://<app-server>:6080/websockify`.
   - Preserve `Upgrade` and `Connection` headers on `/websockify`.
   - Use timeouts of at least `600s` for frontend/backend requests.
   - Use `client_max_body_size 50m` or larger.

5. Restrict direct host ports.

   Normal users should use the company URL. Keep direct `3000`, `8001`, and `6080` private to the app server or trusted network.

## Validation Commands

Run before startup:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml -f docker-compose.dev-override.yml --profile standard --profile security config --quiet
make check-env
```

Start runtime:

```bash
make start
make agent-runtime-ready
```

App-server checks:

```bash
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
- If `QUORVEX_PUBLIC_API_URL` or `NEXT_PUBLIC_API_URL` points to localhost or a direct backend URL, company browsers may hit CORS, mixed-content, or unreachable-host failures.
- If old real API keys were ever present in `.env.prod`, rotate them before deploying.
