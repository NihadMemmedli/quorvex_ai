# How to Set Up Authentication and User Management

Enable authentication, create users, assign project roles, and configure role-based access control for your Quorvex AI instance.

## Prerequisites

- Quorvex AI installed and running (`make dev` or `make prod-dev`)
- `JWT_SECRET_KEY` set in `.env` or `.env.prod` (required for token signing)
- Admin access to the server or `.env` configuration

## Step 1: Enable Authentication

By default, authentication is disabled for local development. Enable it by setting environment variables:

```bash title=".env.prod"
# Enable authentication enforcement
REQUIRE_AUTH=true

# Control user self-registration
ALLOW_REGISTRATION=false

# Generate a secure JWT secret
JWT_SECRET_KEY=$(openssl rand -hex 32)
```

Restart the backend after changing these values:

```bash
make prod-restart
```

!!! note
    With `REQUIRE_AUTH=false` (default), all API endpoints are accessible without authentication. Set to `true` for any deployment shared with multiple users.

## Step 2: Create the Initial Admin User

### Option A: Environment Variable (First Startup)

Set admin credentials before the first startup:

```bash title=".env.prod"
INITIAL_ADMIN_EMAIL=admin@yourcompany.com
INITIAL_ADMIN_PASSWORD=your-secure-password
```

The admin user is created automatically on first startup only. Remove these variables after the initial deployment.

### Option B: Registration Endpoint

Temporarily enable registration:

```bash
ALLOW_REGISTRATION=true
```

Register via the dashboard login page or API:

```bash
curl -X POST http://localhost:8001/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@yourcompany.com",
    "password": "your-secure-password",
    "full_name": "Admin User"
  }'
```

Then disable registration:

```bash
ALLOW_REGISTRATION=false
```

### Option C: Direct Database Script

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec backend \
  python orchestrator/scripts/create_admin.py \
  --email admin@yourcompany.com \
  --password your-secure-password
```

## Step 3: Log In and Get Tokens

### Via Dashboard

1. Open the dashboard at `http://localhost:3000`
2. Enter your email and password on the login page
3. The dashboard stores the JWT token automatically

### Via API

```bash
# Login
curl -X POST http://localhost:8001/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@yourcompany.com",
    "password": "your-secure-password"
  }'
```

Response:

```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer"
}
```

Use the access token in subsequent requests:

```bash
curl http://localhost:8001/projects \
  -H "Authorization: Bearer ACCESS_TOKEN"
```

## Step 4: Manage Users (Superuser Only)

Superusers can manage all users via the admin panel:

### Via Dashboard

1. Navigate to **Admin > Users** (`/admin/users`)
2. View all registered users
3. Toggle active/inactive status
4. Promote users to superuser

### Via API

```bash
# List all users
curl http://localhost:8001/admin/users \
  -H "Authorization: Bearer ADMIN_TOKEN"

# Update user
curl -X PUT http://localhost:8001/admin/users/USER_ID \
  -H "Authorization: Bearer ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "is_active": true,
    "is_superuser": false
  }'
```

## Step 5: Assign Project Roles

Users are assigned to projects with specific roles:

| Role | Permissions |
|------|------------|
| `owner` | Full access, can delete project, manage members |
| `admin` | Full access, can manage members |
| `member` | Run tests, create specs, view results |
| `viewer` | Read-only access to all project data |

### Via Dashboard

1. Navigate to **Projects** (`/projects`)
2. Click on a project
3. Open the **Members** tab
4. Click **Add Member**
5. Select a user and assign a role

### Via API

```bash
# Add a member to a project
curl -X POST http://localhost:8001/projects/PROJECT_ID/members \
  -H "Authorization: Bearer ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "USER_ID",
    "role": "member"
  }'
```

## Step 6: Refresh Expired Tokens

Access tokens expire after 15 minutes. Use the refresh token to get a new one:

```bash
curl -X POST http://localhost:8001/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "REFRESH_TOKEN"
  }'
```

!!! note
    Refresh tokens are single-use and rotated on each refresh. The old refresh token is invalidated immediately. Refresh tokens expire after 7 days, requiring a full re-login.

## Step 7: Handle Account Lockouts

After 5 consecutive failed login attempts, an account is locked for 15 minutes.

**Wait for automatic unlock** (15 minutes), or manually unlock:

```bash
# PostgreSQL
docker compose --env-file .env.prod -f docker-compose.prod.yml exec db \
  psql -U playwright -d playwright_agent \
  -c "UPDATE users SET failed_login_attempts=0, locked_until=NULL WHERE email='user@example.com';"
```

## Security Features Summary

| Feature | Default | Description |
|---------|---------|-------------|
| Password hashing | bcrypt | Secure defaults |
| Access token lifetime | 15 minutes | Short-lived for security |
| Refresh token lifetime | 7 days | Single-use with rotation |
| Account lockout | 5 attempts | Automatic lockout after failed logins |
| Rate limiting | Enabled | Login/register endpoints protected |
| Token rotation | Enabled | Refresh tokens are single-use |

## Verification

Confirm authentication is working:

1. With `REQUIRE_AUTH=true`, unauthenticated API requests return 401
2. Login returns valid access and refresh tokens
3. Protected endpoints accept the access token
4. Token refresh returns new tokens and invalidates the old refresh token
5. After 5 failed logins, the account is locked (HTTP 423)
6. Project members can only access their assigned projects

## Related Guides

- [Credential Management](./credential-management.md) -- manage test secrets
- [Company Deployment](./company-deployment.md) -- production security settings
- [Disaster Recovery](./disaster-recovery.md) -- recover from JWT_SECRET_KEY loss
- [Troubleshooting](./troubleshooting.md) -- auth-related issues
