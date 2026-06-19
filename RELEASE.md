# Release Process

Quorvex AI uses semantic versioning for public releases and keeps release notes in [CHANGELOG.md](CHANGELOG.md).

## Versioning

- Patch releases fix bugs, docs drift, dependency updates, or operational polish.
- Minor releases add backward-compatible product capabilities.
- Major releases contain breaking API, deployment, environment, database, or workflow changes.

Tags use the `vMAJOR.MINOR.PATCH` format, for example `v1.2.3`.

## Release Checklist

1. Confirm `pyproject.toml`, root `package.json`, `web/package.json`, `CHANGELOG.md`, and the intended tag agree.
2. Run deterministic checks:
   ```bash
   python scripts/check_docs_drift.py
   mkdocs build --strict
   python -m pytest orchestrator/tests -v -m "not integration" --ignore=orchestrator/tests/integration
   npm --prefix web run typecheck
   npm --prefix web run lint
   npm --prefix web run build
   ```
3. Run Docker image builds and security scans from CI.
4. Confirm `.env.example` and `.env.prod.example` do not contain real secrets.
5. Confirm production/company docs still describe external-nginx mode for company deployments.
6. Create or update the GitHub Release notes from `CHANGELOG.md`.
7. Publish images only from `main` or a semver tag through the protected `release` GitHub Environment.

## Image Publishing

Container images are published by `.github/workflows/release-images.yml` to GHCR. The workflow should:

- Run only for semver tags or approved manual runs from `main`
- Use the protected `release` environment
- Produce SBOM/provenance metadata where supported
- Run a vulnerability scan before publishing
- Avoid embedding provider tokens, passwords, or runtime `.env` values in images

## Rollback

For company/private deployments, rollback through the private deployment repository:

```bash
./scripts/rollback.sh
```

For public release correction, publish a new patch tag and explain the rollback or correction in `CHANGELOG.md` and GitHub Releases.
