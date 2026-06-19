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

from fastapi import FastAPI

from logging_config import get_logger, setup_logging

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
    main_runtime_dependency_facade_support,
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
    test_data,
    test_run_facade_support,
    testrail,
    testrail_files,
    users,
    workflows,
)

# Initialize logging
setup_logging(level="INFO", console=True)
logger = get_logger(__name__)

main_runtime_dependency_facade_support.configure_main_runtime_dependency_facade(globals())
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
