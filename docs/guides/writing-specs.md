# How to Write Test Specifications

Write plain-English markdown specs that Quorvex AI converts into production-ready Playwright tests.

## Prerequisites

- Quorvex AI installed (`make setup` completed)
- A target web application with a URL to test
- Basic familiarity with the spec format (title + steps + URL)

## Step 1: Create a Minimal Spec

Every spec needs a title and steps with at least one URL. Create a markdown file in `specs/`:

```markdown
# Test: Verify Homepage Loads

1. Navigate to https://example.com
2. Verify the page title contains "Example"
```

This is the simplest valid spec. The system extracts the URL automatically and uses it as the test target.

## Step 2: Add Structure for Complex Tests

For tests with multiple assertions, use the full format with description and expected outcomes:

```markdown
# Test: User Login with Valid Credentials

ID: TC001
Expected Result: User should be logged in

## Description
Verify that a registered user can log in with correct email and password
and is redirected to the dashboard.

## Steps
1. Navigate to https://app.example.com/login
2. Enter "user@example.com" into the email field
3. Enter "{{LOGIN_PASSWORD}}" into the password field
4. Click the "Sign In" button
5. Wait for the dashboard page to load

## Expected Outcome
- User is redirected to the dashboard
- Welcome message displays the user's name
- Navigation menu shows "Logout" option
```

### Section Reference

| Section | Required | Purpose |
|---------|----------|---------|
| `# Test: ...` or `# Title` | Yes | Names the test. The `# ` heading is used as the test name. |
| `ID: ...` | No | Optional test case identifier (e.g., `TC001`). |
| `## Description` | No | Free-text explanation of what the test covers. |
| `## Steps` | Yes | Numbered list of actions the test performs. |
| `## Expected Outcome` / `## Expected Result` | No | Bullet list of assertions to verify. |

## Step 3: Write Effective Steps

Steps are numbered actions that the AI translates into Playwright code. Write them as if telling a person how to use the application.

### Supported Actions

**Navigation**
```
1. Navigate to https://app.example.com
2. Go to https://app.example.com/settings
```

**Clicking**
```
1. Click the "Submit" button
2. Click on "Sign In"
3. Click the navigation menu item "Settings"
```

**Typing and Form Input**
```
1. Enter "john@example.com" into the email field
2. Type "Hello World" into the search box
3. Enter "{{LOGIN_PASSWORD}}" into the password field
```

**Selecting Options**
```
1. Select "United States" from the country dropdown
2. Check the "I agree to terms" checkbox
3. Select the "Monthly" radio button
```

**Waiting**
```
1. Wait for "Success" to be visible
2. Wait for the loading spinner to disappear
3. Wait for the page to finish loading
```

**Assertions**
```
1. Verify the page title contains "Dashboard"
2. Verify the success message appears
3. Detailed assertion of text "Hello World!"
4. Verify the URL contains "/dashboard"
```

**Visual Regression**
```
1. Take a screenshot for visual comparison
2. Verify the page matches the baseline screenshot
```

Visual regression steps use Playwright's `toHaveScreenshot()` API. The first run captures a baseline image; subsequent runs compare against it.

!!! tip
    - Be specific about targets. "Click the Submit button" is better than "Click the button" when there are multiple buttons.
    - Include the URL. Every spec must contain at least one URL, typically in the first step.
    - Use quoted strings. Wrap text values in double quotes: `Enter "value" into the field`.
    - One action per step. Instead of "Fill in the form and submit", write separate steps for each field and the submit click.

## Step 4: Use Credential Placeholders

Never hardcode passwords or secrets in spec files. Use `{{VARIABLE_NAME}}` placeholders that reference environment variables.

1. Define the secret in your `.env` file:

```bash
LOGIN_EMAIL=admin@example.com
LOGIN_PASSWORD=S3cretP@ss
```

2. Reference it in your spec with double curly braces:

```markdown
## Steps
1. Navigate to https://app.example.com/login
2. Enter "{{LOGIN_EMAIL}}" into the email field
3. Enter "{{LOGIN_PASSWORD}}" into the password field
4. Click "Sign In"
```

3. The generated Playwright code uses `process.env.LOGIN_PASSWORD` -- the actual value is never written into test files.

When using the dashboard, credentials can also be configured per-project in **Settings > Credentials** without touching `.env` files.

## Step 5: Reuse Common Flows with Templates

Templates let you share login or setup flows across multiple specs using the `@include` directive.

Create a template in `specs/templates/`:

```markdown title="specs/templates/myapp_login.md"
# Template: MyApp Login

## Steps
1. Navigate to https://pre.myapp.example.com
2. Click on the Sign In button
3. Enter email: {{APP_LOGIN_EMAIL}}
4. Click Next button
5. Enter password: {{APP_LOGIN_PASSWORD}}
6. Click Log In
```

Reference it in any spec:

```markdown
## Steps
1. @include "templates/myapp_login.md"
2. Click to the CRM from the menu
3. Click the Create Contact button
```

The pipeline resolves `@include` directives before processing. Path resolution tries:

1. Relative to the spec file's directory
2. From the project root
3. From the `specs/` directory
4. From `specs/templates/` using just the filename

!!! note
    Templates support credential placeholders (`{{VAR}}`), can include other templates (nested resolution), and selectors discovered during previous template runs are stored in the memory system as hints for future generation.

## Step 6: Organize Your Specs

Organize specs into folders by project or feature area:

```
specs/
  templates/             # Reusable login/setup flows
    myapp_login.md
    mygov-login.md
  myapp/              # Project-specific specs
    crm.md
    new-inventory-insert.md
  smoke_healing.md       # Standalone specs
  test_login_1.md
```

Naming conventions:

- `test_login.md` -- single test case
- `smoke_healing.md` -- smoke/sanity checks
- `crm.md` -- feature-area name

## Step 7: Run the Spec

**Via CLI:**

```bash
# Default (Pipeline -- recommended)
python orchestrator/cli.py specs/my-test.md

# With hybrid healing for complex tests
python orchestrator/cli.py specs/my-test.md --hybrid
```

**Via Web Dashboard:**

1. Navigate to the **Specs** page.
2. Click the play button next to any spec.
3. Monitor progress on the **Runs** page.

## Verification

Confirm your spec works by checking:

1. The CLI completes without errors and reports `status: passed`
2. A generated test file appears in `tests/generated/`
3. Running the generated test directly passes:
   ```bash
   npx playwright test tests/generated/your-test.spec.ts
   ```

## Related Guides

- [Pipeline Modes](./pipeline-modes.md) -- choose the right pipeline for your test
- [Credential Management](./credential-management.md) -- secure credential storage and rotation
- [Getting Started](../tutorials/getting-started.md) -- initial project setup
- [Troubleshooting](./troubleshooting.md) -- common issues and solutions
