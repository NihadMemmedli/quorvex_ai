# Brief: Quorvex AI in 10 Minutes: Generate Your First Playwright Test

## Audience

Playwright teams, QA automation engineers, self-hosted devtool users, and engineering teams evaluating AI testing tools

## Problem

Teams want AI to speed up test creation, but they still need readable Playwright code they can own.

## Promise

Show the fastest credible path from repo setup to a generated Playwright test.

## Call to Action

Star Quorvex AI on GitHub and try the minimal setup path.

## Sources

- `docs/tutorials/getting-started.md`
- `README.md`
- `README.minimal.md`

## Source Excerpts

## docs/tutorials/getting-started.md

> # Your First Test in 10 Minutes

> ![Quorvex UI flow for getting started with the dashboard](../assets/ui/product-flow.gif)

> <p class="caption">Quorvex UI flow for getting started with the dashboard.</p>

> In this tutorial, you will install Quorvex AI, write a test spec in plain English, run it through the AI pipeline, and see a fully generated, passing Playwright test.

> ## Prerequisites

> === "Docker (Recommended)"

>     | Tool | Minimum Version | Check Command |
>     |------|----------------|---------------|
>     | Docker | 20+ | `docker --version` |
>     | Docker Compose | 2.x | `docker compose version` |
>     | Git | 2.x | `git --version` |

> === "Local"

>     | Tool | Minimum Version | Check Command |
>     |------|----------------|---------------|
>     | Python | 3.10+ | `python3 --version` |
>     | Node.js | 20+ | `node -v` |
>     | npm | (any) | `npm -v` |
>     | Git | 2.x | `git --version` |

> ## Step 1: Clone the Repository

> Open a terminal and clone the project:

> ```bash
> git clone https://github.com/NihadMemmedli/quorvex_ai.git
> cd quorvex_ai
> ```

> You should see the project structure:

> ```
> quorvex_ai/
>   orchestrator/     # Python backend
>   web/              # Next.js frontend
>   specs/            # Test specifications
>   tests/generated/  # Output: generated Playwright tests
>   Makefile          # All project commands
>   ...
> ```

> ## Step 2: Install and Start

> === "Docker (Recommended)"

>     Copy the production environment file and fill in your API credentials:

>     ```bash
>     cp .env.prod.example .env.prod
>     ```

>     Edit `.env.prod` and set the required AI credentials (see [Step 3]

## README.md

> <p align="center">
>   <h1 align="center">Quorvex AI</h1>
>   <p align="center">
>     <strong>Self-hosted AI testing agents that turn specs into validated Playwright tests.</strong>
>   </p>
>   <p align="center">
>     Generate code you can inspect, commit, and run in CI without runtime AI dependency.
>   </p>
>   <p align="center">
>     <a href="https://github.com/NihadMemmedli/quorvex_ai/stargazers"><img src="https://img.shields.io/github/stars/NihadMemmedli/quorvex_ai?style=social" alt="GitHub Stars"></a>
>     <a href="https://github.com/NihadMemmedli/quorvex_ai/network/members"><img src="https://img.shields.io/github/forks/NihadMemmedli/quorvex_ai?style=social" alt="GitHub Forks"></a>
>   </p>
>   <p align="center">
>     <a href="https://github.com/NihadMemmedli/quorvex_ai/actions/workflows/ci.yml"><img src="https://github.com/NihadMemmedli/quorvex_ai/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
>     <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
>     <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.10+-3776AB.svg?logo=python&logoColor=white" alt="Python 3.10+"></a>
>     <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/Node.js-20+-339933.svg?logo=nodedotjs&logoColor=white" alt="Node.js 20+"></a>
>     <a href="https://playwright.dev/"><img src="https://img.shields.io/badge/Playwright-45ba4b.svg?logo=playwright&logoColor=white" alt="Playwright"></a>
>     <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-009688.svg?logo=fastapi&logoColor=wh

## README.minimal.md

> # Fast Trial: Minimal Docker Compose Setup

> This is the fastest way to try Quorvex AI from the GitHub repo. It runs the dashboard and backend with **SQLite** instead of PostgreSQL and skips optional services such as Redis, MinIO, and VNC.

> ![Quorvex dashboard overview](docs/assets/ui/dashboard-overview.png)

> *The minimal stack opens the same Quorvex dashboard UI with fewer infrastructure services.*

> Use this path when you want to evaluate the core workflow quickly:

> 1. Start the lightweight stack.
> 2. Open the dashboard.
> 3. Write or paste a plain-English test spec.
> 4. Generate a validated Playwright test you can inspect and run.

> For production, team usage, queues, object storage, browser viewing, and security scanning, use the full stack in the main [README](README.md).

> ## What's Included

> - ✅ **Backend** (FastAPI + Playwright orchestrator)
> - ✅ **Frontend** (Next.js web UI)
> - ✅ **SQLite** database (file-based, no separate DB container)
> - ✅ **Core spec-to-Playwright workflow**

> ## What's Not Included

> - ❌ PostgreSQL (uses SQLite instead)
> - ❌ Redis (distributed K6 mode disabled)
> - ❌ MinIO (object storage)
> - ❌ VNC server

> ## Quick Start

> The only required product credential is an Anthropic-compatible API key. Quorvex uses Anthropic-style environment variables even when the provider is Z.ai, OpenRouter, or another compatible endpoint.

> ### 1. Prerequisites

> - Docker & Docker Compose v2.x
> - `.env` file with your `ANTHROPIC_AUTH_TOKEN`

> Create the file from the local example if you do not already have one:

> ```bash
> cp .env.example .env
> # Edit .env and set ANTHROPIC_AUTH_TOKEN
> ma
