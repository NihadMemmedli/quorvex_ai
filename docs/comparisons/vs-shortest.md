# Quorvex AI vs Shortest

## Overview

Both Quorvex AI and [Shortest](https://shortest.com) use AI to generate Playwright tests from natural language. The key difference is in **when AI runs**: Shortest uses AI at runtime on every test execution, while Quorvex AI generates stable code once and runs it natively.

## Feature Comparison

| Feature | Quorvex AI | Shortest |
|---------|-----------|----------|
| Natural language input | Yes | Yes |
| Output format | Standard Playwright TypeScript | AI-interpreted at runtime |
| AI cost per test run | Zero (generate once, run forever) | Per-execution AI tokens |
| Self-healing | Yes (3 modes) | No |
| Web dashboard | Yes | No |
| CLI mode | Yes | Yes |
| API testing | Yes (OpenAPI import) | No |
| Load testing | Yes (K6) | No |
| Security testing | Yes (ZAP + Nuclei) | No |
| Database testing | Yes | No |
| LLM evaluation | Yes | No |
| PRD to tests | Yes | No |
| Self-hosted | Yes | Yes |
| Open source | Yes (MIT) | Yes |
| CI/CD integration | GitHub Actions, GitLab CI | GitHub Actions |
| Test management | TestRail, Jira | None |

## Key Differences

### Generate Once, Run Forever

Shortest's AI-powered execution means every test run consumes AI tokens. In a CI/CD pipeline running tests on every commit, this adds up quickly. Quorvex AI generates standard Playwright code once -- subsequent runs execute natively with zero AI cost.

### Multi-Domain Testing

Shortest focuses exclusively on UI testing. Quorvex AI covers UI, API, load, security, database, and LLM evaluation in a single platform. You don't need separate tools for each testing domain.

### Self-Healing Pipeline

When UI changes break tests, Quorvex AI's self-healing pipeline automatically detects and fixes selector failures with three escalation modes (Native, Hybrid, Standard). Shortest does not offer automated test repair.

### PRD to Tests

Quorvex AI can convert PDF product requirements documents directly into test suites -- a workflow no other tool offers. This bridges the gap between product management and QA.

## When to Choose Shortest

- You want a lightweight, CLI-only tool for simple UI tests
- You prefer AI interpretation at runtime for maximum flexibility
- Your test suite is small and AI token cost is not a concern

## When to Choose Quorvex AI

- You need stable, reproducible test code for CI/CD pipelines
- You want a comprehensive QA platform (UI + API + load + security)
- AI token cost matters at scale
- You need self-healing, a web dashboard, or test management integrations
- You want to generate tests from PRDs
