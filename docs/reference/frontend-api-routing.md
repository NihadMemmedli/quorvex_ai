# Frontend API Routing

![Dashboard overview showing frontend API routing context](../assets/ui/dashboard-overview.png)

<p class="caption">Dashboard overview showing frontend API routing context.</p>


Reference for dashboard-to-backend URL resolution and proxy behavior.

## Browser API Base

`web/src/lib/api.ts` exports `API_BASE` and `apiUrl()`.

| Runtime condition | API base |
|-------------------|----------|
| `NEXT_PUBLIC_API_URL` is set and browser host is local | `NEXT_PUBLIC_API_URL` |
| Browser host is `localhost` or `127.0.0.1` and no env override is set | `http://localhost:8001` |
| Browser host is not local and env points to localhost or is unset | `/backend-proxy` |
| Browser host is not local and env points to a non-local backend | `NEXT_PUBLIC_API_URL` |

Use `apiUrl(path)` or `API_BASE` from `web/src/lib/api.ts` in browser components. Do not hard-code `http://localhost:8001` in dashboard pages.

## Backend Proxy

`web/src/app/backend-proxy/[...path]/route.ts` proxies browser requests from `/backend-proxy/*` to the backend.

| Behavior | Details |
|----------|---------|
| Target backend | `INTERNAL_API_URL`, then `NEXT_PUBLIC_API_URL`, then `http://localhost:8001` |
| Methods | `GET`, `POST`, `PUT`, `DELETE`, `PATCH`, `OPTIONS` |
| Query strings | Preserved |
| Request body | Forwarded for non-`GET` and non-`HEAD` requests |
| Hop-by-hop headers | Removed before forwarding |
| Timeout | Long timeout for long-running dashboard requests |

The proxy exists so deployed dashboards do not send browser traffic to a localhost backend that only exists inside the server environment.

## Server-Side Backend Client

`web/src/lib/ai/backend-client.ts` is for Next.js server routes.

| Option | Purpose |
|--------|---------|
| `method` | HTTP method |
| `body` | JSON request body |
| `headers` | Extra headers |
| `authToken` | Bearer token forwarded to FastAPI |
| `projectId` | Project context header |
| `timeoutMs` | Abort timeout |

Server routes should prefer `backendFetch()` because it resolves `INTERNAL_API_URL` and returns structured success/error data.

## Authenticated Browser Requests

Use `fetchWithAuth` from `web/src/contexts/AuthContext.tsx` for browser requests that may require authentication.

`fetchWithAuth`:

- attaches the current access token when present
- retries once after a successful refresh on `401`
- uses the shared refresh mutex
- returns the final `Response` object

`getAuthHeaders()` in `web/src/lib/styles.ts` is retained for older inline-style pages, but it reads `localStorage.auth_token`. The current auth runtime keeps the access token in module memory and persists only the refresh token, so prefer `fetchWithAuth()` for new pages and for any page that is already being substantially updated.

## Environment Variables

| Variable | Used by | Purpose |
|----------|---------|---------|
| `NEXT_PUBLIC_API_URL` | Browser and server code | Public backend URL override |
| `INTERNAL_API_URL` | Next.js server routes and backend proxy | Server-side backend URL, usually Docker service or internal network address |

## Related

- [Environment Variables](environment-variables.md)
- [Frontend Architecture](../explanation/frontend-architecture.md)
- [Dashboard Auth and Project Flow](../explanation/dashboard-auth-project-flow.md)
- [API Overview](api-overview.md)
