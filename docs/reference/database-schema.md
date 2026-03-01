# Database Schema

All database models in the Quorvex AI platform. Uses SQLModel (SQLAlchemy) with SQLite (development) or PostgreSQL (production).

Source files: `orchestrator/api/models_db.py`, `orchestrator/api/models_auth.py`, `orchestrator/api/db.py`

## Model Summary

| Model | Table | Group | Description |
|-------|-------|-------|-------------|
| `Project` | `projects` | Multi-Tenancy | Top-level tenant with name, base URL, settings (JSON) |
| `ProjectMember` | `project_members` | Multi-Tenancy | User-project association with role |
| `User` | `users` | Authentication | User account with email, bcrypt password hash, lockout fields |
| `RefreshToken` | `refresh_tokens` | Authentication | JWT refresh tokens with rotation support |
| `TestRun` | `testrun` | Test Execution | Core test execution record with queue, stage, healing tracking |
| `SpecMetadata` | `specmetadata` | Test Execution | Spec tags, description, author |
| `AgentRun` | `agentrun` | Test Execution | Generic AI agent execution record |
| `ExecutionSettings` | `execution_settings` | Test Execution | Singleton row for execution configuration |
| `RegressionBatch` | `regression_batches` | Regression | Batch grouping of test runs with aggregated counts |
| `ExplorationSession` | `exploration_sessions` | Exploration | AI exploration run with discovery counts |
| `DiscoveredTransition` | `discovered_transitions` | Exploration | Individual state change during exploration |
| `DiscoveredFlow` | `discovered_flows` | Exploration | Multi-step user flow |
| `FlowStep` | `flow_steps` | Exploration | Individual step within a flow |
| `DiscoveredApiEndpoint` | `discovered_api_endpoints` | Exploration | API endpoint captured via network monitoring |
| `Requirement` | `requirements` | Requirements | Requirement with code, category, priority, acceptance criteria |
| `RequirementSource` | `requirement_sources` | Requirements | Links requirement to its source |
| `RtmEntry` | `rtm_entries` | RTM | Maps requirements to test specs |
| `RtmSnapshot` | `rtm_snapshots` | RTM | Point-in-time RTM coverage snapshot |
| `CoverageMetric` | `coverage_metrics` | Coverage | Coverage metrics per test run |
| `DiscoveredElement` | `discovered_elements` | Coverage | UI elements found during crawling |
| `TestPattern` | `test_patterns` | Coverage | Successful interaction patterns for reuse |
| `CoverageGap` | `coverage_gaps` | Coverage | Identified gaps with suggested tests |
| `ApplicationMap` | `application_map` | Coverage | Discovered application structure |
| `PrdGenerationResult` | `prd_generation_results` | PRD | PRD feature-to-spec generation progress |
| `RunArtifact` | `run_artifacts` | Storage | Artifact tracking across local and MinIO |
| `ArchiveJob` | `archive_jobs` | Storage | Archival operation audit log |
| `StorageStats` | `storage_stats` | Storage | Daily storage statistics |
| `TestrailCaseMapping` | `testrail_case_mappings` | TestRail | Local spec to TestRail case mapping |
| `TestrailRunMapping` | `testrail_run_mappings` | TestRail | Batch to TestRail run mapping |

## Multi-Tenancy Models

### Project

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | string | PK | UUID |
| `name` | string | Unique | Project name |
| `base_url` | string | -- | Default URL for the project |
| `description` | string | -- | Project description |
| `settings` | JSON | -- | Encrypted credentials, integration config |
| `created_at` | datetime | -- | Creation timestamp |
| `last_active` | datetime | -- | Last activity timestamp |

### ProjectMember

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | int | PK | Auto-increment |
| `project_id` | string | FK (projects) | Project reference |
| `user_id` | string | FK (users) | User reference |
| `role` | string | -- | `owner`, `admin`, `editor`, `viewer` |
| `granted_by` | string | FK (users) | Who granted membership |
| `granted_at` | datetime | -- | When membership was granted |

Unique constraint: `(project_id, user_id)`

## Authentication Models

### User

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | string | PK | UUID |
| `email` | string | Unique, indexed | User email |
| `password_hash` | string | -- | bcrypt hash |
| `full_name` | string | -- | Display name |
| `is_active` | bool | -- | Account active flag |
| `is_superuser` | bool | -- | Full platform access |
| `email_verified` | bool | -- | Email verification status |
| `failed_login_attempts` | int | -- | Counter for lockout |
| `locked_until` | datetime | -- | Lockout expiry |

### RefreshToken

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | string | PK | UUID |
| `user_id` | string | FK (users) | Owner |
| `token_hash` | string | -- | Hashed token value |
| `device_info` | string | -- | Client device info |
| `ip_address` | string | -- | Client IP |
| `expires_at` | datetime | -- | Token expiry |
| `revoked_at` | datetime | -- | When revoked (null if active) |
| `replaced_by` | string | -- | Next token in rotation chain |

## Test Execution Models

### TestRun

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | string | PK | Run ID (format: `YYYY-MM-DD_HH-MM-SS`) |
| `spec_name` | string | -- | Spec file path |
| `status` | string | -- | `queued`, `running`, `passed`, `failed`, `error`, `stopped` |
| `test_name` | string | -- | Display name |
| `steps_completed` | int | -- | Completed step count |
| `total_steps` | int | -- | Total step count |
| `browser` | string | -- | Browser used |
| `queue_position` | int | -- | Position in execution queue |
| `batch_id` | string | FK (regression_batches) | Batch reference (if part of batch) |
| `project_id` | string | FK (projects) | Project scope |
| `error_message` | string | -- | Error details |
| `current_stage` | string | -- | `planning`, `generating`, `testing`, `healing` |
| `healing_attempt` | int | -- | Current healing attempt number |

### SpecMetadata

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `spec_name` | string | PK | Spec file path |
| `tags_json` | string | -- | JSON-encoded tags array |
| `description` | string | -- | Spec description |
| `author` | string | -- | Author name |
| `project_id` | string | FK (projects) | Project scope |

### AgentRun

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | string | PK | UUID |
| `agent_type` | string | -- | `exploratory`, `writer`, `spec-synthesis` |
| `config_json` | string | -- | JSON-encoded configuration |
| `result_json` | string | -- | JSON-encoded results |
| `status` | string | -- | Run status |
| `project_id` | string | FK (projects) | Project scope |

### ExecutionSettings

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | int | PK | Always 1 (singleton) |
| `parallelism` | int | -- | Max concurrent test runs |
| `parallel_mode_enabled` | bool | -- | Enable parallel execution |
| `headless_in_parallel` | bool | -- | Headless mode for parallel runs |
| `memory_enabled` | bool | -- | Memory system toggle |

## Regression Models

### RegressionBatch

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | string | PK | Format: `batch_YYYY-MM-DD_HH-MM-SS` |
| `name` | string | -- | Display name |
| `triggered_by` | string | -- | Who/what triggered the batch |
| `browser` | string | -- | Browser used |
| `hybrid_mode` | bool | -- | Hybrid healing enabled |
| `total_tests` | int | -- | Total test count |
| `passed` | int | -- | Passed count |
| `failed` | int | -- | Failed count |
| `stopped` | int | -- | Stopped count |
| `status` | string | -- | Batch status |
| `project_id` | string | FK (projects) | Project scope |

## Exploration Models

### ExplorationSession

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | string | PK | UUID |
| `project_id` | string | FK (projects) | Project scope |
| `entry_url` | string | -- | Starting URL |
| `status` | string | -- | `pending`, `running`, `paused`, `completed`, `failed` |
| `strategy` | string | -- | `goal_directed`, `breadth_first`, `depth_first` |
| `config` | JSON | -- | Session configuration |
| `pages_discovered` | int | -- | Pages found |
| `flows_discovered` | int | -- | Flows found |
| `api_endpoints_discovered` | int | -- | API endpoints found |

### DiscoveredTransition

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | int | PK | Auto-increment |
| `session_id` | string | FK (exploration_sessions) | Session reference |
| `sequence_number` | int | -- | Order within session |
| `before_url` | string | -- | URL before action |
| `action_type` | string | -- | Action performed |
| `action_target` | JSON | -- | Target element details |
| `after_url` | string | -- | URL after action |
| `transition_type` | string | -- | `navigation`, `modal_open`, `modal_close`, `inline_update`, `error`, `no_change` |
| `api_calls` | JSON | -- | API calls during transition |

### DiscoveredFlow

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | int | PK | Auto-increment |
| `session_id` | string | FK (exploration_sessions) | Session reference |
| `project_id` | string | FK (projects) | Project scope |
| `flow_name` | string | -- | Flow display name |
| `flow_category` | string | -- | `authentication`, `crud`, `navigation`, `form_submission`, `search`, etc. |
| `start_url` | string | -- | First URL in flow |
| `end_url` | string | -- | Last URL in flow |
| `step_count` | int | -- | Number of steps |
| `is_success_path` | bool | -- | Whether this is a happy path |

### FlowStep

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | int | PK | Auto-increment |
| `flow_id` | int | FK (discovered_flows) | Flow reference |
| `step_number` | int | -- | Order within flow |
| `transition_id` | int | FK (discovered_transitions) | Transition reference |
| `action_type` | string | -- | Action performed |
| `action_description` | string | -- | Human-readable description |

### DiscoveredApiEndpoint

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | int | PK | Auto-increment |
| `session_id` | string | FK (exploration_sessions) | Session reference |
| `project_id` | string | FK (projects) | Project scope |
| `method` | string | -- | HTTP method |
| `url` | string | -- | Endpoint URL |
| `response_status` | int | -- | HTTP response status |
| `call_count` | int | -- | Times observed |

## Requirements & RTM Models

### Requirement

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | int | PK | Auto-increment |
| `project_id` | string | FK (projects) | Project scope |
| `req_code` | string | -- | Code (e.g., `REQ-001`) |
| `title` | string | -- | Requirement title |
| `description` | string | -- | Full description |
| `category` | string | -- | Functional category |
| `priority` | string | -- | `low`, `medium`, `high`, `critical` |
| `status` | string | -- | `draft`, `approved`, `implemented`, `tested` |
| `acceptance_criteria` | JSON | -- | List of acceptance criteria |
| `source_session_id` | string | FK (exploration_sessions) | Source exploration |

### RequirementSource

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | int | PK | Auto-increment |
| `requirement_id` | int | FK (requirements) | Requirement reference |
| `source_type` | string | -- | `flow`, `element`, `api_endpoint`, `transition` |
| `source_id` | int | -- | ID of source entity |
| `confidence` | float | -- | Confidence score |

### RtmEntry

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | int | PK | Auto-increment |
| `project_id` | string | FK (projects) | Project scope |
| `requirement_id` | int | FK (requirements) | Requirement reference |
| `test_spec_name` | string | -- | Spec file path |
| `mapping_type` | string | -- | `full`, `partial`, `suggested` |
| `confidence` | float | -- | Mapping confidence score |

### RtmSnapshot

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | int | PK | Auto-increment |
| `project_id` | string | FK (projects) | Project scope |
| `total_requirements` | int | -- | Total requirements at snapshot time |
| `covered_requirements` | int | -- | Covered requirements |
| `coverage_percentage` | float | -- | Coverage percentage |
| `snapshot_data` | JSON | -- | Full RTM data at snapshot time |

## Coverage & Memory Models

### CoverageMetric

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | int | PK | Auto-increment |
| `run_id` | string | -- | Test run reference |
| `metric_type` | string | -- | Coverage metric type |
| `covered` | int | -- | Covered count |
| `total` | int | -- | Total count |
| `percentage` | float | -- | Coverage percentage |

### DiscoveredElement

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | int | PK | Auto-increment |
| `url` | string | -- | Page URL |
| `selector_type` | string | -- | Selector strategy |
| `selector_value` | string | -- | Selector value |
| `element_type` | string | -- | Element type (button, input, etc.) |
| `test_count` | int | -- | Times tested |

### TestPattern

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | int | PK | Auto-increment |
| `pattern_hash` | string | -- | Dedup hash |
| `action` | string | -- | Action type |
| `selector_type` | string | -- | Selector strategy |
| `success_count` | int | -- | Successful uses |

### CoverageGap

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | int | PK | Auto-increment |
| `gap_type` | string | -- | Gap type (page, element, flow) |
| `severity` | string | -- | `high`, `medium`, `low` |
| `description` | string | -- | Gap description |
| `suggested_test` | string | -- | Suggested test to fill gap |

### ApplicationMap

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | int | PK | Auto-increment |
| `url` | string | Unique | Page URL |
| `page_title` | string | -- | Page title |
| `linked_urls` | JSON | -- | Outbound links |
| `elements` | JSON | -- | Interactive elements |
| `forms` | JSON | -- | Form elements |
| `api_endpoints` | JSON | -- | API calls from page |

## PRD Models

### PrdGenerationResult

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | int | PK | Auto-increment |
| `prd_project` | string | -- | PRD project identifier |
| `feature_name` | string | -- | Feature being generated |
| `status` | string | -- | Generation status |
| `spec_path` | string | -- | Generated spec file path |
| `project_id` | string | FK (projects) | Project scope |

## Storage & Archival Models

### RunArtifact

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | int | PK | Auto-increment |
| `run_id` | string | -- | Test run reference |
| `artifact_type` | string | -- | `plan`, `trace`, `report`, `screenshot`, `validation` |
| `artifact_name` | string | -- | File name |
| `storage_path` | string | -- | File path or MinIO key |
| `storage_type` | string | -- | `local` or `minio` |
| `archived_at` | datetime | -- | When archived to MinIO |
| `expires_at` | datetime | -- | Expiration date |

### ArchiveJob

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | int | PK | Auto-increment |
| `job_type` | string | -- | Job type |
| `status` | string | -- | Job status |
| `artifacts_processed` | int | -- | Count of processed artifacts |
| `bytes_freed` | int | -- | Bytes freed by archival |

### StorageStats

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | int | PK | Auto-increment |
| `postgres_size_mb` | float | -- | PostgreSQL database size |
| `runs_dir_size_mb` | float | -- | Runs directory size |
| `minio_backups_size_mb` | float | -- | MinIO backups size |
| `minio_artifacts_size_mb` | float | -- | MinIO artifacts size |

## TestRail Integration Models

### TestrailCaseMapping

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | int | PK | Auto-increment |
| `spec_name` | string | -- | Local spec file path |
| `testrail_case_id` | int | -- | TestRail case ID |
| `local_hash` | string | -- | Content hash of local spec |
| `remote_hash` | string | -- | Content hash of TestRail case |
| `project_id` | string | FK (projects) | Project scope |

### TestrailRunMapping

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | int | PK | Auto-increment |
| `batch_id` | string | -- | Regression batch ID |
| `testrail_run_id` | int | -- | TestRail run ID |
| `results_count` | int | -- | Number of results synced |
| `project_id` | string | FK (projects) | Project scope |

## JSON Storage Pattern

Models store structured data as JSON strings with property accessors:

```python
class Model(SQLModel, table=True):
    data_json: str = "{}"

    @property
    def data(self) -> dict:
        return json.loads(self.data_json)

    @data.setter
    def data(self, value: dict):
        self.data_json = json.dumps(value)
```

Models using `Column(JSON)` for native PostgreSQL JSONB: `CoverageMetric.extra_data`, `DiscoveredElement.attributes`, `ApplicationMap.linked_urls/elements/forms/api_endpoints`, `Project.settings`.

## Database Initialization

- `init_db()` creates all tables via `SQLModel.metadata.create_all(engine)`
- Default project created if none exists
- Default execution settings (singleton row) created
- Database type detected from `DATABASE_URL`
- `is_parallel_mode_available()` returns `True` only for PostgreSQL

## Migrations

Alembic migrations for PostgreSQL. Config: `alembic.ini`. Scripts: `orchestrator/migrations/versions/`.

| Command | Description |
|---------|-------------|
| `make db-upgrade` | Apply pending migrations |
| `make db-downgrade` | Roll back one step |
| `make db-history` | View migration history |
| `make db-migrate M="description"` | Generate new migration |
| `make db-stamp R=001` | Stamp existing DB at a revision |

Auto-upgrade on startup: `init_db()` runs `alembic upgrade head` for PostgreSQL.

## Related

- [API Endpoints](api-endpoints.md)
- [Environment Variables](environment-variables.md)
