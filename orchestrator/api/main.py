# CRITICAL: Load environment variables FIRST before any other imports
from dotenv import load_dotenv

load_dotenv()

# CRITICAL: Add orchestrator directory to sys.path BEFORE any other imports
# This ensures that imports like "from utils.json_utils" work correctly
import os  # noqa: F401
import sys
from pathlib import Path

orchestrator_dir = Path(__file__).resolve().parent.parent
if str(orchestrator_dir) not in sys.path:
    sys.path.insert(0, str(orchestrator_dir))

import asyncio  # noqa: F401
import functools  # noqa: F401
import shutil  # noqa: F401
import subprocess  # noqa: F401
import threading  # noqa: F401
import uuid  # noqa: F401
from datetime import datetime, timedelta  # noqa: F401

from fastapi import FastAPI
from sqlmodel import Session, select  # noqa: F401

from logging_config import get_logger, request_id_var, setup_logging  # noqa: F401
from orchestrator.services.agent_runtimes import normalize_agent_runtime  # noqa: F401
from orchestrator.services.browser_auth_sessions import (
    BrowserAuthSessionError,  # noqa: F401
    ensure_browser_auth_session_usable,  # noqa: F401
    resolve_browser_auth_for_run,  # noqa: F401
    resolve_browser_auth_session_row,  # noqa: F401
)
from orchestrator.services.browser_slots import browser_operation_slot  # noqa: F401
from orchestrator.services.coding_agent import (  # noqa: F401
    CODING_ARTIFACT_PATCH,
    DEFAULT_REPO_ROOT,
    build_coding_agent_prompt,
    build_coding_tool_permission_guard,
    coding_agent_allowed_tools,
    coding_agent_subagents,
    validate_patch_for_repo,
    write_coding_artifacts,
)
from services.browser_pool import AbstractBrowserPool, get_browser_pool  # noqa: F401
from services.browser_pool import OperationType as BrowserOpType  # noqa: F401
from services.resource_manager import (
    ResourceManager,  # noqa: F401
    get_resource_manager,  # noqa: F401
)
from utils.agent_report import (  # noqa: F401
    CUSTOM_AGENT_REPORT_INSTRUCTIONS,
    _as_report_list,
    _build_custom_agent_structured_report,
    _clean_text,
)
from utils.agent_tool_allowlists import get_agent_allowed_tools  # noqa: F401
from utils.claude_config import copy_claude_project_config  # noqa: F401
from utils.playwright_mcp import (
    browser_runtime_status,  # noqa: F401
    prepare_run_playwright_config_content,  # noqa: F401
    write_playwright_test_mcp_config,  # noqa: F401
)
from utils.project_utils import derive_project_id_from_url  # noqa: F401

from . import (  # noqa: F401
    agent_coding_patch,
    agent_definitions,
    agent_exploratory,
    agent_facade_support,
    agent_queue_ops,
    agent_reports,
    agent_run_control,
    agent_run_launch,
    agent_run_observability,
    agent_sessions,
    analytics,
    api_testing,
    app_wiring_support,
    auth,
    autonomous,
    autopilot,
    backup_control,
    browser_auth_sessions,
    chat,
    ci_control,
    dashboard,
    database_testing,
    exploration,
    github_ci,
    gitlab_ci,
    health,
    jira,
    llm_testing,
    load_testing,
    main_static_facade_support,
    memory,
    prd,
    projects,
    recordings,
    regression,
    requirements,
    rtm,
    run_files,
    runs,
    runtime_lifecycle_support,
    runtime_ops,
    scheduling,
    security_testing,
    settings,
    spec_files,
    specs,
    startup_diagnostics_support,
    test_data,
    test_run_batch_watchdog_support,
    test_run_cleanup_support,
    test_run_facade_support,
    test_run_maintenance_loop_support,
    test_run_process_registry_support,
    test_run_queue_manager_support,
    test_run_read_model_support,
    test_run_runtime_support,
    test_run_schedule_watchdog_support,
    testrail,
    testrail_files,
    users,
    workflows,
)
from .db import (
    engine,  # noqa: F401
    get_database_type,  # noqa: F401
    init_db,  # noqa: F401
    is_parallel_mode_available,  # noqa: F401
)
from .middleware.permissions import ProjectRole, check_project_access  # noqa: F401
from .models_db import (
    AgentRun,  # noqa: F401 - exposed through main for agent dependency compatibility
    ExplorationSession,  # noqa: F401
    RegressionBatch,  # noqa: F401
)
from .models_db import ExecutionSettings as DBExecutionSettings  # noqa: F401
from .models_db import SpecMetadata as DBSpecMetadata  # noqa: F401
from .models_db import TestRun as DBTestRun  # noqa: F401
from .models_db import get_spec_metadata as get_db_spec_metadata  # noqa: F401
from .process_manager import ProcessManager, get_process_manager  # noqa: F401

# Initialize logging
setup_logging(level="INFO", console=True)
logger = get_logger(__name__)

main_static_facade_support.configure_main_static_facade(globals())


def _main_runtime():
    return sys.modules[__name__]


app = FastAPI(title="Quorvex AI API")
app_wiring_support.configure_app(_main_runtime(), app)


def _test_run_runtime():
    return sys.modules[__name__]


test_run_facade_support.configure_test_run_facade(_test_run_runtime, globals())


@app.on_event("startup")
async def startup_event():
    await runtime_lifecycle_support.startup(_test_run_runtime())


@app.on_event("shutdown")
async def shutdown_event():
    """Gracefully shut down all running processes."""
    await runtime_lifecycle_support.shutdown(_test_run_runtime())



def _agent_compat_runtime():
    return sys.modules[__name__]


agent_facade_support.configure_agent_facade(_agent_compat_runtime, globals())
