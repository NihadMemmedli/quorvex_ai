import sys
import subprocess
import types
import json
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
)
from orchestrator.api.models_db import AgentRun, AgentRunEvent, DomainJob
from orchestrator.api.requirements import get_bulk_generate_job_status, get_generate_job_status
from orchestrator.api.rtm import get_rtm_generate_job_status
from orchestrator.services.agent_run_activities import (
    execute_agent_run,
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


def test_custom_agent_browser_tool_detection_only_matches_playwright_mcp_tools():
    assert _custom_agent_uses_browser_tools(["mcp__playwright-test__browser_click"]) is True
    assert _custom_agent_uses_browser_tools(["mcp__playwright__browser_navigate"]) is True
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


def test_custom_agent_browser_preflight_fails_without_installing(monkeypatch):
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
        _ensure_custom_agent_browser_available("custom-agent-browser-missing")

    assert progress[0]["phase"] == "browser_setup"
    assert progress[0]["message"] == "Checking local Playwright browser availability"
    assert progress[-1]["phase"] == "failed"
    assert "browser_probe_output" in progress[-1]


def test_custom_agent_browser_preflight_skips_local_probe_when_queue_enabled(monkeypatch):
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

    _ensure_custom_agent_browser_available("custom-agent-browser-queued")

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


def test_custom_agent_browser_preflight_probes_when_direct_vnc_forced(monkeypatch):
    progress: list[dict] = []
    monkeypatch.setattr(main_module, "_custom_agent_browser_runs_via_queue", lambda: True)
    monkeypatch.setattr(main_module, "_probe_custom_agent_browser", lambda: (True, ""))
    monkeypatch.setattr(
        main_module,
        "_update_agent_run_progress",
        lambda _run_id, patch: progress.append(patch),
    )

    _ensure_custom_agent_browser_available(
        "custom-agent-browser-direct",
        force_direct_execution=True,
    )

    phases = [patch["phase"] for patch in progress if "phase" in patch]
    assert "browser_delegated" not in phases
    assert phases[0] == "browser_setup"
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
            self, task_id: str, timeout: int, poll_interval: float
        ):
            assert task_id == "agent-task-existing"
            assert timeout == 12 * 60 * 60
            assert poll_interval == 1.0
            return "reattached result"

    monkeypatch.setattr(
        "orchestrator.services.agent_queue.get_agent_queue", lambda: FakeQueue()
    )

    try:
        result = await execute_agent_run({"run_id": run_id})

        assert result["status"] == "completed"
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            assert run.status == "completed"
            assert run.result["output"] == "reattached result"
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
