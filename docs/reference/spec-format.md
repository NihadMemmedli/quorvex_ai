# Spec Format

Markdown test specification syntax reference for Quorvex AI.

## File Structure

| Section | Required | Heading | Description |
|---------|----------|---------|-------------|
| Title | Yes | `# Test: ...` or `# <Title>` | Test name extracted from the H1 heading |
| ID | No | `ID: ...` (inline, no heading) | Optional test case identifier (e.g., `TC001`) |
| Expected Result | No | `Expected Result: ...` (inline, no heading) | Inline expected result (alternative to section) |
| Description | No | `## Description` | Free-text explanation of what the test covers |
| Steps | Yes | `## Steps` | Numbered list of actions |
| Expected Outcome | No | `## Expected Outcome` or `## Expected Result` or `## Expected Results` | Bullet list of assertions to verify |

## Title Formats

| Format | Example |
|--------|---------|
| Test prefix | `# Test: User Login with Valid Credentials` |
| Plain heading | `# Verify Homepage Loads` |
| Smoke prefix | `# Smoke Test: Self-Healing` |

## Step Syntax

Steps are numbered lines under the `## Steps` section (or directly after the title if no section heading is used).

### Navigation

| Syntax | Description |
|--------|-------------|
| `Navigate to <URL>` | Open URL in browser |
| `Go to <URL>` | Open URL in browser |
| `Open <URL>` | Open URL in browser |

A spec must contain at least one URL. The pipeline extracts the target URL automatically from the first navigation step.

### Click Actions

| Syntax | Description |
|--------|-------------|
| `Click the "<text>" button` | Click a button by visible text |
| `Click on "<text>"` | Click any element by visible text |
| `Click the navigation menu item "<text>"` | Click a nav menu item |

### Text Input

| Syntax | Description |
|--------|-------------|
| `Enter "<value>" into the <field> field` | Type text into a form field |
| `Type "<value>" into the <field>` | Type text into a form field |
| `Enter "{{VARIABLE}}" into the <field> field` | Type credential placeholder value |

### Selection

| Syntax | Description |
|--------|-------------|
| `Select "<option>" from the <name> dropdown` | Choose dropdown option |
| `Check the "<label>" checkbox` | Check a checkbox |
| `Select the "<label>" radio button` | Select a radio option |

### Waiting

| Syntax | Description |
|--------|-------------|
| `Wait for "<text>" to be visible` | Wait until text appears |
| `Wait for the <element> to disappear` | Wait until element is gone |
| `Wait for the page to finish loading` | Wait for load event |

### Assertions

| Syntax | Description |
|--------|-------------|
| `Verify the page title contains "<text>"` | Assert page title |
| `Verify the success message appears` | Assert element visibility |
| `Detailed assertion of text "<text>"` | Assert exact text content |
| `Verify the URL contains "<path>"` | Assert URL substring |

### Visual Regression

| Syntax | Description |
|--------|-------------|
| `Take a screenshot for visual comparison` | Capture screenshot with `toHaveScreenshot()` |
| `Verify the page matches the baseline screenshot` | Compare against baseline |

First run captures a baseline image. Subsequent runs compare against it using Playwright's `toHaveScreenshot()` API.

### Pipe-Separated Steps

Steps can be separated with the pipe character on a single line:

```
1. Navigate to login page|2. Enter credentials|3. Click submit
```

The multi-line numbered list format (one step per line) is the standard format.

## Credential Placeholders

| Syntax | Description |
|--------|-------------|
| `{{VARIABLE_NAME}}` | Replaced with `process.env.VARIABLE_NAME` in generated code |

### Setup

1. Define the variable in `.env`: `LOGIN_PASSWORD=SecretValue`
2. Reference in spec: `Enter "{{LOGIN_PASSWORD}}" into the password field`
3. Generated code uses: `process.env.LOGIN_PASSWORD`

### Common Variables

| Variable | Typical Use |
|----------|------------|
| `LOGIN_EMAIL` | Login email address |
| `LOGIN_USERNAME` | Login username |
| `LOGIN_PASSWORD` | Login password |

Dashboard credentials can also be configured per-project in Settings > Credentials.

## Template Includes

| Syntax | Description |
|--------|-------------|
| `@include "path/to/template.md"` | Inline-expand a template file |

### Path Resolution Order

1. Relative to the spec file's directory
2. From the project root
3. From the `specs/` directory
4. From `specs/templates/` using just the filename

### Template File Location

Templates are stored in `specs/templates/`.

### Template Features

| Feature | Description |
|---------|-------------|
| Credential placeholders | `{{VAR}}` syntax works in templates |
| Nested includes | Templates can include other templates (resolved recursively) |
| Selector reuse | Selectors from previous template runs are stored in memory and passed as hints |

## File Naming

| Convention | Example |
|------------|---------|
| Single test case | `test_login.md` |
| Smoke/sanity check | `smoke_healing.md` |
| Feature area | `crm.md` |

File extension: `.md`

## Folder Structure

```
specs/
  templates/             # Reusable login/setup flows
    myapp_login.md
  myapp/              # Project-specific specs
    crm.md
  smoke_healing.md       # Standalone specs
```

## PRD-Generated Specs

PRD processing generates specs with multiple test cases (TC-001, TC-002, etc.) in a single file. Split into individual files with:

```bash
python orchestrator/cli.py specs/prd-feature.md --split
```

## Related

- [CLI Reference](cli.md)
- [Pipeline Modes](pipeline-modes.md)
