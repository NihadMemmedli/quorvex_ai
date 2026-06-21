import json
import subprocess
import sys
import types
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if "slowapi" not in sys.modules:
    slowapi_module = types.ModuleType("slowapi")
    slowapi_errors = types.ModuleType("slowapi.errors")
    slowapi_util = types.ModuleType("slowapi.util")

    class _Limiter:
        def __init__(self, *args, **kwargs):
            pass

        def limit(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

    class _RateLimitExceeded(Exception):
        pass

    slowapi_module.Limiter = _Limiter
    slowapi_errors.RateLimitExceeded = _RateLimitExceeded
    slowapi_util.get_remote_address = lambda request: "test-client"
    sys.modules["slowapi"] = slowapi_module
    sys.modules["slowapi.errors"] = slowapi_errors
    sys.modules["slowapi.util"] = slowapi_util

from orchestrator.api import db as db_module
from orchestrator.api import main as main_module
from orchestrator.api.db import engine
from orchestrator.api.main import (
    _custom_agent_browser_runs_via_queue,
    _custom_agent_uses_browser_tools,
    _ensure_custom_agent_browser_available,
    _prepare_custom_agent_mcp_config,
    _probe_custom_agent_browser,
    _resolve_playwright_chromium_executable,
    _signal_agent_run_temporal,
    _start_agent_run_temporal_or_fail,
    retry_agent_run,
)
from orchestrator.api.models_db import AgentRun, AgentRunEvent, DomainJob
from orchestrator.api.requirements import get_bulk_generate_job_status, get_generate_job_status
from orchestrator.api.rtm import get_rtm_generate_job_status
from orchestrator.services.agent_run_activities import (
    _finalize_reattached_agent_task,
    _handle_agent_task_reattach_failure,
    _load_agent_run_execution_state,
    _mark_agent_run_activity_cancelled,
    execute_agent_run,
    finalize_agent_run_workflow,
    mark_agent_run_temporal_started,
    set_agent_run_control_status,
)
from orchestrator.services.temporal_client import (
    TemporalUnavailableError,
    TemporalWorkflowStart,
    _agent_run_worker_registration_failure,
    _parse_workflow_task_failures,
    check_agent_run_temporal_health,
)


def _ensure_tables() -> None:
    SQLModel.metadata.create_all(engine, checkfirst=True)
    db_module._run_migrations()


def _cleanup_run(run_id: str) -> None:
    with Session(engine) as session:
        for event in session.exec(
            select(AgentRunEvent).where(AgentRunEvent.run_id == run_id)
        ).all():
            session.delete(event)
        run = session.get(AgentRun, run_id)
        if run:
            session.delete(run)
        session.commit()


def _cleanup_domain_job(job_id: str) -> None:
    with Session(engine) as session:
        job = session.get(DomainJob, job_id)
        if job:
            session.delete(job)
        session.commit()


def _create_run(run_id: str, status: str = "queued") -> AgentRun:
    _ensure_tables()
    _cleanup_run(run_id)
    with Session(engine) as session:
        run = AgentRun(id=run_id, agent_type="custom", status=status, config_json="{}")
        session.add(run)
        session.commit()
        session.refresh(run)
        return run


class _AssertingSpecBackgroundTasks:
    def __init__(self, runs_dir: Path):
        self.runs_dir = runs_dir
        self.tasks: list[tuple] = []

    def add_task(self, func, *args, **kwargs):
        spec_agent_run_id = kwargs["spec_agent_run_id"]
        mcp_config_path = self.runs_dir / spec_agent_run_id / ".mcp.json"
        assert mcp_config_path.exists()
        config = json.loads(mcp_config_path.read_text())
        assert "playwright-test" in config["mcpServers"]
        self.tasks.append((func, args, kwargs))


def _report_source_result(item_id: str = "F-001", page: str = "https://example.test/login") -> dict:
    return {
        "structured_report": {
            "findings": [
                {
                    "id": item_id,
                    "title": "Missing validation",
                    "page": page,
                    "description": "Invalid login can proceed.",
                    "evidence": "Validation message is absent.",
                }
            ],
            "test_ideas": [],
        }
    }


def test_custom_agent_browser_tool_detection_matches_playwright_mcp_and_browser_aliases():
    assert _custom_agent_uses_browser_tools(["mcp__playwright-test__browser_click"]) is True
    assert _custom_agent_uses_browser_tools(["mcp__playwright__browser_navigate"]) is True
    assert _custom_agent_uses_browser_tools(["browser_navigate"]) is True
    assert _custom_agent_uses_browser_tools(["Read", "Write", "mcp__appium-mcp__tap"]) is False
    assert _custom_agent_uses_browser_tools([]) is False


def test_custom_agent_browser_probe_launches_installed_playwright(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(main_module, "_resolve_playwright_chromium_executable", lambda: None)

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        assert cmd[0] == "node"
        assert "@playwright/mcp" not in cmd
        assert "install-browser" not in cmd
        assert kwargs["timeout"] == 30
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(main_module.subprocess, "run", fake_run)

    available, output = _probe_custom_agent_browser()

    assert available is True
    assert output == ""
    assert len(calls) == 1


def test_custom_agent_mcp_config_uses_installed_chromium_executable(tmp_path, monkeypatch):
    chromium = tmp_path / "ms-playwright" / "chromium-1200" / "chrome-linux" / "chrome"
    chromium.parent.mkdir(parents=True)
    chromium.write_text("")
    monkeypatch.setenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", str(chromium))
    monkeypatch.setattr(main_module, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(
        main_module.exploration,
        "_build_playwright_mcp_server_config",
        lambda: {"command": "/app/node_modules/.bin/playwright-mcp", "args": ["--browser", "chromium"]},
    )
    monkeypatch.setenv("HEADLESS", "false")

    run_dir = _prepare_custom_agent_mcp_config("custom-agent-visible-browser")
    config = json.loads((run_dir / ".mcp.json").read_text())
    args = config["mcpServers"]["playwright-test"]["args"]

    assert "--executable-path" in args
    assert args[args.index("--executable-path") + 1] == str(chromium)
    assert "--headless" not in args


def test_resolve_playwright_chromium_executable_prefers_env_override(tmp_path, monkeypatch):
    chromium = tmp_path / "chrome"
    chromium.write_text("")
    monkeypatch.setenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", str(chromium))

    assert _resolve_playwright_chromium_executable() == chromium


def test_run_seed_spec_is_generated_from_target_url(tmp_path):
    seed_path = main_module._write_run_seed_spec(tmp_path, "https://example.test/dashboard")

    content = seed_path.read_text(encoding="utf-8")
    assert seed_path == tmp_path / "tests" / "seed.spec.ts"
    assert 'const targetUrl = "https://example.test/dashboard";' in content
    assert "await page.goto(targetUrl || 'about:blank');" in content


def test_run_seed_spec_overwrites_blank_default_seed(tmp_path):
    seed_path = tmp_path / "tests" / "seed.spec.ts"
    seed_path.parent.mkdir(parents=True)
    seed_path.write_text("import { test } from '@playwright/test';\n\ntest('blank', async () => {});\n")

    main_module._write_run_seed_spec(tmp_path, "https://example.test/flow")

    content = seed_path.read_text(encoding="utf-8")
    assert "test('blank'" not in content
    assert 'const targetUrl = "https://example.test/flow";' in content


def test_run_seed_spec_rewrites_localhost_for_docker_browser(tmp_path):
    seed_path = main_module._write_run_seed_spec(tmp_path, "http://localhost:3000/dashboard?tab=live")

    content = seed_path.read_text(encoding="utf-8")
    assert 'const targetUrl = "http://host.docker.internal:3000/dashboard?tab=live";' in content


@pytest.mark.asyncio
async def test_report_item_spec_generation_writes_mcp_config_before_scheduling(tmp_path, monkeypatch):
    source_run_id = "report-spec-source"
    _ensure_tables()
    _cleanup_run(source_run_id)
    monkeypatch.setattr(main_module, "RUNS_DIR", tmp_path / "runs")
    background_tasks = _AssertingSpecBackgroundTasks(main_module.RUNS_DIR)

    try:
        with Session(engine) as session:
            source_run = AgentRun(id=source_run_id, agent_type="custom", status="completed")
            source_run.config = {"url": "https://example.test"}
            source_run.result = {
                "structured_report": {
                    "findings": [
                        {
                            "id": "F-001",
                            "title": "Missing validation",
                            "page": "https://example.test/login",
                            "description": "Invalid login can proceed.",
                            "evidence": "Validation message is absent.",
                        }
                    ],
                    "test_ideas": [],
                }
            }
            session.add(source_run)
            session.commit()

            response = await main_module.generate_report_item_spec(
                source_run_id,
                "F-001",
                item_type=None,
                project_id=None,
                background_tasks=background_tasks,
                session=session,
            )

            spec_run = session.get(AgentRun, response["agent_run_id"])
            assert spec_run is not None
            assert spec_run.progress["mcp_config_path"] == str(
                main_module.RUNS_DIR / response["agent_run_id"] / ".mcp.json"
            )
            assert spec_run.progress["artifacts_dir"] == str(
                main_module.RUNS_DIR / response["agent_run_id"] / "artifacts"
            )
            assert "mcp__playwright-test__planner_setup_page" in spec_run.config["allowed_tools"]
            assert len(background_tasks.tasks) == 1
    finally:
        if "response" in locals():
            _cleanup_run(response["agent_run_id"])
        _cleanup_run(source_run_id)


@pytest.mark.asyncio
async def test_report_item_spec_generation_inherits_browser_auth_session(tmp_path, monkeypatch):
    source_run_id = "report-spec-source-auth"
    project_id = "project-report-auth"
    _ensure_tables()
    _cleanup_run(source_run_id)
    monkeypatch.setattr(main_module, "RUNS_DIR", tmp_path / "runs")
    calls: list[dict] = []

    def fake_resolve_browser_auth_for_run(
        _db_session,
        resolved_project_id,
        *,
        run_dir,
        browser_auth_session_id=None,
        use_default=False,
    ):
        calls.append(
            {
                "project_id": resolved_project_id,
                "browser_auth_session_id": browser_auth_session_id,
                "use_default": use_default,
            }
        )
        storage_state_path = Path(run_dir) / "browser-auth-storage-state.json"
        storage_state_path.write_text(json.dumps({"cookies": [], "origins": []}))
        return types.SimpleNamespace(
            session_id=browser_auth_session_id,
            session_name="Team login",
            storage_state_path=storage_state_path,
        )

    monkeypatch.setattr(main_module, "resolve_browser_auth_for_run", fake_resolve_browser_auth_for_run)
    background_tasks = _AssertingSpecBackgroundTasks(main_module.RUNS_DIR)

    try:
        with Session(engine) as session:
            source_run = AgentRun(id=source_run_id, agent_type="custom", status="completed", project_id=project_id)
            source_run.config = {
                "url": "https://example.test/user/crm/opportunities",
                "project_id": project_id,
                "browser_auth_session_id": "auth-session-1",
                "auth": {
                    "browser_auth_session_id": "legacy-auth-session",
                    "password": "do-not-copy",
                },
            }
            source_run.result = _report_source_result(page="https://example.test/user/crm/opportunities")
            session.add(source_run)
            session.commit()

            response = await main_module.generate_report_item_spec(
                source_run_id,
                "F-001",
                item_type="finding",
                project_id=project_id,
                background_tasks=background_tasks,
                session=session,
            )

            spec_run = session.get(AgentRun, response["agent_run_id"])
            assert spec_run is not None
            assert spec_run.project_id == project_id
            assert spec_run.config["project_id"] == project_id
            assert spec_run.config["browser_auth_session_id"] == "auth-session-1"
            assert spec_run.config["auth"] == {"browser_auth_session_id": "legacy-auth-session"}
            assert spec_run.config["source_url"] == "https://example.test/user/crm/opportunities"
            assert "do-not-copy" not in spec_run.config_json

            mcp_config = json.loads((main_module.RUNS_DIR / response["agent_run_id"] / ".mcp.json").read_text())
            args = mcp_config["mcpServers"]["playwright-test"]["args"]
            assert "--storage-state" in args
            storage_arg = args[args.index("--storage-state") + 1]
            assert storage_arg.endswith("browser-auth-storage-state.json")

            assert calls == [
                {
                    "project_id": project_id,
                    "browser_auth_session_id": "auth-session-1",
                    "use_default": False,
                }
            ]
            assert len(background_tasks.tasks) == 1
            task_kwargs = background_tasks.tasks[0][2]
            assert task_kwargs["run_config"]["browser_auth_session_id"] == "auth-session-1"
            assert task_kwargs["run_config"]["project_id"] == project_id
    finally:
        if "response" in locals():
            _cleanup_run(response["agent_run_id"])
        _cleanup_run(source_run_id)


@pytest.mark.asyncio
async def test_report_item_spec_generation_uses_project_default_browser_auth(tmp_path, monkeypatch):
    source_run_id = "report-spec-source-default-auth"
    request_project_id = "request-project-default-auth"
    _ensure_tables()
    _cleanup_run(source_run_id)
    monkeypatch.setattr(main_module, "RUNS_DIR", tmp_path / "runs")
    calls: list[dict] = []

    def fake_resolve_browser_auth_for_run(
        _db_session,
        resolved_project_id,
        *,
        run_dir,
        browser_auth_session_id=None,
        use_default=False,
    ):
        calls.append(
            {
                "project_id": resolved_project_id,
                "browser_auth_session_id": browser_auth_session_id,
                "use_default": use_default,
            }
        )
        storage_state_path = Path(run_dir) / "browser-auth-storage-state.json"
        storage_state_path.write_text(json.dumps({"cookies": [], "origins": []}))
        return types.SimpleNamespace(
            session_id="default-auth-session",
            session_name="Default login",
            storage_state_path=storage_state_path,
        )

    monkeypatch.setattr(main_module, "resolve_browser_auth_for_run", fake_resolve_browser_auth_for_run)
    background_tasks = _AssertingSpecBackgroundTasks(main_module.RUNS_DIR)

    try:
        with Session(engine) as session:
            source_run = AgentRun(id=source_run_id, agent_type="custom", status="completed")
            source_run.config = {
                "url": "https://example.test",
                "project_id": "source-config-project",
                "use_project_default_browser_auth": True,
            }
            source_run.result = _report_source_result()
            session.add(source_run)
            session.commit()

            response = await main_module.generate_report_item_spec(
                source_run_id,
                "F-001",
                item_type="finding",
                project_id=request_project_id,
                background_tasks=background_tasks,
                session=session,
            )

            spec_run = session.get(AgentRun, response["agent_run_id"])
            assert spec_run is not None
            assert spec_run.project_id == request_project_id
            assert spec_run.config["project_id"] == request_project_id
            assert spec_run.config["use_project_default_browser_auth"] is True
            assert spec_run.progress["browser_auth_session_id"] == "default-auth-session"
            assert calls == [
                {
                    "project_id": request_project_id,
                    "browser_auth_session_id": None,
                    "use_default": True,
                }
            ]
            task_kwargs = background_tasks.tasks[0][2]
            assert task_kwargs["run_project_id"] == request_project_id
            assert task_kwargs["run_config"]["project_id"] == request_project_id
            assert task_kwargs["run_config"]["use_project_default_browser_auth"] is True
    finally:
        if "response" in locals():
            _cleanup_run(response["agent_run_id"])
        _cleanup_run(source_run_id)


@pytest.mark.asyncio
async def test_report_item_spec_generation_explicit_session_overrides_inherited_auth(tmp_path, monkeypatch):
    source_run_id = "report-spec-source-override-auth"
    project_id = "project-report-override-auth"
    _ensure_tables()
    _cleanup_run(source_run_id)
    monkeypatch.setattr(main_module, "RUNS_DIR", tmp_path / "runs")
    calls: list[dict] = []

    def fake_resolve_browser_auth_for_run(
        _db_session,
        resolved_project_id,
        *,
        run_dir,
        browser_auth_session_id=None,
        use_default=False,
    ):
        calls.append(
            {
                "project_id": resolved_project_id,
                "browser_auth_session_id": browser_auth_session_id,
                "use_default": use_default,
            }
        )
        storage_state_path = Path(run_dir) / "browser-auth-storage-state.json"
        storage_state_path.write_text(json.dumps({"cookies": [], "origins": []}))
        return types.SimpleNamespace(
            session_id=browser_auth_session_id,
            session_name="Active login",
            storage_state_path=storage_state_path,
        )

    monkeypatch.setattr(main_module, "resolve_browser_auth_for_run", fake_resolve_browser_auth_for_run)
    background_tasks = _AssertingSpecBackgroundTasks(main_module.RUNS_DIR)

    try:
        with Session(engine) as session:
            source_run = AgentRun(id=source_run_id, agent_type="custom", status="completed", project_id=project_id)
            source_run.config = {
                "url": "https://example.test",
                "project_id": project_id,
                "browser_auth_session_id": "revoked-auth-session",
                "auth": {"browser_auth_session_id": "legacy-auth-session"},
                "browser_auth": {"session_id": "nested-auth-session"},
            }
            source_run.result = _report_source_result()
            session.add(source_run)
            session.commit()

            response = await main_module.generate_report_item_spec(
                source_run_id,
                "F-001",
                item_type="finding",
                project_id=project_id,
                request_body=main_module.GenerateReportItemSpecRequest(
                    browser_auth_session_id="active-auth-session"
                ),
                background_tasks=background_tasks,
                session=session,
            )

            spec_run = session.get(AgentRun, response["agent_run_id"])
            assert spec_run is not None
            assert spec_run.config["browser_auth_session_id"] == "active-auth-session"
            assert "auth" not in spec_run.config
            assert "browser_auth" not in spec_run.config
            assert "browser_auth_inherited" not in spec_run.config
            assert calls == [
                {
                    "project_id": project_id,
                    "browser_auth_session_id": "active-auth-session",
                    "use_default": False,
                }
            ]
            task_kwargs = background_tasks.tasks[0][2]
            assert task_kwargs["run_config"]["browser_auth_session_id"] == "active-auth-session"
            assert "auth" not in task_kwargs["run_config"]
    finally:
        if "response" in locals():
            _cleanup_run(response["agent_run_id"])
        _cleanup_run(source_run_id)


@pytest.mark.asyncio
async def test_report_item_spec_generation_skip_browser_auth_removes_inherited_auth(tmp_path, monkeypatch):
    source_run_id = "report-spec-source-skip-auth"
    project_id = "project-report-skip-auth"
    _ensure_tables()
    _cleanup_run(source_run_id)
    monkeypatch.setattr(main_module, "RUNS_DIR", tmp_path / "runs")
    calls: list[dict] = []

    def fake_resolve_browser_auth_for_run(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        raise AssertionError("Browser auth should not be resolved when skip_browser_auth is true")

    monkeypatch.setattr(main_module, "resolve_browser_auth_for_run", fake_resolve_browser_auth_for_run)
    background_tasks = _AssertingSpecBackgroundTasks(main_module.RUNS_DIR)

    try:
        with Session(engine) as session:
            source_run = AgentRun(id=source_run_id, agent_type="custom", status="completed", project_id=project_id)
            source_run.config = {
                "url": "https://example.test",
                "project_id": project_id,
                "browser_auth_session_id": "revoked-auth-session",
                "auth": {"browser_auth_session_id": "legacy-auth-session"},
            }
            source_run.result = _report_source_result()
            session.add(source_run)
            session.commit()

            response = await main_module.generate_report_item_spec(
                source_run_id,
                "F-001",
                item_type="finding",
                project_id=project_id,
                request_body=main_module.GenerateReportItemSpecRequest(skip_browser_auth=True),
                background_tasks=background_tasks,
                session=session,
            )

            spec_run = session.get(AgentRun, response["agent_run_id"])
            assert spec_run is not None
            assert "browser_auth_session_id" not in spec_run.config
            assert "use_project_default_browser_auth" not in spec_run.config
            assert "auth" not in spec_run.config
            assert calls == []
            task_kwargs = background_tasks.tasks[0][2]
            assert "browser_auth_session_id" not in task_kwargs["run_config"]
            assert "auth" not in task_kwargs["run_config"]
    finally:
        if "response" in locals():
            _cleanup_run(response["agent_run_id"])
        _cleanup_run(source_run_id)


@pytest.mark.asyncio
async def test_report_item_spec_generation_project_default_overrides_inherited_auth(tmp_path, monkeypatch):
    source_run_id = "report-spec-source-default-override-auth"
    project_id = "project-report-default-override-auth"
    _ensure_tables()
    _cleanup_run(source_run_id)
    monkeypatch.setattr(main_module, "RUNS_DIR", tmp_path / "runs")
    calls: list[dict] = []

    def fake_resolve_browser_auth_for_run(
        _db_session,
        resolved_project_id,
        *,
        run_dir,
        browser_auth_session_id=None,
        use_default=False,
    ):
        calls.append(
            {
                "project_id": resolved_project_id,
                "browser_auth_session_id": browser_auth_session_id,
                "use_default": use_default,
            }
        )
        storage_state_path = Path(run_dir) / "browser-auth-storage-state.json"
        storage_state_path.write_text(json.dumps({"cookies": [], "origins": []}))
        return types.SimpleNamespace(
            session_id="default-auth-session",
            session_name="Default login",
            storage_state_path=storage_state_path,
        )

    monkeypatch.setattr(main_module, "resolve_browser_auth_for_run", fake_resolve_browser_auth_for_run)
    background_tasks = _AssertingSpecBackgroundTasks(main_module.RUNS_DIR)

    try:
        with Session(engine) as session:
            source_run = AgentRun(id=source_run_id, agent_type="custom", status="completed", project_id=project_id)
            source_run.config = {
                "url": "https://example.test",
                "project_id": project_id,
                "browser_auth_session_id": "revoked-auth-session",
                "auth": {"browser_auth_session_id": "legacy-auth-session"},
            }
            source_run.result = _report_source_result()
            session.add(source_run)
            session.commit()

            response = await main_module.generate_report_item_spec(
                source_run_id,
                "F-001",
                item_type="finding",
                project_id=project_id,
                request_body=main_module.GenerateReportItemSpecRequest(
                    use_project_default_browser_auth=True
                ),
                background_tasks=background_tasks,
                session=session,
            )

            spec_run = session.get(AgentRun, response["agent_run_id"])
            assert spec_run is not None
            assert spec_run.config["use_project_default_browser_auth"] is True
            assert "browser_auth_session_id" not in spec_run.config
            assert "auth" not in spec_run.config
            assert spec_run.progress["browser_auth_session_id"] == "default-auth-session"
            assert calls == [
                {
                    "project_id": project_id,
                    "browser_auth_session_id": None,
                    "use_default": True,
                }
            ]
            task_kwargs = background_tasks.tasks[0][2]
            assert task_kwargs["run_config"]["use_project_default_browser_auth"] is True
            assert "auth" not in task_kwargs["run_config"]
    finally:
        if "response" in locals():
            _cleanup_run(response["agent_run_id"])
        _cleanup_run(source_run_id)


@pytest.mark.asyncio
async def test_report_item_spec_generation_invalid_explicit_browser_auth_marks_run_failed(tmp_path, monkeypatch):
    source_run_id = "report-spec-source-invalid-auth"
    project_id = "project-invalid-auth"
    _ensure_tables()
    _cleanup_run(source_run_id)
    monkeypatch.setattr(main_module, "RUNS_DIR", tmp_path / "runs")

    def fake_resolve_browser_auth_for_run(*_args, **_kwargs):
        raise main_module.BrowserAuthSessionError("Browser auth session was not found")

    monkeypatch.setattr(main_module, "resolve_browser_auth_for_run", fake_resolve_browser_auth_for_run)
    background_tasks = _AssertingSpecBackgroundTasks(main_module.RUNS_DIR)

    try:
        with Session(engine) as session:
            source_run = AgentRun(id=source_run_id, agent_type="custom", status="completed", project_id=project_id)
            source_run.config = {
                "url": "https://example.test",
                "project_id": project_id,
                "browser_auth_session_id": "missing-auth-session",
            }
            source_run.result = _report_source_result()
            session.add(source_run)
            session.commit()

            response = await main_module.generate_report_item_spec(
                source_run_id,
                "F-001",
                item_type="finding",
                project_id=project_id,
                request_body=main_module.GenerateReportItemSpecRequest(
                    browser_auth_session_id="missing-auth-session"
                ),
                background_tasks=background_tasks,
                session=session,
            )

            assert response["status"] == "failed"
            spec_run = session.get(AgentRun, response["agent_run_id"])
            assert spec_run is not None
            assert spec_run.status == "failed"
            assert spec_run.result["browser_auth_failure"] is True
            assert spec_run.result["browser_auth_session_id"] == "missing-auth-session"
            assert "Browser auth session was not found" in spec_run.result["browser_auth_error"]
            assert "Choose an active session or generate without auth" in spec_run.result["error"]
            assert spec_run.progress["phase"] == "failed"
            assert spec_run.progress["status"] == "failed"
            assert spec_run.progress["browser_auth_failure"] is True
            assert spec_run.progress["browser_auth_session_id"] == "missing-auth-session"
            assert "Choose an active session or generate without auth" in spec_run.progress["message"]
            assert main_module._flow_spec_jobs[response["job_id"]]["status"] == "failed"
            assert len(background_tasks.tasks) == 0
    finally:
        if "response" in locals():
            main_module._flow_spec_jobs.pop(response["job_id"], None)
            _cleanup_run(response["agent_run_id"])
        _cleanup_run(source_run_id)


@pytest.mark.asyncio
async def test_flow_spec_generation_writes_mcp_config_before_scheduling(tmp_path, monkeypatch):
    source_run_id = "flow-spec-source"
    _ensure_tables()
    _cleanup_run(source_run_id)
    monkeypatch.setattr(main_module, "RUNS_DIR", tmp_path / "runs")
    run_dir = main_module.RUNS_DIR / source_run_id
    run_dir.mkdir(parents=True)
    (run_dir / "flows.json").write_text(
        json.dumps(
            {
                "flows": [
                    {
                        "id": "flow_1",
                        "title": "Login flow",
                        "entry_point": "https://example.test/login",
                        "exit_point": "https://example.test/dashboard",
                        "happy_path": "Open login and submit valid credentials.",
                        "edge_cases": [],
                        "test_ideas": ["Validate login controls."],
                    }
                ]
            }
        )
    )
    background_tasks = _AssertingSpecBackgroundTasks(main_module.RUNS_DIR)

    try:
        with Session(engine) as session:
            source_run = AgentRun(id=source_run_id, agent_type="exploratory", status="completed")
            source_run.config = {"url": "https://example.test"}
            session.add(source_run)
            session.commit()

            response = await main_module.generate_flow_test(
                source_run_id,
                "flow_1",
                force_regenerate=False,
                project_id=None,
                background_tasks=background_tasks,
                session=session,
            )

            spec_run = session.get(AgentRun, response["agent_run_id"])
            assert spec_run is not None
            assert spec_run.progress["mcp_config_path"] == str(
                main_module.RUNS_DIR / response["agent_run_id"] / ".mcp.json"
            )
            assert spec_run.progress["artifacts_dir"] == str(
                main_module.RUNS_DIR / response["agent_run_id"] / "artifacts"
            )
            assert "mcp__playwright-test__planner_setup_page" in spec_run.config["allowed_tools"]
            assert len(background_tasks.tasks) == 1
    finally:
        if "response" in locals():
            _cleanup_run(response["agent_run_id"])
        _cleanup_run(source_run_id)


@pytest.mark.asyncio
async def test_flow_spec_generation_recreates_mcp_config_in_background(tmp_path, monkeypatch):
    run_id = "flow-spec-background-source"
    spec_run_id = "flowspec-background-recreate"
    job_id = spec_run_id
    _ensure_tables()
    _cleanup_run(run_id)
    _cleanup_run(spec_run_id)
    monkeypatch.setattr(main_module, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.syspath_prepend(str(Path(main_module.__file__).resolve().parent.parent))

    import workflows.native_planner as native_planner_module

    flows_file = tmp_path / "flows.json"
    flow = {
        "id": "flow_1",
        "title": "Checkout",
        "entry_point": "https://example.test/checkout",
        "exit_point": "https://example.test/done",
        "happy_path": "Complete checkout.",
        "edge_cases": [],
        "test_ideas": ["Checkout succeeds."],
    }
    flows_file.write_text(json.dumps({"flows": [flow]}))
    spec_run_dir = main_module.RUNS_DIR / spec_run_id
    spec_run_dir.mkdir(parents=True)
    mcp_config_path = spec_run_dir / ".mcp.json"
    assert not mcp_config_path.exists()
    constructed: dict[str, bool] = {}
    auth_calls: list[dict] = []

    def fake_resolve_browser_auth_for_run(
        _db_session,
        resolved_project_id,
        *,
        run_dir,
        browser_auth_session_id=None,
        use_default=False,
    ):
        auth_calls.append(
            {
                "project_id": resolved_project_id,
                "browser_auth_session_id": browser_auth_session_id,
                "use_default": use_default,
            }
        )
        storage_state_path = Path(run_dir) / "browser-auth-storage-state.json"
        storage_state_path.write_text(json.dumps({"cookies": [], "origins": []}))
        return types.SimpleNamespace(
            session_id=browser_auth_session_id,
            session_name="Background auth",
            storage_state_path=storage_state_path,
        )

    class FakeNativePlanner:
        def __init__(self, *args, session_dir=None, cwd=None, **kwargs):
            constructed["mcp_exists_before_planner"] = mcp_config_path.exists()
            assert session_dir == spec_run_dir
            assert cwd == spec_run_dir

        async def generate_spec_from_flow_context(self, **kwargs):
            spec_path = tmp_path / "generated-spec.md"
            spec_path.write_text("# Checkout spec\n\n- Target URL: https://example.test/checkout\n")
            return spec_path

    monkeypatch.setattr(native_planner_module, "NativePlanner", FakeNativePlanner)
    monkeypatch.setattr(main_module, "resolve_browser_auth_for_run", fake_resolve_browser_auth_for_run)
    main_module._flow_spec_jobs[job_id] = {
        "status": "running",
        "message": "Starting spec generation...",
        "started_at": 0,
        "run_id": run_id,
        "flow_id": "flow_1",
        "agent_run_id": spec_run_id,
    }

    try:
        with Session(engine) as session:
            session.add(AgentRun(id=spec_run_id, agent_type="spec_generation", status="running"))
            session.commit()

        await main_module._run_flow_spec_generation(
            job_id=job_id,
            run_id=run_id,
            flow_id="flow_1",
            flow=flow,
            flows=[flow],
            flows_file_path=str(flows_file),
            run_project_id="background-project",
            run_config={
                "url": "https://example.test",
                "project_id": "background-project",
                "browser_auth_session_id": "background-auth-session",
            },
            spec_agent_run_id=spec_run_id,
        )

        assert constructed["mcp_exists_before_planner"] is True
        assert mcp_config_path.exists()
        mcp_config = json.loads(mcp_config_path.read_text())
        args = mcp_config["mcpServers"]["playwright-test"]["args"]
        assert "--storage-state" in args
        assert args[args.index("--storage-state") + 1].endswith("browser-auth-storage-state.json")
        assert auth_calls == [
            {
                "project_id": "background-project",
                "browser_auth_session_id": "background-auth-session",
                "use_default": False,
            }
        ]
        with Session(engine) as session:
            spec_run = session.get(AgentRun, spec_run_id)
            assert spec_run is not None
            assert spec_run.status == "completed"
            assert spec_run.progress["mcp_config_path"] == str(mcp_config_path)
            assert spec_run.progress["artifacts_dir"] == str(spec_run_dir / "artifacts")
            assert spec_run.progress["browser_auth_session_id"] == "background-auth-session"
        assert main_module._flow_spec_jobs[job_id]["status"] == "completed"
    finally:
        main_module._flow_spec_jobs.pop(job_id, None)
        _cleanup_run(spec_run_id)
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_flow_spec_generation_mcp_setup_failure_marks_agent_run_failed(tmp_path, monkeypatch):
    spec_run_id = "reportspec-mcp-setup-failure"
    job_id = spec_run_id
    _ensure_tables()
    _cleanup_run(spec_run_id)
    monkeypatch.setattr(main_module, "RUNS_DIR", tmp_path / "runs")
    flow = {
        "id": "F-001",
        "title": "Broken setup",
        "entry_point": "https://example.test/login",
        "happy_path": "Open login.",
        "edge_cases": [],
        "test_ideas": ["Generate regression spec."],
    }
    flows_file = tmp_path / "source-flow.json"
    flows_file.write_text(json.dumps({"flows": [flow]}))

    def fail_mcp_setup(_run_dir, _storage_state_path=None):
        raise RuntimeError("MCP setup failed for test")

    monkeypatch.setattr(main_module, "_prepare_spec_generation_mcp_config", fail_mcp_setup)
    main_module._flow_spec_jobs[job_id] = {
        "status": "running",
        "message": "Starting spec generation...",
        "started_at": 0,
        "run_id": "source-run",
        "flow_id": "F-001",
        "agent_run_id": spec_run_id,
    }

    try:
        with Session(engine) as session:
            session.add(AgentRun(id=spec_run_id, agent_type="spec_generation", status="running"))
            session.commit()

        await main_module._run_flow_spec_generation(
            job_id=job_id,
            run_id="source-run",
            flow_id="F-001",
            flow=flow,
            flows=[flow],
            flows_file_path=str(flows_file),
            run_project_id=None,
            run_config={"url": "https://example.test"},
            spec_agent_run_id=spec_run_id,
        )

        with Session(engine) as session:
            spec_run = session.get(AgentRun, spec_run_id)
            assert spec_run is not None
            assert spec_run.status == "failed"
            assert spec_run.result["error"] == "MCP setup failed for test"
            assert spec_run.progress["phase"] == "failed"
            assert spec_run.progress["status"] == "failed"
            assert "MCP setup failed for test" in spec_run.progress["message"]
        assert main_module._flow_spec_jobs[job_id]["status"] == "failed"
        assert "MCP setup failed for test" in main_module._flow_spec_jobs[job_id]["message"]
    finally:
        main_module._flow_spec_jobs.pop(job_id, None)
        _cleanup_run(spec_run_id)


def test_extract_run_target_url_reads_spec_content():
    assert (
        main_module._extract_run_target_url_from_content(
            "# Test\n\n- Target URL: https://example.test/path\n\n1. Click Continue"
        )
        == "https://example.test/path"
    )


def test_browser_diagnostics_do_not_count_cli_browser_argument(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":99")

    def fake_run(cmd, **kwargs):
        if cmd[0] == "ps":
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout="123 python /app/orchestrator/cli.py specs/example.md --browser chromium\n",
                stderr="",
            )
        if cmd[0] == "xwininfo":
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(main_module.subprocess, "run", fake_run)

    diagnostics = main_module._live_browser_display_diagnostics()

    assert diagnostics["browser_process_count"] == 0
    assert diagnostics["browser_window_count"] == 0


def test_browser_diagnostics_count_real_chromium_process(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":99")

    def fake_run(cmd, **kwargs):
        if cmd[0] == "ps":
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=(
                    "123 python /app/orchestrator/cli.py specs/example.md --browser chromium\n"
                    "124 chromium /usr/bin/chromium --remote-debugging-port=9222\n"
                ),
                stderr="",
            )
        if cmd[0] == "xwininfo":
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout='     0x400003 "has no name": ()  1280x720+0+0  +0+0\n',
                stderr="",
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(main_module.subprocess, "run", fake_run)

    diagnostics = main_module._live_browser_display_diagnostics()

    assert diagnostics["browser_process_count"] == 1
    assert diagnostics["browser_window_count"] == 1


@pytest.mark.asyncio
async def test_custom_agent_browser_preflight_fails_without_installing(monkeypatch):
    progress: list[dict] = []
    monkeypatch.setattr(main_module, "_custom_agent_browser_runs_via_queue", lambda: False)
    monkeypatch.setattr(main_module, "_resolve_playwright_chromium_executable", lambda: None)

    def fake_run(cmd, **kwargs):
        assert cmd[0] == "node"
        assert "@playwright/mcp" not in cmd
        assert "install-browser" not in cmd
        return subprocess.CompletedProcess(
            cmd,
            1,
            stdout="",
            stderr="Executable doesn't exist at /ms-playwright/chromium",
        )

    monkeypatch.setattr(main_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        main_module,
        "_update_agent_run_progress",
        lambda _run_id, patch: progress.append(patch),
    )

    with pytest.raises(RuntimeError, match="rebuild/recreate the backend image"):
        await _ensure_custom_agent_browser_available("custom-agent-browser-missing")

    assert progress[0]["phase"] == "browser_setup"
    assert progress[0]["message"] == "Checking local Playwright browser availability"
    assert progress[-1]["phase"] == "failed"
    assert "browser_probe_output" in progress[-1]


@pytest.mark.asyncio
async def test_custom_agent_browser_preflight_skips_local_probe_when_queue_enabled(monkeypatch):
    progress: list[dict] = []
    monkeypatch.setattr(main_module, "_custom_agent_browser_runs_via_queue", lambda: True)
    monkeypatch.setattr(
        main_module,
        "browser_runtime_status",
        lambda: {
            "browser_runtime": "temporal_vnc_worker",
            "live_view_available": True,
            "vnc_url": "ws://localhost:6080/websockify",
            "runtime_message": "Browser execution is delegated to the live browser worker.",
        },
    )
    monkeypatch.setattr(
        main_module,
        "_probe_custom_agent_browser",
        lambda: pytest.fail("queue mode should not probe local Chromium"),
    )
    monkeypatch.setattr(
        main_module,
        "_update_agent_run_progress",
        lambda _run_id, patch: progress.append(patch),
    )

    await _ensure_custom_agent_browser_available("custom-agent-browser-queued")

    assert progress == [
        {
            "browser_runtime": "temporal_vnc_worker",
            "live_view_available": True,
            "vnc_url": "ws://localhost:6080/websockify",
            "runtime_message": "Browser execution is delegated to the live browser worker.",
            "phase": "browser_delegated",
            "message": "Browser execution delegated to agent worker",
        }
    ]


@pytest.mark.asyncio
async def test_custom_agent_browser_preflight_probes_when_direct_vnc_forced(monkeypatch):
    progress: list[dict] = []
    monkeypatch.setattr(main_module, "_custom_agent_browser_runs_via_queue", lambda: True)
    monkeypatch.setattr(main_module, "_probe_custom_agent_browser", lambda: (True, ""))
    monkeypatch.setattr(
        main_module,
        "_update_agent_run_progress",
        lambda _run_id, patch: progress.append(patch),
    )

    await _ensure_custom_agent_browser_available(
        "custom-agent-browser-direct",
        force_direct_execution=True,
    )

    phases = [patch["phase"] for patch in progress if "phase" in patch]
    assert "browser_delegated" not in phases
    assert phases[0] == "browser_setup"
    assert phases[-1] == "browser_ready"


@pytest.mark.asyncio
async def test_custom_agent_browser_preflight_reuses_active_agent_slot(monkeypatch):
    progress: list[dict] = []

    class FakePool:
        async def is_running(self, request_id):
            return request_id == "custom-agent-active"

    monkeypatch.setattr(main_module, "_custom_agent_browser_runs_via_queue", lambda: False)
    monkeypatch.setattr(main_module, "BROWSER_POOL", FakePool())
    monkeypatch.setattr(main_module, "_probe_custom_agent_browser", lambda: (True, ""))
    monkeypatch.setattr(
        main_module,
        "browser_operation_slot",
        lambda **_kwargs: pytest.fail("active agent slot should be reused for browser probe"),
    )
    monkeypatch.setattr(
        main_module,
        "_update_agent_run_progress",
        lambda _run_id, patch: progress.append(patch),
    )

    await _ensure_custom_agent_browser_available("custom-agent-active")

    phases = [patch["phase"] for patch in progress if "phase" in patch]
    assert phases[-1] == "browser_ready"


def test_custom_agent_browser_queue_mode_uses_agent_queue_predicate(monkeypatch):
    monkeypatch.setenv("USE_AGENT_QUEUE", "true")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setattr("orchestrator.services.agent_queue.REDIS_AVAILABLE", True)

    assert _custom_agent_browser_runs_via_queue() is True


def _latest_event(run_id: str, event_type: str) -> AgentRunEvent | None:
    with Session(engine) as session:
        return session.exec(
            select(AgentRunEvent).where(
                AgentRunEvent.run_id == run_id,
                AgentRunEvent.event_type == event_type,
            )
        ).first()


@pytest.mark.asyncio
async def test_start_agent_run_temporal_records_workflow_ids(monkeypatch):
    run_id = "agent-temporal-start"
    _create_run(run_id)

    async def fake_start_agent_run_workflow(value: str, *, task_queue: str | None = None):
        assert value == run_id
        assert task_queue == "quorvex-custom-workflows"
        return TemporalWorkflowStart(
            workflow_id="agent-run-agent-temporal-start", run_id="temporal-run-1"
        )

    monkeypatch.setattr(
        "orchestrator.services.temporal_client.start_agent_run_workflow",
        fake_start_agent_run_workflow,
    )

    try:
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            await _start_agent_run_temporal_or_fail(run, session)
            session.refresh(run)
            assert run.temporal_workflow_id == "agent-run-agent-temporal-start"
            assert run.temporal_run_id == "temporal-run-1"
            event = session.exec(
                select(AgentRunEvent).where(
                    AgentRunEvent.run_id == run_id,
                    AgentRunEvent.event_type == "temporal_scheduled",
                )
            ).first()
            assert event is not None
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_browser_agent_run_temporal_uses_vnc_task_queue(monkeypatch):
    run_id = "agent-temporal-browser-queue"
    _ensure_tables()
    _cleanup_run(run_id)
    monkeypatch.setenv("VNC_ENABLED", "true")
    monkeypatch.setenv("HEADLESS", "false")
    monkeypatch.setenv("DISPLAY", ":99")
    captured: dict[str, str | None] = {}
    with Session(engine) as session:
        run = AgentRun(
            id=run_id,
            agent_type="custom",
            status="queued",
            config_json=json.dumps(
                {"allowed_tools": ["mcp__playwright-test__browser_navigate"]}
            ),
        )
        session.add(run)
        session.commit()

    async def fake_start_agent_run_workflow(value: str, *, task_queue: str | None = None):
        assert value == run_id
        captured["task_queue"] = task_queue
        return TemporalWorkflowStart(
            workflow_id="agent-run-agent-temporal-browser-queue",
            run_id="temporal-run-browser",
        )

    monkeypatch.setattr(
        "orchestrator.services.temporal_client.start_agent_run_workflow",
        fake_start_agent_run_workflow,
    )

    try:
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            await _start_agent_run_temporal_or_fail(run, session)
            assert captured["task_queue"] == "quorvex-browser-workflows"
            event = session.exec(
                select(AgentRunEvent).where(
                    AgentRunEvent.run_id == run_id,
                    AgentRunEvent.event_type == "temporal_scheduled",
                )
            ).first()
            assert event is not None
            assert event.payload["task_queue"] == "quorvex-browser-workflows"
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_browser_agent_run_temporal_uses_live_worker_task_queue(monkeypatch):
    run_id = "agent-temporal-browser-live-worker"
    _ensure_tables()
    _cleanup_run(run_id)
    monkeypatch.delenv("VNC_ENABLED", raising=False)
    monkeypatch.setenv("LIVE_BROWSER_WORKER_ENABLED", "true")
    captured: dict[str, str | None] = {}
    with Session(engine) as session:
        run = AgentRun(
            id=run_id,
            agent_type="exploratory",
            status="queued",
            config_json=json.dumps({"url": "https://example.com"}),
        )
        session.add(run)
        session.commit()

    async def fake_start_agent_run_workflow(value: str, *, task_queue: str | None = None):
        assert value == run_id
        captured["task_queue"] = task_queue
        return TemporalWorkflowStart(
            workflow_id="agent-run-agent-temporal-browser-live-worker",
            run_id="temporal-run-browser-worker",
        )

    monkeypatch.setattr(
        "orchestrator.services.temporal_client.start_agent_run_workflow",
        fake_start_agent_run_workflow,
    )

    try:
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            await _start_agent_run_temporal_or_fail(run, session)
            assert captured["task_queue"] == "quorvex-browser-workflows"
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_start_agent_run_temporal_failure_marks_run_failed(monkeypatch):
    run_id = "agent-temporal-start-failed"
    _create_run(run_id)

    async def unavailable(_: str, *, task_queue: str | None = None):
        raise TemporalUnavailableError("Temporal down")

    monkeypatch.setattr(
        "orchestrator.services.temporal_client.start_agent_run_workflow", unavailable
    )

    try:
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            with pytest.raises(HTTPException) as exc_info:
                await _start_agent_run_temporal_or_fail(run, session)
            assert exc_info.value.status_code == 503
            session.refresh(run)
            assert run.status == "failed"
            assert run.completed_at is not None
            assert run.result["error"].startswith("Failed to start Temporal workflow")
    finally:
        _cleanup_run(run_id)


def test_agent_run_temporal_activity_records_started_metadata():
    run_id = "agent-temporal-activity-started"
    _create_run(run_id)

    try:
        result = mark_agent_run_temporal_started(
            {
                "run_id": run_id,
                "workflow_id": "agent-run-wf",
                "temporal_run_id": "temporal-run",
            }
        )

        assert result["status"] == "running"
        assert result["temporal_workflow_id"] == "agent-run-wf"
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            assert run.started_at is not None
            assert run.temporal_workflow_id == "agent-run-wf"
    finally:
        _cleanup_run(run_id)


def test_agent_run_execution_state_copies_context_before_session_close():
    run_id = "agent-temporal-execution-state"
    _ensure_tables()
    _cleanup_run(run_id)
    with Session(engine) as session:
        run = AgentRun(
            id=run_id,
            agent_type="custom",
            status="running",
            agent_task_id="agent-task-existing",
            config_json='{"prompt":"inspect"}',
        )
        session.add(run)
        session.commit()

    try:
        state = _load_agent_run_execution_state(run_id)

        assert state["terminal"] is False
        assert state["agent_type"] == "custom"
        assert state["config"] == {"prompt": "inspect"}
        assert state["agent_task_id"] == "agent-task-existing"
        assert state["payload"]["status"] == "running"
    finally:
        _cleanup_run(run_id)


def test_agent_run_activity_cancelled_helper_persists_terminal_status():
    run_id = "agent-temporal-activity-cancelled"
    _create_run(run_id, status="running")

    try:
        result = _mark_agent_run_activity_cancelled(run_id)

        assert result["status"] == "cancelled"
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            assert run.status == "cancelled"
            assert run.completed_at is not None
            assert run.progress["phase"] == "cancelled"
        assert _latest_event(run_id, "cancel") is not None
    finally:
        _cleanup_run(run_id)


def test_finalize_agent_run_workflow_recovers_custom_raw_output_as_partial(tmp_path, monkeypatch):
    run_id = "agent-temporal-partial-custom"
    _ensure_tables()
    _cleanup_run(run_id)
    monkeypatch.setattr(main_module, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(
        main_module.exploration,
        "_collect_exploration_artifacts",
        lambda session_id: [{"name": "live-step-001.png", "path": f"/artifacts/{session_id}/live-step-001.png", "type": "image"}],
    )
    run_dir = main_module.RUNS_DIR / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "raw_output.txt").write_text(
        "Checked https://example.test/checkout and found a validation error.",
        encoding="utf-8",
    )
    (run_dir / "live-step-001.png").write_bytes(b"png")

    try:
        with Session(engine) as session:
            run = AgentRun(
                id=run_id,
                agent_type="custom",
                runtime="claude_sdk",
                status="running",
                config_json=json.dumps({"prompt": "Inspect checkout", "url": "https://example.test"}),
            )
            session.add(run)
            session.commit()

        result = finalize_agent_run_workflow(
            {
                "run_id": run_id,
                "result": {
                    "status": "failed",
                    "error": "Activity task failed",
                    "activity_failed": True,
                },
            }
        )

        assert result["status"] == "completed_partial"
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            assert run.status == "completed_partial"
            assert run.result["failure_reason"] == "runtime_failed_after_evidence"
            assert run.result["output"].startswith("Checked https://example.test/checkout")
            assert run.result["structured_report"]["evidence"]
            assert run.progress["raw_output_chars"] > 0
            assert run.progress["artifact_count"] >= 1
    finally:
        _cleanup_run(run_id)


def test_reattach_finalizer_failure_falls_back_to_partial_result(monkeypatch):
    run = AgentRun(
        id="agent-temporal-finalizer-fallback",
        agent_type="custom",
        status="running",
        config_json='{"prompt":"inspect"}',
    )

    class BrokenFinalizer:
        def finalize(self, **_kwargs):
            raise RuntimeError("bad finalizer")

    monkeypatch.setattr(
        "orchestrator.services.agent_run_finalizer.AgentRunFinalizer",
        lambda: BrokenFinalizer(),
    )

    _finalize_reattached_agent_task(
        run,
        "agent-temporal-finalizer-fallback",
        "agent-task-existing",
        "partial output",
        [],
        {},
    )

    assert run.status == "completed_partial"
    assert run.result["summary"] == "partial output"
    assert run.result["contract_status"] == "partial"
    assert run.result["diagnostics"]["finalizer"]["agent_task_id"] == "agent-task-existing"


def test_reattach_failure_without_recovery_marks_retry_and_returns_none(monkeypatch):
    run_id = "agent-temporal-reattach-retry"
    _ensure_tables()
    _cleanup_run(run_id)
    with Session(engine) as session:
        run = AgentRun(
            id=run_id,
            agent_type="custom",
            status="running",
            agent_task_id="agent-task-existing",
            config_json='{"prompt":"inspect"}',
        )
        session.add(run)
        session.commit()

    monkeypatch.setattr(
        "orchestrator.services.agent_run_activities._recover_custom_agent_partial_result",
        lambda *_args: None,
    )

    try:
        result = _handle_agent_task_reattach_failure(
            run_id,
            "agent-task-existing",
            RuntimeError("queue disconnected"),
        )

        assert result is None
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            assert run.status == "running"
            assert run.progress["phase"] == "retrying"
            assert run.progress["status"] == "running"
            assert "queue disconnected" in run.progress["message"]
        event = _latest_event(run_id, "retry")
        assert event is not None
        assert event.payload["retryable"] is True
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_retry_agent_run_requeues_same_run_with_unique_temporal_workflow(monkeypatch, tmp_path):
    run_id = "agent-temporal-retry-source"
    created_workflows: list[tuple[str, int | None]] = []
    _ensure_tables()
    _cleanup_run(run_id)
    monkeypatch.setattr(main_module, "RUNS_DIR", tmp_path / "runs")
    run_dir = main_module.RUNS_DIR / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "browser-auth-storage-state.json").write_text("{}", encoding="utf-8")
    (run_dir / "raw_output.txt").write_text("Saw https://example.com/dashboard before timeout.", encoding="utf-8")

    async def fake_start_agent_run_temporal_or_fail(run, session, *, workflow_attempt=None):
        run.temporal_workflow_id = f"agent-run-{run.id}-attempt-{workflow_attempt}"
        run.temporal_run_id = "temporal-retry-run"
        session.add(run)
        session.commit()
        created_workflows.append((run.id, workflow_attempt))

    monkeypatch.setattr(main_module, "_start_agent_run_temporal_or_fail", fake_start_agent_run_temporal_or_fail)

    try:
        with Session(engine) as session:
            source = AgentRun(
                id=run_id,
                agent_type="custom",
                runtime="hermes",
                status="failed",
                config_json=json.dumps(
                    {
                        "url": "https://example.com",
                        "runtime": "hermes",
                        "browser_auth_session_id": "session-1",
                        "use_project_default_browser_auth": True,
                        "test_data_refs": ["login.valid-user"],
                        "allowed_tools": ["mcp__playwright-test__browser_navigate"],
                    }
                ),
            )
            source.agent_task_id = "old-task"
            source.temporal_workflow_id = "agent-run-old-workflow"
            source.temporal_run_id = "old-temporal-run"
            source.result = {"error": "zero evidence"}
            source.progress = {"phase": "failed", "retry_attempt": 1, "last_url": "https://example.com/checkout"}
            session.add(source)
            session.commit()

            response = await retry_agent_run(run_id, session=session, current_user=None)

            session.refresh(source)
            assert response["run_id"] == run_id
            assert response["id"] == run_id
            assert response["retry_in_place"] is True
            assert source.status == "queued"
            assert source.runtime == "claude_sdk"
            assert source.agent_task_id is None
            assert source.temporal_workflow_id == "agent-run-agent-temporal-retry-source-attempt-2"
            assert source.temporal_run_id == "temporal-retry-run"
            assert source.config["source_run_id"] == run_id
            assert source.config["retry_in_place"] is True
            assert source.config["retry_attempt"] == 2
            assert source.config["browser_auth_session_id"] == "session-1"
            assert source.config["use_project_default_browser_auth"] is True
            assert source.config["test_data_refs"] == ["login.valid-user"]
            assert source.config["retry_context"]["last_observed_url"] == "https://example.com/checkout"
            assert source.progress["previous_temporal_workflow_id"] == "agent-run-old-workflow"
            assert source.progress["storage_state_reused"] is True
            assert created_workflows == [(run_id, 2)]
            event = session.exec(
                select(AgentRunEvent).where(
                    AgentRunEvent.run_id == run_id,
                    AgentRunEvent.event_type == "retry_started",
                )
            ).first()
            assert event is not None
            assert event.payload["retry_attempt"] == 2
    finally:
        _cleanup_run(run_id)


def test_agent_run_control_activity_updates_status():
    run_id = "agent-temporal-control"
    _create_run(run_id, status="running")

    try:
        result = set_agent_run_control_status(
            {"run_id": run_id, "status": "paused", "reason": "manual_pause"}
        )

        assert result["status"] == "paused"
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            assert run.status == "paused"
            assert run.progress["paused_from"] == "running"
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_agent_run_temporal_signal_failure_returns_503(monkeypatch):
    run_id = "agent-temporal-signal-failed"
    _create_run(run_id, status="running")

    async def unavailable(*_args):
        raise TemporalUnavailableError("Temporal down")

    monkeypatch.setattr(
        "orchestrator.services.temporal_client.signal_agent_run_workflow", unavailable
    )

    try:
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            run.temporal_workflow_id = "agent-run-signal-failed"
            session.add(run)
            session.commit()

            with pytest.raises(HTTPException) as exc_info:
                await _signal_agent_run_temporal(run, "pause", "manual_pause")
            assert exc_info.value.status_code == 503
            assert "Temporal is unavailable" in exc_info.value.detail
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_execute_agent_run_completes_temporal_smoke_without_llm():
    run_id = "agent-temporal-smoke"
    _ensure_tables()
    _cleanup_run(run_id)
    with Session(engine) as session:
        run = AgentRun(
            id=run_id,
            agent_type="__temporal_smoke__",
            status="running",
            config_json='{"temporal_smoke": true}',
        )
        session.add(run)
        session.commit()

    try:
        result = await execute_agent_run({"run_id": run_id})

        assert result["status"] == "completed"
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            assert run.status == "completed"
            assert run.completed_at is not None
            assert run.result["smoke"] is True
        assert _latest_event(run_id, "complete") is not None
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_exploratory_background_marks_zero_evidence_parse_fallback_failed(monkeypatch):
    run_id = "agent-exploratory-zero-evidence"
    _ensure_tables()
    _cleanup_run(run_id)
    with Session(engine) as session:
        run = AgentRun(
            id=run_id,
            agent_type="exploratory",
            status="running",
            config_json='{"url":"https://example.com","project_id":"default"}',
        )
        session.add(run)
        session.commit()

    from orchestrator.agents.exploratory_agent import ExploratoryAgent

    async def fake_run(self, config: dict):
        return {
            "summary": "Exploration failed: result parsing failed and no browser actions recovered.",
            "parsing_failed": True,
            "failure_reason": "zero_evidence_parse_fallback",
            "action_trace": [],
            "discovered_flow_summaries": [],
            "total_flows_discovered": 0,
        }

    monkeypatch.setattr(ExploratoryAgent, "run", fake_run)

    try:
        await main_module.execute_agent_background(
            run_id,
            "exploratory",
            {"url": "https://example.com", "project_id": "default"},
        )

        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            assert run.status == "failed"
            assert run.completed_at is not None
            assert run.result["failure_reason"] == "zero_evidence_parse_fallback"
            assert run.progress["status"] == "failed"
        assert _latest_event(run_id, "error") is not None
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_exploratory_background_marks_runtime_auth_failed(monkeypatch):
    run_id = "agent-exploratory-runtime-auth"
    _ensure_tables()
    _cleanup_run(run_id)
    with Session(engine) as session:
        run = AgentRun(
            id=run_id,
            agent_type="exploratory",
            status="running",
            config_json='{"url":"https://example.com","project_id":"default"}',
        )
        session.add(run)
        session.commit()

    from orchestrator.agents.exploratory_agent import ExploratoryAgent

    async def fake_run(self, config: dict):
        return {
            "summary": "Claude SDK runtime is not authenticated. Add an API key in Settings or run Claude login in the container.",
            "failure_reason": "runtime_auth_failed",
            "action_trace": [],
            "discovered_flow_summaries": [],
            "total_flows_discovered": 0,
        }

    monkeypatch.setattr(ExploratoryAgent, "run", fake_run)

    try:
        await main_module.execute_agent_background(
            run_id,
            "exploratory",
            {"url": "https://example.com", "project_id": "default"},
        )

        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            assert run.status == "failed"
            assert run.completed_at is not None
            assert run.result["failure_reason"] == "runtime_auth_failed"
            assert run.progress["status"] == "failed"
            assert "Claude SDK runtime is not authenticated" in run.progress["message"]
        event = _latest_event(run_id, "error")
        assert event is not None
        assert "Claude SDK runtime is not authenticated" in event.message
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_execute_agent_run_defaults_to_direct_execution_for_temporal_activity(monkeypatch):
    run_id = "agent-temporal-direct-execution"
    _ensure_tables()
    _cleanup_run(run_id)
    monkeypatch.delenv("USE_AGENT_QUEUE", raising=False)
    with Session(engine) as session:
        run = AgentRun(
            id=run_id,
            agent_type="custom",
            status="running",
            config_json='{"prompt":"inspect"}',
        )
        session.add(run)
        session.commit()

    async def fake_execute_agent_background(value: str, agent_type: str, config: dict):
        assert value == run_id
        assert agent_type == "custom"
        assert config == {"prompt": "inspect"}
        assert main_module.os.environ["USE_AGENT_QUEUE"] == "false"
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            run.status = "completed"
            run.result = {"summary": "direct temporal activity"}
            run.completed_at = main_module.datetime.utcnow()
            session.add(run)
            session.commit()

    monkeypatch.setattr(main_module, "execute_agent_background", fake_execute_agent_background)

    try:
        result = await execute_agent_run({"run_id": run_id})

        assert result["status"] == "completed"
        assert "USE_AGENT_QUEUE" not in main_module.os.environ
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            assert run.agent_task_id is None
            assert run.result["summary"] == "direct temporal activity"
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_execute_agent_run_overrides_redis_queue_for_temporal_activity(monkeypatch):
    run_id = "agent-temporal-queued-execution"
    _ensure_tables()
    _cleanup_run(run_id)
    monkeypatch.setenv("USE_AGENT_QUEUE", "true")
    with Session(engine) as session:
        run = AgentRun(
            id=run_id,
            agent_type="custom",
            status="running",
            config_json='{"prompt":"inspect"}',
        )
        session.add(run)
        session.commit()

    async def fake_execute_agent_background(value: str, agent_type: str, config: dict):
        assert value == run_id
        assert agent_type == "custom"
        assert config == {"prompt": "inspect"}
        assert main_module.os.environ["USE_AGENT_QUEUE"] == "false"
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            run.status = "completed"
            run.result = {"summary": "queued temporal activity"}
            run.completed_at = main_module.datetime.utcnow()
            session.add(run)
            session.commit()

    monkeypatch.setattr(main_module, "execute_agent_background", fake_execute_agent_background)

    try:
        result = await execute_agent_run({"run_id": run_id})

        assert result["status"] == "completed"
        assert main_module.os.environ["USE_AGENT_QUEUE"] == "true"
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            assert run.result["summary"] == "queued temporal activity"
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_execute_agent_run_reattaches_existing_agent_task(monkeypatch):
    run_id = "agent-temporal-reattach"
    _ensure_tables()
    _cleanup_run(run_id)
    with Session(engine) as session:
        run = AgentRun(
            id=run_id,
            agent_type="custom",
            status="running",
            agent_task_id="agent-task-existing",
            config_json='{"prompt":"inspect"}',
        )
        session.add(run)
        session.commit()

    class FakeQueue:
        async def connect(self):
            return None

        async def wait_for_result(
            self, task_id: str, timeout: int, poll_interval: float, on_progress=None
        ):
            assert task_id == "agent-task-existing"
            assert timeout == 12 * 60 * 60
            assert poll_interval == 1.0
            return '```json\n{"structured_report":{"summary":"reattached result","scope":"inspect","findings":[],"test_ideas":[],"requirements":[],"evidence":[],"pages_checked":[],"follow_up_actions":[]}}\n```'

        async def get_task(self, task_id: str):
            return types.SimpleNamespace(telemetry={})

    monkeypatch.setattr(
        "orchestrator.services.agent_queue.get_agent_queue", lambda: FakeQueue()
    )

    try:
        result = await execute_agent_run({"run_id": run_id})

        assert result["status"] == "completed"
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            assert run.status == "completed"
            assert run.result["structured_report"]["summary"] == "reattached result"
            assert run.result["contract_status"] in {"valid", "repaired"}
        assert _latest_event(run_id, "complete") is not None
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_execute_agent_run_reattach_persists_queue_progress(monkeypatch):
    run_id = "agent-temporal-reattach-progress"
    _ensure_tables()
    _cleanup_run(run_id)
    with Session(engine) as session:
        run = AgentRun(
            id=run_id,
            agent_type="custom",
            status="running",
            agent_task_id="agent-task-progress",
            config_json='{"prompt":"inspect"}',
        )
        run.progress = {"phase": "queued", "message": "Queued"}
        session.add(run)
        session.commit()

    class FakeQueue:
        async def connect(self):
            return None

        async def wait_for_result(
            self, task_id: str, timeout: int, poll_interval: float, on_progress=None
        ):
            assert task_id == "agent-task-progress"
            assert on_progress is not None
            on_progress(
                {
                    "phase": "tool_use",
                    "last_tool": "mcp__playwright__browser_click",
                    "tool_calls": 3,
                    "browser_tool_calls": 2,
                    "interactions": 2,
                    "message": "Clicking checkout",
                }
            )
            return '```json\n{"structured_report":{"summary":"reattached result","scope":"inspect","findings":[],"test_ideas":[],"requirements":[],"evidence":[],"pages_checked":[],"follow_up_actions":[]}}\n```'

        async def get_task(self, task_id: str):
            return types.SimpleNamespace(telemetry={})

    monkeypatch.setattr(
        "orchestrator.services.agent_queue.get_agent_queue", lambda: FakeQueue()
    )

    try:
        result = await execute_agent_run({"run_id": run_id})

        assert result["status"] == "completed"
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            assert run.status == "completed"
            assert run.progress["phase"] == "completed"
            assert run.progress["status"] == "completed"
            assert run.progress["tool_calls"] == 3
            assert run.progress["browser_tool_calls"] == 2
            assert run.progress["interactions"] == 2
            assert run.progress["last_tool"] == "mcp__playwright__browser_click"
            assert run.progress["current_tool"] == "mcp__playwright__browser_click"
            assert run.progress["last_tool_label"] == "browser_click"
            assert run.progress["current_tool_label"] == "browser_click"
            assert run.progress["recent_tools"][-1]["label"] == "browser_click"
        assert _latest_event(run_id, "complete") is not None
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_agent_run_temporal_health_reports_worker_contract(monkeypatch):
    async def connected():
        return object()

    monkeypatch.setattr(
        "orchestrator.services.temporal_client._connect_client", connected
    )
    async def task_queue_status(_task_queue: str):
        return {
            "workflow_pollers": 1,
            "activity_pollers": 1,
            "has_workflow_pollers": True,
            "has_activity_pollers": True,
        }

    monkeypatch.setattr(
        "orchestrator.services.temporal_client.describe_temporal_task_queue",
        task_queue_status,
    )

    health = await check_agent_run_temporal_health()

    assert health["available"] is True
    assert health["workflow_type"] == "AgentRunWorkflow"
    assert health["worker_module"] == "orchestrator.services.custom_workflow_worker"
    assert "AgentRunWorkflow" in health["worker_contract"]["workflows"]
    assert "DomainJobWorkflow" in health["worker_contract"]["workflows"]
    assert "execute_agent_run" in health["worker_contract"]["activities"]
    assert "execute_domain_job" in health["worker_contract"]["activities"]
    assert "direct_agent_execution" in health["worker_contract"]["capabilities"]
    assert health["task_queue"]


@pytest.mark.asyncio
async def test_agent_run_temporal_health_degrades_without_worker_pollers(monkeypatch):
    async def connected():
        return object()

    async def task_queue_status(_task_queue: str):
        return {
            "workflow_pollers": 0,
            "activity_pollers": 0,
            "has_workflow_pollers": False,
            "has_activity_pollers": False,
        }

    monkeypatch.setattr(
        "orchestrator.services.temporal_client._connect_client", connected
    )
    monkeypatch.setattr(
        "orchestrator.services.temporal_client.describe_temporal_task_queue",
        task_queue_status,
    )

    health = await check_agent_run_temporal_health()

    assert health["available"] is False
    assert health["status"] == "degraded"
    assert health["worker_pollers"] == {"workflow": 0, "activity": 0}
    assert "No Temporal worker pollers" in health["error"]


@pytest.mark.asyncio
async def test_requirements_job_status_reads_durable_domain_job():
    _ensure_tables()
    job_id = "domain-req-job"
    _cleanup_domain_job(job_id)

    from orchestrator.services.domain_jobs import create_domain_job, update_domain_job

    try:
        create_domain_job(
            job_id=job_id,
            job_type="requirements_generate",
            project_id="default",
            payload={"project_id": "default", "session_id": "session-1"},
        )
        update_domain_job(
            job_id,
            status="completed",
            result={"total_requirements": 2},
            temporal_workflow_id="domain-job-requirements_generate-domain-req-job",
            temporal_run_id="temporal-run",
            completed=True,
        )

        status = await get_generate_job_status(job_id)

        assert status["status"] == "completed"
        assert status["session_id"] == "session-1"
        assert status["temporal_workflow_id"] == "domain-job-requirements_generate-domain-req-job"
        assert status["result"] == {"total_requirements": 2}
    finally:
        _cleanup_domain_job(job_id)


@pytest.mark.asyncio
async def test_bulk_job_status_reads_durable_progress_without_credentials():
    _ensure_tables()
    job_id = "domain-bulk-job"
    _cleanup_domain_job(job_id)

    from orchestrator.services.domain_jobs import create_domain_job, update_domain_job

    try:
        create_domain_job(
            job_id=job_id,
            job_type="requirements_bulk_generate",
            project_id="default",
            payload={
                "project_id": "default",
                "target_url": "http://app.test",
                "credentials": {"username": "user", "password": "secret"},
            },
            progress={"total": 3, "completed": 1, "failed": 0, "results": [], "error": None},
        )
        update_domain_job(job_id, status="running", started=True)

        status = await get_bulk_generate_job_status(job_id)

        assert status["status"] == "running"
        assert status["total"] == 3
        assert status["completed"] == 1
        assert "credentials" not in status
    finally:
        _cleanup_domain_job(job_id)


@pytest.mark.asyncio
async def test_rtm_job_status_reads_durable_domain_job():
    _ensure_tables()
    job_id = "domain-rtm-job"
    _cleanup_domain_job(job_id)

    from orchestrator.services.domain_jobs import create_domain_job, update_domain_job

    try:
        create_domain_job(
            job_id=job_id,
            job_type="rtm_generate",
            project_id="default",
            payload={"project_id": "default", "specs_paths": ["specs/a.yaml"], "use_ai_matching": True},
        )
        update_domain_job(
            job_id,
            status="failed",
            error="ValueError: bad spec",
            temporal_workflow_id="domain-job-rtm_generate-domain-rtm-job",
            completed=True,
        )

        status = await get_rtm_generate_job_status(job_id)

        assert status["status"] == "failed"
        assert status["specs_paths"] == ["specs/a.yaml"]
        assert status["error"] == "ValueError: bad spec"
    finally:
        _cleanup_domain_job(job_id)


@pytest.mark.asyncio
async def test_legacy_exploratory_endpoint_starts_temporal(monkeypatch):
    _ensure_tables()
    started: list[str] = []

    async def fake_start_agent_run_workflow(run_id: str, *, task_queue: str | None = None):
        started.append(run_id)
        return TemporalWorkflowStart(workflow_id=f"agent-run-{run_id}", run_id="temporal-run")

    monkeypatch.setattr(
        "orchestrator.services.temporal_client.start_agent_run_workflow",
        fake_start_agent_run_workflow,
    )

    run_id = None
    try:
        with Session(engine) as session:
            response = await main_module.run_exploratory_agent(
                main_module.ExploratoryRunRequest(url="https://example.com", project_id="default"),
                session=session,
            )
            run_id = response["run_id"]

        assert response["status"] == "queued"
        assert response["temporal_workflow_id"] == f"agent-run-{run_id}"
        assert started == [run_id]
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            assert run.status == "queued"
            assert run.temporal_workflow_id == f"agent-run-{run_id}"
            assert run.agent_task_id is None
    finally:
        if run_id:
            _cleanup_run(run_id)


def test_agent_run_temporal_parses_workflow_task_registration_failure():
    class Failure:
        message = "Workflow class AgentRunWorkflow is not registered on this worker, available workflows: CustomWorkflowRun"
        stack_trace = "stack"
        application_failure_info = type(
            "ApplicationInfo", (), {"type": "NotFoundError"}
        )()

    class Attrs:
        failure = Failure()
        cause = None
        scheduled_event_id = 2
        started_event_id = 3

    class Event:
        event_id = 4
        event_type = "EVENT_TYPE_WORKFLOW_TASK_FAILED"
        workflow_task_failed_event_attributes = Attrs()

    failures = _parse_workflow_task_failures([Event()])

    assert failures[0]["failure_type"] == "NotFoundError"
    assert "AgentRunWorkflow" in failures[0]["message"]
    assert _agent_run_worker_registration_failure(failures) == (
        "Temporal worker does not have AgentRunWorkflow registered. "
        "Restart the custom workflow worker with the latest code."
    )
