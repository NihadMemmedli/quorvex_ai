# Roadmap

This page outlines the current capabilities of Quorvex AI and the features under consideration for future releases.

## Current Release

Quorvex AI ships today with a comprehensive set of testing and automation capabilities:

- **Pipeline** -- AI-powered Plan, Generate, Heal cycle for Playwright test creation
- **Web Dashboard** -- Full management interface for specs, runs, regression batches, and analytics
- **Multi-Domain Testing** -- UI, API, load (K6), security (ZAP + Nuclei), database, and LLM evaluation
- **AI App Exploration** -- Autonomous discovery of pages, flows, API endpoints, and form behaviors
- **Requirements & RTM** -- AI-generated requirements from exploration data with traceability matrix
- **Self-Healing** -- Automatic test repair with Healer (3 attempts) and Hybrid mode (up to 20)
- **Enterprise Features** -- Multi-tenancy, RBAC, cron scheduling, CI/CD integrations (GitHub Actions, GitLab CI)
- **TestRail Sync** -- Bidirectional sync of test cases and run results
- **Jira Integration** -- Link test results to Jira tickets
- **Credential Management** -- Encrypted storage with placeholder substitution in specs
- **Storage & Archival** -- Tiered artifact retention with MinIO support
- **Memory System** -- Vector and graph stores for persistent exploration data and selector patterns

## Planned Features

The following items are under consideration for future development. Items are not listed in priority order.

- [ ] **Visual Test Reporting** -- Rich HTML reports with embedded screenshots, trace viewer links, and step-by-step execution timelines
- [ ] **Slack & Teams Notifications** -- Send test results and failure alerts to Slack channels and Microsoft Teams
- [ ] **Multi-Browser Support** -- Run generated tests across Chromium, Firefox, and WebKit with a single spec
- [ ] **Recording Mode** -- Record browser interactions and convert them into markdown specs automatically
- [ ] **Plugin System** -- Extend the platform with custom pipeline stages, report formatters, and notification providers
- [ ] **Self-Hosted LLM Support** -- Run the AI pipeline with locally hosted models (Ollama, vLLM) for air-gapped environments
- [ ] **Mobile Testing** -- Generate and run tests for mobile web and responsive layouts with device emulation
- [ ] **Test Impact Analysis** -- Identify which tests need re-running based on code changes in the application under test
- [ ] **Spec Version History** -- Track changes to test specifications over time with diff views and rollback
- [ ] **Team Collaboration** -- Shared test libraries, review workflows, and assignment tracking across team members

!!! note "Community Input Welcome"
    These items are under consideration and priorities may shift based on community feedback. If a feature is important to your workflow, please upvote or comment on the relevant [GitHub Discussion](https://github.com/NihadMemmedli/quorvex_ai/discussions) to help us prioritize.
