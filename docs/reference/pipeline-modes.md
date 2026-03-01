# Pipeline Modes

Comparison reference for all Quorvex AI execution pipelines.

## Pipeline Comparison

| Mode | CLI Flag | Stages | Healing Attempts | Browser Required |
|------|----------|--------|------------------|------------------|
| Default | *(none)* | Plan + Generate + Heal | 3 (native) | Yes |
| Hybrid | `--hybrid` | Plan + Generate + Heal | 3 (native) + 17 (Ralph) | Yes |
| Standard (legacy) | `--standard-pipeline` | Plan + Operator + Export + Validate | 7 | Yes |
| PRD | `--prd` | PDF Extract + Plan + Generate + Heal | 3 (native) | Yes |
| Exploration | `--explore URL` | AI Discovery | N/A | Yes |
| Skill | `--skill-mode` | Script Generation + Execution | N/A | Yes |

## Pipeline

| Property | Value |
|----------|-------|
| Default | Yes |
| CLI flag | *(none)* |
| Stages | Planner, Generator, Healer |
| Healing attempts | 3 |
| Healing tool | Playwright `test_debug` MCP |
| Browser interaction | Every stage |

### Stage Sequence

| Stage | Description |
|-------|-------------|
| 1. Planning | AI agent opens browser, navigates to target URL, explores page, builds plan with discovered selectors |
| 2. Generation | AI agent opens fresh browser, reads spec and plan, writes Playwright test code with live app interaction |
| 3. Execution | Generated test runs via `npx playwright test` |
| 4. Healing | On failure: healer uses `test_debug` MCP tool, rewrites failing portions, re-runs (up to 3 attempts) |

## Hybrid Pipeline

| Property | Value |
|----------|-------|
| Default | No |
| CLI flag | `--hybrid` |
| Stages | Default pipeline + Ralph escalation |
| Total healing budget | 20 (configurable via `--max-iterations`) |
| Phase 1 (native) | Attempts 1-3 |
| Phase 2 (Ralph) | Attempts 4-20 |

## Standard Pipeline (Legacy)

| Property | Value |
|----------|-------|
| Default | No |
| CLI flag | `--standard-pipeline` |
| Stages | Planner, Operator, Exporter, Validator |
| Healing attempts | 7 |
| Browser interaction | Operator stage only |
| Status | Not recommended for new tests |

## PRD Pipeline

| Property | Value |
|----------|-------|
| Default | No |
| CLI flag | `--prd` |
| Input | PDF file |
| Stages | PDF extraction, spec generation (per feature), native pipeline (per spec) |
| Feature selection | `--feature "Feature Name"` |
| Spec splitting | `--split` |

## Exploration Pipeline

| Property | Value |
|----------|-------|
| Default | No |
| CLI flag | `--explore URL` |
| Output | Discovered pages, flows, API endpoints |
| Strategies | `goal_directed` (default), `breadth_first`, `depth_first` |
| Max interactions | `--max-interactions` (default: 50) |
| Timeout | `--timeout` (default: 30 minutes) |
| Authentication | `--login-url URL` + `LOGIN_EMAIL`/`LOGIN_PASSWORD` env vars |

### Exploration Strategies

| Strategy | Behavior |
|----------|----------|
| `goal_directed` | Prioritizes meaningful user flows and actions |
| `breadth_first` | Visits as many pages as possible before going deep |
| `depth_first` | Follows each flow to completion before moving to the next |

## Skill Pipeline

| Property | Value |
|----------|-------|
| Default | No |
| CLI flag | `--skill-mode` (from spec) or `--run-skill SCRIPT` (direct) |
| Output | JavaScript skill script |
| Timeout | `--skill-timeout` (default: 30000 ms) |
| Headless | `--skill-headless` |

## Smart Check (Stage 0)

Runs before any pipeline. Checks for existing generated code.

| Condition | Action |
|-----------|--------|
| Valid code exists and passes | Skip pipeline, reuse code |
| Code exists but fails | Jump to healing (skip plan + generate) |
| No code exists or healing fails | Run full pipeline |
| `--try-code PATH` specified | Use the specified file as existing code |

## Common Flags

| Flag | Type | Default | Applies To |
|------|------|---------|------------|
| `--browser` | `chromium` / `firefox` / `webkit` | `chromium` | All modes |
| `--project-id` | string | derived from spec folder | All modes |
| `--no-memory` | flag | `false` | All modes |
| `--run-dir` | path | `runs/TIMESTAMP/` | All modes |
| `--interactive` / `-i` | flag | `false` | Standard pipeline only |
| `--max-iterations` | int | `20` | Hybrid mode |

## Decision Matrix

| Scenario | Recommended Mode |
|----------|-----------------|
| New test from a simple spec | Default |
| Test keeps failing after 3 healing attempts | Hybrid (`--hybrid`) |
| Generate tests from a PDF PRD | PRD (`--prd`) |
| Discover what an app does | Exploration (`--explore`) |
| Need network mocking or multi-tab | Skill (`--skill-mode`) |
| Reproduce a legacy run | Standard (`--standard-pipeline`) |
| Test on Firefox or WebKit | Any mode + `--browser firefox` |
| Disable memory system | Any mode + `--no-memory` |

## Related

- [CLI Reference](cli.md)
- [Spec Format](spec-format.md)
- [Environment Variables](environment-variables.md)
