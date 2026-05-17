# Security Testing Capabilities

## Purpose

Show the complete security-testing surface available in Quorvex AI and give users a concrete way to choose the right scan mode.

## Available scanners

| Capability | Scanner | Use it for | Expected runtime | Safe for shared environments |
| --- | --- | --- | --- | --- |
| Quick Scan | Built-in header and exposure checks | Fast demo, smoke test, CI gate | 10-30 seconds | Yes |
| Nuclei Scan | ProjectDiscovery Nuclei templates | Known CVEs, exposed panels, misconfigurations | 1-5 minutes | Usually, with safe templates |
| ZAP Scan | OWASP ZAP spider and passive scan | DAST coverage, browser-like discovery, passive alerts | 5-30 minutes | Yes for passive/safe |
| Full Scan | Quick + Nuclei + ZAP | Broad security assessment | 10-45 minutes | Use carefully |

## Active scan levels

| Level | Behavior | Recommended target |
| --- | --- | --- |
| passive | No active attack payloads. Collects headers, TLS, cookies, and passive DAST alerts. | Production demos and shared staging |
| safe | Enables crawler/spider behavior and safe checks. Avoids destructive active attacks. | Staging and demo environments |
| full | Enables all configured scanners and ZAP active scan. Can submit forms and send attack payloads. | Disposable test environments only |

## Authenticated scanning

Security scans can log in before scanning when credentials are configured for the project.

Required fields:

- Target URL: page or app area to scan.
- Login URL: login page used to create the authenticated browser session.
- Username credential key.
- Password credential key.

Captured session state is reused as cookies and authorization context for scanner requests.

## Scope control

Use exclusions to keep scans inside safe boundaries.

Recommended exclusions for demos:

```text
/logout
/api/delete
/api/admin
/reset-password
```

## Demo flow

1. Open Security Testing.
2. Show Scanner readiness cards: Quick, Nuclei, and ZAP.
3. Run Quick Scan against `http://host.docker.internal:3000/login`.
4. Open History and show the completed run.
5. Open Findings and show severity grouping.
6. Open Specs and explain that specs are reusable test plans and acceptance criteria.

## Acceptance criteria

- Scanner capability checks report Quick, Nuclei, and ZAP as available.
- A passive Quick Scan can complete without external setup after `make start`.
- Findings include severity, evidence, remediation, scanner source, and status.
- Specs can be created, edited, viewed, and deleted from the UI.
- Full scans are possible when the target is a disposable test environment.
