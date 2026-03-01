# How to Recover from System Failures

Step-by-step recovery procedures for database loss, credential recovery, MinIO failures, and full system rebuilds.

## Prerequisites

- Access to the server or new infrastructure
- `.env.prod` file (or knowledge of the `JWT_SECRET_KEY`)
- Docker and Docker Compose installed
- Backup timestamp to restore from (if restoring data)

## Scenario 1: Full System Recovery

Use when recovering to a new server or after complete data loss.

### Step 1: Prepare Infrastructure

```bash
# Clone repository
git clone https://gitlab.example.com/qa/playwright-agent.git /opt/playwright-agent
cd /opt/playwright-agent

# Restore .env.prod from secure backup
cp /secure-backup/.env.prod .env.prod
# OR recreate from template
cp .env.prod.example .env.prod
# Edit with your values
```

### Step 2: Start Core Services

```bash
# Start database and MinIO first
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d db minio

# Wait for services to be healthy
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
```

### Step 3: Restore from Backup

```bash
# List available local backups
make restore-list

# Restore from local backup
make restore TS=20260115_143022

# Or restore from MinIO
make restore-from-minio TS=20260115_143022
```

### Step 4: Apply Migrations

```bash
make db-upgrade
```

### Step 5: Start Application

```bash
make prod-up
make health-check
```

## Scenario 2: Database Recovery Only

Use when the database is corrupted but files are intact.

### Step 1: Stop the Backend

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml stop backend frontend
```

### Step 2: Restore Database

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml run --rm --profile restore restore bash -c "
  apk add --no-cache postgresql15-client
  export PGPASSWORD=\$POSTGRES_PASSWORD
  gunzip -c /backups/20260115_143022_db.sql.gz | psql -h db -U playwright -d playwright_agent
"
```

### Step 3: Restart Services

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d backend frontend
make health-check
```

## Scenario 3: MinIO Storage Recovery

Use when MinIO data is lost but local backups exist.

```bash
# Stop MinIO
docker compose --env-file .env.prod -f docker-compose.prod.yml stop minio

# Remove corrupted volume
docker volume rm playwright-agent_minio_data

# Restart MinIO (fresh volume)
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d minio

# Re-populate MinIO with a fresh backup
make backup-full
```

## Scenario 4: Lost JWT_SECRET_KEY

!!! danger
    All encrypted credentials (TestRail API keys, Jira tokens, dashboard-stored passwords) are **unrecoverable** without the original `JWT_SECRET_KEY`.

### Step 1: Generate a New Key

```bash
openssl rand -hex 32
```

### Step 2: Update Configuration

Update `JWT_SECRET_KEY` in `.env.prod` with the new value.

### Step 3: Restart and Re-enter Credentials

```bash
make prod-restart
```

Users must re-enter all stored credentials through the dashboard Settings page.

### Step 4: Prevent Future Loss

Back up `.env.prod` to a password manager or secure vault immediately.

## Scenario 5: Lost Database Password

```bash
# Reset PostgreSQL password
docker compose --env-file .env.prod -f docker-compose.prod.yml exec db \
  psql -U postgres -c "ALTER USER playwright WITH PASSWORD 'new-password';"

# Update .env.prod with new password
# Restart
make prod-restart
```

## Scenario 6: Schema-Only Recovery

Use when you have a fresh database but no data backup. Alembic migrations recreate the schema from scratch.

```bash
# Stop backend
docker compose --env-file .env.prod -f docker-compose.prod.yml stop backend

# Apply all migrations
make db-upgrade

# Restart
docker compose --env-file .env.prod -f docker-compose.prod.yml start backend

# Create admin user (no users exist after schema-only recovery)
docker compose --env-file .env.prod -f docker-compose.prod.yml exec backend \
  python orchestrator/scripts/create_admin.py \
  --email admin@yourcompany.com \
  --password YourSecurePassword
```

!!! note
    Schema-only recovery restores the table structure, not data. Use Scenario 1 or 2 to restore data from a backup.

## Post-Recovery Verification

After any recovery, verify these items:

### 1. Service Health

```bash
make health-check
curl http://localhost:8001/health
curl http://localhost:8001/health/storage
```

### 2. User Authentication

```bash
curl -X POST http://localhost:8001/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"your-password"}'
# Should return JWT token, not error
```

### 3. Credential Decryption

1. Log in to the dashboard
2. Navigate to Settings > Credentials
3. Verify stored credentials are readable (not error)

### 4. Data Integrity

```bash
curl http://localhost:8001/health/storage | python3 -m json.tool
ls -la specs/
ls -la tests/
```

### 5. Run a Test

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec backend \
  python orchestrator/cli.py specs/example-test.md
```

## Preventive Measures

1. **Back up `.env.prod` separately** -- store in password manager
2. **Monitor backup age** -- alert if backup is older than 48 hours
3. **Test restores regularly** -- monthly restore to a test environment
4. **Keep backup-scheduler running** -- daily automated backups at 2 AM

## Critical Information Reference

| Secret | Purpose | Recovery |
|--------|---------|----------|
| `.env.prod` | All secrets | Must be backed up separately |
| `JWT_SECRET_KEY` | Decrypts credentials | Without it, credentials are unrecoverable |
| `POSTGRES_PASSWORD` | Database access | Can be reset with server access |
| `MINIO_ROOT_PASSWORD` | MinIO access | Can be reset with server access |

## Verification

Confirm recovery is complete:

1. `make health-check` passes all endpoints
2. Login and token refresh work
3. Encrypted credentials are decryptable
4. Test execution completes
5. Backup service is running and creating new backups

## Related Guides

- [Company Deployment](./company-deployment.md) -- initial deployment setup
- [Deployment](./deployment.md) -- all deployment modes
- [Troubleshooting](./troubleshooting.md) -- diagnose issues before recovery
- [Credential Management](./credential-management.md) -- re-enter credentials after key loss
