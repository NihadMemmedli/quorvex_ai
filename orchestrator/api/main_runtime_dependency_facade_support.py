"""Runtime dependency compatibility exports for the legacy main module facade."""

from __future__ import annotations

from typing import Any


def configure_main_runtime_dependency_facade(namespace: dict[str, Any]) -> None:
    """Populate main-module compatibility exports for runtime dependencies."""
    import asyncio
    import functools
    import shutil
    import subprocess
    import threading
    import uuid
    from datetime import datetime, timedelta

    from sqlmodel import Session, select

    from logging_config import request_id_var
    from orchestrator.services.agent_runtimes import normalize_agent_runtime
    from orchestrator.services.browser_auth_sessions import (
        BrowserAuthSessionError,
        ensure_browser_auth_session_usable,
        resolve_browser_auth_for_run,
        resolve_browser_auth_session_row,
    )
    from orchestrator.services.browser_slots import browser_operation_slot
    from orchestrator.services.coding_agent import (
        CODING_ARTIFACT_PATCH,
        DEFAULT_REPO_ROOT,
        build_coding_agent_prompt,
        build_coding_tool_permission_guard,
        coding_agent_allowed_tools,
        coding_agent_subagents,
        validate_patch_for_repo,
        write_coding_artifacts,
    )
    from services.browser_pool import AbstractBrowserPool, get_browser_pool
    from services.browser_pool import OperationType as BrowserOpType
    from services.resource_manager import ResourceManager, get_resource_manager
    from utils.agent_report import (
        CUSTOM_AGENT_REPORT_INSTRUCTIONS,
        _as_report_list,
        _build_custom_agent_structured_report,
        _clean_text,
    )
    from utils.agent_tool_allowlists import get_agent_allowed_tools
    from utils.claude_config import copy_claude_project_config
    from utils.playwright_mcp import (
        browser_runtime_status,
        prepare_run_playwright_config_content,
        write_playwright_test_mcp_config,
    )
    from utils.project_utils import derive_project_id_from_url

    from .db import engine, get_database_type, init_db, is_parallel_mode_available
    from .middleware.permissions import ProjectRole, check_project_access
    from .models_db import AgentRun, ExplorationSession, RegressionBatch
    from .models_db import ExecutionSettings as DBExecutionSettings
    from .models_db import SpecMetadata as DBSpecMetadata
    from .models_db import TestRun as DBTestRun
    from .models_db import get_spec_metadata as get_db_spec_metadata
    from .process_manager import ProcessManager, get_process_manager

    namespace.update(
        {
            "asyncio": asyncio,
            "functools": functools,
            "shutil": shutil,
            "subprocess": subprocess,
            "threading": threading,
            "uuid": uuid,
            "datetime": datetime,
            "timedelta": timedelta,
            "Session": Session,
            "select": select,
            "request_id_var": request_id_var,
            "normalize_agent_runtime": normalize_agent_runtime,
            "BrowserAuthSessionError": BrowserAuthSessionError,
            "ensure_browser_auth_session_usable": ensure_browser_auth_session_usable,
            "resolve_browser_auth_for_run": resolve_browser_auth_for_run,
            "resolve_browser_auth_session_row": resolve_browser_auth_session_row,
            "browser_operation_slot": browser_operation_slot,
            "CODING_ARTIFACT_PATCH": CODING_ARTIFACT_PATCH,
            "DEFAULT_REPO_ROOT": DEFAULT_REPO_ROOT,
            "build_coding_agent_prompt": build_coding_agent_prompt,
            "build_coding_tool_permission_guard": build_coding_tool_permission_guard,
            "coding_agent_allowed_tools": coding_agent_allowed_tools,
            "coding_agent_subagents": coding_agent_subagents,
            "validate_patch_for_repo": validate_patch_for_repo,
            "write_coding_artifacts": write_coding_artifacts,
            "AbstractBrowserPool": AbstractBrowserPool,
            "get_browser_pool": get_browser_pool,
            "BrowserOpType": BrowserOpType,
            "ResourceManager": ResourceManager,
            "get_resource_manager": get_resource_manager,
            "CUSTOM_AGENT_REPORT_INSTRUCTIONS": CUSTOM_AGENT_REPORT_INSTRUCTIONS,
            "_as_report_list": _as_report_list,
            "_build_custom_agent_structured_report": _build_custom_agent_structured_report,
            "_clean_text": _clean_text,
            "get_agent_allowed_tools": get_agent_allowed_tools,
            "copy_claude_project_config": copy_claude_project_config,
            "browser_runtime_status": browser_runtime_status,
            "prepare_run_playwright_config_content": prepare_run_playwright_config_content,
            "write_playwright_test_mcp_config": write_playwright_test_mcp_config,
            "derive_project_id_from_url": derive_project_id_from_url,
            "engine": engine,
            "get_database_type": get_database_type,
            "init_db": init_db,
            "is_parallel_mode_available": is_parallel_mode_available,
            "ProjectRole": ProjectRole,
            "check_project_access": check_project_access,
            "AgentRun": AgentRun,
            "ExplorationSession": ExplorationSession,
            "RegressionBatch": RegressionBatch,
            "DBExecutionSettings": DBExecutionSettings,
            "DBSpecMetadata": DBSpecMetadata,
            "DBTestRun": DBTestRun,
            "get_db_spec_metadata": get_db_spec_metadata,
            "ProcessManager": ProcessManager,
            "get_process_manager": get_process_manager,
        }
    )
