# How to Evaluate LLM Providers

Full LLM evaluation platform for testing AI providers against structured test suites, comparing models, iterating on prompts, and tracking performance over time.

## Overview

The LLM testing framework provides:

- **Provider management** -- register any OpenAI-compatible API with encrypted credentials and custom pricing
- **Test specs** -- markdown-based test suites with system prompts, test cases, and assertions
- **Datasets** -- reusable test case collections with versioning, CSV import/export, and golden marking
- **Run & Compare** -- execute suites against providers, compare models side-by-side with scoring
- **Prompt iterations** -- A/B test system prompt changes with automated scoring against baselines
- **AI suite generation** -- generate test suites from system prompt + app description
- **Dataset augmentation** -- AI-powered generation of edge cases, adversarial inputs, and boundary tests
- **Scheduling** -- cron-based automated runs with execution history
- **Analytics** -- trends, latency, cost tracking, regression detection, golden dashboard

## Prerequisites

- Quorvex AI installed and running (`make dev` or `make prod-dev`)
- At least one LLM provider API key (OpenAI, Anthropic, or any OpenAI-compatible API)

## Step-by-Step Usage

### 1. Register a Provider

Navigate to **LLM Testing > Providers** in the dashboard, or use the API:

```bash
curl -X POST http://localhost:8001/llm-testing/providers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "OpenAI GPT-4o",
    "provider_type": "openai",
    "api_key": "sk-...",
    "base_url": "https://api.openai.com/v1",
    "model_id": "gpt-4o",
    "input_cost_per_1k": 0.005,
    "output_cost_per_1k": 0.015,
    "project_id": "your-project-id"
  }'
```

The API key is encrypted at rest. You can register multiple providers to compare.

### 2. Create a Test Spec

Write a markdown test suite:

```markdown
# LLM Test: Customer Support Bot

## System Prompt
You are a helpful customer support assistant for an e-commerce platform.
Always be polite, concise, and suggest relevant products when appropriate.

## Test Cases

### Greeting
- Input: "Hello!"
- Expected: Response should be a friendly greeting
- Assertions:
  - Contains a greeting word (hello, hi, hey, welcome)
  - Length < 200 characters

### Order Status
- Input: "Where is my order #12345?"
- Expected: Should acknowledge the order number and offer to help
- Assertions:
  - Mentions order number "12345"
  - Offers to look up the status

### Refund Request
- Input: "I want a refund for my broken laptop"
- Expected: Should empathize and explain the refund process
- Assertions:
  - Shows empathy
  - Mentions refund policy or process

### Off-Topic
- Input: "What's the meaning of life?"
- Expected: Should politely redirect to support topics
- Assertions:
  - Does not provide a philosophical answer
  - Redirects to e-commerce support
```

Save via the dashboard or API:

```bash
curl -X POST http://localhost:8001/llm-testing/specs \
  -H "Content-Type: application/json" \
  -d '{
    "name": "customer-support-bot",
    "content": "# LLM Test: Customer Support Bot\n...",
    "project_id": "your-project-id"
  }'
```

### 3. Run a Test Suite

Execute the suite against a provider:

```bash
curl -X POST http://localhost:8001/llm-testing/run \
  -H "Content-Type: application/json" \
  -d '{
    "spec_name": "customer-support-bot",
    "provider_id": "PROVIDER_ID",
    "project_id": "your-project-id"
  }'
```

The system sends each test case to the provider, evaluates assertions, and stores results.

### 4. Compare Providers

Run the same suite against multiple providers and compare:

```bash
curl -X POST http://localhost:8001/llm-testing/compare \
  -H "Content-Type: application/json" \
  -d '{
    "spec_name": "customer-support-bot",
    "provider_ids": ["PROVIDER_1", "PROVIDER_2", "PROVIDER_3"],
    "project_id": "your-project-id"
  }'
```

The comparison shows a scoring matrix with pass rates, latency, and cost per provider.

### 5. Use Datasets

Create reusable test case collections:

```bash
curl -X POST http://localhost:8001/llm-testing/datasets \
  -H "Content-Type: application/json" \
  -d '{
    "name": "edge-cases",
    "description": "Edge case inputs for support bot",
    "cases": [
      {"input": "🔥🔥🔥", "expected": "Should handle emoji-only input"},
      {"input": "", "expected": "Should handle empty input gracefully"},
      {"input": "a]{{very long input repeated 1000 times}}", "expected": "Should handle long input"}
    ],
    "project_id": "your-project-id"
  }'
```

Datasets support:
- **Versioning** -- track changes over time
- **CSV import/export** -- bulk management
- **Golden marking** -- mark a dataset as the baseline for regression detection
- **AI augmentation** -- generate additional test cases automatically

### 6. AI Dataset Augmentation

Generate additional test cases using AI:

```bash
curl -X POST http://localhost:8001/llm-testing/datasets/DATASET_ID/augment \
  -H "Content-Type: application/json" \
  -d '{
    "augmentation_type": "edge_cases",
    "count": 10,
    "project_id": "your-project-id"
  }'
```

Augmentation types: `edge_cases`, `adversarial`, `boundary`, `rephrase`.

Review and accept/reject generated cases before they are added to the dataset.

### 7. Prompt Iterations

A/B test system prompt changes:

```bash
curl -X POST http://localhost:8001/llm-testing/prompt-iterations \
  -H "Content-Type: application/json" \
  -d '{
    "spec_name": "customer-support-bot",
    "provider_id": "PROVIDER_ID",
    "original_prompt": "You are a helpful customer support assistant...",
    "modified_prompt": "You are an expert customer support agent for a premium e-commerce brand...",
    "project_id": "your-project-id"
  }'
```

Results show scoring comparison between the original and modified prompts.

### 8. AI Suite Generation

Generate a complete test suite from a system prompt and app description:

```bash
curl -X POST http://localhost:8001/llm-testing/generate-suite \
  -H "Content-Type: application/json" \
  -d '{
    "system_prompt": "You are a helpful customer support assistant...",
    "app_description": "E-commerce platform selling electronics",
    "project_id": "your-project-id"
  }'
```

### 9. Schedule Automated Runs

Create cron-based schedules for recurring test execution:

```bash
curl -X POST http://localhost:8001/llm-testing/schedules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Daily Support Bot Check",
    "spec_name": "customer-support-bot",
    "provider_id": "PROVIDER_ID",
    "cron_expression": "0 9 * * *",
    "project_id": "your-project-id"
  }'
```

### 10. Monitor Analytics

Access analytics dashboards:

```bash
# Overview stats
curl http://localhost:8001/llm-testing/analytics/overview?project_id=your-project-id

# Performance trends
curl http://localhost:8001/llm-testing/analytics/trends?project_id=your-project-id

# Cost tracking
curl http://localhost:8001/llm-testing/analytics/cost?project_id=your-project-id

# Regression detection
curl http://localhost:8001/llm-testing/analytics/regressions?project_id=your-project-id

# Golden dashboard
curl http://localhost:8001/llm-testing/analytics/golden?project_id=your-project-id
```

## Configuration

Provider pricing is configured per-provider (input/output cost per 1K tokens). Analytics use these values for cost tracking.

No special environment variables are needed beyond the standard AI credentials in `.env`.

## API Endpoints Reference

| Method | Path | Description |
|--------|------|-------------|
| POST/GET/PUT/DELETE | `/llm-testing/providers` | Provider CRUD |
| POST/GET/PUT/DELETE | `/llm-testing/specs` | Test spec CRUD |
| GET | `/llm-testing/specs/{name}/versions` | Spec versions |
| POST | `/llm-testing/run` | Run suite against provider |
| POST | `/llm-testing/compare` | Compare providers |
| POST | `/llm-testing/bulk-run` | Batch dataset operations |
| POST | `/llm-testing/bulk-compare` | Batch comparison |
| POST | `/llm-testing/generate-suite` | AI suite generation |
| POST/GET/PUT/DELETE | `/llm-testing/datasets` | Dataset CRUD |
| POST | `/llm-testing/datasets/{id}/augment` | AI augmentation |
| POST/GET/PUT/DELETE | `/llm-testing/schedules` | Schedule CRUD |
| GET | `/llm-testing/analytics/*` | Analytics endpoints |
| POST | `/llm-testing/prompt-iterations` | A/B prompt testing |
| POST | `/llm-testing/specs/{name}/suggest-improvements` | AI spec improvements |

## Key Files

| Path | Purpose |
|------|---------|
| `orchestrator/api/llm_testing.py` | All endpoints (~3400 lines) |
| `orchestrator/workflows/dataset_augmentor.py` | AI dataset augmentation |
| `orchestrator/api/models_db.py` | Database models |
| `web/src/app/(dashboard)/llm-testing/` | Frontend (Providers, Specs, Run, Compare, History, Datasets, Analytics, Prompts, Schedules) |

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Provider health check fails | Verify API key and base URL. Check network connectivity. |
| Test cases timeout | The provider may be rate-limited. Check provider dashboard. |
| Cost tracking shows $0 | Configure `input_cost_per_1k` and `output_cost_per_1k` on the provider. |
| Augmentation returns empty results | Check AI credentials in `.env` |
| Schedule not executing | Verify the schedule is enabled and check `make prod-logs` for scheduler errors |
| Golden dashboard empty | Mark a dataset as "golden" first, then run tests against it |
| Regression detection false positives | Adjust the baseline by re-running with the golden dataset |

## Verification

Confirm LLM testing works:

1. Provider health check passes after registration
2. Running a suite returns scored results for each test case
3. Comparison shows a scoring matrix across multiple providers
4. Analytics dashboards display trends, costs, and latency data
5. Scheduled runs execute and appear in execution history

## Related Guides

- [Scheduling](./scheduling.md) -- automate LLM test runs
- [API Testing](./api-testing.md) -- test the LLM provider's HTTP API directly
- [Credential Management](./credential-management.md) -- manage provider API keys
- [Extending](./extending.md) -- add custom assertion types
