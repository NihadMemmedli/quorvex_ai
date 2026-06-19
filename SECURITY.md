# Security Policy

## Supported Versions

Security fixes are targeted at the latest released version and the current `main` branch. Older tags may receive guidance, but backports are not guaranteed unless a maintainer explicitly accepts the work.

| Version | Supported |
|---------|-----------|
| Latest release | Yes |
| `main` | Yes |
| Older releases | Best effort |

## Reporting A Vulnerability

Do not open a public GitHub issue for security vulnerabilities.

Preferred reporting path:

1. Use GitHub private vulnerability reporting if it is enabled for this repository.
2. If private reporting is not available, contact the maintainer through the security contact listed on the maintainer's GitHub profile.
3. Before publishing this repository for wider use, replace this fallback with a dedicated security contact such as `security@example.com`.

Include:

- Affected version, tag, or commit
- Clear reproduction steps
- Expected impact
- Whether the issue affects local development, generated tests, Docker runtime, company external-nginx deployment, integrations, CI/CD, credentials, or artifacts
- Logs, screenshots, or proof-of-concept details only when they are safe to share

## Triage Expectations

This is an open-source project, so response times may vary. The maintainer will aim to:

- Acknowledge valid private reports
- Ask for clarifying details when needed
- Confirm scope and severity before public disclosure
- Coordinate a fix, mitigation, or advisory when appropriate

## Automated Security Scanning

CodeQL runs on pull requests, pushes to `main`, and the scheduled weekly scan. Existing CodeQL alerts are treated as a known security backlog unless a maintainer escalates a specific alert into an active vulnerability response. Pull request scanning should remain enabled so new or changed code is analyzed while backlog triage continues separately.

Dependency Review is enabled for pull requests after confirming GitHub dependency graph support on June 19, 2026. Maintainers should keep the `DEPENDENCY_REVIEW_ENABLED=true` repository variable set so `.github/workflows/dependency-review.yml` runs `actions/dependency-review-action@v4`; if dependency graph support is unavailable in a fork or future repository configuration, unset the variable instead of removing the workflow gate.

## Scope

Useful reports include:

- Authentication, authorization, RBAC, and session handling issues
- Credential storage, masking, encryption, and log-scrubbing failures
- Generated test code that could expose secrets
- Browser worker isolation or sandbox bypasses
- CI/CD integrations, webhooks, repository write operations, and release publishing risks
- Backup, restore, MinIO, and artifact access-control issues
- Dependency or container image vulnerabilities with a practical exploit path

## Secret Handling

Never commit real secrets to tracked files. Use `.env.prod`, `.env`, `.env.local`, `.secrets/`, GitHub Actions secrets, private deployment repositories, or shell environment variables.

Before production use:

- Rotate all default credentials
- Set strong `JWT_SECRET_KEY`, database, MinIO, and provider credentials
- Restrict direct host ports to trusted networks
- Terminate TLS at company nginx or another managed proxy
- Keep `QUORVEX_PUBLIC_API_URL` and `NEXT_PUBLIC_API_URL` blank in company external-nginx mode so browser calls use same-origin routing
- Review [docs/guides/company-deployment.md](docs/guides/company-deployment.md)

## Disclosure

Public disclosure should happen after a fix, mitigation, or clear non-affected determination is available. If a report cannot be fixed immediately, maintainers may publish operational mitigations first.
