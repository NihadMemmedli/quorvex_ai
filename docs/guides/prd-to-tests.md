# How to Generate Tests from a PRD

Convert a PDF Product Requirements Document into test specifications and production-ready Playwright tests automatically.

## Prerequisites

- Quorvex AI installed and running (`make dev` or `make prod-dev`)
- A PDF PRD document describing product features
- AI credentials configured in `.env`
- Optional: a live target URL for the application described in the PRD

## Step 1: Prepare the PRD Document

The system accepts PDF files containing product requirements. For best results, your PRD should include:

- Feature descriptions with acceptance criteria
- User stories or use cases
- Screen flows or navigation descriptions
- A target URL (if the application already exists)

!!! tip
    The AI extracts features from the PRD automatically. Clearly named sections and numbered requirements produce better test specs.

## Step 2: Process the PRD via CLI

```bash
# Process entire PRD -- generates tests for all discovered features
python orchestrator/cli.py requirements.pdf --prd

# Process a specific feature only
python orchestrator/cli.py requirements.pdf --prd --feature "User Login"
```

The PRD pipeline:

1. **PDF Extraction** -- parses the PDF, identifies features, and stores content chunks in the vector store (ChromaDB) for RAG retrieval
2. **Spec Generation** -- for each feature, the Planner retrieves relevant PRD context and generates a test spec
3. **Test Generation** -- each spec runs through the native generator (with live browser exploration if a URL is present)
4. **Healing** -- if tests fail, the native healer fixes them (up to 3 attempts)

## Step 3: Process the PRD via Dashboard

1. Navigate to **PRD** in the dashboard (`/prd`)
2. Click **Upload PRD**
3. Select your PDF file
4. The system parses the document and displays extracted features
5. Select which features to generate tests for (or select all)
6. Click **Generate Tests**
7. Monitor progress on the **Runs** page

## Step 4: Review Generated Specs

PRD processing generates multi-test spec files in `specs/`. Each file may contain multiple test cases (TC-001, TC-002, etc.).

View the generated specs:

```bash
ls specs/prd-*.md
```

Or browse them in the **Specs** page of the dashboard.

## Step 5: Split Multi-Test Specs (Optional)

If a generated spec contains multiple test cases and you want individual files:

```bash
python orchestrator/cli.py specs/prd-user-login.md --split
```

This creates separate files for each test case in the spec.

## Step 6: Run Generated Tests

Run all generated tests:

```bash
npx playwright test tests/generated/
```

Or run a specific generated test:

```bash
npx playwright test tests/generated/prd-user-login.spec.ts
```

## Step 7: Iterate on Failed Tests

If some tests fail after generation:

1. Review the failure output in the run artifacts (`runs/<timestamp>/`)
2. Edit the spec to clarify ambiguous steps
3. Re-run with hybrid healing for more healing attempts:
   ```bash
   python orchestrator/cli.py specs/prd-user-login.md --hybrid
   ```

!!! warning
    PRD-generated specs may need manual refinement if the PRD description is vague or the target application differs from the PRD. Review and edit specs before relying on them for regression testing.

## Verification

Confirm the PRD pipeline completed:

1. Generated specs exist in `specs/` with feature-related names
2. Generated test files exist in `tests/generated/`
3. Run artifacts in `runs/<timestamp>/` show `status: passed`
4. Running the tests directly passes:
   ```bash
   npx playwright test tests/generated/prd-*.spec.ts
   ```

## Related Guides

- [Writing Specs](./writing-specs.md) -- refine generated specs manually
- [Pipeline Modes](./pipeline-modes.md) -- understand the native pipeline
- [Regression Batches](./regression-batches.md) -- batch-run PRD-generated tests
- [Exploration and Requirements](./exploration-requirements.md) -- alternative discovery approach
