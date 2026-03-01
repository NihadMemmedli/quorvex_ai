import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Index
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
    config_json: str = "{}"
    result_json: str | None = None
    status: str = "running"  # running, completed, failed
    created_at: datetime = Field(default_factory=datetime.utcnow)

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
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
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
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    req_code: str = Field(index=True)  # REQ-001, REQ-002, etc.
    title: str
    description: str | None = None
    category: str  # authentication, navigation, crud, validation, etc.
    priority: str = "medium"  # low, medium, high, critical
    status: str = "draft"  # draft, approved, implemented, tested
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
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    requirement_id: int = Field(foreign_key="requirements.id", index=True)
    test_spec_name: str  # Name/path of the test spec
    test_spec_path: str | None = None  # Full path to spec file
    mapping_type: str  # full, partial, suggested
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

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Log file path for real-time streaming
    log_path: str | None = None

    # Project isolation
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)


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
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    source_type: str  # "url" or "file"
    source_url: str | None = None
    source_filename: str | None = None
    feature_filter: str | None = None
    status: str = "running"  # running, completed, failed
    files_generated: int = 0
    generated_paths_json: str = "[]"
    error_message: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    completed_at: datetime | None = None

    @property
    def generated_paths(self) -> list[str]:
        try:
            return json.loads(self.generated_paths_json)
        except json.JSONDecodeError:
            return []

    @generated_paths.setter
    def generated_paths(self, value: list[str]):
        self.generated_paths_json = json.dumps(value)


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


# ========== CI/CD Pipeline Integration Models ==========


class CiPipelineMapping(SQLModel, table=True):
    """Tracks CI/CD pipeline runs triggered from or received by the platform."""

    __tablename__ = "ci_pipeline_mappings"
    __table_args__ = {"extend_existing": True}

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
    __table_args__ = {"extend_existing": True}

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
