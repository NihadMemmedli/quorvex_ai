import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Index, Text, UniqueConstraint
from sqlmodel import Column, Field, SQLModel


class TestRun(SQLModel, table=True):
    __table_args__ = (
        Index("ix_testrun_project_status", "project_id", "status"),
        Index("ix_testrun_project_created", "project_id", "created_at"),
        Index("ix_testrun_spec_name", "spec_name"),
        Index("ix_testrun_status", "status"),
        Index("ix_testrun_batch_status", "batch_id", "status"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)
    spec_name: str
    status: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    test_name: str | None = None
    steps_completed: int = 0
    total_steps: int = 0
    browser: str = "chromium"

    # Queue tracking fields for parallel execution
    queue_position: int | None = None  # Position in queue (null when running/completed)
    queued_at: datetime | None = None  # When added to queue
    started_at: datetime | None = None  # When execution started
    completed_at: datetime | None = None  # When execution completed

    # Regression batch tracking
    batch_id: str | None = Field(default=None, foreign_key="regression_batches.id", index=True)

    # Temporal execution metadata for durable browser test runs.
    temporal_workflow_id: str | None = Field(default=None, index=True)
    temporal_run_id: str | None = None

    # Project isolation
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)

    # Error message for failed runs
    error_message: str | None = None

    # Stage tracking for real-time UI feedback
    current_stage: str | None = None  # "planning", "generating", "testing", "healing"
    stage_started_at: datetime | None = None  # When current stage started
    stage_message: str | None = None  # Detailed stage status, e.g., "Exploring application structure..."
    healing_attempt: int | None = None  # Current healing attempt (1, 2, 3 for native, 4+ for ralph)

    # Test type: "browser" (default), "api", or "mixed"
    test_type: str | None = Field(default="browser")

    # Compact summary of agentic QA artifacts. Full artifacts stay in run directory.
    agentic_summary: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # Browser auth intent/resolution for audit, rerun inheritance, and diagnostics.
    browser_auth: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # We can store heavy JSONs as text/jsonb if needed, or stick to file for big logs.
    # For now, let's keep metadata in DB.


class ExecutionSettings(SQLModel, table=True):
    """Execution settings for parallel test runs"""

    __tablename__ = "execution_settings"
    __table_args__ = {"extend_existing": True}

    id: int = Field(default=1, primary_key=True)  # Singleton pattern
    parallelism: int = Field(default=2, ge=1, le=10)  # 1-10 concurrent tests
    parallel_mode_enabled: bool = Field(default=False)
    headless_in_parallel: bool = Field(default=True)  # Force headless when parallelism > 1
    memory_enabled: bool = Field(default=True)  # Disable memory in parallel mode
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SpecMetadata(SQLModel, table=True):
    __table_args__ = (
        Index("ix_specmetadata_project_spec", "project_id", "spec_name"),
        {"extend_existing": True},
    )

    spec_name: str = Field(primary_key=True)
    tags_json: str = "[]"  # Stored as JSON string
    description: str | None = None
    author: str | None = None
    last_modified: datetime | None = None

    # Project isolation
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)

    @property
    def tags(self) -> list[str]:
        try:
            return json.loads(self.tags_json)
        except json.JSONDecodeError:
            return []

    @tags.setter
    def tags(self, value: list[str]):
        self.tags_json = json.dumps(value)


class AgentRun(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}

    id: str = Field(primary_key=True)
    agent_type: str
    runtime: str = Field(default="claude_sdk", index=True)
    config_json: str = "{}"
    result_json: str | None = None
    progress_json: str | None = None
    agent_task_id: str | None = None
    temporal_workflow_id: str | None = None
    temporal_run_id: str | None = None
    status: str = "running"  # running, completed, failed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Project isolation
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)

    @property
    def config(self) -> dict:
        try:
            return json.loads(self.config_json)
        except json.JSONDecodeError:
            return {}

    @config.setter
    def config(self, value: dict):
        self.config_json = json.dumps(value)

    @property
    def result(self) -> dict | None:
        if not self.result_json:
            return None
        try:
            return json.loads(self.result_json)
        except json.JSONDecodeError:
            return None

    @result.setter
    def result(self, value: dict):
        self.result_json = json.dumps(value)

    @property
    def progress(self) -> dict | None:
        if not self.progress_json:
            return None
        try:
            return json.loads(self.progress_json)
        except json.JSONDecodeError:
            return None

    @progress.setter
    def progress(self, value: dict):
        self.progress_json = json.dumps(value)


class AgentRunEvent(SQLModel, table=True):
    """Durable observable event emitted by agent runs."""

    __tablename__ = "agent_run_events"
    __table_args__ = (
        Index("ix_agent_run_events_run_sequence", "run_id", "sequence"),
        Index("ix_agent_run_events_project_created", "project_id", "created_at"),
        Index("ix_agent_run_events_agent_task", "agent_task_id"),
        Index("ix_agent_run_events_temporal_workflow", "temporal_workflow_id"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    run_id: str = Field(foreign_key="agentrun.id", index=True)
    agent_task_id: str | None = Field(default=None, index=True)
    temporal_workflow_id: str | None = Field(default=None, index=True)
    temporal_run_id: str | None = None
    sequence: int = Field(index=True)
    event_type: str = Field(index=True)
    level: str = Field(default="info", index=True)
    message: str = Field(sa_column=Column(Text))
    payload_json: str = Field(default="{}", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    @property
    def payload(self) -> dict[str, Any]:
        try:
            value = json.loads(self.payload_json or "{}")
            return value if isinstance(value, dict) else {"value": value}
        except json.JSONDecodeError:
            return {}

    @payload.setter
    def payload(self, value: dict[str, Any]):
        self.payload_json = json.dumps(value)


class DomainJob(SQLModel, table=True):
    """Durable status record for Temporal-managed domain background jobs."""

    __tablename__ = "domain_jobs"
    __table_args__ = (
        Index("ix_domain_jobs_type_status", "job_type", "status"),
        Index("ix_domain_jobs_project_created", "project_id", "created_at"),
        Index("ix_domain_jobs_temporal_workflow", "temporal_workflow_id"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)
    job_type: str = Field(index=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    status: str = Field(default="queued", index=True)
    payload_json: str = Field(default="{}", sa_column=Column(Text))
    progress_json: str | None = Field(default=None, sa_column=Column(Text))
    result_json: str | None = Field(default=None, sa_column=Column(Text))
    error: str | None = Field(default=None, sa_column=Column(Text))
    temporal_workflow_id: str | None = Field(default=None, index=True)
    temporal_run_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    @property
    def payload(self) -> dict[str, Any]:
        try:
            value = json.loads(self.payload_json or "{}")
            return value if isinstance(value, dict) else {"value": value}
        except json.JSONDecodeError:
            return {}

    @payload.setter
    def payload(self, value: dict[str, Any]):
        self.payload_json = json.dumps(value)

    @property
    def progress(self) -> dict[str, Any]:
        if not self.progress_json:
            return {}
        try:
            value = json.loads(self.progress_json)
            return value if isinstance(value, dict) else {"value": value}
        except json.JSONDecodeError:
            return {}

    @progress.setter
    def progress(self, value: dict[str, Any] | None):
        self.progress_json = json.dumps(value or {})

    @property
    def result(self) -> dict[str, Any] | None:
        if not self.result_json:
            return None
        try:
            value = json.loads(self.result_json)
            return value if isinstance(value, dict) else {"value": value}
        except json.JSONDecodeError:
            return None

    @result.setter
    def result(self, value: dict[str, Any] | None):
        self.result_json = json.dumps(value) if value is not None else None


class AgentToolDefinition(SQLModel, table=True):
    """Selectable tool metadata for UI-created agents."""

    __tablename__ = "agent_tool_definitions"
    __table_args__ = {"extend_existing": True}

    id: str = Field(primary_key=True)
    label: str
    description: str = ""
    category: str = "general"
    tool_name: str
    risk: str = "low"  # low, medium, high, destructive
    enabled: bool = True
    requires_mcp_server: str | None = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AgentDefinition(SQLModel, table=True):
    """Reusable agent profile created from the UI."""

    __tablename__ = "agent_definitions"
    __table_args__ = (
        Index("ix_agent_definitions_project_status", "project_id", "status"),
        {"extend_existing": True},
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    name: str
    description: str = ""
    system_prompt: str
    runtime: str = Field(default="claude_sdk", index=True)
    model: str | None = None
    model_tier: str | None = None
    timeout_seconds: int = 1800
    tool_ids_json: str = "[]"
    test_data_refs_json: str = Field(default="[]", sa_column=Column(Text))
    status: str = "active"  # active, archived
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def tool_ids(self) -> list[str]:
        try:
            value = json.loads(self.tool_ids_json or "[]")
            return [str(item) for item in value if item]
        except json.JSONDecodeError:
            return []

    @tool_ids.setter
    def tool_ids(self, value: list[str]):
        self.tool_ids_json = json.dumps(value)

    @property
    def test_data_refs(self) -> list[str]:
        try:
            value = json.loads(self.test_data_refs_json or "[]")
            return [str(item) for item in value if item]
        except json.JSONDecodeError:
            return []

    @test_data_refs.setter
    def test_data_refs(self, value: list[str]):
        self.test_data_refs_json = json.dumps([str(item) for item in value if item])


class WorkflowDefinition(SQLModel, table=True):
    """Reusable custom workflow made of ordered, typed action steps."""

    __tablename__ = "workflow_definitions"
    __table_args__ = (
        Index("ix_workflow_definitions_project_status", "project_id", "status"),
        Index("ix_workflow_definitions_project_updated", "project_id", "updated_at"),
        {"extend_existing": True},
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    name: str
    description: str = ""
    version: int = 1
    steps_json: str = "[]"
    status: str = "active"  # active, archived
    created_by: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def steps(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.steps_json or "[]")
            return value if isinstance(value, list) else []
        except json.JSONDecodeError:
            return []

    @steps.setter
    def steps(self, value: list[dict[str, Any]]):
        self.steps_json = json.dumps(value)


class WorkflowDefinitionRevision(SQLModel, table=True):
    """Immutable snapshot of a workflow definition at a specific version."""

    __tablename__ = "workflow_definition_revisions"
    __table_args__ = (
        Index("ix_workflow_revisions_definition_version", "definition_id", "version"),
        Index("ix_workflow_revisions_project_created", "project_id", "created_at"),
        UniqueConstraint("definition_id", "version", name="uq_workflow_revision_definition_version"),
        {"extend_existing": True},
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    definition_id: str = Field(foreign_key="workflow_definitions.id", index=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    version: int = Field(default=1, index=True)
    name: str
    description: str = ""
    steps_json: str = "[]"
    change_summary: str = ""
    created_by: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def steps(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.steps_json or "[]")
            return value if isinstance(value, list) else []
        except json.JSONDecodeError:
            return []

    @steps.setter
    def steps(self, value: list[dict[str, Any]]):
        self.steps_json = json.dumps(value)


class WorkflowRun(SQLModel, table=True):
    """Execution state for a saved custom workflow."""

    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("ix_workflow_runs_project_status", "project_id", "status"),
        Index("ix_workflow_runs_definition_created", "definition_id", "created_at"),
        {"extend_existing": True},
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    # Legacy schema compatibility: older databases used workflow_id before
    # definition_id. Keep it populated for migrated tables with NOT NULL
    # constraints.
    workflow_id: str | None = Field(default=None, foreign_key="workflow_definitions.id", index=True)
    definition_id: str = Field(foreign_key="workflow_definitions.id", index=True)
    revision_id: str | None = Field(default=None, foreign_key="workflow_definition_revisions.id", index=True)
    definition_version: int = 1
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    status: str = "queued"  # queued, running, awaiting_input, paused, completed, failed, cancelled
    current_step_index: int = 0
    progress: float = 0.0
    inputs_json: str = "{}"
    context_json: str = "{}"
    recovery_policy_json: str = "{}"
    result_json: str | None = None
    error_message: str | None = None
    triggered_by: str | None = None
    trigger_type: str = "manual"  # manual, schedule, assistant, api, webhook
    trigger_id: str | None = Field(default=None, index=True)
    temporal_workflow_id: str | None = Field(default=None, index=True)
    temporal_run_id: str | None = None
    heartbeat_at: datetime | None = None
    pause_reason: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def inputs(self) -> dict[str, Any]:
        try:
            value = json.loads(self.inputs_json or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    @inputs.setter
    def inputs(self, value: dict[str, Any]):
        self.inputs_json = json.dumps(value)

    def __init__(self, **data: Any):
        super().__init__(**data)
        if self.workflow_id is None and self.definition_id:
            self.workflow_id = self.definition_id

    @property
    def context(self) -> dict[str, Any]:
        try:
            value = json.loads(self.context_json or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    @context.setter
    def context(self, value: dict[str, Any]):
        self.context_json = json.dumps(value)

    @property
    def recovery_policy(self) -> dict[str, Any]:
        try:
            value = json.loads(self.recovery_policy_json or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    @recovery_policy.setter
    def recovery_policy(self, value: dict[str, Any]):
        self.recovery_policy_json = json.dumps(value)

    @property
    def result(self) -> dict[str, Any] | None:
        if not self.result_json:
            return None
        try:
            value = json.loads(self.result_json)
            return value if isinstance(value, dict) else {"value": value}
        except json.JSONDecodeError:
            return None

    @result.setter
    def result(self, value: dict[str, Any] | None):
        self.result_json = json.dumps(value) if value is not None else None


class WorkflowRunStep(SQLModel, table=True):
    """Persisted state for one step in a custom workflow run."""

    __tablename__ = "workflow_run_steps"
    __table_args__ = (
        Index("ix_workflow_run_steps_run_order", "run_id", "step_order"),
        Index("ix_workflow_run_steps_external", "external_kind", "external_id"),
        {"extend_existing": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="workflow_runs.id", index=True)
    # Legacy schema compatibility for pre-custom-workflow-refresh tables.
    workflow_id: str | None = Field(default=None, foreign_key="workflow_definitions.id", index=True)
    definition_id: str = Field(foreign_key="workflow_definitions.id", index=True)
    step_index: int = 0
    step_order: int
    step_id: str = ""
    step_key: str
    step_type: str
    step_type_version: int = 1
    step_config_json: str = "{}"
    name: str = ""
    label: str
    status: str = "pending"  # pending, running, awaiting_input, paused, completed, failed, skipped, cancelled
    continue_on_error: bool = False
    attempt_count: int = 0
    max_attempts: int = 1
    retry_backoff_seconds: int = 0
    recovery_action: str = "fail"  # fail, retry, skip, pause, notify
    skipped_reason: str | None = None
    input_json: str = "{}"
    rendered_input_json: str = "{}"
    context_snapshot_json: str = "{}"
    input_resolution_json: str = "[]"
    output_json: str | None = None
    output_validation_errors_json: str = "[]"
    error_message: str | None = None
    external_kind: str | None = None
    external_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def input(self) -> dict[str, Any]:
        try:
            value = json.loads(self.input_json or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    def __init__(self, **data: Any):
        super().__init__(**data)
        if self.workflow_id is None and self.definition_id:
            self.workflow_id = self.definition_id
        if self.step_id == "" and self.step_key:
            self.step_id = self.step_key
        if self.name == "" and self.label:
            self.name = self.label
        if self.step_index == 0 and self.step_order:
            self.step_index = self.step_order

    @property
    def step_config(self) -> dict[str, Any]:
        try:
            value = json.loads(self.step_config_json or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    @step_config.setter
    def step_config(self, value: dict[str, Any]):
        self.step_config_json = json.dumps(value)

    @input.setter
    def input(self, value: dict[str, Any]):
        self.input_json = json.dumps(value)

    @property
    def rendered_input(self) -> dict[str, Any]:
        return _json_object(self.rendered_input_json)

    @rendered_input.setter
    def rendered_input(self, value: dict[str, Any]):
        self.rendered_input_json = json.dumps(value)

    @property
    def context_snapshot(self) -> dict[str, Any]:
        return _json_object(self.context_snapshot_json)

    @context_snapshot.setter
    def context_snapshot(self, value: dict[str, Any]):
        self.context_snapshot_json = json.dumps(value)

    @property
    def input_resolution(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.input_resolution_json or "[]")
            return value if isinstance(value, list) else []
        except json.JSONDecodeError:
            return []

    @input_resolution.setter
    def input_resolution(self, value: list[dict[str, Any]]):
        self.input_resolution_json = json.dumps(value)

    @property
    def output(self) -> dict[str, Any] | None:
        if not self.output_json:
            return None
        try:
            value = json.loads(self.output_json)
            return value if isinstance(value, dict) else {"value": value}
        except json.JSONDecodeError:
            return None

    @output.setter
    def output(self, value: dict[str, Any] | None):
        self.output_json = json.dumps(value) if value is not None else None

    @property
    def output_validation_errors(self) -> list[str]:
        try:
            value = json.loads(self.output_validation_errors_json or "[]")
            return [str(item) for item in value]
        except json.JSONDecodeError:
            return []

    @output_validation_errors.setter
    def output_validation_errors(self, value: list[str]):
        self.output_validation_errors_json = json.dumps(value)


class WorkflowSchedule(SQLModel, table=True):
    """Recurring trigger configuration for custom workflows."""

    __tablename__ = "workflow_schedules"
    __table_args__ = (
        Index("ix_workflow_schedules_project_enabled", "project_id", "enabled"),
        Index("ix_workflow_schedules_definition_enabled", "definition_id", "enabled"),
        {"extend_existing": True},
    )

    id: str = Field(default_factory=lambda: f"wfs-{uuid.uuid4().hex[:8]}", primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    definition_id: str = Field(foreign_key="workflow_definitions.id", index=True)
    revision_id: str | None = Field(default=None, foreign_key="workflow_definition_revisions.id", index=True)
    revision_mode: str = "pinned"  # pinned, latest
    name: str
    description: str = ""
    cron_expression: str
    timezone: str = "UTC"
    inputs_json: str = "{}"
    start_step_key: str | None = None
    enabled: bool = True
    status: str = "active"  # active, paused, error
    last_error: str | None = None
    notify_on_completion: bool = False
    notify_on_failure: bool = True
    notify_on_review_needed: bool = True
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_run_status: str | None = None
    last_run_id: str | None = Field(default=None, foreign_key="workflow_runs.id", index=True)
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    avg_duration_seconds: float | None = None
    created_by: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def inputs(self) -> dict[str, Any]:
        try:
            value = json.loads(self.inputs_json or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    @inputs.setter
    def inputs(self, value: dict[str, Any]):
        self.inputs_json = json.dumps(value)

    @property
    def success_rate(self) -> float:
        if self.total_executions == 0:
            return 0.0
        return round((self.successful_executions / self.total_executions) * 100, 1)


class WorkflowScheduleExecution(SQLModel, table=True):
    """One scheduled custom workflow execution."""

    __tablename__ = "workflow_schedule_executions"
    __table_args__ = (
        Index("ix_workflow_schedule_exec_schedule_created", "schedule_id", "created_at"),
        Index("ix_workflow_schedule_exec_run", "workflow_run_id"),
        {"extend_existing": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    schedule_id: str = Field(foreign_key="workflow_schedules.id", index=True)
    workflow_run_id: str | None = Field(default=None, foreign_key="workflow_runs.id", index=True)
    status: str = "pending"  # pending, running, completed, failed, skipped
    trigger_type: str = "schedule"  # schedule, manual
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: int | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WorkflowEvent(SQLModel, table=True):
    """Append-only workflow operational event."""

    __tablename__ = "workflow_events"
    __table_args__ = (
        Index("ix_workflow_events_project_created", "project_id", "created_at"),
        Index("ix_workflow_events_run_created", "run_id", "created_at"),
        Index("ix_workflow_events_type_created", "event_type", "created_at"),
        {"extend_existing": True},
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    definition_id: str | None = Field(default=None, foreign_key="workflow_definitions.id", index=True)
    run_id: str | None = Field(default=None, foreign_key="workflow_runs.id", index=True)
    step_id: int | None = Field(default=None, foreign_key="workflow_run_steps.id", index=True)
    schedule_id: str | None = Field(default=None, foreign_key="workflow_schedules.id", index=True)
    event_type: str = Field(index=True)
    severity: str = "info"
    message: str = ""
    payload_json: str = "{}"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def payload(self) -> dict[str, Any]:
        try:
            value = json.loads(self.payload_json or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    @payload.setter
    def payload(self, value: dict[str, Any]):
        self.payload_json = json.dumps(value)


class WorkflowNotification(SQLModel, table=True):
    """User-visible workflow notification derived from workflow events."""

    __tablename__ = "workflow_notifications"
    __table_args__ = (
        Index("ix_workflow_notifications_project_read", "project_id", "read_at"),
        Index("ix_workflow_notifications_event", "event_id"),
        {"extend_existing": True},
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    event_id: str | None = Field(default=None, foreign_key="workflow_events.id", index=True)
    channel: str = "in_app"
    title: str
    body: str = ""
    target_url: str | None = None
    read_at: datetime | None = None
    delivered_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WorkflowStepType(SQLModel, table=True):
    """Versioned workflow step registry entry used by the custom workflow runner."""

    __tablename__ = "workflow_step_types"
    __table_args__ = (
        Index("ix_workflow_step_types_project_status", "project_id", "status"),
        Index("ix_workflow_step_types_type_version", "type", "version"),
        UniqueConstraint("project_id", "type", "version", name="uq_workflow_step_type_project_type_version"),
        {"extend_existing": True},
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    type: str = Field(index=True)
    version: int = 1
    label: str
    description: str = ""
    required_json: str = "[]"
    input_schema_json: str = "{}"
    ui_schema_json: str = "{}"
    output_schema_json: str = "{}"
    default_input_json: str = "{}"
    category: str = "Utility"
    risk_level: str = "low"
    is_async: bool = False
    auto_wait_defaults_json: str = "{}"
    handler_kind: str = "builtin"
    handler_config_json: str = "{}"
    status: str = "active"  # active, disabled
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def required(self) -> list[str]:
        try:
            value = json.loads(self.required_json or "[]")
            return [str(item) for item in value if item]
        except json.JSONDecodeError:
            return []

    @required.setter
    def required(self, value: list[str]):
        self.required_json = json.dumps(value)

    @property
    def input_schema(self) -> dict[str, Any]:
        return _json_object(self.input_schema_json)

    @input_schema.setter
    def input_schema(self, value: dict[str, Any]):
        self.input_schema_json = json.dumps(value)

    @property
    def ui_schema(self) -> dict[str, Any]:
        return _json_object(self.ui_schema_json)

    @ui_schema.setter
    def ui_schema(self, value: dict[str, Any]):
        self.ui_schema_json = json.dumps(value)

    @property
    def output_schema(self) -> dict[str, Any]:
        return _json_object(self.output_schema_json)

    @output_schema.setter
    def output_schema(self, value: dict[str, Any]):
        self.output_schema_json = json.dumps(value)

    @property
    def default_input(self) -> dict[str, Any]:
        return _json_object(self.default_input_json)

    @default_input.setter
    def default_input(self, value: dict[str, Any]):
        self.default_input_json = json.dumps(value)

    @property
    def auto_wait_defaults(self) -> dict[str, Any]:
        return _json_object(self.auto_wait_defaults_json)

    @auto_wait_defaults.setter
    def auto_wait_defaults(self, value: dict[str, Any]):
        self.auto_wait_defaults_json = json.dumps(value)

    @property
    def handler_config(self) -> dict[str, Any]:
        return _json_object(self.handler_config_json)

    @handler_config.setter
    def handler_config(self, value: dict[str, Any]):
        self.handler_config_json = json.dumps(value)


def _json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


# ========== Phase 1: Coverage and Memory Models ==========


class CoverageMetric(SQLModel, table=True):
    """Coverage metrics for test runs"""

    __tablename__ = "coverage_metrics"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    run_id: str | None = Field(default=None, foreign_key="testrun.id", index=True)
    metric_type: str = Field(index=True)  # 'api_coverage', 'element_coverage', 'flow_coverage'
    metric_name: str  # e.g., 'login_page_elements'
    covered: int = Field(default=0)
    total: int = Field(default=0)
    percentage: float = Field(default=0.0)
    extra_data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DiscoveredElement(SQLModel, table=True):
    """Discovered UI elements from application crawling"""

    __tablename__ = "discovered_elements"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    url: str = Field(index=True)
    selector_type: str  # 'role', 'text', 'label', 'placeholder', 'selector'
    selector_value: str
    element_type: str  # 'button', 'input', 'link', etc.
    attributes: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    test_count: int = Field(default=0)


class TestPattern(SQLModel, table=True):
    """Successful test patterns for reuse"""

    __tablename__ = "test_patterns"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    pattern_hash: str = Field(unique=True, index=True)
    action: str  # 'click', 'fill', etc.
    selector_type: str
    selector_template: str  # Template for the selector
    success_count: int = Field(default=0)
    failure_count: int = Field(default=0)
    avg_duration: int = Field(default=0)  # milliseconds
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return (self.success_count / total * 100) if total > 0 else 0.0


class CoverageGap(SQLModel, table=True):
    """Identified gaps in test coverage"""

    __tablename__ = "coverage_gaps"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    gap_type: str  # 'untested_element', 'untested_flow', 'missing_edge_case'
    severity: str = Field(default="medium")  # 'low', 'medium', 'high', 'critical'
    description: str
    suggested_test: str | None = None
    url: str | None = None
    extra_data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved: bool = Field(default=False)


class ApplicationMap(SQLModel, table=True):
    """Discovered application structure (pages, links, forms)"""

    __tablename__ = "application_map"
    __table_args__ = (
        Index("ix_application_map_project_surface", "project_id", "app_surface_key"),
        {"extend_existing": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    app_surface_key: str | None = Field(default=None, index=True)
    url: str = Field(unique=True, index=True)
    page_title: str | None = None
    linked_urls: list[str] | None = Field(default=None, sa_column=Column(JSON))
    elements: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    forms: list[dict[str, Any]] | None = Field(default=None, sa_column=Column(JSON))
    api_endpoints: list[dict[str, Any]] | None = Field(default=None, sa_column=Column(JSON))  # For Phase 2
    last_crawled: datetime = Field(default_factory=datetime.utcnow)

    @property
    def linked_urls_json(self) -> str | None:
        return json.dumps(self.linked_urls) if self.linked_urls else None

    @linked_urls_json.setter
    def linked_urls_json(self, value: str):
        self.linked_urls = json.loads(value) if value else None


class Project(SQLModel, table=True):
    """Project isolation for multi-tenant memory"""

    __tablename__ = "projects"
    __table_args__ = {"extend_existing": True}

    id: str | None = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(unique=True, index=True)
    base_url: str | None = None
    description: str | None = None
    settings: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_active: datetime = Field(default_factory=datetime.utcnow)


class BrowserAuthSession(SQLModel, table=True):
    """Encrypted project-scoped reusable browser authentication state."""

    __tablename__ = "browser_auth_sessions"
    __table_args__ = (
        Index("ix_browser_auth_sessions_project_status", "project_id", "status"),
        Index("ix_browser_auth_sessions_project_default", "project_id", "is_default"),
        UniqueConstraint("project_id", "name", name="uq_browser_auth_sessions_project_name"),
        {"extend_existing": True},
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    name: str
    base_url: str
    login_url: str
    username_key: str
    password_key: str
    username_selector: str | None = None
    password_selector: str | None = None
    username_continue_selector: str | None = None
    submit_selector: str | None = None
    success_url_pattern: str | None = None
    storage_state_json_encrypted: str | None = Field(default=None, sa_column=Column(Text))
    status: str = Field(default="pending", index=True)  # pending, active, invalid, revoked, expired
    is_default: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_validated_at: datetime | None = None
    expires_at: datetime | None = None
    failure_reason: str | None = Field(default=None, sa_column=Column(Text))


class TestDataSet(SQLModel, table=True):
    """Project-scoped reusable test data collection."""

    __tablename__ = "test_data_sets"
    __table_args__ = (
        Index("ix_test_data_sets_project_status", "project_id", "status"),
        Index("ix_test_data_sets_project_format", "project_id", "format"),
        UniqueConstraint("project_id", "key", name="uq_test_data_sets_project_key"),
        {"extend_existing": True},
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    key: str = Field(index=True)
    name: str
    description: str = ""
    tags_json: str = Field(default="[]", sa_column=Column(Text))
    status: str = Field(default="active", index=True)  # active, archived
    format: str = Field(default="json", index=True)  # json, text, mixed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def tags(self) -> list[str]:
        try:
            value = json.loads(self.tags_json or "[]")
            return [str(item) for item in value if str(item).strip()]
        except json.JSONDecodeError:
            return []

    @tags.setter
    def tags(self, value: list[str]):
        self.tags_json = json.dumps([str(item).strip() for item in value if str(item).strip()])


class TestDataItem(SQLModel, table=True):
    """One project-scoped test data fixture item."""

    __tablename__ = "test_data_items"
    __table_args__ = (
        Index("ix_test_data_items_dataset_status", "dataset_id", "status"),
        UniqueConstraint("dataset_id", "key", name="uq_test_data_items_dataset_key"),
        {"extend_existing": True},
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    dataset_id: str = Field(foreign_key="test_data_sets.id", index=True)
    key: str = Field(index=True)
    name: str = ""
    description: str = ""
    status: str = Field(default="active", index=True)  # active, archived
    format: str = Field(default="json", index=True)  # json, text, mixed
    data_json: str | None = Field(default=None, sa_column=Column(Text))
    data_text: str | None = Field(default=None, sa_column=Column(Text))
    sensitive_fields_json: str = Field(default="[]", sa_column=Column(Text))
    encrypted_values_json: str = Field(default="{}", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def data(self) -> Any:
        if not self.data_json:
            return None
        try:
            return json.loads(self.data_json)
        except json.JSONDecodeError:
            return None

    @data.setter
    def data(self, value: Any):
        self.data_json = json.dumps(value) if value is not None else None

    @property
    def sensitive_fields(self) -> list[str]:
        try:
            value = json.loads(self.sensitive_fields_json or "[]")
            return [str(item) for item in value if str(item).strip()]
        except json.JSONDecodeError:
            return []

    @sensitive_fields.setter
    def sensitive_fields(self, value: list[str]):
        self.sensitive_fields_json = json.dumps([str(item).strip() for item in value if str(item).strip()])

    @property
    def encrypted_values(self) -> dict[str, str]:
        try:
            value = json.loads(self.encrypted_values_json or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    @encrypted_values.setter
    def encrypted_values(self, value: dict[str, str]):
        self.encrypted_values_json = json.dumps(value or {})


class RegressionBatch(SQLModel, table=True):
    """Regression batch for grouping related test runs"""

    __tablename__ = "regression_batches"
    __table_args__ = (
        Index("ix_regressionbatch_project_status", "project_id", "status"),
        Index("ix_regressionbatch_project_created", "project_id", "created_at"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)  # batch_YYYY-MM-DD_HH-MM-SS
    name: str | None = None
    triggered_by: str | None = None  # User or system that triggered the batch
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    browser: str = "chromium"
    tags_used_json: str = "[]"  # Tags used to filter specs (stored as JSON)
    hybrid_mode: bool = False  # Whether hybrid healing was enabled

    # Project isolation
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)

    # Aggregated counts (updated as tests complete)
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    stopped: int = 0
    running: int = 0
    queued: int = 0
    status: str = "pending"  # pending, running, completed

    # Cached actual test counts (populated by refresh_batch_stats)
    actual_total_tests: int | None = None
    actual_passed: int | None = None
    actual_failed: int | None = None

    @property
    def tags_used(self) -> list[str]:
        try:
            return json.loads(self.tags_used_json)
        except json.JSONDecodeError:
            return []

    @tags_used.setter
    def tags_used(self, value: list[str]):
        self.tags_used_json = json.dumps(value)

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage"""
        completed = self.passed + self.failed + self.stopped
        if completed == 0:
            return 0.0
        return round((self.passed / completed) * 100, 1)

    @property
    def duration_seconds(self) -> int | None:
        """Calculate duration in seconds if completed"""
        if self.started_at and self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds())
        return None


class RecordingSession(SQLModel, table=True):
    """Playwright codegen recording session."""

    __tablename__ = "recording_sessions"
    __table_args__ = (
        Index("ix_recordings_project_status", "project_id", "status"),
        Index("ix_recordings_project_created", "project_id", "created_at"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    status: str = Field(default="starting", index=True)  # starting, recording, completed, stopped, failed
    target_url: str
    engine: str = "playwright-codegen"
    name: str | None = None
    output_spec_path: str | None = None
    output_code_path: str | None = None
    artifact_dir: str | None = None
    process_id: int | None = None
    error: str | None = None
    config_json: str = "{}"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def config(self) -> dict[str, Any]:
        try:
            return json.loads(self.config_json)
        except json.JSONDecodeError:
            return {}

    @config.setter
    def config(self, value: dict[str, Any]):
        self.config_json = json.dumps(value)

    @property
    def duration_seconds(self) -> int | None:
        if self.started_at and self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds())
        return None


# ========== AI-Powered Exploration & RTM Models ==========


class ExplorationSession(SQLModel, table=True):
    """Exploration sessions for AI-powered app discovery"""

    __tablename__ = "exploration_sessions"
    __table_args__ = {"extend_existing": True}

    id: str = Field(primary_key=True)  # explore_YYYY-MM-DD_HH-MM-SS
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    entry_url: str
    status: str = "pending"  # pending, running, paused, completed, failed
    strategy: str = "goal_directed"  # breadth_first, depth_first, goal_directed
    config_json: str = "{}"  # Exploration parameters
    started_at: datetime | None = None
    completed_at: datetime | None = None
    pages_discovered: int = 0
    flows_discovered: int = 0
    elements_discovered: int = 0
    api_endpoints_discovered: int = 0
    issues_discovered: int = 0
    progress_data: str | None = None  # JSON with live progress during execution
    created_at: datetime = Field(default_factory=datetime.utcnow)
    error_message: str | None = None

    @property
    def config(self) -> dict[str, Any]:
        try:
            return json.loads(self.config_json)
        except json.JSONDecodeError:
            return {}

    @config.setter
    def config(self, value: dict[str, Any]):
        self.config_json = json.dumps(value)

    @property
    def duration_seconds(self) -> int | None:
        if self.started_at and self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds())
        return None


class DiscoveredTransition(SQLModel, table=True):
    """Individual state transitions discovered during exploration"""

    __tablename__ = "discovered_transitions"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="exploration_sessions.id", index=True)
    sequence_number: int  # Order in exploration
    before_url: str
    before_page_type: str | None = None  # login, dashboard, form, list, detail, etc.
    before_snapshot_ref: str | None = None  # Reference to stored snapshot file
    action_type: str  # click, fill, navigate, select, hover
    action_target_json: str = "{}"  # Element details (ref, role, name)
    action_value: str | None = None  # Value if fill/select
    after_url: str
    after_page_type: str | None = None
    after_snapshot_ref: str | None = None
    transition_type: str  # navigation, modal_open, modal_close, inline_update, error, no_change
    api_calls_json: str = "[]"  # Array of captured API calls
    changes_description: str | None = None  # Human-readable description of what changed
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def action_target(self) -> dict[str, Any]:
        try:
            return json.loads(self.action_target_json)
        except json.JSONDecodeError:
            return {}

    @action_target.setter
    def action_target(self, value: dict[str, Any]):
        self.action_target_json = json.dumps(value)

    @property
    def api_calls(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.api_calls_json)
        except json.JSONDecodeError:
            return []

    @api_calls.setter
    def api_calls(self, value: list[dict[str, Any]]):
        self.api_calls_json = json.dumps(value)


class DiscoveredFlow(SQLModel, table=True):
    """Discovered user flows from exploration"""

    __tablename__ = "discovered_flows"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="exploration_sessions.id", index=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    flow_name: str
    flow_category: str  # authentication, crud, navigation, form_submission, search, etc.
    description: str | None = None
    start_url: str
    end_url: str
    step_count: int
    is_success_path: bool = True  # True for happy path, False for error/edge cases
    preconditions_json: str = "[]"  # Required state before flow
    postconditions_json: str = "[]"  # Expected state after flow
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def preconditions(self) -> list[str]:
        try:
            return json.loads(self.preconditions_json)
        except json.JSONDecodeError:
            return []

    @preconditions.setter
    def preconditions(self, value: list[str]):
        self.preconditions_json = json.dumps(value)

    @property
    def postconditions(self) -> list[str]:
        try:
            return json.loads(self.postconditions_json)
        except json.JSONDecodeError:
            return []

    @postconditions.setter
    def postconditions(self, value: list[str]):
        self.postconditions_json = json.dumps(value)


class DiscoveredFlowReview(SQLModel, table=True):
    """Review decision metadata for a discovered flow."""

    __tablename__ = "discovered_flow_reviews"
    __table_args__ = (
        Index("ix_discovered_flow_reviews_project_status", "project_id", "review_status"),
        Index("ix_discovered_flow_reviews_session_status", "session_id", "review_status"),
        UniqueConstraint("flow_id", name="uq_discovered_flow_reviews_flow_id"),
        {"extend_existing": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    flow_id: int = Field(foreign_key="discovered_flows.id", index=True)
    session_id: str = Field(foreign_key="exploration_sessions.id", index=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    review_status: str = Field(default="pending", index=True)  # pending, approved, rejected, generated
    reviewer: str | None = None
    comment: str | None = None
    decided_at: datetime | None = None
    generated_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class FlowStep(SQLModel, table=True):
    """Steps within a discovered flow"""

    __tablename__ = "flow_steps"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    flow_id: int = Field(foreign_key="discovered_flows.id", index=True)
    step_number: int
    transition_id: int | None = Field(default=None, foreign_key="discovered_transitions.id", index=True)
    action_type: str  # click, fill, navigate, select, verify
    action_description: str  # Human-readable step description
    element_ref: str | None = None
    element_role: str | None = None
    element_name: str | None = None
    value: str | None = None


class BrowserPageState(SQLModel, table=True):
    """Canonical browser UI state discovered during autonomous exploration."""

    __tablename__ = "browser_page_states"
    __table_args__ = (
        Index("ix_browser_page_states_project_page", "project_id", "page_key"),
        Index("ix_browser_page_states_project_state", "project_id", "state_key"),
        Index("ix_browser_page_states_project_seen", "project_id", "last_seen_at"),
        UniqueConstraint("project_id", "state_key", name="uq_browser_page_states_project_state"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    session_id: str | None = Field(default=None, foreign_key="exploration_sessions.id", index=True)
    page_key: str = Field(index=True)
    state_key: str = Field(index=True)
    url: str
    url_template: str
    title: str | None = None
    page_type: str | None = None
    auth_state: str | None = None
    viewport: str | None = None
    locale: str | None = None
    exact_hash: str = Field(index=True)
    simhash: str | None = Field(default=None, index=True)
    embedding_id: str | None = None
    snapshot_ref: str | None = None
    canonical_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    first_seen_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    visit_count: int = 1
    novelty_score: float = 1.0
    importance_score: float = 0.5
    decay_score: float = 1.0
    status: str = Field(default="active", index=True)


class BrowserElement(SQLModel, table=True):
    """Stable element memory for a canonical browser state."""

    __tablename__ = "browser_elements"
    __table_args__ = (
        Index("ix_browser_elements_project_state", "project_id", "state_id"),
        Index("ix_browser_elements_project_key", "project_id", "element_key"),
        Index("ix_browser_elements_project_role", "project_id", "role"),
        UniqueConstraint("project_id", "state_id", "element_key", name="uq_browser_elements_project_state_key"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    state_id: str = Field(foreign_key="browser_page_states.id", index=True)
    element_key: str = Field(index=True)
    role: str | None = Field(default=None, index=True)
    name: str | None = None
    text: str | None = None
    element_type: str | None = None
    locator_candidates_json: list[dict[str, Any]] | None = Field(default=None, sa_column=Column(JSON))
    attributes_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    form_context_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    first_seen_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    seen_count: int = 1
    tested_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    importance_score: float = 0.5
    stability_score: float = 0.5
    status: str = Field(default="active", index=True)

    @property
    def locator_candidates(self) -> list[dict[str, Any]]:
        return self.locator_candidates_json or []

    @locator_candidates.setter
    def locator_candidates(self, value: list[dict[str, Any]]):
        self.locator_candidates_json = value


class BrowserTransition(SQLModel, table=True):
    """Observed action edge between two browser page states."""

    __tablename__ = "browser_transitions"
    __table_args__ = (
        Index("ix_browser_transitions_project_from", "project_id", "from_state_id"),
        Index("ix_browser_transitions_project_to", "project_id", "to_state_id"),
        Index("ix_browser_transitions_project_seen", "project_id", "last_seen_at"),
        UniqueConstraint(
            "project_id",
            "from_state_id",
            "to_state_id",
            "action_signature",
            name="uq_browser_transitions_project_signature",
        ),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    session_id: str | None = Field(default=None, foreign_key="exploration_sessions.id", index=True)
    from_state_id: str = Field(foreign_key="browser_page_states.id", index=True)
    to_state_id: str = Field(foreign_key="browser_page_states.id", index=True)
    action_type: str = Field(index=True)
    action_signature: str = Field(index=True)
    element_id: str | None = Field(default=None, foreign_key="browser_elements.id", index=True)
    action_value_kind: str | None = None
    transition_type: str = "interaction"
    api_signature_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    success_count: int = 1
    failure_count: int = 0
    avg_duration_ms: float = 0.0
    first_seen_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    novelty_at_discovery: float = 1.0
    risk_level: str = "low"
    status: str = Field(default="active", index=True)


class BrowserFrontierItem(SQLModel, table=True):
    """Persistent work queue item for 24/7 browser exploration."""

    __tablename__ = "browser_frontier_items"
    __table_args__ = (
        Index("ix_browser_frontier_project_status_priority", "project_id", "status", "priority_score"),
        Index("ix_browser_frontier_project_due", "project_id", "next_due_at"),
        UniqueConstraint("project_id", "state_id", "element_id", "action_type", name="uq_browser_frontier_action"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    state_id: str = Field(foreign_key="browser_page_states.id", index=True)
    element_id: str | None = Field(default=None, foreign_key="browser_elements.id", index=True)
    action_type: str = Field(index=True)
    priority_score: float = Field(default=0.5, index=True)
    status: str = Field(default="queued", index=True)
    attempts: int = 0
    last_attempted_at: datetime | None = None
    next_due_at: datetime | None = Field(default=None, index=True)
    block_reason: str | None = None
    lease_owner: str | None = None
    lease_until: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class BrowserStateCluster(SQLModel, table=True):
    """Near-duplicate browser state cluster."""

    __tablename__ = "browser_state_clusters"
    __table_args__ = (
        Index("ix_browser_state_clusters_project_key", "project_id", "cluster_key"),
        UniqueConstraint("project_id", "cluster_key", name="uq_browser_state_clusters_project_key"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    cluster_key: str = Field(index=True)
    representative_state_id: str | None = Field(default=None, foreign_key="browser_page_states.id")
    member_count: int = 0
    summary: str | None = Field(default=None, sa_column=Column(Text))
    embedding_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DiscoveredApiEndpoint(SQLModel, table=True):
    """API endpoints discovered during exploration"""

    __tablename__ = "discovered_api_endpoints"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="exploration_sessions.id", index=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    method: str  # GET, POST, PUT, DELETE, PATCH
    url: str = Field(index=True)
    request_headers_json: str = "{}"
    request_body_sample: str | None = None
    response_status: int | None = None
    response_body_sample: str | None = None
    triggered_by_action: str | None = None  # Description of UI action that triggered this
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    call_count: int = 1

    @property
    def request_headers(self) -> dict[str, Any]:
        try:
            return json.loads(self.request_headers_json)
        except json.JSONDecodeError:
            return {}

    @request_headers.setter
    def request_headers(self, value: dict[str, Any]):
        self.request_headers_json = json.dumps(value)


class DiscoveredIssue(SQLModel, table=True):
    """Issues discovered during exploration (broken links, errors, accessibility, etc.)"""

    __tablename__ = "discovered_issues"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="exploration_sessions.id", index=True)
    issue_type: str  # broken_link, error_page, accessibility, performance, usability, security, missing_content
    severity: str = "medium"  # critical, high, medium, low
    url: str = ""
    description: str = ""
    element: str | None = None
    evidence: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Requirement(SQLModel, table=True):
    """Requirements inferred from exploration"""

    __tablename__ = "requirements"
    __table_args__ = (
        Index("ix_requirements_project_canonical", "project_id", "canonical_key"),
        UniqueConstraint("project_id", "canonical_key", name="uq_requirements_project_canonical"),
        {"extend_existing": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    req_code: str = Field(index=True)  # REQ-001, REQ-002, etc.
    title: str
    description: str | None = None
    category: str  # authentication, navigation, crud, validation, etc.
    priority: str = "medium"  # low, medium, high, critical
    status: str = "draft"  # draft, approved, implemented, tested
    canonical_key: str | None = Field(default=None, index=True)
    truth_state: str = Field(default="candidate_requirement", index=True)
    source_type: str = Field(default="manual", index=True)
    confidence: float = Field(default=0.9)
    uncertainty_reason: str | None = Field(default=None, sa_column=Column(Text))
    provenance_metadata_json: str = Field(default="{}", sa_column=Column(Text))
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    rejected_by: str | None = None
    rejected_at: datetime | None = None
    acceptance_criteria_json: str = "[]"
    title_embedding_json: str | None = None  # Cached embedding for deduplication
    source_session_id: str | None = Field(default=None, foreign_key="exploration_sessions.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def acceptance_criteria(self) -> list[str]:
        try:
            return json.loads(self.acceptance_criteria_json)
        except json.JSONDecodeError:
            return []

    @acceptance_criteria.setter
    def acceptance_criteria(self, value: list[str]):
        self.acceptance_criteria_json = json.dumps(value)

    @property
    def title_embedding(self) -> list[float] | None:
        if not self.title_embedding_json:
            return None
        try:
            return json.loads(self.title_embedding_json)
        except json.JSONDecodeError:
            return None

    @title_embedding.setter
    def title_embedding(self, value: list[float] | None):
        self.title_embedding_json = json.dumps(value) if value else None

    @property
    def provenance_metadata(self) -> dict[str, Any]:
        try:
            value = json.loads(self.provenance_metadata_json or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    @provenance_metadata.setter
    def provenance_metadata(self, value: dict[str, Any] | None):
        self.provenance_metadata_json = json.dumps(value or {})


class RequirementSource(SQLModel, table=True):
    """Links requirements to their source flows/elements"""

    __tablename__ = "requirement_sources"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    requirement_id: int = Field(foreign_key="requirements.id", index=True)
    source_type: str  # flow, element, api_endpoint, transition
    source_id: int  # ID of the source entity
    confidence: float = 1.0  # Confidence of the mapping (0.0 - 1.0)


class RtmEntry(SQLModel, table=True):
    """Requirements Traceability Matrix entries"""

    __tablename__ = "rtm_entries"
    __table_args__ = (
        Index("ix_rtm_entries_project_dedupe", "project_id", "dedupe_key"),
        UniqueConstraint("project_id", "dedupe_key", name="uq_rtm_entries_project_dedupe"),
        {"extend_existing": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    requirement_id: int = Field(foreign_key="requirements.id", index=True)
    test_spec_name: str  # Name/path of the test spec
    test_spec_path: str | None = None  # Full path to spec file
    mapping_type: str  # full, partial, suggested
    dedupe_key: str | None = Field(default=None, index=True)
    confidence: float = 1.0  # Confidence of the mapping (0.0 - 1.0)
    coverage_notes: str | None = None  # Notes about what's covered
    gap_notes: str | None = None  # Notes about gaps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RtmSnapshot(SQLModel, table=True):
    """Snapshots of RTM for historical tracking"""

    __tablename__ = "rtm_snapshots"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    snapshot_name: str | None = None  # Optional name for the snapshot
    total_requirements: int = 0
    covered_requirements: int = 0
    partial_requirements: int = 0
    uncovered_requirements: int = 0
    coverage_percentage: float = 0.0
    snapshot_data_json: str = "{}"  # Full RTM data at time of snapshot
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def snapshot_data(self) -> dict[str, Any]:
        try:
            return json.loads(self.snapshot_data_json)
        except json.JSONDecodeError:
            return {}

    @snapshot_data.setter
    def snapshot_data(self, value: dict[str, Any]):
        self.snapshot_data_json = json.dumps(value)


class PrdGenerationResult(SQLModel, table=True):
    """Tracks PRD feature generation results for persistence across page refreshes"""

    __tablename__ = "prd_generation_results"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    prd_project: str = Field(index=True)  # PRD project name (folder in prds/)
    feature_name: str = Field(index=True)  # Feature being generated

    # Status tracking
    status: str = "pending"  # pending, running, completed, failed
    current_stage: str | None = None  # "initializing", "retrieving_context", "invoking_agent", "saving_spec"
    stage_message: str | None = None  # Detailed progress message

    # Results
    spec_path: str | None = None
    error_message: str | None = None
    target_url: str | None = None
    live_browser_requested: bool = False

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Log file path for real-time streaming
    log_path: str | None = None

    # Queued agent ownership and live queue diagnostics
    agent_task_id: str | None = Field(default=None, index=True)
    agent_worker_id: str | None = Field(default=None, index=True)
    last_heartbeat_at: datetime | None = None
    queue_telemetry_json: str = "{}"

    # Project isolation
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)

    @property
    def queue_telemetry(self) -> dict[str, Any]:
        try:
            value = json.loads(self.queue_telemetry_json or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    @queue_telemetry.setter
    def queue_telemetry(self, value: dict[str, Any]):
        self.queue_telemetry_json = json.dumps(value or {})


class PrdGenerationEvent(SQLModel, table=True):
    """Compact structured timeline for a PRD generation run."""

    __tablename__ = "prd_generation_events"
    __table_args__ = (
        Index("ix_prd_generation_events_generation_sequence", "generation_id", "sequence"),
        {"extend_existing": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    generation_id: int = Field(foreign_key="prd_generation_results.id", index=True)
    sequence: int = Field(index=True)
    role: str = Field(index=True)
    event_type: str = Field(index=True)
    level: str = "info"
    message: str
    payload_json: str = "{}"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def payload(self) -> dict[str, Any]:
        try:
            value = json.loads(self.payload_json or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    @payload.setter
    def payload(self, value: dict[str, Any]):
        self.payload_json = json.dumps(value or {})


# ========== Production Data Management Models ==========


class RunArtifact(SQLModel, table=True):
    """Tracks run artifacts and their storage location for archival management.

    This model enables:
    - Tracking artifacts across local and MinIO storage
    - Implementing retention policies (hot vs warm storage)
    - Retrieving archived artifacts on demand
    """

    __tablename__ = "run_artifacts"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)  # References testrun.id
    artifact_type: str = Field(index=True)  # 'plan', 'trace', 'report', 'screenshot', 'validation'
    artifact_name: str  # Original filename
    storage_path: str  # Path in storage (local path or S3 key)
    storage_type: str = "local"  # 'local', 'minio'
    size_bytes: int | None = None
    checksum: str | None = None  # SHA256 for verification

    # Lifecycle tracking
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    archived_at: datetime | None = None  # When moved to MinIO
    expires_at: datetime | None = None  # When to delete completely
    deleted_at: datetime | None = None  # Soft delete timestamp

    # Extra data for quick retrieval
    extra_data_json: str = "{}"  # Additional artifact data

    @property
    def extra_data(self) -> dict[str, Any]:
        try:
            return json.loads(self.extra_data_json)
        except json.JSONDecodeError:
            return {}

    @extra_data.setter
    def extra_data(self, value: dict[str, Any]):
        self.extra_data_json = json.dumps(value)

    @property
    def is_archived(self) -> bool:
        return self.storage_type == "minio" and self.archived_at is not None

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at


class ArchiveJob(SQLModel, table=True):
    """Tracks archival job executions for audit and debugging.

    Each job represents one archival run that processes multiple artifacts.
    """

    __tablename__ = "archive_jobs"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    job_type: str = "archival"  # 'archival', 'deletion', 'restore'
    status: str = "pending"  # 'pending', 'running', 'completed', 'failed'

    # Execution details
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Results
    artifacts_processed: int = 0
    artifacts_archived: int = 0
    artifacts_deleted: int = 0
    bytes_archived: int = 0
    bytes_freed: int = 0

    # Error tracking
    error_message: str | None = None
    error_details_json: str = "[]"  # Array of individual artifact errors

    # Configuration used
    config_json: str = "{}"  # hot_days, total_days, etc.

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def error_details(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.error_details_json)
        except json.JSONDecodeError:
            return []

    @error_details.setter
    def error_details(self, value: list[dict[str, Any]]):
        self.error_details_json = json.dumps(value)

    @property
    def config(self) -> dict[str, Any]:
        try:
            return json.loads(self.config_json)
        except json.JSONDecodeError:
            return {}

    @config.setter
    def config(self, value: dict[str, Any]):
        self.config_json = json.dumps(value)

    @property
    def duration_seconds(self) -> int | None:
        if self.started_at and self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds())
        return None


class StorageStats(SQLModel, table=True):
    """Daily storage statistics for monitoring and alerting.

    Captures point-in-time snapshots of storage usage.
    """

    __tablename__ = "storage_stats"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    # Database stats
    postgres_size_mb: float = 0.0
    testrun_count: int = 0

    # Local storage stats
    runs_dir_size_mb: float = 0.0
    runs_dir_count: int = 0
    specs_count: int = 0
    tests_count: int = 0

    # MinIO stats
    minio_backups_size_mb: float = 0.0
    minio_backups_count: int = 0
    minio_artifacts_size_mb: float = 0.0
    minio_artifacts_count: int = 0

    # Backup stats
    last_backup_at: datetime | None = None
    backup_age_hours: float | None = None

    # Health indicators
    minio_connected: bool = True
    postgres_connected: bool = True

    # Alerts triggered
    alerts_json: str = "[]"  # Array of alert messages

    @property
    def alerts(self) -> list[str]:
        try:
            return json.loads(self.alerts_json)
        except json.JSONDecodeError:
            return []

    @alerts.setter
    def alerts(self, value: list[str]):
        self.alerts_json = json.dumps(value)


# ========== TestRail Integration Models ==========


class TestrailCaseMapping(SQLModel, table=True):
    """Maps local specs to TestRail cases for sync tracking."""

    __tablename__ = "testrail_case_mappings"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    spec_name: str = Field(index=True)
    testrail_case_id: int
    testrail_suite_id: int
    testrail_section_id: int
    testrail_project_id: int
    sync_direction: str = "push"  # push, pull, bidirectional
    last_pushed_at: datetime | None = None
    last_pulled_at: datetime | None = None
    local_hash: str | None = None  # Hash of spec content at last sync
    remote_hash: str | None = None  # Hash of TestRail case at last sync
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TestrailRunMapping(SQLModel, table=True):
    """Maps local batch runs to TestRail test runs (Phase 2b readiness)."""

    __tablename__ = "testrail_run_mappings"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    batch_id: str = Field(index=True)
    testrail_run_id: int
    testrail_project_id: int
    synced_at: datetime = Field(default_factory=datetime.utcnow)
    results_count: int = 0


# ========== Jira Integration Models ==========


class JiraIssueMapping(SQLModel, table=True):
    """Maps test runs to Jira issues created from failure data."""

    __tablename__ = "jira_issue_mappings"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    run_id: str = Field(index=True)
    jira_issue_key: str  # e.g. "PROJ-123"
    jira_issue_id: str  # Jira internal ID
    jira_project_key: str
    issue_type: str = "Bug"
    summary: str = ""
    status: str = "open"  # open, resolved, closed
    jira_url: str = ""
    bug_report_json: str | None = None  # Stores AI-generated report
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ========== Load Testing Models ==========


class LoadTestRun(SQLModel, table=True):
    """K6 load test execution records."""

    __tablename__ = "load_test_runs"
    __table_args__ = (
        Index("ix_loadtestrun_project_status", "project_id", "status"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)  # load-<uuid8>
    spec_name: str | None = None
    script_path: str | None = None
    status: str = "pending"  # pending, running, completed, failed, cancelled
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)

    # Configuration
    vus: int | None = None
    duration: str | None = None  # e.g. "30s", "1m", "5m"
    stages_json: str = "[]"  # K6 stages config [{duration, target}]
    thresholds_json: str = "{}"  # K6 thresholds config

    # Core metrics
    total_requests: int | None = None
    failed_requests: int | None = None
    avg_response_time_ms: float | None = None
    p50_response_time_ms: float | None = None
    p90_response_time_ms: float | None = None
    p95_response_time_ms: float | None = None
    p99_response_time_ms: float | None = None
    max_response_time_ms: float | None = None
    min_response_time_ms: float | None = None
    requests_per_second: float | None = None
    peak_rps: float | None = None
    peak_vus: int | None = None
    data_received_bytes: int | None = None
    data_sent_bytes: int | None = None

    # Result details
    thresholds_passed: bool | None = None
    thresholds_detail_json: str = "{}"
    checks_json: str = "[]"
    http_status_counts_json: str = "{}"
    metrics_summary_json: str = "{}"
    timeseries_json: str = "[]"
    ai_analysis_json: str = "{}"

    # Tracking
    error_message: str | None = None
    current_stage: str | None = None  # generating, validating, running, parsing, done
    worker_count: int | None = None  # Number of workers used for distributed execution
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def stages(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.stages_json)
        except json.JSONDecodeError:
            return []

    @stages.setter
    def stages(self, value: list[dict[str, Any]]):
        self.stages_json = json.dumps(value)

    @property
    def thresholds(self) -> dict[str, Any]:
        try:
            return json.loads(self.thresholds_json)
        except json.JSONDecodeError:
            return {}

    @thresholds.setter
    def thresholds(self, value: dict[str, Any]):
        self.thresholds_json = json.dumps(value)

    @property
    def thresholds_detail(self) -> dict[str, Any]:
        try:
            return json.loads(self.thresholds_detail_json)
        except json.JSONDecodeError:
            return {}

    @thresholds_detail.setter
    def thresholds_detail(self, value: dict[str, Any]):
        self.thresholds_detail_json = json.dumps(value)

    @property
    def checks(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.checks_json)
        except json.JSONDecodeError:
            return []

    @checks.setter
    def checks(self, value: list[dict[str, Any]]):
        self.checks_json = json.dumps(value)

    @property
    def http_status_counts(self) -> dict[str, int]:
        try:
            return json.loads(self.http_status_counts_json)
        except json.JSONDecodeError:
            return {}

    @http_status_counts.setter
    def http_status_counts(self, value: dict[str, int]):
        self.http_status_counts_json = json.dumps(value)

    @property
    def metrics_summary(self) -> dict[str, Any]:
        try:
            return json.loads(self.metrics_summary_json)
        except json.JSONDecodeError:
            return {}

    @metrics_summary.setter
    def metrics_summary(self, value: dict[str, Any]):
        self.metrics_summary_json = json.dumps(value)

    @property
    def timeseries(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.timeseries_json)
        except json.JSONDecodeError:
            return []

    @timeseries.setter
    def timeseries(self, value: list[dict[str, Any]]):
        self.timeseries_json = json.dumps(value)

    @property
    def ai_analysis(self) -> dict[str, Any]:
        try:
            return json.loads(self.ai_analysis_json)
        except json.JSONDecodeError:
            return {}

    @ai_analysis.setter
    def ai_analysis(self, value: dict[str, Any]):
        self.ai_analysis_json = json.dumps(value)

    @property
    def duration_seconds(self) -> int | None:
        if self.started_at and self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds())
        return None


# ========== Security Testing Models ==========


class SecurityScanRun(SQLModel, table=True):
    __tablename__ = "security_scan_runs"
    __table_args__ = (
        Index("ix_securityscanrun_project_status", "project_id", "status"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)  # sec-<uuid8>
    spec_name: str | None = None
    target_url: str
    scan_type: str = "quick"  # quick, nuclei, zap, full
    status: str = "pending"  # pending, running, completed, failed, cancelled
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)

    # Severity counts (denormalized for dashboard performance)
    total_findings: int = 0
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    info_count: int = 0

    # Phase tracking
    quick_scan_completed: bool = False
    nuclei_scan_completed: bool = False
    zap_scan_completed: bool = False

    # Progress
    current_stage: str | None = None  # quick_scan, nuclei_scan, zap_spider, zap_active, ai_analysis
    stage_message: str | None = None
    error_message: str | None = None

    # Passive mode link
    source_test_run_id: str | None = None  # FK to TestRun if triggered by passive proxy

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def duration_seconds(self) -> int | None:
        if self.started_at and self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds())
        return None


class SecurityFinding(SQLModel, table=True):
    __tablename__ = "security_findings"
    __table_args__ = (
        Index("ix_securityfinding_project_severity", "project_id", "severity", "status"),
        Index("ix_securityfinding_scan_severity", "scan_id", "severity"),
        {"extend_existing": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    scan_id: str = Field(foreign_key="security_scan_runs.id", index=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)

    # Classification
    severity: str = Field(index=True)  # critical, high, medium, low, info
    finding_type: str  # missing_header, weak_cookie, ssl_issue, etc.
    category: str  # owasp_a01..a10, misconfiguration, exposure
    scanner: str  # quick, nuclei, zap

    # Details
    title: str
    description: str
    url: str
    evidence: str | None = None
    remediation: str | None = None
    reference_urls_json: str = "[]"

    # Scanner-specific
    template_id: str | None = None  # Nuclei template ID
    zap_alert_ref: str | None = None  # ZAP alert reference
    zap_cweid: int | None = None

    # Dedup + status
    finding_hash: str = Field(index=True)  # SHA256 for dedup
    status: str = "open"  # open, false_positive, fixed, accepted_risk
    notes: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def reference_urls(self) -> list[str]:
        try:
            return json.loads(self.reference_urls_json)
        except json.JSONDecodeError:
            return []

    @reference_urls.setter
    def reference_urls(self, value: list[str]):
        self.reference_urls_json = json.dumps(value)


# ========== Database Testing Models ==========


class DbConnection(SQLModel, table=True):
    __tablename__ = "db_connections"
    __table_args__ = {"extend_existing": True}

    id: str = Field(primary_key=True)  # dbc-<uuid8>
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    name: str
    host: str
    port: int = Field(default=5432)
    database: str
    username: str
    password_encrypted: str = ""  # Fernet encrypted
    ssl_mode: str = Field(default="prefer")
    schema_name: str = Field(default="public")
    is_read_only: bool = Field(default=True)

    last_tested_at: datetime | None = None
    last_test_success: bool | None = None
    last_test_error: str | None = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DbTestRun(SQLModel, table=True):
    __tablename__ = "db_test_runs"
    __table_args__ = (
        Index("ix_dbtestrun_project_status", "project_id", "status"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)  # dbt-<uuid8>
    connection_id: str = Field(foreign_key="db_connections.id", index=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    spec_name: str | None = None
    run_type: str = "full"  # schema_analysis, data_quality, full
    status: str = "pending"  # pending, running, completed, failed

    # Real-time progress
    current_stage: str | None = None
    stage_message: str | None = None

    # Schema analysis results (stored as JSON text)
    schema_snapshot_json: str | None = None
    schema_findings_json: str | None = None

    # Data quality counts
    total_checks: int = 0
    passed_checks: int = 0
    failed_checks: int = 0
    error_checks: int = 0

    # Severity breakdown
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    info_count: int = 0

    # AI analysis output
    ai_summary: str | None = None
    ai_suggestions_json: str | None = None

    error_message: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def pass_rate(self) -> float:
        if self.total_checks == 0:
            return 0.0
        return round((self.passed_checks / self.total_checks) * 100, 1)

    @property
    def duration_seconds(self) -> int | None:
        if self.started_at and self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds())
        return None

    @property
    def schema_snapshot(self) -> dict | None:
        if not self.schema_snapshot_json:
            return None
        try:
            return json.loads(self.schema_snapshot_json)
        except json.JSONDecodeError:
            return None

    @schema_snapshot.setter
    def schema_snapshot(self, value: dict):
        self.schema_snapshot_json = json.dumps(value)

    @property
    def schema_findings(self) -> list | None:
        if not self.schema_findings_json:
            return None
        try:
            return json.loads(self.schema_findings_json)
        except json.JSONDecodeError:
            return None

    @schema_findings.setter
    def schema_findings(self, value: list):
        self.schema_findings_json = json.dumps(value)

    @property
    def ai_suggestions(self) -> list | None:
        if not self.ai_suggestions_json:
            return None
        try:
            return json.loads(self.ai_suggestions_json)
        except json.JSONDecodeError:
            return None

    @ai_suggestions.setter
    def ai_suggestions(self, value: list):
        self.ai_suggestions_json = json.dumps(value)


class DbTestCheck(SQLModel, table=True):
    __tablename__ = "db_test_checks"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="db_test_runs.id", index=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)

    check_name: str
    check_type: str  # null_check, uniqueness, referential, range, pattern, custom, freshness
    table_name: str | None = None
    column_name: str | None = None
    description: str | None = None

    sql_query: str = ""
    status: str = "pending"  # pending, passed, failed, error, skipped
    severity: str = "medium"  # critical, high, medium, low, info

    expected_result: str | None = None
    actual_result: str | None = None
    row_count: int | None = None
    sample_data_json: str | None = None  # max 10 rows
    error_message: str | None = None
    execution_time_ms: int | None = None

    @property
    def sample_data(self) -> list | None:
        if not self.sample_data_json:
            return None
        try:
            return json.loads(self.sample_data_json)
        except json.JSONDecodeError:
            return None

    @sample_data.setter
    def sample_data(self, value: list):
        self.sample_data_json = json.dumps(value)


# ========== LLM Testing Models ==========


class LlmProvider(SQLModel, table=True):
    """LLM provider configuration with encrypted API keys."""

    __tablename__ = "llm_providers"
    __table_args__ = {"extend_existing": True}

    id: str = Field(primary_key=True)  # llm-<uuid8>
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    name: str
    base_url: str
    api_key_encrypted: str = ""  # Fernet encrypted
    model_id: str
    default_params_json: str = "{}"  # {"temperature": 0.7, "max_tokens": 4096}
    custom_pricing_json: str | None = None  # [input_per_1m, output_per_1m]
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def default_params(self) -> dict[str, Any]:
        try:
            return json.loads(self.default_params_json)
        except json.JSONDecodeError:
            return {}

    @default_params.setter
    def default_params(self, value: dict[str, Any]):
        self.default_params_json = json.dumps(value)

    @property
    def custom_pricing(self) -> tuple | None:
        if not self.custom_pricing_json:
            return None
        try:
            data = json.loads(self.custom_pricing_json)
            if isinstance(data, list) and len(data) == 2:
                return tuple(data)
            return None
        except json.JSONDecodeError:
            return None

    @custom_pricing.setter
    def custom_pricing(self, value: tuple | None):
        self.custom_pricing_json = json.dumps(list(value)) if value else None


class LlmTestRun(SQLModel, table=True):
    """LLM test run execution record."""

    __tablename__ = "llm_test_runs"
    __table_args__ = (
        Index("ix_llmtestrun_project_status", "project_id", "status"),
        Index("ix_llmtestrun_project_created", "project_id", "created_at"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)  # llmr-<uuid8>
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    provider_id: str | None = Field(default=None, foreign_key="llm_providers.id", index=True)
    comparison_id: str | None = None  # FK to llm_comparison_runs
    dataset_id: str | None = Field(default=None, index=True)
    dataset_name: str | None = None  # Denormalized for display
    dataset_version: int | None = None
    spec_name: str
    status: str = "pending"  # pending, running, completed, failed

    # Aggregated counts
    total_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0
    error_cases: int = 0

    # Performance metrics
    avg_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost_usd: float = 0.0

    # Aggregated scores
    avg_scores_json: str = "{}"  # {"answer_relevancy": 0.85, "judge:helpfulness": 9}

    # Progress tracking
    progress_current: int = 0
    progress_total: int = 0

    error_message: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def pass_rate(self) -> float:
        if self.total_cases == 0:
            return 0.0
        return round((self.passed_cases / self.total_cases) * 100, 1)

    @property
    def duration_seconds(self) -> int | None:
        if self.started_at and self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds())
        return None

    @property
    def avg_scores(self) -> dict[str, float]:
        try:
            return json.loads(self.avg_scores_json)
        except json.JSONDecodeError:
            return {}

    @avg_scores.setter
    def avg_scores(self, value: dict[str, float]):
        self.avg_scores_json = json.dumps(value)


class LlmTestResult(SQLModel, table=True):
    """Individual LLM test case result."""

    __tablename__ = "llm_test_results"
    __table_args__ = (
        Index("ix_llmtestresult_run_case", "run_id", "test_case_id"),
        {"extend_existing": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="llm_test_runs.id", index=True)
    test_case_id: str
    test_case_name: str

    # I/O
    input_prompt: str = ""
    expected_output: str = ""
    actual_output: str = ""
    model_id: str = ""

    # Metrics
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    estimated_cost_usd: float = 0.0

    # Results
    overall_passed: bool = True
    assertions_json: str = "[]"  # [{name, category, passed, score, explanation}]
    scores_json: str = "{}"  # {metric_name: score}

    @property
    def assertions(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.assertions_json)
        except json.JSONDecodeError:
            return []

    @assertions.setter
    def assertions(self, value: list[dict[str, Any]]):
        self.assertions_json = json.dumps(value)

    @property
    def scores(self) -> dict[str, float]:
        try:
            return json.loads(self.scores_json)
        except json.JSONDecodeError:
            return {}

    @scores.setter
    def scores(self, value: dict[str, float]):
        self.scores_json = json.dumps(value)


class LlmComparisonRun(SQLModel, table=True):
    """Multi-provider comparison run."""

    __tablename__ = "llm_comparison_runs"
    __table_args__ = {"extend_existing": True}

    id: str = Field(primary_key=True)  # llmc-<uuid8>
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    name: str = ""
    spec_name: str = ""
    provider_ids_json: str = "[]"  # ["llm-abc", "llm-def"]
    status: str = "pending"  # pending, running, completed, failed
    winner_provider_id: str | None = None
    comparison_summary_json: str = "{}"  # {provider_id: {pass_rate, avg_latency, cost, scores, wins}}
    error_message: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

    @property
    def provider_ids(self) -> list[str]:
        try:
            return json.loads(self.provider_ids_json)
        except json.JSONDecodeError:
            return []

    @provider_ids.setter
    def provider_ids(self, value: list[str]):
        self.provider_ids_json = json.dumps(value)

    @property
    def comparison_summary(self) -> dict[str, Any]:
        try:
            return json.loads(self.comparison_summary_json)
        except json.JSONDecodeError:
            return {}

    @comparison_summary.setter
    def comparison_summary(self, value: dict[str, Any]):
        self.comparison_summary_json = json.dumps(value)


# ========== OpenAPI Import History ==========


class OpenApiImportHistory(SQLModel, table=True):
    """Persistent history of OpenAPI/Swagger spec imports."""

    __tablename__ = "openapi_import_history"
    __table_args__ = {"extend_existing": True}

    id: str = Field(primary_key=True)  # oai-<uuid8>
    job_id: str | None = Field(default=None, index=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    source_type: str  # "url" or "file"
    source_url: str | None = None
    source_filename: str | None = None
    base_url: str | None = None
    feature_filter: str | None = None
    method_filter_json: str = "[]"
    mode: str = "plan_and_tests"
    status: str = "running"  # running, completed, failed, needs_input
    needs_input: bool = False
    missing_fields_json: str = "[]"
    files_generated: int = 0
    generated_paths_json: str = "[]"
    plan_path: str | None = None
    spec_paths_json: str = "[]"
    test_paths_json: str = "[]"
    evidence_paths_json: str = "[]"
    matched_operations: int = 0
    executed_operations: int = 0
    blocked_operations_json: str = "[]"
    failed_operations_json: str = "[]"
    skipped_operations: int = 0
    chunk_count: int = 0
    recommended_mode: str = "plan_and_tests"
    recommended_next_action: str | None = None
    warnings_json: str = "[]"
    diagnostics_json: str = "{}"
    error_message: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    completed_at: datetime | None = None

    @property
    def generated_paths(self) -> list[str]:
        try:
            return json.loads(self.generated_paths_json)
        except (json.JSONDecodeError, TypeError):
            return []

    @generated_paths.setter
    def generated_paths(self, value: list[str]):
        self.generated_paths_json = json.dumps(value)

    @property
    def method_filter(self) -> list[str]:
        try:
            return json.loads(self.method_filter_json)
        except (json.JSONDecodeError, TypeError):
            return []

    @method_filter.setter
    def method_filter(self, value: list[str]):
        self.method_filter_json = json.dumps(value)

    @property
    def missing_fields(self) -> list[str]:
        try:
            return json.loads(self.missing_fields_json)
        except (json.JSONDecodeError, TypeError):
            return []

    @missing_fields.setter
    def missing_fields(self, value: list[str]):
        self.missing_fields_json = json.dumps(value)

    @property
    def spec_paths(self) -> list[str]:
        try:
            return json.loads(self.spec_paths_json)
        except (json.JSONDecodeError, TypeError):
            return []

    @spec_paths.setter
    def spec_paths(self, value: list[str]):
        self.spec_paths_json = json.dumps(value)

    @property
    def test_paths(self) -> list[str]:
        try:
            return json.loads(self.test_paths_json)
        except (json.JSONDecodeError, TypeError):
            return []

    @test_paths.setter
    def test_paths(self, value: list[str]):
        self.test_paths_json = json.dumps(value)

    @property
    def evidence_paths(self) -> list[str]:
        try:
            return json.loads(self.evidence_paths_json)
        except (json.JSONDecodeError, TypeError):
            return []

    @evidence_paths.setter
    def evidence_paths(self, value: list[str]):
        self.evidence_paths_json = json.dumps(value)

    @property
    def blocked_operations(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.blocked_operations_json)
        except (json.JSONDecodeError, TypeError):
            return []

    @blocked_operations.setter
    def blocked_operations(self, value: list[dict[str, Any]]):
        self.blocked_operations_json = json.dumps(value)

    @property
    def failed_operations(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.failed_operations_json)
        except (json.JSONDecodeError, TypeError):
            return []

    @failed_operations.setter
    def failed_operations(self, value: list[dict[str, Any]]):
        self.failed_operations_json = json.dumps(value)

    @property
    def warnings(self) -> list[str]:
        try:
            return json.loads(self.warnings_json)
        except (json.JSONDecodeError, TypeError):
            return []

    @warnings.setter
    def warnings(self, value: list[str]):
        self.warnings_json = json.dumps(value)

    @property
    def diagnostics(self) -> dict[str, Any]:
        try:
            value = json.loads(self.diagnostics_json)
            return value if isinstance(value, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    @diagnostics.setter
    def diagnostics(self, value: dict[str, Any]):
        self.diagnostics_json = json.dumps(value)


# ========== LLM Dataset Models ==========


class LlmDataset(SQLModel, table=True):
    """LLM test dataset for structured test case collections."""

    __tablename__ = "llm_datasets"
    __table_args__ = {"extend_existing": True}

    id: str = Field(primary_key=True)  # llmd-<uuid8>
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    name: str
    description: str = ""
    version: int = 1
    tags_json: str = "[]"
    total_cases: int = 0
    is_golden: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def tags(self) -> list[str]:
        try:
            return json.loads(self.tags_json)
        except json.JSONDecodeError:
            return []

    @tags.setter
    def tags(self, value: list[str]):
        self.tags_json = json.dumps(value)


class LlmDatasetCase(SQLModel, table=True):
    """Individual test case within an LLM dataset."""

    __tablename__ = "llm_dataset_cases"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    dataset_id: str = Field(foreign_key="llm_datasets.id", index=True)
    case_index: int = 0
    input_prompt: str = ""
    expected_output: str = ""
    context_json: str = "[]"
    assertions_json: str = "[]"
    tags_json: str = "[]"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def context(self) -> list[str]:
        try:
            return json.loads(self.context_json)
        except json.JSONDecodeError:
            return []

    @context.setter
    def context(self, value: list[str]):
        self.context_json = json.dumps(value)

    @property
    def assertions(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.assertions_json)
        except json.JSONDecodeError:
            return []

    @assertions.setter
    def assertions(self, value: list[dict[str, Any]]):
        self.assertions_json = json.dumps(value)

    @property
    def tags(self) -> list[str]:
        try:
            return json.loads(self.tags_json)
        except json.JSONDecodeError:
            return []

    @tags.setter
    def tags(self, value: list[str]):
        self.tags_json = json.dumps(value)


class LlmDatasetVersion(SQLModel, table=True):
    """Version history for LLM dataset mutations."""

    __tablename__ = "llm_dataset_versions"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    dataset_id: str = Field(index=True)
    version: int
    change_type: str = "initial"  # initial, cases_added, cases_removed, cases_modified
    change_summary: str = ""
    cases_snapshot_json: str = "[]"  # [{case_id, hash, input_preview}]
    total_cases: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LlmSchedule(SQLModel, table=True):
    """Scheduled recurring LLM dataset test runs."""

    __tablename__ = "llm_schedules"
    __table_args__ = {"extend_existing": True}

    id: str = Field(primary_key=True)  # llms-<uuid8>
    project_id: str | None = Field(default=None, index=True)
    name: str
    dataset_id: str = Field(index=True)
    provider_ids_json: str = "[]"
    cron_expression: str
    timezone: str = "UTC"
    enabled: bool = True
    notify_on_regression: bool = True
    regression_threshold: float = 20.0
    last_run_at: datetime | None = None
    total_executions: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def provider_ids(self) -> list[str]:
        try:
            return json.loads(self.provider_ids_json)
        except json.JSONDecodeError:
            return []

    @provider_ids.setter
    def provider_ids(self, value: list[str]):
        self.provider_ids_json = json.dumps(value)


class LlmScheduleExecution(SQLModel, table=True):
    """Execution record for a scheduled LLM dataset run."""

    __tablename__ = "llm_schedule_executions"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    schedule_id: str = Field(index=True)
    status: str = "pending"  # pending, running, completed, failed
    run_ids_json: str = "[]"
    dataset_version: int = 0
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def run_ids(self) -> list[str]:
        try:
            return json.loads(self.run_ids_json)
        except json.JSONDecodeError:
            return []

    @run_ids.setter
    def run_ids(self, value: list[str]):
        self.run_ids_json = json.dumps(value)


# ========== LLM Prompt Engineering Models ==========


class LlmSpecVersion(SQLModel, table=True):
    """Version history for LLM test specs."""

    __tablename__ = "llm_spec_versions"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    spec_name: str = Field(index=True)
    version: int
    content: str = ""
    change_summary: str = ""
    system_prompt_hash: str = ""
    run_ids_json: str = "[]"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def run_ids(self) -> list[str]:
        try:
            return json.loads(self.run_ids_json)
        except json.JSONDecodeError:
            return []

    @run_ids.setter
    def run_ids(self, value: list[str]):
        self.run_ids_json = json.dumps(value)


class LlmPromptIteration(SQLModel, table=True):
    """A/B comparison between two spec versions."""

    __tablename__ = "llm_prompt_iterations"
    __table_args__ = {"extend_existing": True}

    id: str = Field(primary_key=True)  # llmi-<uuid8>
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    spec_name: str = Field(index=True)
    name: str = ""
    version_a: int = 0
    version_b: int = 0
    provider_id: str = ""
    run_id_a: str | None = None
    run_id_b: str | None = None
    status: str = "pending"  # pending, running, completed, failed
    winner: str | None = None  # "a", "b", "tie"
    summary_json: str = "{}"
    ai_suggestions: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

    @property
    def summary(self) -> dict[str, Any]:
        try:
            return json.loads(self.summary_json)
        except json.JSONDecodeError:
            return {}

    @summary.setter
    def summary(self, value: dict[str, Any]):
        self.summary_json = json.dumps(value)


# ========== Cron Scheduling Models ==========


class CronSchedule(SQLModel, table=True):
    """Scheduled regression batch configurations with cron expressions."""

    __tablename__ = "cron_schedules"
    __table_args__ = {"extend_existing": True}

    id: str = Field(primary_key=True)  # sched-<uuid8>
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    name: str
    description: str | None = None
    cron_expression: str  # 5-field: "0 8 * * 1-5"
    timezone: str = "UTC"  # IANA timezone

    # Batch configuration
    tags_json: str = "[]"
    automated_only: bool = True
    browser: str = "chromium"
    hybrid_mode: bool = False
    max_iterations: int = 20
    spec_names_json: str = "[]"  # Explicit spec list (empty = use tags/automated_only)

    # State
    enabled: bool = True
    status: str = "active"  # active, paused, error
    last_error: str | None = None

    # Denormalized stats
    last_run_at: datetime | None = None
    last_batch_id: str | None = None
    last_run_status: str | None = None  # passed, failed, mixed
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    avg_duration_seconds: float | None = None

    # Audit
    created_by: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def tags(self) -> list[str]:
        try:
            return json.loads(self.tags_json)
        except json.JSONDecodeError:
            return []

    @tags.setter
    def tags(self, value: list[str]):
        self.tags_json = json.dumps(value)

    @property
    def spec_names(self) -> list[str]:
        try:
            return json.loads(self.spec_names_json)
        except json.JSONDecodeError:
            return []

    @spec_names.setter
    def spec_names(self, value: list[str]):
        self.spec_names_json = json.dumps(value)

    @property
    def success_rate(self) -> float:
        if self.total_executions == 0:
            return 0.0
        return round((self.successful_executions / self.total_executions) * 100, 1)


class ScheduleExecution(SQLModel, table=True):
    """Individual execution records for scheduled runs."""

    __tablename__ = "schedule_executions"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    schedule_id: str = Field(foreign_key="cron_schedules.id", index=True)
    batch_id: str | None = Field(default=None, foreign_key="regression_batches.id", index=True)
    status: str = "pending"  # pending, running, completed, failed, skipped
    trigger_type: str = "cron"  # cron, manual

    # Result summary
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    duration_seconds: int | None = None
    error_message: str | None = None

    # Timestamps
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ========== Autonomous Testing Missions ==========


class AutonomousMission(SQLModel, table=True):
    """Persistent 24/7 autonomous testing mission configuration."""

    __tablename__ = "autonomous_missions"
    __table_args__ = (
        Index("ix_autonomous_missions_project_status", "project_id", "status"),
        Index("ix_autonomous_missions_project_type", "project_id", "mission_type"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    name: str
    description: str | None = None
    mission_type: str = Field(default="mixed", index=True)  # coverage, exploration, regression, flake_triage, mixed
    status: str = Field(default="paused", index=True)  # paused, running, completed, cancelled, error

    target_urls_json: str = "[]"
    schedule_cron: str | None = None
    timezone: str = "UTC"
    autonomy_level: str = "draft_validate"
    approval_policy: str = "approval_required"
    max_runtime_minutes: int = 60
    max_iterations: int = 0  # 0 means unbounded until cancelled
    max_llm_budget_usd: float | None = None
    budget_used_usd: float = 0.0
    config_json: str = "{}"

    latest_workflow_id: str | None = None
    latest_run_id: str | None = None
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    last_error: str | None = None
    health_status: str = Field(default="healthy", index=True)  # healthy, degraded, blocked, offline
    paused_reason: str | None = None
    consecutive_failures: int = 0
    last_heartbeat_at: datetime | None = None
    current_stage: str | None = None
    next_action: str | None = None
    total_runs: int = 0
    total_findings: int = 0

    created_by: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def target_urls(self) -> list[str]:
        try:
            value = json.loads(self.target_urls_json or "[]")
            return [str(item) for item in value if item]
        except json.JSONDecodeError:
            return []

    @target_urls.setter
    def target_urls(self, value: list[str]):
        self.target_urls_json = json.dumps(value)

    @property
    def config(self) -> dict[str, Any]:
        try:
            value = json.loads(self.config_json or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    @config.setter
    def config(self, value: dict[str, Any]):
        self.config_json = json.dumps(value)


class AutonomousMissionRun(SQLModel, table=True):
    """One durable execution iteration of an autonomous testing mission."""

    __tablename__ = "autonomous_mission_runs"
    __table_args__ = (
        Index("ix_autonomous_runs_mission_created", "mission_id", "created_at"),
        Index("ix_autonomous_runs_project_status", "project_id", "status"),
        Index("ix_autonomous_runs_workflow", "workflow_id"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)
    mission_id: str = Field(foreign_key="autonomous_missions.id", index=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    workflow_id: str | None = None
    mission_type: str = "mixed"
    trigger_type: str = "temporal"  # manual, temporal, schedule, webhook
    status: str = Field(default="queued", index=True)  # queued, running, completed, failed, cancelled
    current_stage: str | None = None
    summary_json: str = "{}"
    artifacts_json: str = "[]"
    checkpoint_json: str = "{}"
    error_message: str | None = None
    budget_used_usd: float = 0.0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def summary(self) -> dict[str, Any]:
        try:
            value = json.loads(self.summary_json or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    @summary.setter
    def summary(self, value: dict[str, Any]):
        self.summary_json = json.dumps(value)

    @property
    def artifacts(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.artifacts_json or "[]")
            return value if isinstance(value, list) else []
        except json.JSONDecodeError:
            return []

    @artifacts.setter
    def artifacts(self, value: list[dict[str, Any]]):
        self.artifacts_json = json.dumps(value)

    @property
    def checkpoint(self) -> dict[str, Any]:
        try:
            value = json.loads(self.checkpoint_json or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    @checkpoint.setter
    def checkpoint(self, value: dict[str, Any]):
        self.checkpoint_json = json.dumps(value)


class AutonomousAgentWorkItem(SQLModel, table=True):
    """Durable child work item assigned to one autonomous mission agent."""

    __tablename__ = "autonomous_agent_work_items"
    __table_args__ = (
        Index("ix_autonomous_work_items_mission_status", "mission_id", "status"),
        Index("ix_autonomous_work_items_project_status", "project_id", "status"),
        Index("ix_autonomous_work_items_agent_task", "agent_task_id"),
        Index("ix_autonomous_work_items_role_status", "role", "status"),
        Index("ix_autonomous_work_items_mission_planner", "mission_id", "planner_key"),
        Index("ix_autonomous_work_items_mission_lease", "mission_id", "lease_until"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)
    mission_id: str = Field(foreign_key="autonomous_missions.id", index=True)
    run_id: str | None = Field(default=None, foreign_key="autonomous_mission_runs.id", index=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    role: str = Field(index=True)
    planner_key: str | None = Field(default=None, index=True)
    objective: str = Field(sa_column=Column(Text))
    assigned_surface_json: str = "[]"
    status: str = Field(default="queued", index=True)  # queued, running, completed, failed, blocked, cancelled
    priority: int = Field(default=50, index=True)
    agent_task_id: str | None = Field(default=None, index=True)
    progress_json: str = "{}"
    artifacts_json: str = "[]"
    result_json: str = "{}"
    error_message: str | None = None
    attempt_count: int = 0
    budget_used_usd: float = 0.0
    started_at: datetime | None = None
    lease_until: datetime | None = None
    last_heartbeat_at: datetime | None = None
    recovery_count: int = 0
    recovery_reason: str | None = None
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def assigned_surface(self) -> list[str]:
        try:
            value = json.loads(self.assigned_surface_json or "[]")
            return [str(item) for item in value if item]
        except json.JSONDecodeError:
            return []

    @assigned_surface.setter
    def assigned_surface(self, value: list[str]):
        self.assigned_surface_json = json.dumps(value)

    @property
    def progress(self) -> dict[str, Any]:
        try:
            value = json.loads(self.progress_json or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    @progress.setter
    def progress(self, value: dict[str, Any]):
        self.progress_json = json.dumps(value)

    @property
    def artifacts(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.artifacts_json or "[]")
            return value if isinstance(value, list) else []
        except json.JSONDecodeError:
            return []

    @artifacts.setter
    def artifacts(self, value: list[dict[str, Any]]):
        self.artifacts_json = json.dumps(value)

    @property
    def result(self) -> dict[str, Any]:
        try:
            value = json.loads(self.result_json or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    @result.setter
    def result(self, value: dict[str, Any]):
        self.result_json = json.dumps(value)


class AutonomousAgentEvent(SQLModel, table=True):
    """Durable observable event emitted by autonomous mission agents."""

    __tablename__ = "autonomous_agent_events"
    __table_args__ = (
        Index("ix_autonomous_agent_events_mission_sequence", "mission_id", "sequence"),
        Index("ix_autonomous_agent_events_work_item_sequence", "work_item_id", "sequence"),
        Index("ix_autonomous_agent_events_project_created", "project_id", "created_at"),
        Index("ix_autonomous_agent_events_agent_task", "agent_task_id"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    mission_id: str = Field(foreign_key="autonomous_missions.id", index=True)
    run_id: str | None = Field(default=None, foreign_key="autonomous_mission_runs.id", index=True)
    work_item_id: str | None = Field(default=None, foreign_key="autonomous_agent_work_items.id", index=True)
    agent_task_id: str | None = Field(default=None, index=True)
    sequence: int = Field(index=True)
    event_type: str = Field(index=True)  # lifecycle, status, assistant_output, tool_call, browser_action, pause, resume, error, complete
    level: str = Field(default="info", index=True)
    message: str = Field(sa_column=Column(Text))
    payload_json: str = Field(default="{}", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    @property
    def payload(self) -> dict[str, Any]:
        try:
            value = json.loads(self.payload_json or "{}")
            return value if isinstance(value, dict) else {"value": value}
        except json.JSONDecodeError:
            return {}

    @payload.setter
    def payload(self, value: dict[str, Any]):
        self.payload_json = json.dumps(value)


class AutonomousFinding(SQLModel, table=True):
    """Validated internal finding produced by an autonomous mission."""

    __tablename__ = "autonomous_findings"
    __table_args__ = (
        Index("ix_autonomous_findings_project_status", "project_id", "status"),
        Index("ix_autonomous_findings_mission_created", "mission_id", "created_at"),
        Index("ix_autonomous_findings_dedupe", "project_id", "dedupe_key"),
        UniqueConstraint("project_id", "dedupe_key", name="uq_autonomous_findings_project_dedupe"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)
    mission_id: str = Field(foreign_key="autonomous_missions.id", index=True)
    run_id: str | None = Field(default=None, foreign_key="autonomous_mission_runs.id", index=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    finding_type: str = Field(index=True)  # coverage_gap, bug, flake, security, exploration
    severity: str = "medium"
    title: str
    description: str = Field(sa_column=Column(Text))
    status: str = Field(default="open", index=True)  # open, awaiting_approval, approved, rejected, resolved
    confidence: float = 0.7
    dedupe_key: str = Field(index=True)
    evidence_json: str = "{}"
    source_type: str | None = None
    source_id: str | None = None
    approval_required: bool = True
    external_issue_url: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def evidence(self) -> dict[str, Any]:
        try:
            value = json.loads(self.evidence_json or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    @evidence.setter
    def evidence(self, value: dict[str, Any]):
        self.evidence_json = json.dumps(value)


class AutonomousTestProposal(SQLModel, table=True):
    """Approval-gated generated test artifact proposed by an autonomous mission."""

    __tablename__ = "autonomous_test_proposals"
    __table_args__ = (
        Index("ix_autonomous_test_proposals_project_status", "project_id", "approval_status"),
        Index("ix_autonomous_test_proposals_mission_created", "mission_id", "created_at"),
        Index("ix_autonomous_test_proposals_dedupe", "project_id", "dedupe_key"),
        UniqueConstraint("project_id", "dedupe_key", name="uq_autonomous_test_proposals_project_dedupe"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)
    mission_id: str = Field(foreign_key="autonomous_missions.id", index=True)
    run_id: str | None = Field(default=None, foreign_key="autonomous_mission_runs.id", index=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    finding_id: str | None = Field(default=None, foreign_key="autonomous_findings.id", index=True)
    coverage_gap_id: int | None = Field(default=None, foreign_key="coverage_gaps.id", index=True)
    approval_id: str | None = Field(default=None, foreign_key="autonomous_approvals.id", index=True)

    title: str
    target_url: str | None = None
    route: str | None = None
    test_type: str = Field(index=True)  # e2e, api, regression, security, accessibility, unit
    rationale: str = Field(sa_column=Column(Text))
    generated_spec_content: str = Field(sa_column=Column(Text))
    suggested_file_path: str
    risk_level: str = "medium"
    approval_status: str = Field(default="pending", index=True)  # pending, approved, rejected, materialized
    dedupe_key: str = Field(index=True)
    source_type: str | None = None
    source_id: str | None = None
    source_metadata_json: str = "{}"
    materialized_file_path: str | None = None
    materialization_result_json: str | None = None
    validation_status: str = Field(default="not_run", index=True)
    validation_result_json: str | None = None
    validation_artifacts_json: str = "[]"
    validation_log_path: str | None = None
    validation_trace_path: str | None = None
    validated_at: datetime | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    rejected_by: str | None = None
    rejected_at: datetime | None = None
    materialized_by: str | None = None
    materialized_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def source_metadata(self) -> dict[str, Any]:
        try:
            value = json.loads(self.source_metadata_json or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    @source_metadata.setter
    def source_metadata(self, value: dict[str, Any]):
        self.source_metadata_json = json.dumps(value)

    @property
    def materialization_result(self) -> dict[str, Any] | None:
        if not self.materialization_result_json:
            return None
        try:
            value = json.loads(self.materialization_result_json)
            return value if isinstance(value, dict) else {"value": value}
        except json.JSONDecodeError:
            return None

    @materialization_result.setter
    def materialization_result(self, value: dict[str, Any] | None):
        self.materialization_result_json = json.dumps(value) if value is not None else None

    @property
    def validation_result(self) -> dict[str, Any] | None:
        if not self.validation_result_json:
            return None
        try:
            value = json.loads(self.validation_result_json)
            return value if isinstance(value, dict) else {"value": value}
        except json.JSONDecodeError:
            return None

    @validation_result.setter
    def validation_result(self, value: dict[str, Any] | None):
        self.validation_result_json = json.dumps(value) if value is not None else None

    @property
    def validation_artifacts(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.validation_artifacts_json or "[]")
            return value if isinstance(value, list) else []
        except json.JSONDecodeError:
            return []

    @validation_artifacts.setter
    def validation_artifacts(self, value: list[dict[str, Any]]):
        self.validation_artifacts_json = json.dumps(value)


class AutonomousApproval(SQLModel, table=True):
    """Human approval gate for high-impact autonomous actions."""

    __tablename__ = "autonomous_approvals"
    __table_args__ = (
        Index("ix_autonomous_approvals_project_status", "project_id", "status"),
        Index("ix_autonomous_approvals_mission_status", "mission_id", "status"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)
    mission_id: str = Field(foreign_key="autonomous_missions.id", index=True)
    run_id: str | None = Field(default=None, foreign_key="autonomous_mission_runs.id", index=True)
    finding_id: str | None = Field(default=None, foreign_key="autonomous_findings.id", index=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    action_type: str = "external_issue"  # external_issue, persist_test, quarantine_test
    status: str = Field(default="pending", index=True)  # pending, approved, rejected, expired
    requested_payload_json: str = "{}"
    response_json: str | None = None
    decided_by: str | None = None
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    decided_at: datetime | None = None

    @property
    def requested_payload(self) -> dict[str, Any]:
        try:
            value = json.loads(self.requested_payload_json or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    @requested_payload.setter
    def requested_payload(self, value: dict[str, Any]):
        self.requested_payload_json = json.dumps(value)

    @property
    def response(self) -> dict[str, Any] | None:
        if not self.response_json:
            return None
        try:
            value = json.loads(self.response_json)
            return value if isinstance(value, dict) else {"value": value}
        except json.JSONDecodeError:
            return None

    @response.setter
    def response(self, value: dict[str, Any] | None):
        self.response_json = json.dumps(value) if value is not None else None


# ========== CI/CD Pipeline Integration Models ==========


class CiPipelineMapping(SQLModel, table=True):
    """Tracks CI/CD pipeline runs triggered from or received by the platform."""

    __tablename__ = "ci_pipeline_mappings"
    __table_args__ = (
        Index("ix_ci_pipeline_project_provider_created", "project_id", "provider", "created_at"),
        Index("ix_ci_pipeline_project_provider_external", "project_id", "provider", "external_pipeline_id", unique=True),
        {"extend_existing": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    provider: str = Field(index=True)  # "gitlab" or "github"

    # External identifiers
    external_pipeline_id: str = Field(index=True)
    external_project_id: str | None = None
    external_url: str | None = None
    ref: str | None = None  # Branch/tag

    # Context
    triggered_from: str = "dashboard"  # dashboard, schedule, webhook
    batch_id: str | None = Field(default=None, foreign_key="regression_batches.id", index=True)
    schedule_id: str | None = Field(default=None, foreign_key="cron_schedules.id", index=True)

    # Status
    status: str = "pending"  # pending, running, success, failed, cancelled
    stages_json: str = "[]"

    # Results
    total_tests: int | None = None
    passed_tests: int | None = None
    failed_tests: int | None = None
    test_report_url: str | None = None
    artifacts_json: str = "[]"

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def stages(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.stages_json)
        except json.JSONDecodeError:
            return []

    @stages.setter
    def stages(self, value: list[dict[str, Any]]):
        self.stages_json = json.dumps(value)

    @property
    def artifacts(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.artifacts_json)
        except json.JSONDecodeError:
            return []

    @artifacts.setter
    def artifacts(self, value: list[dict[str, Any]]):
        self.artifacts_json = json.dumps(value)


class CiWorkflowChangeRequest(SQLModel, table=True):
    """A generated CI workflow proposal awaiting human review."""

    __tablename__ = "ci_workflow_change_requests"
    __table_args__ = (
        Index("ix_ci_workflow_change_project_created", "project_id", "created_at"),
        Index("ix_ci_workflow_change_project_status", "project_id", "status"),
        {"extend_existing": True},
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    provider: str = Field(default="github", index=True)
    workflow_name: str
    workflow_path: str
    ref: str | None = None
    status: str = Field(default="draft", index=True)  # draft, proposed, opened, rejected
    generated_yaml: str = Field(sa_column=Column(Text))
    prompt: str | None = Field(default=None, sa_column=Column(Text))
    validation_errors: list[str] | None = Field(default=None, sa_column=Column(JSON))
    validation_warnings: list[str] | None = Field(default=None, sa_column=Column(JSON))
    pull_request_url: str | None = None
    pull_request_number: int | None = None
    pull_request_branch: str | None = None
    pull_request_base_ref: str | None = None
    commit_sha: str | None = None
    last_error: str | None = Field(default=None, sa_column=Column(Text))
    created_by: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CiAuditEvent(SQLModel, table=True):
    """Audit trail for CI/CD actions initiated from Quorvex."""

    __tablename__ = "ci_audit_events"
    __table_args__ = (
        Index("ix_ci_audit_project_created", "project_id", "created_at"),
        Index("ix_ci_audit_project_action", "project_id", "action"),
        {"extend_existing": True},
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    provider: str = Field(index=True)
    action: str = Field(index=True)
    target_type: str | None = None
    target_id: str | None = None
    status: str = Field(default="ok", index=True)
    actor_id: str | None = None
    actor_email: str | None = None
    event_metadata: dict[str, Any] | None = Field(default=None, sa_column=Column("metadata", JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class CiTestSubset(SQLModel, table=True):
    """Named set of generated tests that can be installed into CI."""

    __tablename__ = "ci_test_subsets"
    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_ci_test_subset_project_slug"),
        Index("ix_ci_test_subset_project_created", "project_id", "created_at"),
        Index("ix_ci_test_subset_project_slug", "project_id", "slug"),
        {"extend_existing": True},
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    name: str
    slug: str = Field(index=True)
    description: str | None = None
    mode: str = Field(default="both", index=True)  # manual, pr-impact, both
    default_browser: str = "chromium"
    base_url_secret: str = "APP_BASE_URL"
    created_by: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CiTestSubsetItem(SQLModel, table=True):
    """One generated test file selected into a CI subset."""

    __tablename__ = "ci_test_subset_items"
    __table_args__ = (
        UniqueConstraint("subset_id", "spec_name", name="uq_ci_test_subset_item_spec"),
        Index("ix_ci_test_subset_items_subset", "subset_id"),
        Index("ix_ci_test_subset_items_spec", "spec_name"),
        {"extend_existing": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    subset_id: str = Field(foreign_key="ci_test_subsets.id", index=True)
    spec_name: str = Field(index=True)
    code_path: str
    target_path: str
    content_hash: str
    tags: list[str] | None = Field(default=None, sa_column=Column(JSON))
    categories: list[str] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PrImpactAnalysis(SQLModel, table=True):
    """Stored PR test-impact recommendation for a project repository."""

    __tablename__ = "pr_impact_analyses"
    __table_args__ = (
        Index("ix_pr_impact_project_created", "project_id", "created_at"),
        Index("ix_pr_impact_project_pr", "project_id", "pr_number"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    provider: str = Field(default="github", index=True)
    owner: str
    repo: str
    pr_number: int = Field(index=True)
    title: str | None = None
    base_ref: str | None = None
    head_ref: str | None = None
    head_sha: str | None = None
    author: str | None = None

    status: str = Field(default="completed", index=True)
    risk_level: str = Field(default="medium", index=True)
    confidence: str = Field(default="medium", index=True)
    summary: str | None = None
    fallback_reason: str | None = None
    ai_notes: str | None = None

    changed_files_count: int = 0
    selected_tests_count: int = 0
    total_candidate_tests: int = 0
    estimated_duration_seconds: int | None = None
    saved_tests_count: int | None = None
    category_summary: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    batch_id: str | None = Field(default=None, foreign_key="regression_batches.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = Field(default_factory=datetime.utcnow)


class PrQualityGateRun(SQLModel, table=True):
    """Durable CI-facing quality gate run for a specific PR head SHA."""

    __tablename__ = "pr_quality_gate_runs"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "provider",
            "owner",
            "repo",
            "pr_number",
            "head_sha",
            name="uq_pr_quality_gate_identity",
        ),
        Index("ix_pr_quality_gate_project_pr_sha", "project_id", "pr_number", "head_sha"),
        Index("ix_pr_quality_gate_batch", "batch_id"),
        Index("ix_pr_quality_gate_status_updated", "status", "updated_at"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    provider: str = Field(default="github", index=True)
    owner: str
    repo: str
    pr_number: int = Field(index=True)
    head_sha: str = Field(index=True)
    analysis_id: str | None = Field(default=None, foreign_key="pr_impact_analyses.id", index=True)
    batch_id: str | None = Field(default=None, foreign_key="regression_batches.id", index=True)

    status: str = Field(default="initializing", index=True)
    github_state: str = Field(default="pending", index=True)
    error_message: str | None = None

    post_feedback: bool = True
    create_commit_status: bool = True
    feedback_comment_id: str | None = None
    feedback_comment_url: str | None = None
    commit_status_url: str | None = None
    last_feedback_state: str | None = None
    feedback_errors_json: str = "[]"
    final_feedback_published_at: datetime | None = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

    @property
    def feedback_errors(self) -> list[str]:
        try:
            return json.loads(self.feedback_errors_json)
        except json.JSONDecodeError:
            return []

    @feedback_errors.setter
    def feedback_errors(self, value: list[str]):
        self.feedback_errors_json = json.dumps(value)


class PrChangedFile(SQLModel, table=True):
    """Changed file captured for a PR impact analysis."""

    __tablename__ = "pr_changed_files"
    __table_args__ = (
        Index("ix_pr_changed_analysis", "analysis_id"),
        Index("ix_pr_changed_path", "path"),
        {"extend_existing": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    analysis_id: str = Field(foreign_key="pr_impact_analyses.id", index=True)
    path: str = Field(index=True)
    status: str = "modified"
    additions: int = 0
    deletions: int = 0
    changes: int = 0
    previous_filename: str | None = None
    area: str = "unknown"
    risk_level: str = "medium"
    reason: str | None = None


class PrSelectedTest(SQLModel, table=True):
    """Test selected by a PR impact analysis with its explanation."""

    __tablename__ = "pr_selected_tests"
    __table_args__ = (
        Index("ix_pr_selected_analysis", "analysis_id"),
        Index("ix_pr_selected_spec", "spec_name"),
        {"extend_existing": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    analysis_id: str = Field(foreign_key="pr_impact_analyses.id", index=True)
    spec_name: str = Field(index=True)
    test_path: str | None = None
    reason: str
    confidence: str = "medium"
    risk_level: str = "medium"
    selection_source: str = "rule"
    estimated_duration_seconds: int | None = None
    tags: list[str] | None = Field(default=None, sa_column=Column(JSON))
    categories: list[str] | None = Field(default=None, sa_column=Column(JSON))


class TestImpactMap(SQLModel, table=True):
    """Project-level mapping from source areas/files to specs/tests."""

    __tablename__ = "test_impact_maps"
    __table_args__ = (
        Index("ix_test_impact_project_spec", "project_id", "spec_name"),
        {"extend_existing": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    spec_name: str = Field(index=True)
    test_path: str | None = None
    impacted_paths: list[str] | None = Field(default=None, sa_column=Column(JSON))
    tags: list[str] | None = Field(default=None, sa_column=Column(JSON))
    categories: list[str] | None = Field(default=None, sa_column=Column(JSON))
    source: str = "metadata"
    confidence: str = "medium"
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TestExecutionHistory(SQLModel, table=True):
    """Normalized test execution facts used by PR test selection."""

    __tablename__ = "test_execution_history"
    __table_args__ = (
        Index("ix_test_history_project_spec", "project_id", "spec_name"),
        Index("ix_test_history_project_executed", "project_id", "executed_at"),
        Index("ix_test_history_run_id", "run_id"),
        {"extend_existing": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    spec_name: str = Field(index=True)
    test_name: str | None = None
    test_path: str | None = None
    browser: str = "chromium"
    status: str = Field(index=True)
    duration_seconds: int | None = None
    failure_category: str | None = None
    run_id: str | None = Field(default=None, foreign_key="testrun.id", index=True)
    batch_id: str | None = Field(default=None, foreign_key="regression_batches.id", index=True)
    is_flaky: bool = False
    executed_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class RepoIndexSnapshot(SQLModel, table=True):
    """Indexed view of a tested repository used before PR impact analysis."""

    __tablename__ = "repo_index_snapshots"
    __table_args__ = (
        Index("ix_repo_index_project_created", "project_id", "created_at"),
        Index("ix_repo_index_project_ref", "project_id", "ref"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    provider: str = Field(default="github", index=True)
    owner: str
    repo: str
    ref: str
    commit_sha: str | None = None
    status: str = Field(default="completed", index=True)
    indexed_files_count: int = 0
    source_files_count: int = 0
    test_files_count: int = 0
    route_count: int = 0
    summary: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = Field(default_factory=datetime.utcnow)


class RepoIndexedFile(SQLModel, table=True):
    """A parsed repository file from a RepoIndexSnapshot."""

    __tablename__ = "repo_indexed_files"
    __table_args__ = (
        Index("ix_repo_indexed_snapshot_path", "snapshot_id", "path"),
        Index("ix_repo_indexed_project_path", "project_id", "path"),
        {"extend_existing": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    snapshot_id: str = Field(foreign_key="repo_index_snapshots.id", index=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    path: str = Field(index=True)
    file_type: str = "source"  # source, test, config, docs, unknown
    area: str = "unknown"
    language: str | None = None
    size: int | None = None
    sha: str | None = None
    imports: list[str] | None = Field(default=None, sa_column=Column(JSON))
    imported_by: list[str] | None = Field(default=None, sa_column=Column(JSON))
    routes: list[str] | None = Field(default=None, sa_column=Column(JSON))
    symbols: list[str] | None = Field(default=None, sa_column=Column(JSON))
    keywords: list[str] | None = Field(default=None, sa_column=Column(JSON))
    risk_flags: list[str] | None = Field(default=None, sa_column=Column(JSON))


# ========== AI Assistant Chat Models ==========


class ChatConversation(SQLModel, table=True):
    """Chat conversations for the AI assistant."""

    __tablename__ = "chat_conversations"
    __table_args__ = (
        Index("ix_chatconversation_project_created", "project_id", "created_at"),
        {"extend_existing": True},
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    user_id: str | None = Field(default=None, index=True)
    title: str = "New Conversation"
    is_starred: bool = Field(default=False)
    summary: str | None = Field(default=None)  # Auto-generated conversation summary
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ChatMessage(SQLModel, table=True):
    """Individual messages within a chat conversation."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chatmessage_conversation_created", "conversation_id", "created_at"),
        {"extend_existing": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    conversation_id: str = Field(foreign_key="chat_conversations.id", index=True)
    role: str  # user, assistant, tool
    content: str = ""
    tool_name: str | None = None
    tool_args_json: str | None = None
    tool_result_json: str | None = None
    content_json: str | None = None  # Full UIMessage parts as JSON for round-trip fidelity
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def tool_args(self) -> dict[str, Any] | None:
        if not self.tool_args_json:
            return None
        try:
            return json.loads(self.tool_args_json)
        except json.JSONDecodeError:
            return None

    @tool_args.setter
    def tool_args(self, value: dict[str, Any] | None):
        self.tool_args_json = json.dumps(value) if value else None

    @property
    def tool_result(self) -> dict[str, Any] | None:
        if not self.tool_result_json:
            return None
        try:
            return json.loads(self.tool_result_json)
        except json.JSONDecodeError:
            return None

    @tool_result.setter
    def tool_result(self, value: dict[str, Any] | None):
        self.tool_result_json = json.dumps(value) if value else None


class ChatMessageFeedback(SQLModel, table=True):
    """Feedback on AI assistant messages (thumbs up/down)."""

    __tablename__ = "chat_message_feedback"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    conversation_id: str = Field(foreign_key="chat_conversations.id", index=True)
    message_index: int  # Index of the message in the conversation
    rating: str  # "up" or "down"
    comment: str | None = None
    user_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentMemory(SQLModel, table=True):
    """Curated working memory for assistant and autonomous agents."""

    __tablename__ = "agent_memories"
    __table_args__ = (
        Index("ix_agentmemory_project_status", "project_id", "status"),
        Index("ix_agentmemory_project_kind", "project_id", "kind"),
        Index("ix_agentmemory_project_type", "project_id", "memory_type"),
        Index("ix_agentmemory_scope_status", "scope", "status"),
        Index("ix_agentmemory_user_status", "user_id", "status"),
        Index("ix_agentmemory_source", "source_type", "source_id"),
        Index("ix_agentmemory_last_used", "last_used_at"),
        {"extend_existing": True},
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    user_id: str | None = Field(default=None, index=True)
    kind: str = Field(index=True)
    memory_type: str = Field(default="semantic", index=True)
    scope: str = Field(default="project", index=True)
    content: str = Field(sa_column=Column(Text))
    summary: str | None = Field(default=None, sa_column=Column(Text))
    tags: list[str] | None = Field(default=None, sa_column=Column(JSON))
    confidence: float = Field(default=0.7)
    importance: float = Field(default=0.5)
    source_type: str | None = None
    source_id: str | None = None
    agent_type: str | None = Field(default=None, index=True)
    status: str = Field(default="active", index=True)
    supersedes_id: str | None = Field(default=None, index=True)
    review_required: bool = Field(default=False)
    extra_data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_verified_at: datetime | None = None
    last_used_at: datetime | None = None
    use_count: int = Field(default=0)


class MemoryInjectionEvent(SQLModel, table=True):
    """Audit record of memory context injected into a prompt or agent task."""

    __tablename__ = "memory_injection_events"
    __table_args__ = (
        Index("ix_memory_injection_project_created", "project_id", "created_at"),
        Index("ix_memory_injection_stage_created", "stage", "created_at"),
        Index("ix_memory_injection_source", "source_type", "source_id"),
        {"extend_existing": True},
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    actor_type: str = Field(index=True)
    stage: str = Field(index=True)
    source_type: str | None = Field(default=None, index=True)
    source_id: str | None = Field(default=None, index=True)
    query: str = Field(default="", sa_column=Column(Text))
    memory_ids_json: str = Field(default="[]", sa_column=Column(Text))
    context_preview: str = Field(default="", sa_column=Column(Text))
    outcome: str = Field(default="injected", index=True)
    extra_data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    @property
    def memory_ids(self) -> list[str]:
        try:
            value = json.loads(self.memory_ids_json or "[]")
            return [str(item) for item in value] if isinstance(value, list) else []
        except json.JSONDecodeError:
            return []

    @memory_ids.setter
    def memory_ids(self, value: list[str]):
        self.memory_ids_json = json.dumps(value)


class MemoryFeedbackEvent(SQLModel, table=True):
    """Durable user/system feedback attributed to an injected memory."""

    __tablename__ = "memory_feedback_events"
    __table_args__ = (
        Index("ix_memory_feedback_project_created", "project_id", "created_at"),
        Index("ix_memory_feedback_memory", "memory_id"),
        Index("ix_memory_feedback_injection", "injection_event_id"),
        Index("ix_memory_feedback_source", "source"),
        {"extend_existing": True},
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    memory_id: str = Field(foreign_key="agent_memories.id", index=True)
    injection_event_id: str | None = Field(default=None, foreign_key="memory_injection_events.id", index=True)
    conversation_id: str | None = Field(default=None, foreign_key="chat_conversations.id", index=True)
    message_index: int | None = None
    rating: str = Field(index=True)
    signal: float = Field(default=0.0)
    source: str = Field(default="manual_dashboard", index=True)
    comment: str | None = Field(default=None, sa_column=Column(Text))
    user_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class MemoryFeedbackAggregate(SQLModel, table=True):
    """Project-scoped aggregate feedback signal for graph scoring."""

    __tablename__ = "memory_feedback_aggregates"
    __table_args__ = (
        Index("ix_memory_feedback_aggregate_project_score", "project_id", "feedback_score"),
        Index("ix_memory_feedback_aggregate_memory", "memory_id"),
        UniqueConstraint("project_key", "memory_id", name="uq_memory_feedback_aggregate_project_memory"),
        {"extend_existing": True},
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    project_key: str = Field(default="__global__", index=True)
    memory_id: str = Field(foreign_key="agent_memories.id", index=True)
    positive_feedback_count: int = Field(default=0)
    negative_feedback_count: int = Field(default=0)
    feedback_score: float = Field(default=0.0)
    last_feedback_at: datetime | None = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MemoryGraphNode(SQLModel, table=True):
    """Typed node in the agent memory knowledge graph."""

    __tablename__ = "memory_graph_nodes"
    __table_args__ = (
        Index("ix_memory_graph_nodes_project_type", "project_id", "node_type"),
        Index("ix_memory_graph_nodes_project_status", "project_id", "status"),
        Index("ix_memory_graph_nodes_memory", "memory_id"),
        UniqueConstraint("project_id", "node_type", "entity_key", name="uq_memory_graph_node_identity"),
        {"extend_existing": True},
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    node_type: str = Field(index=True)
    label: str = Field(sa_column=Column(Text))
    memory_id: str | None = Field(default=None, foreign_key="agent_memories.id", index=True)
    entity_key: str = Field(index=True)
    confidence: float = Field(default=0.7)
    status: str = Field(default="active", index=True)
    extra_data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MemoryGraphEdge(SQLModel, table=True):
    """Typed relationship between knowledge graph nodes."""

    __tablename__ = "memory_graph_edges"
    __table_args__ = (
        Index("ix_memory_graph_edges_project_type", "project_id", "relationship_type"),
        Index("ix_memory_graph_edges_source", "source_node_id"),
        Index("ix_memory_graph_edges_target", "target_node_id"),
        Index("ix_memory_graph_edges_evidence", "evidence_memory_id"),
        UniqueConstraint(
            "project_id",
            "source_node_id",
            "target_node_id",
            "relationship_type",
            name="uq_memory_graph_edge_identity",
        ),
        {"extend_existing": True},
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    source_node_id: str = Field(foreign_key="memory_graph_nodes.id", index=True)
    target_node_id: str = Field(foreign_key="memory_graph_nodes.id", index=True)
    relationship_type: str = Field(index=True)
    weight: float = Field(default=0.7)
    evidence_memory_id: str | None = Field(default=None, foreign_key="agent_memories.id", index=True)
    status: str = Field(default="active", index=True)
    extra_data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ========== Auto Pilot Pipeline Models ==========


class AutoPilotSession(SQLModel, table=True):
    """Auto Pilot end-to-end test engineering pipeline session."""

    __tablename__ = "autopilot_sessions"
    __table_args__ = (
        Index("ix_autopilotsession_project_status", "project_id", "status"),
        {"extend_existing": True},
    )

    id: str = Field(primary_key=True)  # autopilot_YYYY-MM-DD_HH-MM-SS
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)

    # User inputs
    entry_urls_json: str = "[]"
    login_url: str | None = None
    credentials_json: str = "{}"
    test_data_json: str = "{}"
    instructions: str | None = None
    config_json: str = "{}"

    # State machine
    status: str = "pending"  # pending, running, awaiting_input, paused,
    # completed, failed, cancelled
    current_phase: str | None = None
    current_phase_progress: float = 0.0
    overall_progress: float = 0.0
    phases_completed_json: str = "[]"
    temporal_workflow_id: str | None = Field(default=None, index=True)
    temporal_run_id: str | None = None

    # Linked entities (multiple exploration sessions for multi-URL)
    exploration_session_ids_json: str = "[]"

    # Aggregate stats
    total_pages_discovered: int = 0
    total_flows_discovered: int = 0
    total_requirements_generated: int = 0
    total_specs_generated: int = 0
    total_tests_generated: int = 0
    total_tests_passed: int = 0
    total_tests_failed: int = 0
    coverage_percentage: float = 0.0

    # Error & timing
    error_message: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    triggered_by: str | None = None

    @property
    def entry_urls(self) -> list[str]:
        try:
            return json.loads(self.entry_urls_json)
        except json.JSONDecodeError:
            return []

    @entry_urls.setter
    def entry_urls(self, value: list[str]):
        self.entry_urls_json = json.dumps(value)

    @property
    def credentials(self) -> dict[str, Any]:
        try:
            return json.loads(self.credentials_json)
        except json.JSONDecodeError:
            return {}

    @credentials.setter
    def credentials(self, value: dict[str, Any]):
        self.credentials_json = json.dumps(value)

    @property
    def test_data(self) -> dict[str, Any]:
        try:
            return json.loads(self.test_data_json)
        except json.JSONDecodeError:
            return {}

    @test_data.setter
    def test_data(self, value: dict[str, Any]):
        self.test_data_json = json.dumps(value)

    @property
    def config(self) -> dict[str, Any]:
        try:
            return json.loads(self.config_json)
        except json.JSONDecodeError:
            return {}

    @config.setter
    def config(self, value: dict[str, Any]):
        self.config_json = json.dumps(value)

    @property
    def phases_completed(self) -> list[str]:
        try:
            return json.loads(self.phases_completed_json)
        except json.JSONDecodeError:
            return []

    @phases_completed.setter
    def phases_completed(self, value: list[str]):
        self.phases_completed_json = json.dumps(value)

    @property
    def exploration_session_ids(self) -> list[str]:
        try:
            return json.loads(self.exploration_session_ids_json)
        except json.JSONDecodeError:
            return []

    @exploration_session_ids.setter
    def exploration_session_ids(self, value: list[str]):
        self.exploration_session_ids_json = json.dumps(value)


class AutoPilotPhase(SQLModel, table=True):
    """Individual phase within an Auto Pilot session."""

    __tablename__ = "autopilot_phases"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="autopilot_sessions.id", index=True)
    phase_name: str  # exploration, requirements, spec_generation,
    # test_generation, reporting
    phase_order: int
    status: str = "pending"  # pending, running, completed, failed, skipped
    progress: float = 0.0
    current_step: str | None = None  # Human-readable: "Exploring login flow..."
    items_total: int = 0
    items_completed: int = 0
    result_summary_json: str = "{}"
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def result_summary(self) -> dict[str, Any]:
        try:
            return json.loads(self.result_summary_json)
        except json.JSONDecodeError:
            return {}

    @result_summary.setter
    def result_summary(self, value: dict[str, Any]):
        self.result_summary_json = json.dumps(value)


class AutoPilotQuestion(SQLModel, table=True):
    """Questions the pipeline asks the user mid-execution."""

    __tablename__ = "autopilot_questions"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="autopilot_sessions.id", index=True)
    phase_name: str  # Which phase triggered the question
    question_type: str  # review_exploration, review_requirements,
    # need_test_data, confirm_skip, custom
    question_text: str  # The actual question
    context_json: str = "{}"  # Supporting data (flow summaries, etc.)
    suggested_answers_json: str = "[]"  # ["Proceed with all", "Focus on auth only", ...]
    default_answer: str | None = None  # Auto-selected if timeout

    # Response
    status: str = "pending"  # pending, answered, auto_continued, skipped
    answer_text: str | None = None
    answered_at: datetime | None = None
    auto_continue_at: datetime | None = None  # When to auto-continue if no answer

    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def context(self) -> dict[str, Any]:
        try:
            return json.loads(self.context_json)
        except json.JSONDecodeError:
            return {}

    @context.setter
    def context(self, value: dict[str, Any]):
        self.context_json = json.dumps(value)

    @property
    def suggested_answers(self) -> list[str]:
        try:
            return json.loads(self.suggested_answers_json)
        except json.JSONDecodeError:
            return []

    @suggested_answers.setter
    def suggested_answers(self, value: list[str]):
        self.suggested_answers_json = json.dumps(value)


class AutoPilotSpecTask(SQLModel, table=True):
    """Individual spec generation task within Auto Pilot."""

    __tablename__ = "autopilot_spec_tasks"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="autopilot_sessions.id", index=True)
    requirement_id: int | None = None
    requirement_title: str | None = None
    priority: str = "medium"  # critical, high, medium, low
    status: str = "pending"  # pending, generating, completed, failed, skipped
    spec_name: str | None = None
    spec_path: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None


class AutoPilotTestTask(SQLModel, table=True):
    """Individual test generation task within Auto Pilot."""

    __tablename__ = "autopilot_test_tasks"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="autopilot_sessions.id", index=True)
    spec_task_id: int | None = None
    spec_name: str | None = None
    spec_path: str | None = None
    run_id: str | None = None
    status: str = "pending"  # pending, running, passed, failed, error, skipped
    current_stage: str | None = None  # planning, generating, testing, healing
    healing_attempt: int = 0
    test_path: str | None = None
    passed: bool | None = None
    error_summary: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
