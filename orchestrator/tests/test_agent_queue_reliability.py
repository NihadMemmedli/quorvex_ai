import asyncio
import json
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import orchestrator.api.db as db_module
from orchestrator.api.models_db import BrowserAuthSession, PrdGenerationResult, Project
from orchestrator.services.agent_queue import AgentQueue, AgentTask, AgentTaskStatus
from orchestrator.services.agent_worker import (
    AgentWorker,
    BrowserObservationRecorder,
    BrowserToolTimeoutError,
    _event_tool_uses,
)
from orchestrator.utils import browser_cleanup
from orchestrator.utils.agent_runner import AgentRunner

UTC = timezone.utc


class _MemoryPipeline:
    def __init__(self, redis):
        self.redis = redis

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def hset(self, key, field, value):
        self.redis.hashes.setdefault(key, {})[field] = value

    def rpush(self, key, value):
        self.redis.lists.setdefault(key, []).append(value)

    def sadd(self, key, value):
        self.redis.sets.setdefault(key, set()).add(value)

    def srem(self, key, value):
        self.redis.sets.setdefault(key, set()).discard(value)

    def set(self, key, value, ex=None):
        self.redis.values[key] = value

    def delete(self, key):
        self.redis.values.pop(key, None)

    async def execute(self):
        return True


class _MemoryRedis:
    def __init__(self):
        self.hashes = {}
        self.lists = {}
        self.sets = {}
        self.values = {}

    def pipeline(self, transaction=True):
        return _MemoryPipeline(self)

    async def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value

    async def lrange(self, key, start, end):
        values = self.lists.get(key, [])
        if end == -1:
            end = len(values) - 1
        return values[start : end + 1]

    async def llen(self, key):
        return len(self.lists.get(key, []))

    async def lrem(self, key, count, value):
        values = self.lists.get(key, [])
        before = len(values)
        self.lists[key] = [item for item in values if item != value]
        return before - len(self.lists[key])

    async def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    async def lpop(self, key):
        values = self.lists.get(key, [])
        return values.pop(0) if values else None

    async def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    async def blpop(self, key, timeout=0):
        value = await self.lpop(key)
        return (key, value) if value else None

    async def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)

    async def smembers(self, key):
        return set(self.sets.get(key, set()))

    async def scard(self, key):
        return len(self.sets.get(key, set()))

    async def srem(self, key, value):
        self.sets.setdefault(key, set()).discard(value)

    async def sismember(self, key, value):
        return value in self.sets.get(key, set())

    async def set(self, key, value, ex=None):
        self.values[key] = value

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.values.pop(key, None)

    async def exists(self, key):
        return 1 if key in self.values else 0

    async def scan_iter(self, pattern):
        prefix = pattern.rstrip("*")
        for key in list(self.values):
            if key.startswith(prefix):
                yield key


class _MemoryQueue(AgentQueue):
    def __init__(self, redis):
        self._redis = redis
        self._worker_id = "memory-worker"

    async def _ensure_connected(self):
        return self._redis


def _make_prd_generation_engine(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine, tables=[PrdGenerationResult.__table__])
    monkeypatch.setattr(db_module, "engine", engine)
    return engine


def _create_prd_generation(engine, status="running"):
    with Session(engine) as session:
        generation = PrdGenerationResult(
            prd_project="wetravel-manage-rooms",
            feature_name="Package Management",
            status=status,
        )
        session.add(generation)
        session.commit()
        session.refresh(generation)
    return generation.id


def _make_browser_auth_engine(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine, tables=[Project.__table__, BrowserAuthSession.__table__])
    monkeypatch.setattr(db_module, "engine", engine)
    return engine


def _create_browser_auth_session(engine, status="pending"):
    with Session(engine) as session:
        project = Project(id="browser-auth-project", name="Browser Auth Project")
        session.add(project)
        row = BrowserAuthSession(
            project_id=project.id,
            name="Login",
            base_url="https://example.com",
            login_url="https://example.com/login",
            username_key="LOGIN_USERNAME",
            password_key="LOGIN_PASSWORD",
            status=status,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def test_agent_task_round_trips_execution_telemetry():
    task = AgentTask(
        id="agent-test",
        prompt="inspect the app",
        created_at=datetime.now(UTC).replace(tzinfo=None),
        allowed_tools=["Read"],
        tools=["Read"],
        disallowed_tools=["Bash"],
        permission_mode="dontAsk",
        strict_mcp_config=True,
        max_budget_usd=0.25,
        task_budget={"total": 25000},
        include_hook_events=True,
        include_partial_messages=True,
        output_format={"type": "json_schema", "schema": {"type": "object"}},
        fallback_model="claude-fallback",
        reasoning_budget=2048,
        max_buffer_size=123456,
        betas=["context-1m-2025-08-07"],
        user="operator@example.test",
        permission_prompt_tool_name="permission_prompt",
        enable_file_checkpointing=True,
        sandbox={"enabled": True, "allowUnsandboxedCommands": False},
        owner_type="autopilot",
        owner_id="autopilot-test",
        owner_label="AutoPilot test",
        browser_slot_parent_owner_type="test_run",
        browser_slot_parent_run_id="run-parent",
        requires_live_browser=True,
        telemetry={
            "worker_id": "worker-1",
            "tool_calls": 4,
            "interactions": 2,
            "assistant_messages": 3,
            "error_type": "timeout",
        },
    )

    restored = AgentTask.from_dict(task.to_dict())

    assert restored.allowed_tools == ["Read"]
    assert restored.tools == ["Read"]
    assert restored.disallowed_tools == ["Bash"]
    assert restored.permission_mode == "dontAsk"
    assert restored.strict_mcp_config is True
    assert restored.max_budget_usd == 0.25
    assert restored.task_budget == {"total": 25000}
    assert restored.include_hook_events is True
    assert restored.include_partial_messages is True
    assert restored.output_format == {"type": "json_schema", "schema": {"type": "object"}}
    assert restored.fallback_model == "claude-fallback"
    assert restored.reasoning_budget == 2048
    assert restored.max_buffer_size == 123456
    assert restored.betas == ["context-1m-2025-08-07"]
    assert restored.user == "operator@example.test"
    assert restored.permission_prompt_tool_name == "permission_prompt"
    assert restored.enable_file_checkpointing is True
    assert restored.sandbox == {"enabled": True, "allowUnsandboxedCommands": False}
    assert restored.owner_type == "autopilot"
    assert restored.owner_id == "autopilot-test"
    assert restored.owner_label == "AutoPilot test"
    assert restored.browser_slot_parent_owner_type == "test_run"
    assert restored.browser_slot_parent_run_id == "run-parent"
    assert restored.requires_live_browser is True
    assert restored.telemetry["worker_id"] == "worker-1"
    assert restored.telemetry["tool_calls"] == 4
    assert restored.telemetry["interactions"] == 2
    assert restored.telemetry["assistant_messages"] == 3
    assert restored.telemetry["error_type"] == "timeout"


@pytest.mark.asyncio
async def test_agent_runner_retries_transient_sdk_provider_error_without_key_cooldown(monkeypatch):
    from orchestrator.utils import agent_runner as agent_runner_module

    calls = {"query": 0, "rate_limit": 0}

    class _Slot:
        masked = "test...slot"

    class _FakeRotator:
        key_count = 2

        def get_active_key(self):
            return _Slot()

        def activate_key(self, _slot):
            return None

        def report_success(self, _slot):
            return None

        def report_rate_limit(self, _slot, _retry_after=None):
            calls["rate_limit"] += 1

    async def fake_query(**_kwargs):
        calls["query"] += 1
        if calls["query"] == 1:
            raise RuntimeError("529 temporarily overloaded, try again later")
        yield SimpleNamespace(type="text", text="Recovered response")

    monkeypatch.setenv("AGENT_PROVIDER_RETRY_ATTEMPTS", "2")
    monkeypatch.setenv("AGENT_PROVIDER_RETRY_BASE_SECONDS", "0")
    monkeypatch.setattr(agent_runner_module, "query", fake_query)
    monkeypatch.setattr(agent_runner_module, "ClaudeAgentOptions", lambda **kwargs: kwargs)
    monkeypatch.setattr(agent_runner_module, "get_api_key_rotator", lambda: _FakeRotator())

    runner = AgentRunner(
        allowed_tools=[],
        tools=[],
        inject_memory=False,
        capture_memory=False,
        force_direct_execution=True,
    )
    result = await runner.run("hello")

    assert result.success is True
    assert result.output == "Recovered response"
    assert result.api_error_status == 529
    assert calls["query"] == 2
    assert calls["rate_limit"] == 0


@pytest.mark.asyncio
async def test_agent_runner_returns_provider_overloaded_after_sdk_retries_exhausted(monkeypatch):
    from orchestrator.utils import agent_runner as agent_runner_module

    calls = {"query": 0, "rate_limit": 0}

    class _Slot:
        masked = "test...slot"

    class _FakeRotator:
        key_count = 2

        def get_active_key(self):
            return _Slot()

        def activate_key(self, _slot):
            return None

        def report_success(self, _slot):
            return None

        def report_rate_limit(self, _slot, _retry_after=None):
            calls["rate_limit"] += 1

    async def fake_query(**_kwargs):
        calls["query"] += 1
        if calls["query"] == 1:
            yield SimpleNamespace(type="text", text="partial")
        raise RuntimeError("HTTP status 529: service unavailable")

    monkeypatch.setenv("AGENT_PROVIDER_RETRY_ATTEMPTS", "2")
    monkeypatch.setenv("AGENT_PROVIDER_RETRY_BASE_SECONDS", "0")
    monkeypatch.setattr(agent_runner_module, "query", fake_query)
    monkeypatch.setattr(agent_runner_module, "ClaudeAgentOptions", lambda **kwargs: kwargs)
    monkeypatch.setattr(agent_runner_module, "get_api_key_rotator", lambda: _FakeRotator())

    runner = AgentRunner(
        allowed_tools=[],
        tools=[],
        inject_memory=False,
        capture_memory=False,
        force_direct_execution=True,
    )
    result = await runner.run("hello")

    assert result.success is False
    assert result.error_type == "provider_overloaded"
    assert result.api_error_status == 529
    assert result.output == ""
    assert calls["query"] == 2
    assert calls["rate_limit"] == 0


def test_agent_worker_detects_browser_capable_tasks():
    worker = AgentWorker.__new__(AgentWorker)

    assert worker._task_requires_browser_slot(
        AgentTask(id="agent-browser-owner", prompt="run", owner_type="autonomous_work_item")
    )
    assert worker._task_requires_browser_slot(
        AgentTask(id="agent-browser-tool", prompt="run", allowed_tools=["browser_navigate"], tools=["browser_click"])
    )
    assert not worker._task_requires_browser_slot(
        AgentTask(
            id="agent-prd-live",
            prompt="run",
            owner_type="prd_generation",
            requires_live_browser=True,
            allowed_tools=["mcp__playwright-test__browser_navigate"],
            tools=["mcp__playwright-test__planner_setup_page"],
        )
    )
    assert not worker._task_requires_browser_slot(
        AgentTask(id="agent-no-tools", prompt="run", allowed_tools=["Read"], tools=[])
    )


def test_agent_worker_filters_mcp_tools_from_claude_cli_tools():
    assert AgentWorker._builtin_cli_tools(
        [
            "Read",
            "mcp__playwright-test__planner_setup_page",
            "mcp__playwright-test__browser_navigate",
            "Bash",
        ]
    ) == ["Read", "Bash"]
    assert AgentWorker._builtin_cli_tools(["mcp__playwright-test__planner_setup_page"]) == []
    assert AgentWorker._builtin_cli_tools([]) == []


def test_agent_worker_reports_sdk_only_options_unsupported_in_cli_queue():
    task = AgentTask(
        id="agent-sdk-only",
        prompt="run",
        reasoning_budget=1024,
        max_buffer_size=4096,
        user="user@example.test",
        permission_prompt_tool_name="permission_prompt",
        enable_file_checkpointing=True,
        sandbox={"enabled": True},
    )

    assert AgentWorker._unsupported_cli_options(task) == [
        "reasoning_budget/max_thinking_tokens",
        "max_buffer_size",
        "user",
        "permission_prompt_tool_name",
        "enable_file_checkpointing",
        "sandbox",
    ]


def test_agent_runner_treats_hooks_agents_skills_plugins_as_direct_sdk_only():
    runner = AgentRunner(
        allowed_tools=["Read"],
        hooks={"PreToolUse": []},
        agents={"reviewer": {"prompt": "review", "tools": ["Read"]}},
        skills=["playwright"],
        plugins=[{"type": "local", "path": "./plugin"}],
        session_store=object(),
        fork_session=True,
    )

    assert runner._requires_direct_sdk_execution() is True


@pytest.mark.asyncio
async def test_agent_runner_records_sdk_object_tool_calls_by_tool_use_id(monkeypatch, tmp_path):
    from orchestrator.utils import agent_runner as agent_runner_module

    async def fake_query(**_kwargs):
        yield SimpleNamespace(
            type="assistant",
            message=SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id="toolu_nav",
                        name="mcp__playwright-test__browser_navigate",
                        input={"url": "https://example.test/checkout"},
                    ),
                    SimpleNamespace(
                        type="tool_use",
                        id="toolu_snapshot",
                        name="mcp__playwright-test__browser_snapshot",
                        input={},
                    ),
                ]
            ),
        )
        yield SimpleNamespace(
            type="user",
            message=SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="tool_result",
                        tool_use_id="toolu_nav",
                        content="Navigated",
                    ),
                    SimpleNamespace(
                        type="tool_result",
                        tool_use_id="toolu_snapshot",
                        content=[{"type": "text", "text": "Checkout page"}],
                    ),
                ]
            ),
        )
        yield SimpleNamespace(
            type="assistant",
            message=SimpleNamespace(
                content=[SimpleNamespace(type="text", text="done")]
            ),
            session_id="sdk-session-stream",
        )

    seen_tools: list[tuple[str, dict]] = []
    progress_events: list[dict] = []
    (tmp_path / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "playwright-test": {
                        "command": "true",
                        "args": ["run-test-mcp-server"],
                    }
                }
            }
        )
    )
    monkeypatch.setattr(agent_runner_module, "query", fake_query)
    monkeypatch.setattr(agent_runner_module, "ClaudeAgentOptions", lambda **kwargs: kwargs)
    monkeypatch.setattr(agent_runner_module, "get_api_key_rotator", lambda: None)

    runner = AgentRunner(
        allowed_tools=["mcp__playwright-test__browser_navigate"],
        tools=["mcp__playwright-test__browser_navigate"],
        log_tools=False,
        on_tool_use=lambda name, tool_input: seen_tools.append((name, tool_input)),
        on_progress=lambda event: progress_events.append(event),
        session_dir=tmp_path,
        cwd=tmp_path,
        inject_memory=False,
        capture_memory=False,
        force_direct_execution=True,
    )

    result = await runner.run("inspect checkout")

    assert result.success is True
    assert result.output == "done"
    assert [name for name, _input in seen_tools] == [
        "mcp__playwright-test__browser_navigate",
        "mcp__playwright-test__browser_snapshot",
    ]
    assert [call.name for call in result.tool_calls] == [
        "mcp__playwright-test__browser_navigate",
        "mcp__playwright-test__browser_snapshot",
    ]
    assert result.tool_calls[0].input == {"url": "https://example.test/checkout"}
    assert any(event["phase"] == "tool_use" and event["tool_calls"] == 2 for event in progress_events)
    persisted = json.loads((tmp_path / "tool_calls.json").read_text())
    assert [item["name"] for item in persisted] == [call.name for call in result.tool_calls]


@pytest.mark.asyncio
async def test_agent_runner_recovers_tool_calls_from_session_jsonl(monkeypatch, tmp_path):
    from orchestrator.utils import agent_runner as agent_runner_module

    session_id = "sdk-session-fallback"
    project_dir = tmp_path / "projects" / "fallback"
    project_dir.mkdir(parents=True)
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "setup",
                        "name": "mcp__playwright-test__planner_setup_page",
                        "input": {"seedFile": "tests/seed.spec.ts"},
                    }
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "setup",
                        "content": "ready",
                    }
                ]
            },
        },
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "nav",
                        "name": "mcp__playwright-test__browser_navigate",
                        "input": {"url": "https://example.test/checkout"},
                    }
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "nav",
                        "content": "navigated",
                    }
                ]
            },
        },
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "snapshot",
                        "name": "mcp__playwright-test__browser_snapshot",
                        "input": {},
                    }
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "snapshot",
                        "content": 'https://example.test/checkout\n- heading "Checkout"',
                    }
                ]
            },
        },
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "save",
                        "name": "mcp__playwright-test__planner_save_plan",
                        "input": {"content": "# Test Plan"},
                    }
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "save",
                        "content": "saved",
                    }
                ]
            },
        },
    ]
    (project_dir / f"{session_id}.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events)
    )
    (tmp_path / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "playwright-test": {
                        "command": "true",
                        "args": ["run-test-mcp-server"],
                    }
                }
            }
        )
    )

    async def fake_query(**_kwargs):
        yield SimpleNamespace(
            type="assistant",
            message=SimpleNamespace(
                content=[SimpleNamespace(type="text", text="finished")]
            ),
            session_id=session_id,
        )

    monkeypatch.setattr(agent_runner_module, "query", fake_query)
    monkeypatch.setattr(agent_runner_module, "ClaudeAgentOptions", lambda **kwargs: kwargs)
    monkeypatch.setattr(agent_runner_module, "get_api_key_rotator", lambda: None)

    runner = AgentRunner(
        allowed_tools=[],
        tools=[],
        log_tools=False,
        session_dir=tmp_path,
        cwd=tmp_path,
        inject_memory=False,
        capture_memory=False,
        force_direct_execution=True,
    )

    result = await runner.run("make a plan")

    assert [call.name for call in result.tool_calls] == [
        "mcp__playwright-test__planner_setup_page",
        "mcp__playwright-test__browser_navigate",
        "mcp__playwright-test__browser_snapshot",
        "mcp__playwright-test__planner_save_plan",
    ]
    persisted = json.loads((tmp_path / "tool_calls.json").read_text())
    assert [item["name"] for item in persisted] == [call.name for call in result.tool_calls]
    assert persisted[-1]["input_content_length"] == len("# Test Plan")


def test_agent_worker_cli_args_preserve_supported_sdk_options(monkeypatch, tmp_path):
    from orchestrator.services import agent_worker as worker_module

    captured: dict[str, list[str]] = {}

    class _Stdout:
        def readline(self):
            return b""

        def close(self):
            return None

    class _FakeProc:
        pid = 12345
        returncode = 0
        stdout = _Stdout()

        def poll(self):
            return 0

        def wait(self):
            return 0

    def fake_popen(args, **kwargs):
        captured["args"] = list(args)
        captured["cwd"] = kwargs.get("cwd")
        return _FakeProc()

    worker = AgentWorker.__new__(AgentWorker)
    worker.cwd = str(tmp_path)
    worker._process_lock = threading.Lock()
    worker._running_processes = {}
    worker._cancelled_task_ids = set()
    worker._pause_lock = threading.Lock()
    worker._paused_task_ids = set()
    worker._pause_started_at = {}
    worker._paused_duration_seconds = {}
    worker._progress_lock = threading.Lock()
    worker._current_progress = AgentWorker._empty_progress()
    worker._last_execution_telemetry = {}
    worker._parse_cli_output = lambda raw: "parsed"

    monkeypatch.setattr(worker_module.subprocess, "Popen", fake_popen)

    result = worker._run_cli_sync(
        task_id="agent-cli-options",
        prompt="return json",
        cwd=str(tmp_path),
        allowed_tools=["Read"],
        tools=["Read"],
        permission_mode="dontAsk",
        include_hook_events=True,
        include_partial_messages=True,
        output_format={"type": "json_schema", "schema": {"type": "object"}},
        fallback_model="claude-fallback",
        betas=["context-1m-2025-08-07"],
    )

    args = captured["args"]
    assert result == "parsed"
    assert captured["cwd"] == str(tmp_path)
    assert args[args.index("--fallback-model") + 1] == "claude-fallback"
    assert args[args.index("--betas") + 1] == "context-1m-2025-08-07"
    assert "--include-hook-events" in args
    assert "--include-partial-messages" in args
    assert json.loads(args[args.index("--json-schema") + 1]) == {"type": "object"}


def test_agent_worker_browser_tool_watchdog_kills_hung_process(monkeypatch, tmp_path):
    from orchestrator.services import agent_worker as worker_module
    (tmp_path / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "playwright-test": {
                        "command": "npx",
                        "args": ["@playwright/mcp"],
                    }
                }
            }
        )
    )

    class _HungStdout:
        def __init__(self, proc):
            self.proc = proc
            self.sent_tool = False

        def readline(self):
            if not self.sent_tool:
                self.sent_tool = True
                return (
                    json.dumps(
                        {
                            "type": "assistant",
                            "message": {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "toolu_hung",
                                        "name": "mcp__playwright-test__browser_run_code",
                                        "input": {"code": "while (true) {}"},
                                    }
                                ]
                            },
                        }
                    )
                    + "\n"
                ).encode()
            while not self.proc.killed:
                time.sleep(0.01)
            return b""

        def close(self):
            self.proc.killed = True

    class _FakeProc:
        pid = 12345

        def __init__(self):
            self.killed = False
            self.returncode = None
            self.stdout = _HungStdout(self)

        def poll(self):
            return -9 if self.killed else None

        def kill(self):
            self.killed = True
            self.returncode = -9

        def terminate(self):
            self.kill()

        def wait(self):
            self.killed = True
            self.returncode = -9
            return self.returncode

    proc = _FakeProc()

    def fake_popen(*_args, **_kwargs):
        return proc

    worker = AgentWorker.__new__(AgentWorker)
    worker.worker_id = "worker-test"
    worker.cwd = str(tmp_path)
    worker._process_lock = threading.Lock()
    worker._running_processes = {}
    worker._cancelled_task_ids = set()
    worker._pause_lock = threading.Lock()
    worker._paused_task_ids = set()
    worker._pause_started_at = {}
    worker._paused_duration_seconds = {}
    worker._progress_lock = threading.Lock()
    worker._current_progress = AgentWorker._empty_progress()
    worker._last_execution_telemetry = {}

    monkeypatch.setenv("AGENT_BROWSER_TOOL_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setattr(worker_module.subprocess, "Popen", fake_popen)

    with pytest.raises(BrowserToolTimeoutError) as exc_info:
        worker._run_cli_sync(
            task_id="agent-hung-browser-tool",
            prompt="run browser code",
            cwd=str(tmp_path),
            allowed_tools=["mcp__playwright-test__browser_run_code"],
            tools=["mcp__playwright-test__browser_run_code"],
        )

    assert proc.killed is True
    assert exc_info.value.tool_name == "mcp__playwright-test__browser_run_code"
    assert exc_info.value.tool_use_id == "toolu_hung"
    with worker._progress_lock:
        records = worker._current_progress["tool_call_records"]
        progress = dict(worker._current_progress)
    assert records[0]["success"] is False
    assert records[0]["error_type"] == "browser_tool_timeout"
    assert progress["browser_tool_timeout"] is True
    assert worker._last_execution_telemetry["error_type"] == "browser_tool_timeout"


@pytest.mark.asyncio
async def test_agent_worker_submits_browser_tool_timeout_result(monkeypatch):
    from orchestrator.services import agent_worker as worker_module

    submitted: dict[str, object] = {}

    class _FakeQueue:
        async def update_heartbeat(self, *_args, **_kwargs):
            return None

        async def is_cancelled(self, *_args, **_kwargs):
            return False

        async def is_paused(self, *_args, **_kwargs):
            return False

        async def submit_result(self, task_id, result, success=True, error=None, telemetry=None):
            submitted.update(
                {
                    "task_id": task_id,
                    "result": result,
                    "success": success,
                    "error": error,
                    "telemetry": telemetry,
                }
            )

    class _FakeRotator:
        key_count = 0

        def initialize(self):
            return None

        def get_active_key(self):
            return None

    worker = AgentWorker.__new__(AgentWorker)
    worker.worker_id = "worker-test"
    worker.queue = _FakeQueue()
    worker.cwd = str(Path(__file__).resolve().parents[2])
    worker._progress_lock = threading.RLock()
    worker._current_progress = AgentWorker._empty_progress()
    worker._process_lock = threading.Lock()
    worker._running_processes = {}
    worker._cancelled_task_ids = set()
    worker._pause_lock = threading.Lock()
    worker._paused_task_ids = set()
    worker._pause_started_at = {}
    worker._paused_duration_seconds = {}
    worker._last_execution_telemetry = {}

    async def fake_run_claude_cli(**_kwargs):
        with worker._progress_lock:
            worker._current_progress.update(
                {
                    "tool_calls": 1,
                    "browser_tool_calls": 1,
                    "last_tool": "mcp__playwright-test__browser_run_code",
                    "tool_names": ["mcp__playwright-test__browser_run_code"],
                    "tool_call_records": [
                        {
                            "name": "mcp__playwright-test__browser_run_code",
                            "tool_use_id": "toolu_hung",
                            "input": {"code": "while (true) {}"},
                            "success": None,
                            "started_at": time.time() - 121,
                        }
                    ],
                }
            )
        raise BrowserToolTimeoutError(
            tool_name="mcp__playwright-test__browser_run_code",
            tool_use_id="toolu_hung",
            elapsed_seconds=121.0,
            timeout_seconds=120.0,
        )

    monkeypatch.setattr(worker_module, "get_api_key_rotator", lambda: _FakeRotator())
    worker._run_claude_cli = fake_run_claude_cli

    task = AgentTask(
        id="agent-browser-timeout",
        prompt="run browser code",
        allowed_tools=["mcp__playwright-test__browser_run_code"],
        tools=["mcp__playwright-test__browser_run_code"],
        timeout_seconds=300,
    )

    await worker._execute_task(task)

    assert submitted["task_id"] == task.id
    assert submitted["success"] is False
    assert "Browser tool timed out" in submitted["error"]
    telemetry = submitted["telemetry"]
    assert telemetry["error_type"] == "browser_tool_timeout"
    assert telemetry["timed_out_tool_name"] == "mcp__playwright-test__browser_run_code"
    assert telemetry["timed_out_tool_use_id"] == "toolu_hung"
    assert telemetry["browser_tool_calls"] == 1


@pytest.mark.asyncio
async def test_agent_worker_retries_provider_overload_and_submits_telemetry(monkeypatch):
    from orchestrator.services import agent_worker as worker_module

    submitted: dict[str, object] = {}
    calls = {"run": 0, "rate_limit": 0}

    class _FakeQueue:
        async def update_heartbeat(self, *_args, **_kwargs):
            return None

        async def is_cancelled(self, *_args, **_kwargs):
            return False

        async def is_paused(self, *_args, **_kwargs):
            return False

        async def submit_result(self, task_id, result, success=True, error=None, telemetry=None):
            submitted.update(
                {
                    "task_id": task_id,
                    "result": result,
                    "success": success,
                    "error": error,
                    "telemetry": telemetry,
                }
            )

    class _Slot:
        masked = "test...slot"

    class _FakeRotator:
        key_count = 2

        def initialize(self):
            return None

        def get_active_key(self):
            return _Slot()

        def activate_key(self, _slot):
            return None

        def report_success(self, _slot):
            return None

        def report_rate_limit(self, _slot, _retry_after=None):
            calls["rate_limit"] += 1

    worker = AgentWorker.__new__(AgentWorker)
    worker.worker_id = "worker-test"
    worker.queue = _FakeQueue()
    worker.cwd = str(Path(__file__).resolve().parents[2])
    worker._progress_lock = threading.RLock()
    worker._current_progress = AgentWorker._empty_progress()
    worker._process_lock = threading.Lock()
    worker._running_processes = {}
    worker._cancelled_task_ids = set()
    worker._pause_lock = threading.Lock()
    worker._paused_task_ids = set()
    worker._pause_started_at = {}
    worker._paused_duration_seconds = {}
    worker._last_execution_telemetry = {}

    async def fake_run_claude_cli(**_kwargs):
        calls["run"] += 1
        with worker._progress_lock:
            worker._current_progress.update(
                {
                    "tool_calls": 1,
                    "last_tool": "mcp__playwright-test__generator_write_test",
                    "tool_names": ["mcp__playwright-test__generator_write_test"],
                    "tool_call_records": [
                        {
                            "name": "mcp__playwright-test__generator_write_test",
                            "input": {"code": "import { test, expect } from '@playwright/test';\ntest('x', async ({ page }) => { await expect(page.locator('body')).toBeVisible(); });"},
                            "success": True,
                        }
                    ],
                }
            )
            worker._last_execution_telemetry = {
                "api_error_status": 529,
                "tool_calls": 1,
                "last_tool": "mcp__playwright-test__generator_write_test",
                "tool_names": ["mcp__playwright-test__generator_write_test"],
                "tool_call_records": worker._current_progress["tool_call_records"],
            }
        raise RuntimeError("CLI returned error (status 529): temporarily overloaded")

    monkeypatch.setenv("AGENT_PROVIDER_RETRY_ATTEMPTS", "2")
    monkeypatch.setenv("AGENT_PROVIDER_RETRY_BASE_SECONDS", "0")
    monkeypatch.setattr(worker_module, "get_api_key_rotator", lambda: _FakeRotator())
    worker._run_claude_cli = fake_run_claude_cli

    task = AgentTask(
        id="agent-provider-overload",
        prompt="generate",
        allowed_tools=["mcp__playwright-test__generator_write_test"],
        tools=["mcp__playwright-test__generator_write_test"],
        timeout_seconds=300,
    )

    await worker._execute_task(task)

    assert calls["run"] == 2
    assert calls["rate_limit"] == 0
    assert submitted["task_id"] == task.id
    assert submitted["success"] is False
    telemetry = submitted["telemetry"]
    assert telemetry["error_type"] == "provider_overloaded"
    assert telemetry["api_error_status"] == 529
    assert telemetry["attempt"] == 2
    assert telemetry["last_tool"] == "mcp__playwright-test__generator_write_test"
    assert telemetry["tool_names"] == ["mcp__playwright-test__generator_write_test"]
    assert telemetry["tool_call_records"][0]["input"]["code"].startswith("import { test, expect }")


@pytest.mark.asyncio
async def test_worker_capability_summary_counts_live_browser_workers():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    await redis.set(
        f"{queue.WORKER_HEARTBEAT_PREFIX}worker-live",
        json.dumps({"ts": "2026-05-31T13:00:00", "capabilities": {"live_browser": True}}),
    )
    await redis.set(
        f"{queue.WORKER_HEARTBEAT_PREFIX}worker-headless",
        json.dumps({"ts": "2026-05-31T13:00:01", "capabilities": {"live_browser": False}}),
    )

    summary = await queue.worker_capability_summary()
    health = await queue.get_worker_health()

    assert summary["worker_count"] == 2
    assert summary["live_browser_worker_count"] == 1
    assert summary["non_live_browser_worker_count"] == 1
    assert health["live_browser_worker_count"] == 1
    assert health["non_live_browser_worker_count"] == 1


def test_agent_worker_detects_parent_test_run_browser_slot():
    worker = AgentWorker.__new__(AgentWorker)

    task = AgentTask(
        id="agent-child",
        prompt="run",
        allowed_tools=["mcp__playwright-test__browser_snapshot"],
        browser_slot_parent_owner_type="test_run",
        browser_slot_parent_run_id="run-123",
    )

    assert worker._parent_test_run_slot_id(task) == "run-123"


def test_agent_runner_uses_parent_test_run_as_queue_owner(monkeypatch):
    monkeypatch.setenv("BROWSER_SLOT_PARENT_OWNER_TYPE", "test_run")
    monkeypatch.setenv("BROWSER_SLOT_PARENT_RUN_ID", "run-123")
    runner = AgentRunner(owner_type=None, owner_id=None)

    assert runner._queue_owner_metadata() == (
        "test_run",
        "run-123",
        "Test run run-123",
        "test_run",
        "run-123",
    )


@pytest.mark.asyncio
async def test_agent_runner_adds_browser_dialog_policy_before_queue_enqueue(monkeypatch):
    from orchestrator.utils import agent_runner as agent_runner_module

    captured: dict[str, str] = {}

    class _CompletedTask:
        telemetry = {"tool_calls": 0, "text_blocks": 1}

    class _FakeQueue:
        async def connect(self):
            return None

        async def get_metrics(self):
            return {"workers_alive": 1, "queue_length": 0, "running": 0}

        async def enqueue_task(self, *, prompt, **_kwargs):
            captured["prompt"] = prompt
            return "task-dialog"

        async def wait_for_result(self, *_args, **_kwargs):
            return "Queued browser run completed with enough detail to pass validation."

        async def get_task(self, task_id):
            assert task_id == "task-dialog"
            return _CompletedTask()

    monkeypatch.setattr(agent_runner_module, "AGENT_QUEUE_AVAILABLE", True)
    monkeypatch.setattr(agent_runner_module, "should_use_agent_queue", lambda: True)
    monkeypatch.setattr(agent_runner_module, "get_agent_queue", lambda: _FakeQueue())

    runner = AgentRunner(
        allowed_tools=["browser_dialog"],
        inject_memory=False,
        capture_memory=False,
    )
    result = await runner.run("browse")

    assert result.success is True
    assert "## Browser Dialog Recovery" in captured["prompt"]
    assert "Leave site?" in captured["prompt"]
    assert "`accept: true`" in captured["prompt"]


@pytest.mark.asyncio
async def test_agent_worker_reuses_active_parent_test_run_slot():
    worker = AgentWorker.__new__(AgentWorker)
    task = AgentTask(
        id="agent-child",
        prompt="run",
        browser_slot_parent_owner_type="test_run",
        browser_slot_parent_run_id="run-123",
    )

    class _Pool:
        async def is_running(self, request_id):
            return request_id == "run-123"

    assert await worker._can_reuse_parent_browser_slot(task, _Pool()) is True


@pytest.mark.asyncio
async def test_agent_worker_does_not_reuse_inactive_parent_test_run_slot():
    worker = AgentWorker.__new__(AgentWorker)
    task = AgentTask(
        id="agent-child",
        prompt="run",
        browser_slot_parent_owner_type="test_run",
        browser_slot_parent_run_id="run-123",
    )

    class _Pool:
        async def is_running(self, request_id):
            return False

    assert await worker._can_reuse_parent_browser_slot(task, _Pool()) is False


def test_autopilot_process_tree_matches_session_root_and_cleanup_descendants(monkeypatch):
    current_pid = 999
    processes = {
        current_pid: browser_cleanup.ProcessInfo(
            pid=current_pid,
            ppid=1,
            comm="claude",
            args="claude --session autopilot_2026-05-25_16-33-34",
        ),
        101: browser_cleanup.ProcessInfo(
            pid=101,
            ppid=1,
            comm="claude",
            args="claude --session autopilot_2026-05-25_16-33-34",
        ),
        102: browser_cleanup.ProcessInfo(
            pid=102,
            ppid=101,
            comm="node",
            args="node playwright-mcp",
        ),
        103: browser_cleanup.ProcessInfo(
            pid=103,
            ppid=102,
            comm="chromium",
            args="/usr/bin/chromium --type=renderer",
        ),
        104: browser_cleanup.ProcessInfo(
            pid=104,
            ppid=101,
            comm="python",
            args="python unrelated-child.py",
        ),
        201: browser_cleanup.ProcessInfo(
            pid=201,
            ppid=1,
            comm="chromium",
            args="/usr/bin/chromium --remote-debugging-port=9222",
        ),
    }

    monkeypatch.setattr(browser_cleanup, "_process_table", lambda: processes)
    monkeypatch.setattr(browser_cleanup.os, "getpid", lambda: current_pid)

    assert browser_cleanup.find_autopilot_process_tree("autopilot_2026-05-25_16-33-34") == {
        101,
        102,
        103,
    }


def test_test_run_process_tree_matches_run_root_and_cleanup_descendants(monkeypatch):
    current_pid = 999
    run_id = "2026-05-30_07-23-08"
    processes = {
        current_pid: browser_cleanup.ProcessInfo(
            pid=current_pid,
            ppid=1,
            comm="python",
            args=f"python unrelated.py {run_id}",
        ),
        101: browser_cleanup.ProcessInfo(
            pid=101,
            ppid=1,
            comm="claude",
            args=f"claude --mcp-config /app/runs/{run_id}/.mcp.json",
        ),
        102: browser_cleanup.ProcessInfo(
            pid=102,
            ppid=101,
            comm="node",
            args="node playwright run-test-mcp-server",
        ),
        103: browser_cleanup.ProcessInfo(
            pid=103,
            ppid=102,
            comm="chromium",
            args="/usr/bin/chromium --type=renderer",
        ),
        104: browser_cleanup.ProcessInfo(
            pid=104,
            ppid=101,
            comm="ffmpeg",
            args="ffmpeg -f x11grab :99",
        ),
        105: browser_cleanup.ProcessInfo(
            pid=105,
            ppid=101,
            comm="python",
            args="python unrelated-child.py",
        ),
        201: browser_cleanup.ProcessInfo(
            pid=201,
            ppid=1,
            comm="claude",
            args="claude --mcp-config /app/runs/2026-05-30_07-32-00/.mcp.json",
        ),
    }

    monkeypatch.setattr(browser_cleanup, "_process_table", lambda: processes)
    monkeypatch.setattr(browser_cleanup.os, "getpid", lambda: current_pid)

    assert browser_cleanup.find_test_run_process_tree(run_id) == {101, 102, 103, 104}


def test_test_run_ids_are_extracted_from_cleanup_processes(monkeypatch):
    processes = {
        101: browser_cleanup.ProcessInfo(
            pid=101,
            ppid=1,
            comm="claude",
            args="claude --mcp-config /app/runs/2026-05-30_07-23-08/.mcp.json",
        ),
        102: browser_cleanup.ProcessInfo(
            pid=102,
            ppid=1,
            comm="python",
            args="python /app/orchestrator/cli.py /app/runs/2026-05-30_07-32-00/spec.md",
        ),
        103: browser_cleanup.ProcessInfo(
            pid=103,
            ppid=1,
            comm="python",
            args="python unrelated.py 2026-05-30_07-40-00",
        ),
    }

    monkeypatch.setattr(browser_cleanup, "_process_table", lambda: processes)

    assert browser_cleanup.find_test_run_ids_in_processes() == {
        "2026-05-30_07-23-08",
        "2026-05-30_07-32-00",
    }


def test_autopilot_session_ids_are_extracted_only_from_cleanup_processes(monkeypatch):
    processes = {
        101: browser_cleanup.ProcessInfo(
            pid=101,
            ppid=1,
            comm="claude",
            args="claude --session autopilot_2026-05-25_16-33-34",
        ),
        102: browser_cleanup.ProcessInfo(
            pid=102,
            ppid=1,
            comm="node",
            args="node /tmp/autopilot_2026-05-25_16-44-10/playwright-mcp",
        ),
        103: browser_cleanup.ProcessInfo(
            pid=103,
            ppid=1,
            comm="python",
            args="python mentions autopilot_2026-05-25_16-55-00",
        ),
    }

    monkeypatch.setattr(browser_cleanup, "_process_table", lambda: processes)

    assert browser_cleanup.find_autopilot_session_ids_in_processes() == {
        "autopilot_2026-05-25_16-33-34",
        "autopilot_2026-05-25_16-44-10",
    }


@pytest.mark.asyncio
async def test_pause_and_resume_queued_task_requeues_after_resume():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(id="agent-queued", prompt="inspect", status=AgentTaskStatus.QUEUED)
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, task.id)

    assert await queue.pause_task(task.id) is True
    paused = await queue.get_task(task.id)
    assert paused.status == AgentTaskStatus.PAUSED
    assert redis.lists[queue.QUEUE_KEY] == []
    assert await queue.is_paused(task.id) is True

    assert await queue.resume_task(task.id) is True
    resumed = await queue.get_task(task.id)
    assert resumed.status == AgentTaskStatus.QUEUED
    assert redis.lists[queue.QUEUE_KEY] == [task.id]
    assert await queue.is_paused(task.id) is False


@pytest.mark.asyncio
async def test_wait_for_result_keeps_queued_task_when_workers_are_busy():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(
        id="agent-busy-queued", prompt="inspect", status=AgentTaskStatus.QUEUED
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, task.id)

    async def worker_count():
        return 2

    async def queue_length():
        return 4

    async def running_count():
        return 2

    queue.worker_count = worker_count
    queue.queue_length = queue_length
    queue.running_count = running_count

    with pytest.raises(asyncio.TimeoutError):
        await queue.wait_for_result(
            task.id, timeout=0.05, poll_interval=0.001, queued_timeout=0.01
        )

    assert await queue.get_task(task.id) is not None


@pytest.mark.asyncio
async def test_wait_for_result_fails_live_task_when_workers_have_no_live_browser_capability():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(
        id="agent-live-queued",
        prompt="inspect",
        status=AgentTaskStatus.QUEUED,
        requires_live_browser=True,
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, task.id)
    await redis.set(
        f"{queue.WORKER_HEARTBEAT_PREFIX}worker-headless",
        json.dumps({"ts": "2026-05-31T13:00:00", "capabilities": {"live_browser": False}}),
    )

    with pytest.raises(RuntimeError, match="No live-browser-capable agent worker"):
        await queue.wait_for_result(
            task.id, timeout=1, poll_interval=0.001, queued_timeout=0.001
        )

    cancelled = await queue.get_task(task.id)
    assert cancelled.status == AgentTaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_dequeue_routes_live_browser_task_only_to_live_browser_worker(monkeypatch):
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(
        id="agent-live-browser",
        prompt="inspect",
        status=AgentTaskStatus.QUEUED,
        requires_live_browser=True,
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, task.id)

    monkeypatch.setattr(
        AgentQueue, "_worker_supports_live_browser", staticmethod(lambda: False)
    )

    assert await queue.dequeue_task(timeout=1) is None
    skipped = await queue.get_task(task.id)
    assert skipped.status == AgentTaskStatus.QUEUED
    assert redis.lists[queue.QUEUE_KEY] == [task.id]

    queue._worker_id = "live-worker"
    monkeypatch.setattr(
        AgentQueue, "_worker_supports_live_browser", staticmethod(lambda: True)
    )

    dequeued = await queue.dequeue_task(timeout=1)

    assert dequeued.id == task.id
    assert dequeued.status == AgentTaskStatus.RUNNING
    assert dequeued.worker_id == "live-worker"
    assert redis.lists[queue.QUEUE_KEY] == []
    assert await redis.sismember(queue.RUNNING_KEY, task.id) is True


@pytest.mark.asyncio
async def test_pause_and_resume_running_task_keeps_worker_ownership():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(
        id="agent-running",
        prompt="inspect",
        status=AgentTaskStatus.RUNNING,
        worker_id="worker-1",
        started_at=datetime.now(UTC).replace(tzinfo=None),
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.sadd(queue.RUNNING_KEY, task.id)

    assert await queue.pause_task(task.id) is True
    paused = await queue.get_task(task.id)
    assert paused.status == AgentTaskStatus.PAUSED
    assert await redis.sismember(queue.RUNNING_KEY, task.id) is True

    assert await queue.resume_task(task.id) is True
    resumed = await queue.get_task(task.id)
    assert resumed.status == AgentTaskStatus.RUNNING
    assert redis.lists.get(queue.QUEUE_KEY, []) == []
    assert await redis.sismember(queue.RUNNING_KEY, task.id) is True


@pytest.mark.asyncio
async def test_pause_resume_reject_terminal_task():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(
        id="agent-complete", prompt="inspect", status=AgentTaskStatus.COMPLETED
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))

    assert await queue.pause_task(task.id) is False
    assert await queue.resume_task(task.id) is False


@pytest.mark.asyncio
async def test_cancel_paused_queued_task_clears_pause_and_queue():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(
        id="agent-paused-queued", prompt="inspect", status=AgentTaskStatus.QUEUED
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, task.id)

    assert await queue.pause_task(task.id) is True
    assert await queue.is_paused(task.id) is True

    assert await queue.cancel_task(task.id) is True
    cancelled = await queue.get_task(task.id)
    assert cancelled.status == AgentTaskStatus.CANCELLED
    assert redis.lists[queue.QUEUE_KEY] == []
    assert await queue.is_paused(task.id) is False
    assert await queue.is_cancelled(task.id) is True


@pytest.mark.asyncio
async def test_cancel_running_task_sets_cancel_requested_and_keeps_worker_membership():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(
        id="agent-running-cancel",
        prompt="inspect",
        status=AgentTaskStatus.RUNNING,
        worker_id="worker-1",
        started_at=datetime.now(UTC).replace(tzinfo=None),
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.sadd(queue.RUNNING_KEY, task.id)

    assert await queue.cancel_task(task.id) is True
    cancelled = await queue.get_task(task.id)
    assert cancelled.status == AgentTaskStatus.CANCEL_REQUESTED
    assert await redis.sismember(queue.RUNNING_KEY, task.id) is True
    assert await queue.is_cancelled(task.id) is True


@pytest.mark.asyncio
async def test_cancel_tasks_for_test_run_cancels_owner_and_parent_tasks():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    owned = AgentTask(
        id="agent-owned",
        prompt="inspect",
        status=AgentTaskStatus.QUEUED,
        owner_type="test_run",
        owner_id="run-123",
    )
    parented = AgentTask(
        id="agent-parented",
        prompt="inspect",
        status=AgentTaskStatus.RUNNING,
        worker_id="worker-1",
        started_at=datetime.now(UTC).replace(tzinfo=None),
        browser_slot_parent_owner_type="test_run",
        browser_slot_parent_run_id="run-123",
    )
    unrelated = AgentTask(
        id="agent-unrelated",
        prompt="inspect",
        status=AgentTaskStatus.QUEUED,
        owner_type="test_run",
        owner_id="run-456",
    )
    for task in (owned, parented, unrelated):
        await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, owned.id)
    await redis.rpush(queue.QUEUE_KEY, unrelated.id)
    await redis.sadd(queue.RUNNING_KEY, parented.id)

    summary = await queue.cancel_tasks_for_test_run("run-123")

    assert summary["matched"] == 2
    assert summary["cancelled"] == 2
    assert set(summary["task_ids"]) == {"agent-owned", "agent-parented"}
    assert (await queue.get_task(owned.id)).status == AgentTaskStatus.CANCELLED
    assert (await queue.get_task(parented.id)).status == AgentTaskStatus.CANCEL_REQUESTED
    assert (await queue.get_task(unrelated.id)).status == AgentTaskStatus.QUEUED
    assert redis.lists[queue.QUEUE_KEY] == [unrelated.id]
    assert await redis.sismember(queue.RUNNING_KEY, parented.id) is True


@pytest.mark.asyncio
async def test_wait_for_result_cancels_task_when_owner_is_cancelled():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(
        id="agent-owner-cancelled",
        prompt="inspect",
        status=AgentTaskStatus.QUEUED,
        owner_type="autonomous_work_item",
        owner_id="amwi-cancelled",
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, task.id)

    with pytest.raises(RuntimeError, match="Task cancelled"):
        await queue.wait_for_result(task.id, timeout=5, poll_interval=0.01, is_cancelled=lambda: True)

    cancelled = await queue.get_task(task.id)
    assert cancelled.status == AgentTaskStatus.CANCELLED
    assert await queue.is_cancelled(task.id) is True
    assert redis.lists[queue.QUEUE_KEY] == []


@pytest.mark.asyncio
async def test_cancel_requested_task_becomes_cancelled_when_worker_submits_cancel_result():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(
        id="agent-running-cancel-result",
        prompt="inspect",
        status=AgentTaskStatus.RUNNING,
        worker_id="worker-1",
        started_at=datetime.now(UTC).replace(tzinfo=None),
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.sadd(queue.RUNNING_KEY, task.id)

    assert await queue.cancel_task(task.id) is True
    await queue.submit_result(task.id, "", success=False, error="Task cancelled")

    cancelled = await queue.get_task(task.id)
    assert cancelled.status == AgentTaskStatus.CANCELLED
    assert cancelled.error == "Task cancelled"
    assert await redis.sismember(queue.RUNNING_KEY, task.id) is False


@pytest.mark.asyncio
async def test_cleanup_times_out_running_task_by_task_timeout():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    started_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=10)
    task = AgentTask(
        id="agent-timeout",
        prompt="inspect",
        status=AgentTaskStatus.RUNNING,
        worker_id="worker-1",
        started_at=started_at,
        timeout_seconds=60,
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.sadd(queue.RUNNING_KEY, task.id)

    counts = await queue.cleanup_orphaned_and_stale_tasks()

    cleaned = await queue.get_task(task.id)
    assert counts["timed_out"] == 1
    assert cleaned.status == AgentTaskStatus.TIMEOUT
    assert await redis.sismember(queue.RUNNING_KEY, task.id) is False
    assert await queue.is_cancelled(task.id) is True


@pytest.mark.asyncio
async def test_cleanup_fails_running_task_with_missing_heartbeat_immediately():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(
        id="agent-lost-heartbeat",
        prompt="inspect",
        status=AgentTaskStatus.RUNNING,
        worker_id="worker-1",
        started_at=datetime.now(UTC).replace(tzinfo=None),
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.sadd(queue.RUNNING_KEY, task.id)

    counts = await queue.cleanup_orphaned_and_stale_tasks()

    cleaned = await queue.get_task(task.id)
    assert counts["cancelled_orphaned"] == 1
    assert cleaned.status == AgentTaskStatus.FAILED
    assert cleaned.error == "Agent task heartbeat was lost"
    assert await redis.sismember(queue.RUNNING_KEY, task.id) is False
    assert await queue.is_cancelled(task.id) is True


@pytest.mark.asyncio
async def test_cleanup_keeps_running_task_with_live_heartbeat():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(
        id="agent-live-heartbeat",
        prompt="inspect",
        status=AgentTaskStatus.RUNNING,
        worker_id="worker-1",
        started_at=datetime.now(UTC).replace(tzinfo=None),
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.sadd(queue.RUNNING_KEY, task.id)
    await queue.update_heartbeat(task.id)

    counts = await queue.cleanup_orphaned_and_stale_tasks()

    kept = await queue.get_task(task.id)
    assert counts["skipped_active"] == 1
    assert counts["cancelled_orphaned"] == 0
    assert kept.status == AgentTaskStatus.RUNNING
    assert await redis.sismember(queue.RUNNING_KEY, task.id) is True
    assert await queue.is_cancelled(task.id) is False


@pytest.mark.asyncio
async def test_cleanup_cancels_task_when_owner_is_terminal():
    redis = _MemoryRedis()

    class OwnerTerminalQueue(_MemoryQueue):
        async def _get_owner_state(self, task):
            return {
                "type": task.owner_type,
                "id": task.owner_id,
                "label": task.owner_label,
                "status": "failed",
                "terminal": True,
            }

    queue = OwnerTerminalQueue(redis)
    task = AgentTask(
        id="agent-terminal-owner",
        prompt="inspect",
        status=AgentTaskStatus.RUNNING,
        worker_id="worker-1",
        started_at=datetime.now(UTC).replace(tzinfo=None),
        owner_type="autopilot",
        owner_id="autopilot-failed",
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.sadd(queue.RUNNING_KEY, task.id)
    await queue.update_heartbeat(task.id)

    counts = await queue.cleanup_orphaned_and_stale_tasks()

    cleaned = await queue.get_task(task.id)
    assert counts["terminal_owner"] == 1
    assert cleaned.status == AgentTaskStatus.FAILED
    assert await redis.sismember(queue.RUNNING_KEY, task.id) is False
    assert await queue.is_cancelled(task.id) is True


@pytest.mark.asyncio
async def test_get_owner_state_returns_active_prd_generation(monkeypatch):
    engine = _make_prd_generation_engine(monkeypatch)
    generation_id = _create_prd_generation(engine, status="running")
    queue = _MemoryQueue(_MemoryRedis())
    task = AgentTask(
        id="agent-prd-owner",
        prompt="plan",
        owner_type="prd_generation",
        owner_id=str(generation_id),
        owner_label="PRD generation",
    )

    state = await queue._get_owner_state(task)

    assert state == {
        "type": "prd_generation",
        "id": str(generation_id),
        "label": "PRD generation",
        "status": "running",
        "terminal": False,
    }


@pytest.mark.asyncio
async def test_cleanup_preserves_queued_task_with_active_prd_generation_owner(monkeypatch):
    engine = _make_prd_generation_engine(monkeypatch)
    generation_id = _create_prd_generation(engine, status="running")
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(
        id="agent-active-prd-owner",
        prompt="plan",
        status=AgentTaskStatus.QUEUED,
        owner_type="prd_generation",
        owner_id=str(generation_id),
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, task.id)

    counts = await queue.cleanup_orphaned_and_stale_tasks()

    kept = await queue.get_task(task.id)
    assert counts["terminal_owner"] == 0
    assert kept.status == AgentTaskStatus.QUEUED
    assert redis.lists[queue.QUEUE_KEY] == [task.id]


@pytest.mark.asyncio
async def test_cleanup_fails_tasks_with_failed_prd_generation_owner(monkeypatch):
    engine = _make_prd_generation_engine(monkeypatch)
    generation_id = _create_prd_generation(engine, status="failed")
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    queued = AgentTask(
        id="agent-failed-prd-queued",
        prompt="plan",
        status=AgentTaskStatus.QUEUED,
        owner_type="prd_generation",
        owner_id=str(generation_id),
    )
    running = AgentTask(
        id="agent-failed-prd-running",
        prompt="plan",
        status=AgentTaskStatus.RUNNING,
        worker_id="worker-1",
        started_at=datetime.now(UTC).replace(tzinfo=None),
        owner_type="prd_generation",
        owner_id=str(generation_id),
    )
    await redis.hset(queue.TASKS_KEY, queued.id, json.dumps(queued.to_dict()))
    await redis.hset(queue.TASKS_KEY, running.id, json.dumps(running.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, queued.id)
    await redis.sadd(queue.RUNNING_KEY, running.id)

    counts = await queue.cleanup_orphaned_and_stale_tasks()

    cleaned_queued = await queue.get_task(queued.id)
    cleaned_running = await queue.get_task(running.id)
    assert counts["terminal_owner"] == 2
    assert cleaned_queued.status == AgentTaskStatus.FAILED
    assert cleaned_running.status == AgentTaskStatus.FAILED
    assert redis.lists[queue.QUEUE_KEY] == []
    assert await redis.sismember(queue.RUNNING_KEY, running.id) is False


@pytest.mark.asyncio
async def test_cleanup_cancels_tasks_with_cancelled_prd_generation_owner(monkeypatch):
    engine = _make_prd_generation_engine(monkeypatch)
    generation_id = _create_prd_generation(engine, status="cancelled")
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    queued = AgentTask(
        id="agent-cancelled-prd-queued",
        prompt="plan",
        status=AgentTaskStatus.QUEUED,
        owner_type="prd_generation",
        owner_id=str(generation_id),
    )
    running = AgentTask(
        id="agent-cancelled-prd-running",
        prompt="plan",
        status=AgentTaskStatus.RUNNING,
        worker_id="worker-1",
        started_at=datetime.now(UTC).replace(tzinfo=None),
        owner_type="prd_generation",
        owner_id=str(generation_id),
    )
    await redis.hset(queue.TASKS_KEY, queued.id, json.dumps(queued.to_dict()))
    await redis.hset(queue.TASKS_KEY, running.id, json.dumps(running.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, queued.id)
    await redis.sadd(queue.RUNNING_KEY, running.id)

    counts = await queue.cleanup_orphaned_and_stale_tasks()

    cleaned_queued = await queue.get_task(queued.id)
    cleaned_running = await queue.get_task(running.id)
    assert counts["terminal_owner"] == 2
    assert cleaned_queued.status == AgentTaskStatus.CANCELLED
    assert cleaned_running.status == AgentTaskStatus.CANCELLED
    assert redis.lists[queue.QUEUE_KEY] == []
    assert await redis.sismember(queue.RUNNING_KEY, running.id) is False


@pytest.mark.asyncio
async def test_cleanup_fails_tasks_with_missing_or_invalid_prd_generation_owner(monkeypatch):
    _make_prd_generation_engine(monkeypatch)
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    missing = AgentTask(
        id="agent-missing-prd-owner",
        prompt="plan",
        status=AgentTaskStatus.QUEUED,
        owner_type="prd_generation",
        owner_id="9999",
    )
    invalid = AgentTask(
        id="agent-invalid-prd-owner",
        prompt="plan",
        status=AgentTaskStatus.QUEUED,
        owner_type="prd_generation",
        owner_id="not-an-int",
    )
    await redis.hset(queue.TASKS_KEY, missing.id, json.dumps(missing.to_dict()))
    await redis.hset(queue.TASKS_KEY, invalid.id, json.dumps(invalid.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, missing.id)
    await redis.rpush(queue.QUEUE_KEY, invalid.id)

    counts = await queue.cleanup_orphaned_and_stale_tasks()

    cleaned_missing = await queue.get_task(missing.id)
    cleaned_invalid = await queue.get_task(invalid.id)
    assert counts["terminal_owner"] == 2
    assert cleaned_missing.status == AgentTaskStatus.FAILED
    assert cleaned_missing.error == (
        "Agent task stopped because owner prd_generation:9999 is missing"
    )
    assert cleaned_invalid.status == AgentTaskStatus.FAILED
    assert cleaned_invalid.error == (
        "Agent task stopped because owner prd_generation:not-an-int is missing"
    )
    assert redis.lists[queue.QUEUE_KEY] == []


@pytest.mark.asyncio
async def test_cleanup_keeps_browser_auth_session_owner_queued(monkeypatch):
    engine = _make_browser_auth_engine(monkeypatch)
    session_id = _create_browser_auth_session(engine, status="pending")
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(
        id="agent-browser-auth-owner",
        prompt="capture login",
        status=AgentTaskStatus.QUEUED,
        owner_type="browser_auth_session",
        owner_id=session_id,
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, task.id)

    counts = await queue.cleanup_orphaned_and_stale_tasks(max_age_minutes=45)

    kept = await queue.get_task(task.id)
    assert counts["terminal_owner"] == 0
    assert kept.status == AgentTaskStatus.QUEUED
    assert redis.lists[queue.QUEUE_KEY] == [task.id]


@pytest.mark.asyncio
async def test_cleanup_fails_queued_task_missing_from_queue_list():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=10)
    task = AgentTask(
        id="agent-orphaned-queued",
        prompt="inspect",
        status=AgentTaskStatus.QUEUED,
        created_at=created_at,
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))

    counts = await queue.cleanup_orphaned_and_stale_tasks()

    cleaned = await queue.get_task(task.id)
    assert counts["orphaned_queued"] == 1
    assert cleaned.status == AgentTaskStatus.FAILED
    assert await queue.is_cancelled(task.id) is True


@pytest.mark.asyncio
async def test_cleanup_cancels_stale_ownerless_queued_task_in_queue_list():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=90)
    task = AgentTask(
        id="agent-stale-ownerless",
        prompt="inspect",
        status=AgentTaskStatus.QUEUED,
        created_at=created_at,
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, task.id)

    counts = await queue.cleanup_orphaned_and_stale_tasks(max_age_minutes=45)

    cleaned = await queue.get_task(task.id)
    assert counts["stale_ownerless_queued"] == 1
    assert cleaned.status == AgentTaskStatus.CANCELLED
    assert redis.lists[queue.QUEUE_KEY] == []
    assert await queue.is_cancelled(task.id) is True


@pytest.mark.asyncio
async def test_cleanup_keeps_fresh_ownerless_queued_task():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)
    task = AgentTask(
        id="agent-fresh-ownerless",
        prompt="inspect",
        status=AgentTaskStatus.QUEUED,
        created_at=created_at,
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, task.id)

    counts = await queue.cleanup_orphaned_and_stale_tasks(max_age_minutes=45)

    kept = await queue.get_task(task.id)
    assert counts["stale_ownerless_queued"] == 0
    assert kept.status == AgentTaskStatus.QUEUED
    assert redis.lists[queue.QUEUE_KEY] == [task.id]


@pytest.mark.asyncio
async def test_dequeue_skips_stale_ownerless_task_before_valid_agent_run():
    redis = _MemoryRedis()

    class ValidOwnerQueue(_MemoryQueue):
        async def _get_owner_state(self, task):
            if task.owner_id == "run-1":
                return {
                    "type": task.owner_type,
                    "id": task.owner_id,
                    "label": task.owner_label,
                    "status": "running",
                    "terminal": False,
                }
            return await super()._get_owner_state(task)

    queue = ValidOwnerQueue(redis)
    stale = AgentTask(
        id="agent-old-ownerless",
        prompt="old",
        status=AgentTaskStatus.QUEUED,
        created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=90),
    )
    valid = AgentTask(
        id="agent-linked-run",
        prompt="inspect",
        status=AgentTaskStatus.QUEUED,
        owner_type="agent_run",
        owner_id="run-1",
    )
    await redis.hset(queue.TASKS_KEY, stale.id, json.dumps(stale.to_dict()))
    await redis.hset(queue.TASKS_KEY, valid.id, json.dumps(valid.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, stale.id)
    await redis.rpush(queue.QUEUE_KEY, valid.id)

    skipped = await queue.dequeue_task(timeout=1)

    cleaned = await queue.get_task(stale.id)
    kept = await queue.get_task(valid.id)
    assert skipped is None
    assert cleaned.status == AgentTaskStatus.CANCELLED
    assert kept.status == AgentTaskStatus.QUEUED
    assert redis.lists[queue.QUEUE_KEY] == [valid.id]

    dequeued = await queue.dequeue_task(timeout=1)
    assert dequeued.id == valid.id
    assert dequeued.status == AgentTaskStatus.RUNNING
    assert await redis.sismember(queue.RUNNING_KEY, valid.id) is True


@pytest.mark.asyncio
async def test_dequeue_terminalizes_queued_task_with_terminal_owner():
    redis = _MemoryRedis()

    class OwnerTerminalQueue(_MemoryQueue):
        async def _get_owner_state(self, task):
            return {
                "type": task.owner_type,
                "id": task.owner_id,
                "label": task.owner_label,
                "status": "failed",
                "terminal": True,
            }

    queue = OwnerTerminalQueue(redis)
    task = AgentTask(
        id="agent-terminal-owner-queued",
        prompt="inspect",
        status=AgentTaskStatus.QUEUED,
        owner_type="agent_run",
        owner_id="run-failed",
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, task.id)

    assert await queue.dequeue_task(timeout=1) is None
    cleaned = await queue.get_task(task.id)
    assert cleaned.status == AgentTaskStatus.FAILED
    assert redis.lists[queue.QUEUE_KEY] == []


def test_worker_effective_elapsed_excludes_paused_duration():
    worker = AgentWorker.__new__(AgentWorker)
    worker._pause_lock = threading.Lock()
    worker._paused_task_ids = set()
    worker._pause_started_at = {}
    worker._paused_duration_seconds = {"agent-running": 25.0}

    start = time.time() - 40.0
    elapsed = worker._effective_elapsed_seconds("agent-running", start)

    assert 14.0 <= elapsed <= 16.0


def test_worker_extracts_nested_tool_use_stream_items():
    event = {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "text",
                    "text": "Inspecting the page",
                },
                {
                    "type": "tool_result",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_nested",
                            "name": "mcp__playwright-test__browser_snapshot",
                            "input": {},
                        }
                    ],
                },
            ],
        },
    }

    assert [item["name"] for item in _event_tool_uses(event)] == [
        "mcp__playwright-test__browser_snapshot"
    ]


def test_worker_telemetry_preserves_execution_tool_counts():
    worker = AgentWorker.__new__(AgentWorker)
    worker.worker_id = "worker-1"
    worker._progress_lock = threading.RLock()
    worker._current_progress = {
        "tool_calls": 0,
        "browser_tool_calls": 0,
        "interactions": 0,
        "last_tool": "",
        "tool_names": [],
        "chars": 120,
    }
    worker._last_execution_telemetry = {
        "tool_calls": 3,
        "browser_tool_calls": 2,
        "interactions": 1,
        "last_tool": "mcp__playwright-test__browser_click",
        "tool_names": [
            "mcp__playwright-test__browser_navigate",
            "mcp__playwright-test__browser_snapshot",
            "mcp__playwright-test__browser_click",
        ],
        "tool_call_records": [
            {"name": "mcp__playwright-test__browser_navigate", "input": {"url": "https://example.test"}},
            {"name": "mcp__playwright-test__browser_snapshot", "input": {}},
            {"name": "mcp__playwright-test__browser_click", "input": {"element": "Submit"}},
        ],
    }
    task = AgentTask(
        id="task-1",
        prompt="prompt",
        agent_type="AgentRunner",
        operation_type="run",
        allowed_tools=["mcp__playwright-test__browser_click"],
        tools=["mcp__playwright-test__browser_click"],
    )

    telemetry = worker._build_task_telemetry(task, attempt=1)

    assert telemetry["tool_calls"] == 3
    assert telemetry["browser_tool_calls"] == 2
    assert telemetry["interactions"] == 1
    assert telemetry["last_tool"] == "mcp__playwright-test__browser_click"
    assert telemetry["tool_names"][-1] == "mcp__playwright-test__browser_click"
    assert telemetry["tool_call_records"][0]["input"]["url"] == "https://example.test"


def test_browser_observation_recorder_persists_snapshot_result(tmp_path):
    class FakeState:
        def __init__(self, state_id):
            self.id = state_id

    class FakeService:
        def __init__(self):
            self.states = []
            self.transitions = []

        def upsert_page_state(self, **kwargs):
            state = FakeState(f"state-{len(self.states) + 1}")
            self.states.append({**kwargs, "state": state})
            return state

        def record_transition(self, **kwargs):
            self.transitions.append(kwargs)

    service = FakeService()
    recorder = BrowserObservationRecorder(
        session_id="explore-1",
        cwd=str(tmp_path),
        service_factory=lambda: service,
    )

    recorder.observe_event(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_snapshot",
                        "name": "mcp__playwright-test__browser_snapshot",
                        "input": {},
                    }
                ]
            },
        }
    )
    recorder.observe_event(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_snapshot",
                        "content": [
                            {
                                "type": "text",
                                "text": 'Page title: Login\nhttps://example.test/login\n- button "Sign in"',
                            }
                        ],
                    }
                ]
            },
        }
    )

    assert len(service.states) == 1
    assert service.states[0]["session_id"] == "explore-1"
    assert service.states[0]["url"] == "https://example.test/login"
    assert service.states[0]["title"] == "Login"
    assert recorder.telemetry()["browser_memory_snapshots"] == 1
    assert (tmp_path / "browser-memory-observations.jsonl").exists()


def test_browser_observation_recorder_pairs_interaction_with_next_snapshot(tmp_path):
    class FakeState:
        def __init__(self, state_id):
            self.id = state_id

    class FakeService:
        def __init__(self):
            self.states = []
            self.transitions = []

        def upsert_page_state(self, **kwargs):
            state = FakeState(f"state-{len(self.states) + 1}")
            self.states.append({**kwargs, "state": state})
            return state

        def record_transition(self, **kwargs):
            self.transitions.append(kwargs)

    service = FakeService()
    recorder = BrowserObservationRecorder(
        session_id="explore-1",
        cwd=str(tmp_path),
        service_factory=lambda: service,
    )

    def event_tool_use(tool_id, name, tool_input=None):
        recorder.observe_event(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": tool_id,
                            "name": f"mcp__playwright-test__{name}",
                            "input": tool_input or {},
                        }
                    ]
                },
            }
        )

    def event_tool_result(tool_id, text):
        recorder.observe_event(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": text,
                        }
                    ]
                },
            }
        )

    event_tool_use("s1", "browser_snapshot")
    event_tool_result("s1", 'https://example.test\n- button "Open menu"')
    event_tool_use("c1", "browser_click", {"element": "Open menu"})
    event_tool_result("c1", "Clicked")
    event_tool_use("s2", "browser_snapshot")
    event_tool_result("s2", 'https://example.test\n- menuitem "Settings"')

    assert len(service.states) == 2
    assert len(service.transitions) == 1
    assert service.transitions[0]["from_state"].id == "state-1"
    assert service.transitions[0]["to_state"].id == "state-2"
    assert service.transitions[0]["action_type"] == "click"
    assert service.transitions[0]["target"] == "Open menu"
    assert recorder.telemetry()["browser_memory_transitions"] == 1


def test_browser_observation_recorder_ignores_malformed_result_without_raising(
    tmp_path,
):
    recorder = BrowserObservationRecorder(
        session_id="explore-1",
        cwd=str(tmp_path),
        service_factory=lambda: (_ for _ in ()).throw(
            AssertionError("service should not be called")
        ),
    )

    recorder.observe_event(
        {
            "type": "user",
            "message": {"content": [{"type": "tool_result", "content": "orphan"}]},
        }
    )

    assert recorder.telemetry()["browser_memory_snapshots"] == 0
    assert recorder.telemetry()["browser_memory_transitions"] == 0


@pytest.mark.asyncio
async def test_running_task_summaries_are_sanitized():
    started_at = datetime.now(UTC).replace(tzinfo=None)
    task = AgentTask(
        id="agent-running",
        prompt="secret user prompt",
        system_prompt="secret system prompt",
        status=AgentTaskStatus.RUNNING,
        worker_id="worker-1",
        agent_type="AgentRunner",
        operation_type="run",
        cwd="/tmp/project",
        env_vars={"ANTHROPIC_API_KEY": "secret"},
        started_at=started_at,
    )

    class FakeRedis:
        async def smembers(self, _key):
            return {"agent-running"}

    class FakeQueue(AgentQueue):
        def __init__(self):
            pass

        async def _ensure_connected(self):
            return FakeRedis()

        async def get_task(self, task_id: str):
            return task if task_id == "agent-running" else None

        async def get_task_progress(self, task_id: str):
            assert task_id == "agent-running"
            return {
                "activity_label": "Exploring https://example.test",
                "tool_calls": 3,
                "last_tool": "mcp__playwright-test__browser_snapshot",
                "last_tool_input": {"password": "secret"},
            }

        async def check_heartbeat(self, task_id: str, max_stale_seconds: int = 120):
            assert task_id == "agent-running"
            return True

    summaries = await FakeQueue().get_running_task_summaries()

    assert summaries == [
        {
            "id": "agent-running",
            "status": "running",
            "worker_id": "worker-1",
            "agent_type": "AgentRunner",
            "operation_type": "run",
            "created_at": task.created_at.isoformat(),
            "started_at": started_at.isoformat(),
            "timeout_seconds": 1800,
            "heartbeat_alive": True,
            "owner_type": None,
            "owner_id": None,
            "owner_label": None,
            "owner_status": None,
            "owner_terminal": False,
            "live": True,
            "orphaned": False,
            "progress": {
                "activity_label": "Exploring https://example.test",
                "tool_calls": 3,
                "last_tool": "mcp__playwright-test__browser_snapshot",
            },
        }
    ]
    assert "prompt" not in summaries[0]
    assert "system_prompt" not in summaries[0]
    assert "env_vars" not in summaries[0]
    assert "last_tool_input" not in summaries[0]["progress"]


@pytest.mark.asyncio
async def test_running_summary_marks_missing_heartbeat_stale_not_live():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(
        id="agent-stale-running",
        prompt="inspect",
        status=AgentTaskStatus.RUNNING,
        worker_id="worker-1",
        started_at=datetime.now(UTC).replace(tzinfo=None),
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.sadd(queue.RUNNING_KEY, task.id)

    summaries = await queue.get_running_task_summaries()

    assert len(summaries) == 1
    assert summaries[0]["id"] == task.id
    assert summaries[0]["heartbeat_alive"] is False
    assert summaries[0]["live"] is False
    assert summaries[0]["orphaned"] is True


@pytest.mark.asyncio
async def test_running_summary_marks_terminal_owner_not_live():
    redis = _MemoryRedis()

    class OwnerTerminalQueue(_MemoryQueue):
        async def _get_owner_state(self, task):
            return {
                "type": task.owner_type,
                "id": task.owner_id,
                "label": task.owner_label,
                "status": "failed",
                "terminal": True,
            }

    queue = OwnerTerminalQueue(redis)
    task = AgentTask(
        id="agent-terminal-running",
        prompt="inspect",
        status=AgentTaskStatus.RUNNING,
        worker_id="worker-1",
        started_at=datetime.now(UTC).replace(tzinfo=None),
        owner_type="agent_run",
        owner_id="run-failed",
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.sadd(queue.RUNNING_KEY, task.id)
    await queue.update_heartbeat(task.id)

    summaries = await queue.get_running_task_summaries()

    assert summaries[0]["heartbeat_alive"] is True
    assert summaries[0]["owner_terminal"] is True
    assert summaries[0]["live"] is False
    assert summaries[0]["orphaned"] is True


@pytest.mark.asyncio
async def test_running_summary_counts_paused_active_owner_as_live():
    redis = _MemoryRedis()

    class ActiveOwnerQueue(_MemoryQueue):
        async def _get_owner_state(self, task):
            return {
                "type": task.owner_type,
                "id": task.owner_id,
                "label": task.owner_label,
                "status": "running",
                "terminal": False,
            }

    queue = ActiveOwnerQueue(redis)
    task = AgentTask(
        id="agent-paused-active",
        prompt="inspect",
        status=AgentTaskStatus.PAUSED,
        worker_id="worker-1",
        started_at=datetime.now(UTC).replace(tzinfo=None),
        owner_type="agent_run",
        owner_id="run-paused",
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.sadd(queue.RUNNING_KEY, task.id)

    summaries = await queue.get_running_task_summaries()

    assert summaries[0]["heartbeat_alive"] is False
    assert summaries[0]["owner_terminal"] is False
    assert summaries[0]["live"] is True
    assert summaries[0]["orphaned"] is False
