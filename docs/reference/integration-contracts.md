# Integration Contracts

![Settings dashboard for integration contract configuration](../assets/ui/settings.png)

<p class="caption">Settings dashboard for integration contract configuration.</p>


Reference for external integration ownership, credentials, local mappings, and primary APIs.

## Integration Map

| Integration | API router | Service client |
|-------------|------------|----------------|
| TestRail | `testrail.py` | `testrail_client.py` |
| Jira | `jira.py` | `jira_client.py` |
| GitHub Actions | `github_ci.py`, `ci_control.py` | `github_client.py` |
| GitLab CI | `gitlab_ci.py`, `ci_control.py` | `gitlab_client.py` |

TestRail and Jira store configuration under `Project.settings["integrations"]`. CI providers use project integration settings plus local mapping models such as `CiPipelineMapping`, `PrImpactAnalysis`, and `PrQualityGateRun`.

## Credential Handling

| Integration | Sensitive fields | Handling |
|-------------|------------------|----------|
| TestRail | API key | Encrypted before storage, masked in config responses |
| Jira | API token | Encrypted before storage, masked in config responses |
| GitHub | access token, webhook secret | Stored in project integration settings and used by GitHub client |
| GitLab | access token, trigger token, webhook secret | Stored in project integration settings and used by GitLab client |

Credential encryption depends on the same application secret used by the credential management layer. Losing the encryption key makes stored integration credentials unrecoverable.

## TestRail Contract

| Capability | Endpoint group | Notes |
|------------|----------------|-------|
| Save config | `/testrail/{project_id}/config` | Base URL, email, API key, project and suite defaults |
| Test connection | `/testrail/{project_id}/test-connection` | Verifies stored credentials |
| Browse remote data | remote projects and suites endpoints | Used by settings and setup flows |
| Push cases | `/testrail/{project_id}/push-cases` | Converts local specs to TestRail cases |
| Sync results | `/testrail/{project_id}/sync-results` | Creates a TestRail run from a regression batch |
| Manage mappings | `/testrail/{project_id}/mappings` | Tracks local spec to remote case IDs |

## Jira Contract

| Capability | Endpoint group | Notes |
|------------|----------------|-------|
| Save config | `/jira/{project_id}/config` | Base URL, email, API token, project key, issue type |
| Test connection | `/jira/{project_id}/test-connection` | Verifies stored credentials |
| Generate bug report | Jira bug report job endpoints | Uses failed run data and artifacts |
| Create issue | Jira create issue endpoint | Creates remote issue and local mapping |
| List mappings | Jira issue listing endpoints | Shows issues created for a project or run |

## CI Provider Contract

| Capability | GitHub | GitLab |
|------------|--------|--------|
| List workflows | Supported through provider-neutral CI API | Supported as pipeline/project data |
| Sync runs | Workflow runs | Pipelines |
| Dispatch | `workflow_dispatch` | trigger pipeline |
| Cancel | workflow run cancellation | pipeline cancellation |
| Rerun | workflow rerun | pipeline retry |
| Logs | workflow/job logs where available | job trace |
| Artifacts | provider artifact links | job artifact links |
| Webhooks | GitHub workflow events | GitLab pipeline events |

Provider-neutral CI state is stored in `CiPipelineMapping` and audited through `CiAuditEvent`.

## PR Advisor and Quality Gate Contract

| Concept | Model | Purpose |
|---------|-------|---------|
| Impact analysis | `PrImpactAnalysis` | Changed-file analysis and selected tests |
| Changed files | `PrChangedFile` | Files considered during analysis |
| Selected tests | `PrSelectedTest` | Recommended Quorvex tests |
| Quality gate run | `PrQualityGateRun` | Combined analysis, test execution, and final feedback |
| Repository index | `RepoIndexSnapshot`, `RepoIndexedFile` | Parsed repository state for impact mapping |

Quality gate operations can dispatch tests and publish feedback, so assistant/tool flows should treat them as approval-required actions.

## Related

- [CI/CD and PR Advisor Architecture](../explanation/ci-pr-advisor-architecture.md)
- [Integrations](../guides/integrations.md)
- [CI/CD Setup](../tutorials/ci-cd-setup.md)
- [Credential Management](../guides/credential-management.md)
- [API Endpoints](api-endpoints.md)
