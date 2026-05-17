# Quorvex Login Security Demo

## Target

`http://host.docker.internal:3000/login`

Use `host.docker.internal` when scanning the UI from Docker-based services.

## Demo scan

| Field | Value |
| --- | --- |
| Scan type | Quick Scan |
| Active scan level | passive |
| Run ID | sec-614064b7 |
| Result | completed |
| Total findings | 5 |

## Findings from demo run

| Severity | Finding | Evidence | Expected remediation |
| --- | --- | --- | --- |
| high | Site Not Using HTTPS | URL scheme: http | Enforce HTTPS in production and redirect HTTP to HTTPS. |
| medium | Missing Content-Security-Policy Header | Response header absent | Add a restrictive CSP for scripts, styles, images, frames, and connections. |
| low | X-Powered-By Disclosure | X-Powered-By: Next.js | Disable framework disclosure headers. |
| low | Missing Permissions-Policy Header | Response header absent | Add a least-privilege Permissions-Policy. |
| info | Missing HSTS Header | Response header absent | Add HSTS on HTTPS responses after TLS is enabled. |

## Why this is useful as a demo

The test is fast, deterministic, and shows the full workflow:

- start a scan
- track scanner progress
- persist a security run
- create findings with severity and evidence
- show remediation guidance
- keep reusable specs beside the run history

## Retest criteria

The login page is considered remediated when:

- production URLs redirect to HTTPS
- `Content-Security-Policy` is present
- `X-Powered-By` is absent
- `Permissions-Policy` is present
- `Strict-Transport-Security` is present on HTTPS responses

## Recommended next scan

After the quick demo, run:

| Scan | Target | Level | Notes |
| --- | --- | --- | --- |
| Nuclei | `http://host.docker.internal:3000/login` | safe | Checks known template-based exposures. |
| ZAP | `http://host.docker.internal:3000/login` | passive | Adds passive DAST alerts without attack payloads. |
| Full | disposable staging URL | full | Use only where active payloads are allowed. |
