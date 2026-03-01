# How to Explore an App and Generate Requirements

Use AI-powered exploration to discover application flows, generate structured requirements, and create a Requirements Traceability Matrix (RTM) for test coverage analysis.

## Prerequisites

- Quorvex AI installed and running (`make dev` or `make prod-dev`)
- A target web application with a URL accessible from the server
- AI credentials configured in `.env`
- For authenticated exploration: login credentials stored in `.env`

## Step 1: Start an Exploration Session

### Via CLI

```bash
# Basic exploration with default settings
python orchestrator/cli.py --explore https://app.example.com

# Customize exploration depth and strategy
python orchestrator/cli.py --explore https://app.example.com \
  --strategy breadth_first \
  --max-interactions 100 \
  --timeout 60
```

### Via Dashboard

1. Navigate to **Exploration** in the dashboard (`/exploration`)
2. Click **New Exploration**
3. Enter the target URL
4. Select a strategy (`goal_directed`, `breadth_first`, or `depth_first`)
5. Configure max interactions (default: 50)
6. Click **Start**

### Via API

```bash
curl -X POST http://localhost:8001/exploration/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://app.example.com",
    "strategy": "goal_directed",
    "max_interactions": 50,
    "project_id": "your-project-id"
  }'
```

!!! tip
    Start with `goal_directed` strategy (default) for meaningful user flows. Switch to `breadth_first` if you want maximum page coverage.

## Step 2: Explore with Authentication

For applications that require login, set credentials in `.env` and provide the login URL:

```bash
# Set credentials
export LOGIN_EMAIL=user@example.com
export LOGIN_PASSWORD=secret

# Explore with authentication
python orchestrator/cli.py --explore https://app.example.com \
  --login-url https://app.example.com/login
```

The AI agent performs the login flow before starting exploration.

## Step 3: Review Discovered Flows

After exploration completes, review what the AI discovered:

### Via CLI

```bash
python orchestrator/cli.py --exploration-results SESSION_ID
```

### Via Dashboard

1. Navigate to **Exploration** in the dashboard
2. Click on the completed session
3. Review the discovered items:
   - **Pages** -- URLs and page titles discovered
   - **User Flows** -- Multi-step interactions (login, form submission, navigation paths)
   - **API Endpoints** -- HTTP requests captured during exploration
   - **Form Behaviors** -- Input fields, validation, and submission results
   - **Error States** -- Error pages or error messages encountered

### Via API

```bash
# Get session details with discovered flows
curl http://localhost:8001/exploration/sessions/SESSION_ID

# List all sessions for a project
curl http://localhost:8001/exploration/sessions?project_id=your-project-id
```

## Step 4: Generate Requirements from Exploration

Convert exploration discoveries into structured requirements:

### Via CLI

```bash
python orchestrator/cli.py --generate-requirements --from-exploration SESSION_ID
```

### Via Dashboard

1. Navigate to **Requirements** (`/requirements`)
2. Click **Generate from Exploration**
3. Select the exploration session
4. Review and edit the generated requirements

### Via API

```bash
curl -X POST http://localhost:8001/requirements/generate \
  -H "Content-Type: application/json" \
  -d '{
    "exploration_session_id": "SESSION_ID",
    "project_id": "your-project-id"
  }'
```

The AI analyzes discovered flows, API endpoints, and user interactions to produce requirements with:

- **Title** -- concise description of the requirement
- **Category** -- functional, non-functional, security, performance, etc.
- **Priority** -- high, medium, low
- **Acceptance criteria** -- specific conditions that must be met
- **Requirement code** -- auto-generated (e.g., `REQ-001`, `REQ-002`)

## Step 5: Edit and Organize Requirements

Refine the AI-generated requirements through the dashboard or API:

```bash
# List requirements
curl http://localhost:8001/requirements?project_id=your-project-id

# Update a requirement
curl -X PUT http://localhost:8001/requirements/REQ_ID \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Updated title",
    "priority": "high",
    "acceptance_criteria": "Updated criteria"
  }'

# Create a manual requirement
curl -X POST http://localhost:8001/requirements \
  -H "Content-Type: application/json" \
  -d '{
    "title": "User can reset password via email",
    "category": "functional",
    "priority": "high",
    "acceptance_criteria": "Password reset email sent within 30 seconds",
    "project_id": "your-project-id"
  }'
```

## Step 6: Create a Requirements Traceability Matrix (RTM)

Map requirements to test specs with coverage analysis:

### Via CLI

```bash
# Generate RTM
python orchestrator/cli.py --generate-rtm --project-id my-project

# Export RTM
python orchestrator/cli.py --rtm-export markdown --output rtm.md
python orchestrator/cli.py --rtm-export csv --output rtm.csv
```

### Via Dashboard

1. Navigate to **RTM** (`/rtm`)
2. Click **Generate RTM**
3. Review the traceability matrix showing requirements mapped to test specs
4. Use the coverage analysis to identify gaps

### Via API

```bash
# Generate RTM
curl -X POST http://localhost:8001/rtm/generate \
  -H "Content-Type: application/json" \
  -d '{"project_id": "your-project-id"}'

# Query RTM
curl http://localhost:8001/rtm?project_id=your-project-id

# Export RTM
curl "http://localhost:8001/rtm/export?project_id=your-project-id&format=csv" -o rtm.csv
curl "http://localhost:8001/rtm/export?project_id=your-project-id&format=json" -o rtm.json
```

The RTM maps each requirement to test specs with:

- **Coverage status** -- covered, partial, uncovered, suggested
- **Confidence score** -- how well the test spec matches the requirement
- **Gap analysis** -- AI-identified untested requirements with suggested test specs

## Step 7: Act on Coverage Gaps

Use the RTM gap analysis to improve test coverage:

1. Review **uncovered** requirements in the RTM
2. The AI suggests test specs for each gap
3. Write new specs based on the suggestions (see [Writing Specs](./writing-specs.md))
4. Run the specs through the pipeline
5. Regenerate the RTM to confirm coverage improvement

!!! warning
    Exploration discovers what the AI can find through browser interaction. Pages behind complex authentication, CAPTCHAs, or feature flags may not be discovered. Add manual requirements for known features the exploration missed.

## Exploration Strategies Reference

| Strategy | Behavior | Best For |
|----------|----------|----------|
| `goal_directed` | Prioritizes meaningful user flows | Most applications |
| `breadth_first` | Visits many pages before going deep | Large sites with many pages |
| `depth_first` | Follows each flow to completion | Deep multi-step workflows |

## Verification

Confirm the end-to-end pipeline worked:

1. Exploration session shows status `completed` with discovered flows
2. Requirements list is populated with auto-generated codes (REQ-001, etc.)
3. RTM shows coverage percentages and identifies gaps
4. Exported RTM file (CSV/JSON) contains the expected mappings

## Related Guides

- [Writing Specs](./writing-specs.md) -- create specs to fill coverage gaps
- [Pipeline Modes](./pipeline-modes.md) -- run specs through the test generation pipeline
- [Regression Batches](./regression-batches.md) -- batch-run generated tests
- [Scheduling](./scheduling.md) -- automate test execution on a schedule
