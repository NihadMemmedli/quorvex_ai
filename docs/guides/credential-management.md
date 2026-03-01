# How to Manage Test Credentials Securely

Store, use, and rotate test credentials without exposing secrets in spec files or generated test code.

## Prerequisites

- Quorvex AI installed and running (`make dev` or `make prod-dev`)
- Access to the `.env` file (CLI mode) or the dashboard Settings page (web mode)
- `JWT_SECRET_KEY` set in `.env` (required for credential encryption)

## Step 1: Store Credentials in Environment Variables

For CLI usage, add secrets to your `.env` file:

```bash title=".env"
# Application credentials
LOGIN_EMAIL=admin@example.com
LOGIN_PASSWORD=S3cretP@ss

# API keys
API_TOKEN=bearer-token-value
API_KEY=your-api-key

# App-specific credentials
APP_LOGIN_EMAIL=user@myapp.example.com
APP_LOGIN_PASSWORD=travelpass123
```

!!! danger
    Never commit `.env` files to version control. The `.gitignore` already excludes `.env` and `.env.prod`.

## Step 2: Reference Credentials in Specs

Use `{{VARIABLE_NAME}}` placeholders in your markdown specs:

```markdown
## Steps
1. Navigate to https://app.example.com/login
2. Enter "{{LOGIN_EMAIL}}" into the email field
3. Enter "{{LOGIN_PASSWORD}}" into the password field
4. Click the "Sign In" button
```

The pipeline replaces `{{LOGIN_PASSWORD}}` with a reference to `process.env.LOGIN_PASSWORD` in the generated Playwright code. The actual secret value is never written to test files.

## Step 3: Store Credentials via the Dashboard

For web dashboard usage, store credentials per-project without touching `.env` files:

### Via Dashboard

1. Navigate to **Settings** (`/settings`)
2. Open the **Credentials** tab
3. Click **Add Credential**
4. Enter:
   - **Key** -- the variable name (e.g., `LOGIN_PASSWORD`)
   - **Value** -- the secret value
5. Click **Save**

### Via API

```bash
# Store a credential
curl -X POST http://localhost:8001/credentials \
  -H "Content-Type: application/json" \
  -d '{
    "key": "LOGIN_PASSWORD",
    "value": "S3cretP@ss",
    "project_id": "your-project-id"
  }'

# List credentials (values are masked)
curl http://localhost:8001/credentials?project_id=your-project-id
```

Credentials stored via the dashboard are encrypted at rest using Fernet symmetric encryption derived from `JWT_SECRET_KEY`.

## Step 4: Use Credentials in Generated Tests

When you run a spec with credential placeholders:

1. The pipeline resolves `{{VARIABLE_NAME}}` during planning
2. Generated Playwright code references `process.env.VARIABLE_NAME`
3. At test runtime, Playwright reads from the process environment

Example generated code:

```typescript title="tests/generated/login-test.spec.ts"
test('User Login', async ({ page }) => {
  await page.goto('https://app.example.com/login');
  await page.getByLabel('Email').fill(process.env.LOGIN_EMAIL!);
  await page.getByLabel('Password').fill(process.env.LOGIN_PASSWORD!);
  await page.getByRole('button', { name: 'Sign In' }).click();
});
```

## Step 5: Rotate Credentials

When a password or API key changes:

### For `.env` credentials

1. Update the value in `.env`:
   ```bash
   LOGIN_PASSWORD=NewS3cretP@ss
   ```
2. Restart the backend if running:
   ```bash
   make prod-restart
   ```
3. Re-run affected tests -- no spec or code changes needed

### For dashboard credentials

1. Navigate to **Settings > Credentials**
2. Click **Edit** on the credential
3. Enter the new value
4. Click **Save**

No spec or generated code changes are required. The new value is used on the next test run.

## Step 6: Manage Integration Credentials

Integration API keys (TestRail, Jira, etc.) are also encrypted at rest:

- Stored in the project settings (`Project.settings["integrations"]`)
- Encrypted with the same `JWT_SECRET_KEY`
- Managed through the Settings page or integration-specific API endpoints

!!! warning
    If `JWT_SECRET_KEY` is lost, all encrypted credentials become **unrecoverable**. Back up `.env.prod` to a password manager immediately after deployment. See [Disaster Recovery](./disaster-recovery.md) for recovery procedures.

## Common Credential Variables

| Variable | Typical Use |
|----------|------------|
| `LOGIN_EMAIL` / `LOGIN_USERNAME` | Login email or username |
| `LOGIN_PASSWORD` | Login password |
| `API_TOKEN` | Bearer token for API testing |
| `API_KEY` | API key for service authentication |
| `APP_LOGIN_EMAIL` / `APP_LOGIN_PASSWORD` | App-specific credentials |

## Verification

Confirm credentials work:

1. Run a spec with credential placeholders:
   ```bash
   python orchestrator/cli.py specs/login-test.md
   ```
2. The generated test should log in successfully without hardcoded secrets
3. Check the generated code in `tests/generated/` -- no secret values should appear
4. Dashboard credentials should display masked values (not plaintext)

## Related Guides

- [Writing Specs](./writing-specs.md) -- use `{{VAR}}` placeholders in specs
- [Authentication](./authentication.md) -- manage Quorvex AI user accounts
- [Disaster Recovery](./disaster-recovery.md) -- recover from lost JWT_SECRET_KEY
- [Company Deployment](./company-deployment.md) -- production credential management
