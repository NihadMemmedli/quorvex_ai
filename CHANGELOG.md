# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.2.14] - 2026-06-23

### Fixed

- Register queued-worker MCP browser tools with the Claude CLI when a run-local `.mcp.json` exists, so Service Analyser custom-agent runs can call Playwright MCP tools after deployment.

## [1.2.13] - 2026-06-23

### Added

- `--validate-only` / `--dry-run` CLI flag: validate spec format, template includes, and target URL reachability without running the pipeline (useful for CI pre-checks). Optional `--validate-timeout SECONDS` for URL check timeout (default: 10).
- Documentation refresh covering current features, install paths, Make targets, AutoPilot/autonomous agents, long-running missions, support policies, and GitHub-facing project positioning.
- GitHub presentation refresh with a shorter README, curated examples index, support/security/maintainer/release docs, issue forms, label taxonomy, Dependabot expansion, security automation workflows, and a dry-run issue cleanup playbook.

### Fixed

- Attach run-local MCP configs for custom BaseAgent browser runs, validate requested MCP server prefixes before execution, and remove the stale Chromium revision pin from private deploy templates.

## [1.0.0] - 2026-03-01

### Added

- Natural language to Playwright test conversion via AI-powered pipeline
- Self-healing test pipeline with three modes: Native (3 attempts), Hybrid (up to 20 iterations), and Standard
- Smart Check system that reuses passing tests and only regenerates when necessary
- Web dashboard with Next.js frontend and FastAPI backend
- AI-powered app exploration for autonomous discovery of pages, flows, and API endpoints
- Requirements generation from exploration data with structured output
- Requirements Traceability Matrix (RTM) with coverage scoring and gap analysis
- API testing with OpenAPI/Swagger import and AI-generated HTTP test suites
- Load testing with K6 integration, AI-generated scripts, and distributed execution
- Security testing with multi-tier scanning (Quick checks, Nuclei, ZAP DAST) and AI remediation
- Database testing with PostgreSQL schema analysis and data quality checks
- LLM evaluation platform with provider management, datasets, A/B prompt comparison, and analytics
- CI/CD integration for GitHub Actions and GitLab CI pipeline generation
- TestRail bidirectional sync for test cases and results
- Jira integration for issue tracking
- Multi-project isolation with role-based access control
- Authentication system with JWT tokens, rate limiting, and account lockout
- Browser pool with managed concurrent instances and FIFO queuing
- Cron scheduling for automated regression runs
- Template system with `@include` directives and selector hints
- Visual regression testing with pixel-level screenshot comparison
- Secure credential handling with environment variable placeholders
- PRD-to-test pipeline for converting PDF requirements documents
- Regression batch execution with HTML/JSON/CSV export
- Tiered artifact storage with configurable retention policies
- CLI mode for direct execution without a database

[Unreleased]: https://github.com/NihadMemmedli/quorvex_ai/compare/v1.2.14...HEAD
[1.2.14]: https://github.com/NihadMemmedli/quorvex_ai/compare/v1.2.13...v1.2.14
[1.2.13]: https://github.com/NihadMemmedli/quorvex_ai/compare/v1.0.0...v1.2.13
[1.0.0]: https://github.com/NihadMemmedli/quorvex_ai/releases/tag/v1.0.0
