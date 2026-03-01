# How to Deploy Quorvex AI On-Premises

Deploy Quorvex AI to an on-premises or private network environment, including VM setup, TLS configuration, and ongoing maintenance.

## Prerequisites

- A Linux VM with at least 8 CPU cores, 32 GB RAM, and 200 GB SSD (Ubuntu 22.04 LTS recommended)
- Docker Engine and Docker Compose v2 installed
- Network access to your AI provider API (direct or via proxy)
- An internal Git repository for hosting the code
- Organization-issued TLS certificates (optional but recommended)

## Step 1: Prepare Code for Internal Git

Push the repository to a clean internal Git server:

```bash
cd /path/to/playwright-agent

# Create orphan branch with single commit (no dev history)
git checkout --orphan clean-main
git add -A
git commit -m "Initial commit: AI-Powered Test Automation Platform"
git branch -M main

# Add internal remote and push
git remote add origin https://gitlab.example.com/qa/playwright-agent.git
git push -u origin main
```

Verify no secrets leaked into tracked files:

```bash
git ls-files | xargs grep -l "password\|secret\|token\|api.key" 2>/dev/null
# Expected: only .env.prod.example (with placeholders), CLAUDE.md, docs/
```

!!! danger
    `.gitignore` excludes `.env`, `.env.prod`, `test.db*`, `runs/`, `logs/`, `node_modules/`, `venv/`. Verify no secrets are in tracked files before pushing.

## Step 2: Install Prerequisites on the VM

```bash
# Install Docker Engine
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker

# Install Docker Compose plugin (if not bundled)
sudo apt-get install -y docker-compose-plugin

# Verify
docker --version
docker compose version
```

If behind a corporate proxy, configure Docker daemon proxy:

```bash
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo tee /etc/systemd/system/docker.service.d/http-proxy.conf <<EOF
[Service]
Environment="HTTP_PROXY=http://proxy.example.com:8080"
Environment="HTTPS_PROXY=http://proxy.example.com:8080"
Environment="NO_PROXY=localhost,127.0.0.1,*.example.com"
EOF
sudo systemctl daemon-reload
sudo systemctl restart docker
```

## Step 3: Clone and Configure

```bash
git clone https://gitlab.example.com/qa/playwright-agent.git /opt/playwright-agent
cd /opt/playwright-agent

# Create production environment file
cp .env.prod.example .env.prod
```

Edit `.env.prod` with production values:

```bash title=".env.prod"
# Required secrets -- generate secure values
ANTHROPIC_AUTH_TOKEN=<your-api-key>
ANTHROPIC_BASE_URL=<your-endpoint>
ANTHROPIC_DEFAULT_SONNET_MODEL=<model-id>
JWT_SECRET_KEY=$(openssl rand -hex 32)
POSTGRES_PASSWORD=$(openssl rand -base64 32)
MINIO_ROOT_PASSWORD=$(openssl rand -base64 32)

# Admin user (created on first startup only)
INITIAL_ADMIN_EMAIL=admin@example.com
INITIAL_ADMIN_PASSWORD=<strong-password>

# Security
REQUIRE_AUTH=true
ALLOW_REGISTRATION=false

# URLs -- adjust to your domain/IP
NEXT_PUBLIC_API_URL=https://playwright.example.com/api
ALLOWED_ORIGINS=https://playwright.example.com

# Corporate proxy (if needed)
HTTP_PROXY=http://proxy.example.com:8080
HTTPS_PROXY=http://proxy.example.com:8080
```

## Step 4: Set Up TLS (Optional but Recommended)

```bash
mkdir -p nginx/certs

# Option A: Organization-issued certificates
cp /path/to/your-cert.pem nginx/certs/cert.pem
cp /path/to/your-key.pem nginx/certs/key.pem

# Option B: Self-signed certificates
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/certs/key.pem \
  -out nginx/certs/cert.pem \
  -subj "/CN=playwright.example.com"
```

## Step 5: Build and Start

```bash
# Build images (first time -- no cache)
make prod-build-no-cache

# Start all services
make prod-up

# With TLS/nginx:
docker compose --env-file .env.prod -f docker-compose.prod.yml --profile standard --profile nginx up -d
```

Services started:

| Service | Port | Purpose |
|---------|------|---------|
| Backend | 8001 | API server + Playwright browsers + VNC |
| Frontend | 3000 | Next.js web dashboard |
| PostgreSQL | 5432 | Database |
| Redis | 6379 | Rate limiting + job queue |
| MinIO | 9000/9001 | Object storage for backups |
| Backup Scheduler | -- | Automated daily backups |
| Nginx (with TLS) | 80/443 | TLS termination + reverse proxy |

## Step 6: Back Up `.env.prod` Immediately

!!! danger
    `JWT_SECRET_KEY` encrypts integration credentials (TestRail API keys, Jira tokens, etc.). Losing it means all encrypted credentials become **unrecoverable**. Store `.env.prod` in your password manager or secure vault immediately.

## Step 7: Verify the Deployment

```bash
# All-in-one health check
make health-check

# Individual checks
curl -sf http://localhost:8001/health
curl -sf http://localhost:3000
curl -sf http://localhost:8001/health/storage
```

Functional verification:

1. Log in to the dashboard with admin credentials
2. Create a new project
3. Upload a test spec
4. Run a test -- verify it completes
5. Check VNC view at port 6080 during test execution

Backup verification:

```bash
make backup-full
make backup-status
```

## Step 8: Set Up Health Monitoring

```bash
chmod +x scripts/health-monitor.sh

# Test manually
./scripts/health-monitor.sh

# Add to cron (every 5 minutes)
(crontab -l 2>/dev/null; echo "*/5 * * * * /opt/playwright-agent/scripts/health-monitor.sh") | crontab -
```

## Daily Operations

| Time | Task | Service |
|------|------|---------|
| 2:00 AM | Full backup with MinIO sync | backup-scheduler (automatic) |
| 3:00 AM | Artifact archival | backup-scheduler (automatic) |
| Daily | `make health-check` | Manual check |
| Weekly | `df -h`, `make volume-sizes` | Disk monitoring |

## Upgrading

```bash
cd /opt/playwright-agent
git pull origin main
make upgrade    # Backup -> rebuild -> migrate -> restart -> verify
```

Rollback if needed:

```bash
make db-downgrade
git checkout <previous-commit>
make prod-build && make prod-up
```

## Verification

Confirm the full deployment:

1. `make health-check` passes all endpoints
2. Dashboard login works with admin credentials
3. Test execution completes with VNC showing browser activity
4. `make backup-full` creates a backup visible in MinIO console (port 9001)
5. Health monitoring cron is active: `crontab -l | grep health-monitor`

## Related Guides

- [Deployment](./deployment.md) -- all deployment modes (local, Docker, Swarm, K8s)
- [Disaster Recovery](./disaster-recovery.md) -- recovery procedures
- [Authentication](./authentication.md) -- user and role management
- [Troubleshooting](./troubleshooting.md) -- common production issues
