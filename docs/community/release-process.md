# Release Process

![CI/CD dashboard for release readiness and workflow status](../assets/ui/ci-cd.png)

<p class="caption">CI/CD dashboard for release readiness and workflow status.</p>

The canonical release checklist is maintained in the repository root at [`RELEASE.md`](https://github.com/NihadMemmedli/quorvex_ai/blob/main/RELEASE.md).

Use this docs page when browsing the published documentation site. In short:

- Keep package versions, tags, release notes, and `CHANGELOG.md` aligned.
- Run deterministic docs, backend, and frontend checks before tagging.
- Publish images only from `main` or semver tags.
- Use the protected `release` GitHub Environment for package or image publishing.
- Keep company deployments in external-nginx mode unless a maintainer explicitly chooses a different topology.
