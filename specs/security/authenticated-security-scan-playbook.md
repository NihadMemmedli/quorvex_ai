# Authenticated Security Scan Playbook

## Purpose

Validate security controls that are only visible after login, including authenticated pages, API calls, cookies, and authorization boundaries.

## Preconditions

- The app is running through `make start`.
- The UI target is reachable as `http://host.docker.internal:3000`.
- A project credential exists for the username.
- A project credential exists for the password.
- The target account has demo-safe permissions.

## Scanner setup

| Field | Recommended demo value |
| --- | --- |
| Target URL | `http://host.docker.internal:3000/security-testing` |
| Login URL | `http://host.docker.internal:3000/login` |
| Username key | Project credential key for the demo user |
| Password key | Project credential key for the demo password |
| Active scan level | passive or safe |
| Exclusions | `/logout`, `/api/delete`, `/api/admin`, `/reset-password` |

## What the scanner should verify

### Session handling

- Cookies use secure attributes in production.
- Session cookies are not exposed to client-side JavaScript unless required.
- Logout invalidates the session.
- Authenticated pages are not cached with sensitive content.

### Authorization

- Authenticated pages require a valid session.
- Role-restricted routes reject lower-privilege users.
- APIs return 401 or 403 instead of sensitive data when unauthorized.

### Browser security headers

- `Content-Security-Policy`
- `Permissions-Policy`
- `Referrer-Policy`
- `X-Content-Type-Options`
- `Strict-Transport-Security` on HTTPS

### Exposure checks

- No stack traces.
- No framework debug pages.
- No exposed admin panels.
- No secrets in JavaScript bundles or HTML.

## Demo script

1. Select Full Scan or ZAP Scan.
2. Enable authenticated scan.
3. Select username and password credential keys.
4. Keep active scan level at `passive` for a live demo.
5. Start the scan.
6. Open History to show scanner stages.
7. Open Findings to filter by scanner and severity.

## Safety notes

Use `full` active scan level only on disposable staging environments. Full mode can submit forms, send attack payloads, and create noisy logs.
