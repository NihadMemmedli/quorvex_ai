# Launch Kit

Use this kit when sharing Quorvex AI with developers, QA engineers, and open-source communities.

## Core Positioning

**One-line tagline:**

Self-hosted AI testing agents that turn specs into validated Playwright tests you can commit.

**Short description:**

Quorvex AI lets QA and engineering teams describe a flow, let an agent explore the real app, and generate validated Playwright code. The broader platform also supports PRD-to-tests, API checks, K6 load tests, security scans, database checks, mobile smoke flows, LLM evaluations, CI quality gates, and autonomous coverage discovery.

**Primary audience:**

- QA engineers tired of brittle end-to-end tests
- Engineering teams already using Playwright
- Self-hosted and open-source devtool users
- Teams evaluating AI testing tools but wanting code ownership

## Recommended Assets

| Asset | Path | Use |
|---|---|---|
| Demo GIF | `docs/assets/demo.gif` | README, Hacker News, Reddit, LinkedIn, X |
| Demo video | `docs/assets/demo.webm` | Product Hunt, blog posts, launch pages |
| Dashboard screenshot | `docs/assets/dashboard-screenshot.png` | Product overview and docs |
| Social preview | `docs/assets/social-preview.png` | Open graph, social posts, launch cards |
| Example input/output | `demo/` | Technical proof and README snippets |

## Launch Copy

### Hacker News

Title:

```text
Show HN: Quorvex AI - self-hosted agents that generate validated Playwright tests
```

Body:

```text
I built Quorvex AI for teams that want AI-assisted testing without turning every test run into an AI runtime dependency.

The core workflow is: write a markdown spec or import requirements, let an agent explore the app in a real browser, generate Playwright code, validate it, and heal selector/timing failures when possible.

It is MIT licensed and self-hosted. The dashboard also supports PRD-to-tests, API checks, K6 load tests, security scans, database checks, mobile smoke flows, LLM evals, CI quality gates, and autonomous coverage discovery.

Repo: https://github.com/NihadMemmedli/quorvex_ai
Docs: https://nihadmemmedli.github.io/quorvex_ai/
```

### Reddit

Use a workflow-specific post, not a generic announcement.

```text
I built an open-source tool that turns markdown QA specs into validated Playwright tests.

The part I wanted to solve: AI can draft tests quickly, but teams still need code they can inspect, commit, and run in CI without paying for AI on every test run. Quorvex explores the app in a browser, generates Playwright, runs it, and attempts healing when selectors or timing break.

Demo and repo: https://github.com/NihadMemmedli/quorvex_ai

I would especially like feedback from teams already maintaining Playwright suites.
```

### LinkedIn

```text
I am building Quorvex AI: self-hosted AI testing agents that turn specs and PRDs into validated Playwright tests.

The main idea is simple: AI should help discover and generate coverage, but the output should still be code your team owns.

Workflow:
1. Write a plain-English spec.
2. Let an agent explore the app in a real browser.
3. Generate Playwright code.
4. Validate and heal the test.
5. Commit it like normal automation code.

Open source repo: https://github.com/NihadMemmedli/quorvex_ai
```

### X

```text
I built Quorvex AI: self-hosted AI testing agents that turn specs into validated Playwright tests.

AI helps explore, generate, validate, and heal.
Your team keeps normal test code it can inspect, commit, and run in CI.

Repo: https://github.com/NihadMemmedli/quorvex_ai
```

## Launch Checklist

- README leads with the spec-to-validated-Playwright workflow.
- Demo GIF is visible above the first long feature table.
- Minimal setup path is linked from the first screen.
- GitHub topics include `ai-testing`, `playwright`, `qa-automation`, `test-generation`, `self-healing`, and `e2e-testing`.
- At least five `good first issue` items are open or easy to create from `docs/community/good-first-issues.md`.
- Launch day owner can respond to comments for 6-8 hours.
- Follow-up release notes are ready for fixes shipped after launch feedback.

## Success Metrics

Track the first four weeks after launch:

- Stars, forks, and watchers
- GitHub traffic referrers
- Clones and Codespaces/Gitpod starts where available
- Issues or discussions from outside users
- New contributors or serious contribution inquiries
