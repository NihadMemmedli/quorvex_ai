from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response model."""

    items: list[T]
    total: int
    limit: int
    offset: int
    has_more: bool


class TestSpecBase(BaseModel):
    name: str


class TestSpec(TestSpecBase):
    path: str
    content: str
    is_automated: bool = False
    code_path: str | None = None


class TestRun(BaseModel):
    id: str
    timestamp: str
    status: str
    test_name: str | None = None
    spec_name: str | None = None  # File name/path of the spec (use this to re-run)
    steps_completed: int = 0
    total_steps: int = 0
    browser: str | None = "chromium"
    canStop: bool = False  # Whether this run can be stopped (has active process)
    queue_position: int | None = None  # Position in queue (null when running/completed)
    queued_at: str | None = None  # When added to queue (ISO format)
    started_at: str | None = None  # When execution started (ISO format)
    completed_at: str | None = None  # When execution completed (ISO format)
    batch_id: str | None = None  # Regression batch ID if part of a batch
    error_message: str | None = None  # Error message if failed

    # Stage tracking for real-time UI feedback
    current_stage: str | None = None  # "planning", "generating", "testing", "healing"
    stage_started_at: str | None = None  # When current stage started (ISO format)
    stage_message: str | None = None  # Detailed stage status message
    healing_attempt: int | None = None  # Current healing attempt number


class CreateSpecRequest(BaseModel):
    name: str
    content: str
    project_id: str | None = None  # Project to associate spec with


class UpdateSpecRequest(BaseModel):
    content: str


class SpecMetadata(BaseModel):
    tags: list[str] = []
    description: str | None = None
    author: str | None = None
    lastModified: str | None = None


class UpdateMetadataRequest(BaseModel):
    tags: list[str] | None = None
    description: str | None = None
    author: str | None = None
    project_id: str | None = None  # Allows reassigning spec to different project


class BulkRunRequest(BaseModel):
    """Request model for creating bulk test runs.

    Native pipeline is always used. The only choice is healing mode:
    - hybrid=False: Native Healer (3 attempts)
    - hybrid=True: Hybrid (Native 3 + Ralph up to max_iterations - 3)

    For regression testing:
    - automated_only=True: Run only specs with generated .spec.ts files
    - tags: Filter specs by tags (OR logic - matches ANY of the selected tags)
    - project_id: Filter specs and tag runs by project
    """

    spec_names: list[str] | None = None  # Optional now - can auto-discover if automated_only=True
    tags: list[str] | None = None  # Filter by tags (OR logic)
    automated_only: bool = False  # Only run automated specs
    browser: str = "chromium"
    hybrid: bool | None = False
    max_iterations: int | None = 20
    project_id: str | None = None  # Project to associate runs with

    # Legacy fields - kept for backward compatibility
    ralph: bool | None = False
    native_healer: bool | None = False
    native_generator: bool | None = False


class UpdateGeneratedCodeRequest(BaseModel):
    """Request model for updating generated test code."""

    content: str


class ExecutionSettingsResponse(BaseModel):
    """Response model for execution settings."""

    parallelism: int  # 1-10 concurrent tests
    parallel_mode_enabled: bool
    headless_in_parallel: bool
    memory_enabled: bool
    database_type: str  # "sqlite" or "postgresql"
    parallel_mode_available: bool  # False if SQLite


class UpdateExecutionSettingsRequest(BaseModel):
    """Request model for updating execution settings."""

    parallelism: int | None = None  # 1-10
    parallel_mode_enabled: bool | None = None
    headless_in_parallel: bool | None = None
    memory_enabled: bool | None = None


class AgentWorkerHealth(BaseModel):
    """Health info for the Redis-based agent worker."""

    workers_alive: bool = False
    active_heartbeats: int = 0
    running_tasks: int = 0
    alive_tasks: int = 0
    error: str | None = None


class QueueStatusResponse(BaseModel):
    """Response model for queue status."""

    running_count: int
    queued_count: int
    parallelism_limit: int
    database_type: str
    parallel_mode_enabled: bool
    orphaned_running_count: int = 0  # Running in DB but no active process
    active_process_count: int = 0  # Actually tracked processes
    orphaned_queued_count: int = 0  # Queued in DB but no backing asyncio task
    agent_worker_health: AgentWorkerHealth | None = None


class ClearQueueRequest(BaseModel):
    """Request model for clearing stuck queue entries."""

    include_running: bool = False  # Clear orphaned running entries
    include_queued: bool = True  # Clear queued entries


class ClearQueueResponse(BaseModel):
    """Response model for clear queue operation."""

    cleared_count: int
    cleared_runs: list[str]
    message: str


# ========== Regression Batch Models ==========


class BatchRunInList(BaseModel):
    """Single run info in batch list response."""

    id: str
    spec_name: str
    test_name: str | None = None
    status: str
    steps_completed: int = 0
    total_steps: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None
    duration_seconds: int | None = None
    # Actual test count within the test file (if file has multiple tests)
    actual_test_count: int = 1


class RegressionBatchSummary(BaseModel):
    """Summary info for batch list."""

    id: str
    name: str | None = None
    status: str
    created_at: str
    completed_at: str | None = None
    browser: str
    tags_used: list[str] = []
    hybrid_mode: bool = False
    total_tests: int = 0  # Number of test files/specs
    passed: int = 0
    failed: int = 0
    stopped: int = 0
    running: int = 0
    queued: int = 0
    success_rate: float = 0.0
    duration_seconds: int | None = None
    # Actual test counts (may differ from total_tests when files have multiple tests)
    actual_total_tests: int | None = None  # Total individual tests across all files
    actual_passed: int | None = None
    actual_failed: int | None = None
    project_id: str | None = None


class RegressionBatchDetail(RegressionBatchSummary):
    """Full batch detail with runs."""

    triggered_by: str | None = None
    started_at: str | None = None
    runs: list[BatchRunInList] = []


class RegressionBatchListResponse(BaseModel):
    """Paginated batch list response."""

    batches: list[RegressionBatchSummary]
    total: int
    limit: int
    offset: int
    has_more: bool


class CreateBatchResponse(BaseModel):
    """Response from creating a batch run."""

    batch_id: str
    run_ids: list[str]
    count: int
    mode: str
    max_iterations: int | None = None


class BatchExportResponse(BaseModel):
    """Export batch data response."""

    batch_id: str
    name: str | None = None
    created_at: str
    completed_at: str | None = None
    status: str
    browser: str
    tags_used: list[str] = []
    hybrid_mode: bool = False
    summary: dict
    tests: list[dict]


# ========== Folder Tree Models ==========


class FolderNode(BaseModel):
    """Represents a folder in the spec hierarchy."""

    name: str
    path: str
    spec_count: int
    children: list["FolderNode"] = []


# Enable recursive types
FolderNode.model_rebuild()


class FolderTreeResponse(BaseModel):
    """Response for folder tree endpoint."""

    folders: list[FolderNode]
    total_specs: int


# ========== Paginated Specs Response ==========


class AutomatedSpecItem(BaseModel):
    """Single automated spec in paginated response."""

    name: str
    path: str
    code_path: str
    spec_type: str
    test_count: int
    categories: list[str]
    tags: list[str]
    last_run_status: str | None = None
    last_run_id: str | None = None
    last_run_at: str | None = None


class PaginatedAutomatedSpecsResponse(BaseModel):
    """Paginated response for automated specs."""

    specs: list[AutomatedSpecItem]
    total: int
    limit: int
    offset: int
    has_more: bool
    filtered_folder: str | None = None
    filtered_by_tags: list[str] | None = None


# ========== Project Models ==========


class ProjectCreate(BaseModel):
    """Request model for creating a project."""

    name: str
    base_url: str | None = None
    description: str | None = None


class ProjectUpdate(BaseModel):
    """Request model for updating a project."""

    name: str | None = None
    base_url: str | None = None
    description: str | None = None


class ProjectResponse(BaseModel):
    """Response model for a project."""

    id: str
    name: str
    base_url: str | None = None
    description: str | None = None
    created_at: str
    last_active: str | None = None
    spec_count: int = 0
    run_count: int = 0
    batch_count: int = 0


class ProjectListResponse(BaseModel):
    """Response model for listing projects."""

    projects: list[ProjectResponse]
    total: int


# ========== Spec Move Models ==========


class MoveSpecRequest(BaseModel):
    """Request model for moving specs or folders."""

    source_path: str  # e.g., "folder/spec.md" or "folder"
    destination_folder: str  # e.g., "new-folder" or "" for root
    is_folder: bool = False
    project_id: str | None = None


class MovedItemInfo(BaseModel):
    """Info about a moved spec or test file."""

    old_path: str
    new_path: str


class MoveSpecResponse(BaseModel):
    """Response model for move spec operation."""

    status: str
    old_path: str
    new_path: str
    moved_specs: list[MovedItemInfo]
    moved_tests: list[MovedItemInfo]


# ========== Spec Rename Models ==========


class RenameRequest(BaseModel):
    """Request model for renaming specs or folders."""

    old_path: str  # e.g., "auth/login.md" or "auth"
    new_name: str  # Just the new name, e.g., "sign-in.md" or "authentication"
    is_folder: bool = False
    project_id: str | None = None


class RenameResponse(BaseModel):
    """Response model for rename operation."""

    status: str
    old_path: str
    new_path: str
    renamed_specs: list[MovedItemInfo]
    renamed_tests: list[MovedItemInfo]


# ========== Create Folder Models ==========


class CreateFolderRequest(BaseModel):
    """Request model for creating an empty folder."""

    folder_name: str
    parent_path: str = ""  # empty = specs root
    project_id: str | None = None


class CreateFolderResponse(BaseModel):
    """Response model for create folder operation."""

    status: str
    path: str


# ========== Credentials Models ==========


class CredentialCreate(BaseModel):
    """Request model for creating/updating a credential."""

    key: str  # e.g., "LOGIN_PASSWORD"
    value: str  # The plaintext credential value


class CredentialResponse(BaseModel):
    """Response model for a credential (masked value)."""

    key: str
    masked_value: str  # e.g., "****1234"
    source: str  # "project" or "env"


class CredentialListResponse(BaseModel):
    """Response model for listing credentials."""

    credentials: list[CredentialResponse]
    project_id: str
