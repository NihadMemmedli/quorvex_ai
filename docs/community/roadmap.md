# Roadmap

This page outlines the current capabilities of Quorvex AI and the features under consideration for future releases.

## Current Release

Quorvex AI ships today with a comprehensive set of testing and automation capabilities:

- **Pipeline** -- AI-powered Plan, Generate, Heal cycle for Playwright test creation
- **Web Dashboard** -- Full management interface for specs, runs, regression batches, and analytics
- **Multi-Domain Testing** -- UI, API, load (K6), security (ZAP + Nuclei), database, and LLM evaluation
- **AI App Exploration** -- Autonomous discovery of pages, flows, API endpoints, and form behaviors
- **AutoPilot & Autonomous Missions** -- Interactive app discovery plus recurring and long-running agent workflows with approval gates
- **Requirements & RTM** -- AI-generated requirements from exploration data with traceability matrix
- **Self-Healing** -- Automatic test repair with Healer (3 attempts) and Hybrid mode (up to 20)
- **Mobile Testing** -- Appium-based mobile smoke flows and generated mobile automation support
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
- [ ] **Cross-Browser Campaigns** -- Expand browser selection into managed Chromium, Firefox, and WebKit regression campaigns with reporting
- [ ] **Recording Mode Enhancements** -- Improve browser recording import, editing, and conversion into markdown specs
- [ ] **Plugin System** -- Extend the platform with custom pipeline stages, report formatters, and notification providers
- [ ] **Self-Hosted LLM Support** -- Run the AI pipeline with locally hosted models (Ollama, vLLM) for air-gapped environments
- [ ] **Mobile Testing Expansion** -- Broaden Appium coverage beyond smoke flows, including richer device farms and responsive layout checks
- [ ] **Test Impact Analysis Expansion** -- Expand PR advisor recommendations into deeper changed-code-to-test mapping
- [ ] **Spec Version History** -- Track changes to test specifications over time with diff views and rollback
- [ ] **Team Collaboration** -- Shared test libraries, review workflows, and assignment tracking across team members

!!! note "Community Input Welcome"
    These items are under consideration and priorities may shift based on community feedback. If a feature is important to your workflow, please upvote or comment on the relevant [GitHub Discussion](https://github.com/NihadMemmedli/quorvex_ai/discussions) to help us prioritize.
