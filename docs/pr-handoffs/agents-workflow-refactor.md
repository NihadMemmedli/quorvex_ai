# PR Handoff: Agents Workflow Refactor

Suggested PR title: `Refactor custom agent workflow into local hook`

## Summary

Refactors the Agents workspace so the custom-agent workflow state and actions live in a local hook instead of the page component.

- Adds `useAgentCustomAgentWorkflow` to own custom agent library loading, builder actions, run setup state, start/control/retry flows, session loading, runtime settings, and derived setup data.
- Keeps `page.tsx` focused on rendering the existing panels, dialogs, confirmations, and result views while consuming workflow values from local hooks.
- Updates report search opening so in-page report links preserve the current UI state and deep links for report/run items keep explicit `view=run`.
- Adds unit coverage for preserving explicit run view when report search deep links include run/report item state.

Behavior preservation is the intent: API payloads, route paths, toast text, validation messages, modals, and query behavior should remain unchanged except for the report search deep-link fix.

## Risk

- [ ] Low: docs, tests, or isolated UI change
- [x] Medium: shared behavior, deployment, auth, generated output, or API contract change
- [ ] High: migrations, secrets, release, CI publishing, or production runtime change

Rationale: this is a UI state refactor on a shared dashboard route. It should not change backend API contracts or persisted data.

## Tests Run

```bash
npm --prefix web run typecheck
# passed

npm --prefix web test
# 14 test files passed, 62 tests passed

PLAYWRIGHT_START_WEB_SERVER=true BASE_URL=http://localhost:3200 PLAYWRIGHT_WEB_PORT=3200 API_BASE=http://localhost:8001 PLAYWRIGHT_WORKERS=1 npx playwright test tests/e2e/agents.spec.ts --project=chromium
# 33 passed (43.2s)
```

Prior verification note to include in the PR: the first focused E2E attempt hit a Turbopack cache panic, then the retry passed 33/33 after cache recovery. A fresh run in this handoff also passed 33/33.

## Docs Drift

- [x] README/docs updated, or not needed
- [x] Environment variable reference updated, or not needed
- [x] API/reference docs updated, or not needed
- [x] Screenshots/demo assets updated, or not needed

No user-facing docs or environment references are expected to change.

## Deployment Impact

- [x] No deployment impact
- [ ] Docker/Compose changed
- [ ] Company external-nginx mode changed
- [ ] Kubernetes or worker topology changed
- [ ] Database migration changed

## Secrets And Data

- [x] No real secrets, tokens, passwords, private URLs, or customer data are included
- [x] Logs, screenshots, traces, and generated tests were reviewed for sensitive values

## Screenshots Or Artifacts

No screenshots were generated for this handoff. The focused Playwright suite covers the affected Agents workflows.

## Rollback

Revert the PR. The change is local to the web Agents route, its local hooks, report search opening behavior, and associated tests.

## Suggested PR Slice

Include these files for the custom-agent workflow refactor and report-search URL-state fix:

```text
tests/e2e/agents.spec.ts
web/src/app/(dashboard)/agents/agents-panels.tsx
web/src/app/(dashboard)/agents/agents-workspace-state.test.ts
web/src/app/(dashboard)/agents/agents-workspace-state.ts
web/src/app/(dashboard)/agents/page.tsx
web/src/app/(dashboard)/agents/use-agent-custom-agent-workflow.ts
web/src/app/(dashboard)/agents/use-agent-report-editing.ts
web/src/app/(dashboard)/agents/use-agent-spec-generation.ts
web/src/app/(dashboard)/agents/use-agent-workspace-query.ts
```

`use-agent-report-editing.ts` and `use-agent-spec-generation.ts` are included because `page.tsx` now imports them as part of the local hook extraction. If those belong to a prior protected slice, keep them with that slice and ensure this PR still typechecks after staging.

## Existing Dirty Files To Review Before Committing

The working tree has dirty files outside this PR focus. Review or exclude them before committing this branch:

```text
package.json
tests/e2e/browser-auth-sessions.spec.ts
tests/e2e/coverage-intelligence.spec.ts
tests/e2e/dashboard-feature-controls.spec.ts
tests/e2e/dashboard-route-smoke.spec.ts
tests/e2e/helpers/dashboard-mocks.ts
tests/e2e/memory.spec.ts
tests/e2e/openapi-import.spec.ts
tests/e2e/pr-advisor.spec.ts
tests/e2e/workflow-creation.spec.ts
web/src/app/(dashboard)/autopilot/page.tsx
web/src/app/(dashboard)/projects/page.tsx
web/src/app/(dashboard)/requirements/page.tsx
web/src/components/TestDataPicker.test.tsx
web/src/components/TestDataPicker.tsx
```
