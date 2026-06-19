# Maintainers

This document describes lightweight ownership and review expectations for Quorvex AI.

## Current Ownership

- Primary maintainer: Nihad Mammadli
- Repository: `NihadMemmedli/quorvex_ai`

## Review Expectations

Pull requests should be reviewed against these questions:

- Does the change preserve self-hosted operation and avoid introducing hosted-service assumptions?
- Are secrets kept out of tracked files, logs, screenshots, generated tests, and docs examples?
- Does the implementation match the existing FastAPI, Next.js, Playwright, Docker, and documentation patterns?
- Are required checks deterministic without external credentials?
- Are optional AI, browser, deployment, or account-mutating checks clearly marked as optional?
- Does the PR update docs when behavior, setup, environment variables, deployment, or user-facing workflows change?

## CODEOWNERS Direction

Use `.github/CODEOWNERS` for broad review routing. Expand it gradually as stable ownership areas emerge:

- Backend runtime and API: `orchestrator/`
- Frontend dashboard: `web/`
- Documentation: `docs/`, `README.md`, governance docs
- Deployment and CI: `.github/`, `docker*`, `deploy/`, `k8s/`, `Makefile`

## Release Stewardship

Release changes should follow [RELEASE.md](RELEASE.md), update [CHANGELOG.md](CHANGELOG.md), and use a protected `release` environment before publishing package or container artifacts.
