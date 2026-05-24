# Launch Kit

![Quorvex product demo GIF for launch materials](../assets/ui/product-flow.gif)

<p class="caption">Quorvex product demo GIF for launch materials.</p>


Use this kit when sharing Quorvex AI with developers, QA engineers, and open-source communities.

## Core Positioning

**One-line tagline:**

Self-hosted AI testing agents that turn specs into validated Playwright tests you can commit.

**Short description:**

Quorvex AI lets QA and engineering teams describe a flow, let an agent explore the real app, and generate validated Playwright code. The broader platform also supports PRD-to-tests, API checks, K6 load tests, security scans, database checks, mobile smoke flows, LLM evaluations, CI quality gates, and autonomous coverage discovery.

**Primary audience:**

- Engineering teams already using Playwright
- QA engineers tired of brittle end-to-end tests
- Self-hosted and open-source devtool users
- Teams evaluating AI testing tools but wanting code ownership

## Recommended Assets

| Asset | Path | Use |
|---|---|---|
| UI demo GIF | `docs/assets/ui/product-flow.gif` | README, Hacker News, Reddit, LinkedIn, X |
| Demo video | `docs/assets/demo.webm` | Product Hunt, blog posts, launch pages |
| Dashboard screenshot | `docs/assets/dashboard-screenshot.png` | Product overview and docs |
| Social preview | `docs/assets/social-preview.png` | Open graph, social posts, launch cards |
| Example input/output | `demo/` | Technical proof and README snippets |

## Product Hunt Launch Packet

Primary link: `https://github.com/NihadMemmedli/quorvex_ai`

Secondary link: `https://nihadmemmedli.github.io/quorvex_ai/`

### Listing Copy

**Product name:**

```text
Quorvex AI
```

**Tagline:**

```text
Self-hosted AI agents that generate validated Playwright tests
```

**Short description:**

```text
Turn specs, PRDs, and app exploration into Playwright tests your team can inspect, commit, and run in CI.
```

**First comment:**

```text
Hi Product Hunt,

I built Quorvex AI for Playwright and QA teams that want AI-assisted test creation without depending on AI at runtime.

The core workflow is:

1. Write a plain-English spec, import a PRD, or let an agent explore the app.
2. Quorvex plans the flow against the real target.
3. It generates Playwright TypeScript.
4. It validates the test in a browser.
5. If selectors or timing break, it attempts to heal the test.
6. Your team keeps normal code that can be reviewed, committed, and run in CI.

It is MIT licensed and self-hosted. The broader platform also includes PRD-to-tests, API checks, K6 load tests, security scans, database checks, mobile smoke flows, LLM evaluations, CI quality gates, and autonomous coverage discovery.

I would especially value feedback from teams already maintaining Playwright suites: what would make this trustworthy enough to add to your QA workflow?

Repo: https://github.com/NihadMemmedli/quorvex_ai
Docs: https://nihadmemmedli.github.io/quorvex_ai/
```

### Gallery Captions

Use these captions with the demo video, GIF, screenshot, and social preview:

| Asset | Caption |
|---|---|
| Demo video | From plain-English spec to validated Playwright test, with browser execution in the loop. |
| Demo GIF | Quorvex plans, generates, validates, and heals tests before handing you code. |
| Dashboard screenshot | Manage specs, runs, requirements, regression batches, credentials, analytics, and integrations. |
| Input/output example | The final artifact is readable Playwright code your team can inspect, commit, and run in CI. |

### 60-90 Second Demo Video Script

```text
0-10s: Show the problem.
"Playwright is a great runtime, but writing and maintaining end-to-end coverage is still slow. AI can draft tests, but most teams still need code they own."

10-25s: Show the spec.
"In Quorvex AI, start with a plain-English flow, PRD, OpenAPI file, or app exploration mission."

25-40s: Show planning and browser execution.
"The agent plans against the target app and uses live browser context instead of guessing selectors from a prompt."

40-55s: Show generated Playwright.
"Quorvex generates normal Playwright TypeScript that can be reviewed like any other test."

55-70s: Show validation and healing.
"It runs the generated test, captures artifacts, and attempts to repair selector or timing failures when the UI changes."

70-90s: Close on repo and dashboard.
"The result is self-hosted AI-assisted testing without runtime AI dependency. Star Quorvex AI on GitHub and try the minimal Docker setup."
```

### Launch-Day Response Bank

Use short replies that move the discussion back to the core value:

| Question | Suggested reply |
|---|---|
| How is this different from prompt-generated tests? | Quorvex uses planning, browser context, validation, and healing. The goal is not a draft snippet; it is a test that has been run before you keep it. |
| Does it run AI every time CI runs? | No. Generated Playwright tests run normally. AI is used for generation, validation support, exploration, and healing workflows. |
| Can I self-host it? | Yes. The project is MIT licensed and supports local, Docker, production, and Kubernetes-oriented setup paths. |
| Who is this for? | Teams using or evaluating Playwright, QA automation engineers maintaining E2E suites, and self-hosted devtool users. |
| Is this only for UI testing? | UI generation is the wedge, but the platform also supports API, load, security, database, mobile, LLM evaluation, PRD-to-tests, CI quality gates, and coverage discovery. |

### Launch-Day Rhythm

- Launch early in the Product Hunt day and keep the GitHub repo as the primary URL.
- Update the README and social preview before submitting.
- Stay active for 6-8 hours and reply to every substantive comment.
- Pin the clearest founder comment or repo explanation where possible.
- Share one technical post after launch starts, not only a generic "we launched" post.
- Watch GitHub traffic, stars, forks, issues, and comments throughout the day.
- Collect repeated objections and turn them into README or FAQ improvements within 48 hours.

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
- Product Hunt listing uses the GitHub repository as the primary link.
- Demo video, GIF, dashboard screenshot, and social preview are uploaded and checked in Product Hunt preview.
- Founder comment is ready before launch day, including the direct repo and docs links.
- GitHub topics include `ai-testing`, `playwright`, `qa-automation`, `test-generation`, `self-healing`, and `e2e-testing`.
- At least five `good first issue` items are open or easy to create from `docs/community/good-first-issues.md`.
- Launch day owner can respond to comments for 6-8 hours.
- Hacker News, Reddit, LinkedIn, and X posts are staged before launch starts.
- Follow-up release notes are ready for fixes shipped after launch feedback.

## Success Metrics

Track the first four weeks after launch:

- Stars, forks, and watchers
- GitHub traffic referrers
- Product Hunt visits, upvotes, comments, and click-throughs to GitHub
- Clones and Codespaces/Gitpod starts where available
- Issues or discussions from outside users
- New contributors or serious contribution inquiries
- Repeated objections or questions that should become README or FAQ updates
