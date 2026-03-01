# How to Diagnose and Fix Common Issues

Expanded troubleshooting guide for resolving setup, pipeline, authentication, browser, database, Docker, and Kubernetes problems.

## Prerequisites

- Access to the Quorvex AI server or development environment
- Ability to run CLI commands and view logs

## Step 1: Run Quick Diagnostics

Before investigating specific issues, gather system state:

```bash
make check-env          # Validate configuration
make health-check       # Hit all health endpoints
make prod-status        # Docker service status (production)
```

Check log files:

```bash
tail -f api.log         # Backend API logs (local dev)
tail -f web.log         # Frontend logs (local dev)
make prod-logs          # Docker production logs
```

## Setup and Configuration Issues

### "ANTHROPIC_AUTH_TOKEN not set"

**Symptom**: CLI or API fails with missing token error.

**Fix**:
```bash
make check-env
# Edit .env and set ANTHROPIC_AUTH_TOKEN=your-actual-token
```

If running in Docker, ensure `.env.prod` has the variable and restart:
```bash
make prod-restart
```

### "ModuleNotFoundError: No module named 'orchestrator'"

**Fix**: Activate the virtual environment:
```bash
source venv/bin/activate
python orchestrator/cli.py specs/my-test.md
```

Or use `make run SPEC=...` which activates the venv automatically.

### "venv not found" or Missing Dependencies

**Fix**:
```bash
make setup
```

### Port 8001 or 3000 Already in Use

**Fix**:
```bash
make stop
```

If ports are still occupied:
```bash
lsof -ti :8001 | xargs kill -15
lsof -ti :3000 | xargs kill -15
```

## Test Generation Issues

### "No target URL found in spec"

**Cause**: The spec file does not contain a navigable URL.

**Fix**: Ensure your spec includes a URL starting with `http://` or `https://`:
```markdown
## Steps
1. Navigate to https://example.com
```

### Generated Test Selectors Fail

**Fix**:
1. Healer automatically retries (up to 3 attempts)
2. Use hybrid mode for extended healing:
   ```bash
   python orchestrator/cli.py specs/my-test.md --hybrid
   ```
3. Check if the target application requires authentication or changed its UI

### Test Times Out on Complex Pages

**Fix**: Increase agent timeouts in `.env`:
```bash
AGENT_TIMEOUT_SECONDS=3600
GENERATOR_TIMEOUT_SECONDS=3600
```

Or use hybrid mode for more healing attempts.

### SDK Cancel Scope Errors

**Symptom**: Error mentioning "cancel scope" in stderr.

**Cause**: Expected behavior -- the Claude Agent SDK throws cleanup errors during shutdown. These are handled automatically by the pipeline.

**If you see this in custom code**, apply the fix pattern:
```python
result_text = ""
try:
    result_text = await runner.run(prompt)
except Exception as e:
    if "cancel scope" in str(e).lower():
        pass  # SDK cleanup -- result_text already captured
    else:
        raise
# Parse result AFTER the except block
```

## Authentication Issues

### "Account locked"

**Symptom**: Login returns HTTP 423.

**Fix**: Wait 15 minutes for automatic unlock, or manually clear:
```sql
-- PostgreSQL
UPDATE users SET failed_login_attempts = 0, locked_until = NULL WHERE email = 'user@example.com';
```

### "Invalid token" Errors

**Cause**: Access token expired (15-minute lifetime) or JWT secret key changed.

**Fix**:
1. Refresh using `POST /auth/refresh` with your refresh token
2. If refresh token expired (7 days), re-login
3. If `JWT_SECRET_KEY` changed, all tokens are invalidated -- users must re-login

### Registration Disabled

**Fix**: Set `ALLOW_REGISTRATION=true` in `.env` and restart.

## Browser Pool Issues

### Browser Slots Exhausted

**Symptom**: Tests queue up and timeout with "Could not acquire browser slot".

**Diagnostics**:
```bash
curl http://localhost:8001/api/browser-pool/status | python3 -m json.tool
```

**Fix**:
1. Wait for running operations to complete
2. Increase limit: `MAX_BROWSER_INSTANCES=10` in `.env`
3. Force cleanup: `curl -X POST http://localhost:8001/api/browser-pool/cleanup`
4. Scale browser workers: `make workers-up && make workers-scale N=8`

### Exploration Stops Early

**Fix**: Increase limits:
```bash
python orchestrator/cli.py --explore https://example.com --max-interactions 100 --timeout 60
```

## Database Issues

### "Database connection refused"

**Fix** (PostgreSQL in Docker):
```bash
docker compose up -d db
# or
make prod-up
```

**Fix** (SQLite fallback):
```bash
# In .env
DATABASE_URL=sqlite:///./test.db
```

### Migration Errors

**Fix**:
```bash
# Check migration state
make db-history

# If schema already exists, stamp it
make db-stamp R=001

# Apply pending migrations
make db-upgrade
```

### Auth Endpoints Return 500 After Restore

**Cause**: Missing database columns after Alembic restore.

**Fix**:
```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec db \
  psql -U playwright -d playwright_agent -c "
    ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login TIMESTAMP;
    ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS device_info VARCHAR;
    ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS ip_address VARCHAR;
  "
make prod-restart
```

## Docker / Production Issues

### Container OOM (Out of Memory)

**Symptom**: Container killed with exit code 137.

**Fix**:
1. Check usage: `docker stats`
2. Increase limits in `docker-compose.prod.yml`
3. Ensure `shm_size: 2gb` for the backend
4. Consider workers mode: `make workers-up`

### VNC Not Connecting

**Fix**:
1. Verify `VNC_ENABLED=true` in `.env.prod`
2. Check supervisord status:
   ```bash
   docker exec playwright-agent-backend-1 supervisorctl status
   ```
   All processes (xvfb, fluxbox, x11vnc, websockify, uvicorn) should be `RUNNING`.

### Backup Services Can't Connect

**Symptom**: DNS errors like `lookup minio: no such host`.

**Fix**: Ensure backup services have `networks: - playwright-network` in `docker-compose.prod.yml`.

### Redis Connection Failed

**Fix**:
```bash
docker ps | grep redis
docker compose restart redis
docker exec -it playwright-agent-redis-1 redis-cli ping
```

The application degrades gracefully: rate limiting uses in-memory storage and the agent queue falls back to direct execution.

## Kubernetes Issues

### Pods Stuck in Pending

**Diagnostics**:
```bash
kubectl describe pod <pod-name> -n playwright-agent
kubectl get pvc -n playwright-agent
```

### HPA Not Scaling

**Fix**: Install metrics server if missing:
```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
```

### Browser Worker Crashes

**Cause**: Insufficient shared memory for Chromium.

**Fix**: Increase `sizeLimit` for the `/dev/shm` emptyDir in `browser-worker-deployment.yaml`.

## Log File Locations

| Environment | Log | Location |
|-------------|-----|----------|
| Local dev | Backend | `api.log` (project root) |
| Local dev | Frontend | `web.log` (project root) |
| Docker prod | All | `make prod-logs` |
| Kubernetes | Backend | `kubectl logs -l app=backend -n playwright-agent` |
| Kubernetes | Workers | `kubectl logs -l app=browser-worker -n playwright-agent` |

## Health Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Backend API status |
| `GET /health/storage` | Local + MinIO storage |
| `GET /health/backup` | Last backup info |
| `GET /health/alerts` | Active alerts |
| `GET /api/browser-pool/status` | Browser pool usage |
| `GET /api/agents/queue-status` | Agent queue status |

## Verification

After fixing any issue:

1. Run `make health-check` to verify all services are healthy
2. Run a simple test spec to confirm end-to-end functionality
3. Check the dashboard loads and can list specs/runs

## Related Guides

- [Getting Started](../tutorials/getting-started.md) -- initial setup
- [Deployment](./deployment.md) -- deployment modes and configuration
- [Disaster Recovery](./disaster-recovery.md) -- recovery from data loss
- [Authentication](./authentication.md) -- auth-specific issues
