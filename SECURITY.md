# Security Policy

## Reporting a Vulnerability

Please do not open a public GitHub issue for security vulnerabilities.

Report suspected vulnerabilities privately to the project maintainer through the contact method listed on the maintainer's GitHub profile. Include:

- Affected version or commit, if known
- Clear reproduction steps
- Expected impact
- Logs, screenshots, or proof-of-concept details when safe to share
- Whether the issue affects default local development, Docker production, integrations, generated tests, or deployment assets

## Scope

Security reports are especially useful for:

- Authentication, authorization, RBAC, and session handling
- Credential storage, masking, encryption, and log scrubbing
- Generated test code that could expose secrets
- CI/CD integrations, webhooks, and repository write operations
- Browser worker isolation and sandboxing
- Backup, restore, MinIO, and artifact access controls
- Dependency or container image vulnerabilities with a practical exploit path

## Response Expectations

This is an open-source project, so response times may vary. The maintainer will triage valid reports, ask for clarifying details when needed, and coordinate a fix before public disclosure when appropriate.

## Deployment Responsibility

Quorvex AI is self-hosted. Before using it in production, change default secrets in `.env.prod`, restrict network access, configure TLS, back up `.env.prod`, and follow the deployment guidance in `docs/guides/company-deployment.md`.
