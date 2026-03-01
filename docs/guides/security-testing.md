# How to Run Security Scans

Multi-tier security scanning with Python-native checks, Nuclei templates, OWASP ZAP DAST, and AI-powered finding analysis with remediation planning.

## Overview

The security testing framework provides four scanner tiers:

| Tier | Tool | Speed | Depth | Use Case |
|------|------|-------|-------|----------|
| Quick Scan | Python (`httpx`) | ~10-30s | Surface-level | Headers, cookies, SSL, CORS, info disclosure |
| Nuclei Scan | `nuclei` binary | ~1-5min | Template-based | Known CVEs, misconfigurations, tech detection |
| ZAP DAST | OWASP ZAP | ~5-30min | Deep | Spider + active scan, XSS, SQLi, CSRF |
| AI Analysis | Claude | ~1-2min | Contextual | Finding prioritization, remediation planning |

Additionally, **passive mode** lets functional Playwright tests proxy through ZAP for automatic security analysis during normal test runs.

## Prerequisites

- Quorvex AI installed and running (`make dev` or `make prod-dev`)
- For Nuclei scans: `nuclei` binary installed ([installation guide](https://docs.projectdiscovery.io/tools/nuclei/install))
- For ZAP scans: ZAP daemon running via Docker
- A target application to scan

### Start ZAP Daemon (for ZAP and Full scans)

```bash
docker compose --profile security up -d zap
```

This starts ZAP as a daemon on port 8090.

## Step-by-Step Usage

### 1. Create a Security Test Spec

Write a markdown spec describing what to scan:

```markdown
# Security Test: Production API

## Target
https://api.example.com

## Scan Type
full

## Focus Areas
- Authentication endpoints
- API input validation
- CORS configuration
- Information disclosure

## Authentication
Bearer token: {{API_TOKEN}}

## Exclusions
- /health
- /docs
```

Save via the dashboard at `/security-testing` or the API:

```bash
curl -X POST http://localhost:8001/security-testing/specs \
  -H "Content-Type: application/json" \
  -d '{
    "name": "production-api",
    "content": "# Security Test: Production API\n...",
    "project_id": "your-project-id"
  }'
```

### 2. Run a Scan

Choose a scan tier based on your needs:

**Quick Scan** (fastest, no external tools needed):
```bash
curl -X POST http://localhost:8001/security-testing/scan/quick \
  -H "Content-Type: application/json" \
  -d '{"spec_name": "production-api", "project_id": "your-project-id"}'
```

**Nuclei Scan** (requires `nuclei` binary):
```bash
curl -X POST http://localhost:8001/security-testing/scan/nuclei \
  -H "Content-Type: application/json" \
  -d '{"spec_name": "production-api", "project_id": "your-project-id"}'
```

**ZAP DAST Scan** (requires ZAP daemon):
```bash
curl -X POST http://localhost:8001/security-testing/scan/zap \
  -H "Content-Type: application/json" \
  -d '{"spec_name": "production-api", "project_id": "your-project-id"}'
```

**Full Scan** (runs all tiers sequentially):
```bash
curl -X POST http://localhost:8001/security-testing/scan/full \
  -H "Content-Type: application/json" \
  -d '{"spec_name": "production-api", "project_id": "your-project-id"}'
```

All scans run as background jobs. Poll the status:
```bash
curl http://localhost:8001/security-testing/jobs/JOB_ID
```

### 3. Review Findings

View findings from a scan run:

```bash
# All findings
curl http://localhost:8001/security-testing/runs/RUN_ID/findings

# Filter by severity
curl "http://localhost:8001/security-testing/runs/RUN_ID/findings?severity=high"

# Aggregated summary
curl http://localhost:8001/security-testing/findings/summary?project_id=your-project-id
```

Findings include severity levels: `critical`, `high`, `medium`, `low`, `info`.

### 4. Triage Findings

Update finding status as you review them:

```bash
curl -X PATCH http://localhost:8001/security-testing/findings/FINDING_ID/status \
  -H "Content-Type: application/json" \
  -d '{"status": "false_positive", "notes": "Expected behavior for this endpoint"}'
```

Available statuses: `open`, `false_positive`, `fixed`, `accepted_risk`.

### 5. AI Remediation Analysis

Get AI-powered analysis and remediation plan:

```bash
curl -X POST http://localhost:8001/security-testing/analyze/RUN_ID \
  -H "Content-Type: application/json" \
  -d '{"project_id": "your-project-id"}'
```

The AI analyzes all findings, prioritizes them by risk, and generates actionable remediation steps.

### 6. Generate Spec from Exploration

If you have run an AI exploration session, generate a security spec from the discovered endpoints:

```bash
curl -X POST http://localhost:8001/security-testing/generate-spec \
  -H "Content-Type: application/json" \
  -d '{"exploration_id": "SESSION_ID", "project_id": "your-project-id"}'
```

## Passive Mode (ZAP Proxy)

When `ZAP_PROXY_ENABLED=true`, functional Playwright tests automatically proxy through ZAP. This means every UI test also performs passive security analysis -- detecting issues like missing security headers, insecure cookies, and information leaks without any extra configuration.

Enable in `.env`:
```bash
ZAP_PROXY_ENABLED=true
ZAP_HOST=localhost
ZAP_PORT=8090
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ZAP_HOST` | `localhost` | ZAP daemon host |
| `ZAP_PORT` | `8090` | ZAP daemon port |
| `ZAP_API_KEY` | -- | ZAP API key (optional) |
| `ZAP_PROXY_ENABLED` | `false` | Enable passive mode |
| `NUCLEI_TIMEOUT_SECONDS` | `600` | Nuclei scan timeout (10 min) |
| `SECURITY_SCAN_TIMEOUT` | `1800` | Overall scan timeout (30 min) |

## API Endpoints Reference

| Method | Path | Description |
|--------|------|-------------|
| POST | `/security-testing/specs` | Create security spec |
| GET | `/security-testing/specs` | List specs |
| POST | `/security-testing/scan/quick` | Run quick scan |
| POST | `/security-testing/scan/nuclei` | Run Nuclei scan |
| POST | `/security-testing/scan/zap` | Run ZAP DAST scan |
| POST | `/security-testing/scan/full` | Run all tiers |
| GET | `/security-testing/jobs/{job_id}` | Poll job status |
| GET | `/security-testing/runs` | List scan history |
| GET | `/security-testing/runs/{run_id}` | Scan details |
| GET | `/security-testing/runs/{run_id}/findings` | Findings with filter |
| PATCH | `/security-testing/findings/{id}/status` | Update finding status |
| GET | `/security-testing/findings/summary` | Aggregated counts |
| POST | `/security-testing/analyze/{run_id}` | AI remediation analysis |
| POST | `/security-testing/generate-spec` | AI spec from exploration |

## Key Files

| Path | Purpose |
|------|---------|
| `orchestrator/api/security_testing.py` | API endpoints |
| `orchestrator/services/security/quick_scanner.py` | Python-native security checks |
| `orchestrator/services/security/nuclei_runner.py` | Nuclei subprocess execution |
| `orchestrator/services/security/zap_client.py` | ZAP API client wrapper |
| `orchestrator/services/security/finding_deduplicator.py` | Cross-scanner dedup |
| `orchestrator/workflows/security_analyzer.py` | AI analysis workflow |
| `.claude/agents/security-analyzer.md` | AI agent prompt |

## Quick Scan Checks

The quick scanner performs these Python-native checks:

- **Security headers** -- Content-Security-Policy, X-Frame-Options, X-Content-Type-Options, Strict-Transport-Security, etc.
- **Cookie security** -- HttpOnly, Secure, SameSite flags
- **SSL/TLS** -- certificate validity, protocol version
- **CORS** -- overly permissive Access-Control-Allow-Origin
- **Information disclosure** -- server version headers, error page details, debug endpoints

## Troubleshooting

| Problem | Solution |
|---------|----------|
| ZAP not reachable | Start with: `docker compose --profile security up -d zap` |
| Nuclei not found | Install: `go install github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest` |
| Scan timeout | Increase `SECURITY_SCAN_TIMEOUT` in `.env` |
| Duplicate findings across scanners | The `finding_deduplicator.py` handles this automatically |
| Passive mode not detecting issues | Verify `ZAP_PROXY_ENABLED=true` and ZAP daemon is running |
| AI analysis returns empty results | Check AI credentials in `.env` |

## Verification

Confirm security testing works:

1. Quick scan completes and returns findings (or "no issues found")
2. Findings include severity levels and descriptions
3. AI remediation analysis returns actionable recommendations
4. Finding status updates persist (open, false_positive, fixed, accepted_risk)
5. If using passive mode, running a UI test generates passive findings in ZAP

## Related Guides

- [API Testing](./api-testing.md) -- functional API testing
- [Load Testing](./load-testing.md) -- performance testing
- [Exploration and Requirements](./exploration-requirements.md) -- discover endpoints to scan
- [Credential Management](./credential-management.md) -- manage scan authentication
