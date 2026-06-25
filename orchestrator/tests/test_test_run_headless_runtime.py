import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from orchestrator.api import test_run_runtime_support
from orchestrator.api.test_run_runtime_support import execute_run_task, resolve_run_headless_mode


class _Settings:
    def __init__(self, *, headless_in_parallel=True, memory_enabled=True):
        self.headless_in_parallel = headless_in_parallel
        self.memory_enabled = memory_enabled


def test_resolve_run_headless_defaults_to_headless_without_env_or_settings():
    assert resolve_run_headless_mode(env={}) is True


def test_resolve_run_headless_honors_true_env_values():
    assert resolve_run_headless_mode(env={"HEADLESS": "true"}) is True
    assert resolve_run_headless_mode(env={"PLAYWRIGHT_HEADLESS": "true"}) is True


def test_resolve_run_headless_false_env_requires_display_capable_vnc():
    assert resolve_run_headless_mode(env={"HEADLESS": "false"}) is True
    assert resolve_run_headless_mode(env={"PLAYWRIGHT_HEADLESS": "false"}) is True
    assert (
        resolve_run_headless_mode(
            env={"VNC_ENABLED": "true", "DISPLAY": ":99", "HEADLESS": "false"}
        )
        is False
    )


def test_resolve_run_headless_uses_db_settings_when_env_absent():
    assert resolve_run_headless_mode(env={}, execution_settings=_Settings(headless_in_parallel=True)) is True
    assert (
        resolve_run_headless_mode(
            env={"VNC_ENABLED": "true", "DISPLAY": ":99"},
            execution_settings=_Settings(headless_in_parallel=False),
        )
        is False
    )


def test_resolve_run_headless_env_overrides_db_settings():
    assert (
        resolve_run_headless_mode(
            env={"HEADLESS": "true", "VNC_ENABLED": "true", "DISPLAY": ":99"},
            execution_settings=_Settings(headless_in_parallel=False),
        )
        is True
    )


def test_resolve_run_headless_vnc_requires_display():
    assert resolve_run_headless_mode(env={"VNC_ENABLED": "true"}) is True
    assert resolve_run_headless_mode(env={"VNC_ENABLED": "true", "DISPLAY": ":99"}) is False


class _NullSession:
    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, *_args, **_kwargs):
        return None


def _fake_runtime(tmp_path, captured_env):
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    (base_dir / "playwright.config.ts").write_text("export default {};\n")

    def capture_subprocess(**kwargs):
        captured_env.update(kwargs["env"])

    return SimpleNamespace(
        datetime=datetime,
        Session=_NullSession,
        engine=object(),
        DBTestRun=object,
        sys=sys,
        os=os,
        BASE_DIR=base_dir,
        logger=logging.getLogger("test-run-headless-runtime"),
        _write_run_browser_metadata=lambda *_args, **_kwargs: None,
        _build_run_browser_metadata=lambda **kwargs: kwargs,
        _merge_run_browser_metadata=lambda *metadata, **kwargs: {**kwargs},
        copy_claude_project_config=lambda *_args, **_kwargs: None,
        prepare_run_playwright_config_content=lambda content, **_kwargs: content,
        write_playwright_test_mcp_config=lambda **_kwargs: {"mcp_args": ["--headless"]},
        _extract_run_target_url=lambda *_args, **_kwargs: None,
        _write_run_seed_spec=lambda run_dir, _target_url: Path(run_dir) / "tests" / "seed.spec.ts",
        _normalize_request_test_data_refs=lambda refs: refs or [],
        _run_test_cli_subprocess_with_retry=capture_subprocess,
    )


def test_execute_run_task_sets_headless_subprocess_env_defaults(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("TEST_RUN_PLAYWRIGHT_WORKERS", raising=False)
    monkeypatch.delenv("PLAYWRIGHT_WORKERS", raising=False)
    monkeypatch.setenv("HEADLESS", "false")
    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", "false")
    captured_env = {}
    runtime = _fake_runtime(tmp_path, captured_env)

    execute_run_task(
        runtime,
        spec_path=str(tmp_path / "spec.md"),
        run_dir=str(tmp_path / "run"),
        run_id="run-headless-default",
        headless=False,
    )

    assert captured_env["HEADLESS"] == "true"
    assert captured_env["PLAYWRIGHT_HEADLESS"] == "true"
    assert "CI" not in captured_env
    assert captured_env["PLAYWRIGHT_WORKERS"] == "1"


def test_execute_run_task_honors_test_run_playwright_workers_for_headless_subprocess(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("TEST_RUN_PLAYWRIGHT_WORKERS", "4")
    monkeypatch.setenv("PLAYWRIGHT_WORKERS", "9")
    captured_env = {}
    runtime = _fake_runtime(tmp_path, captured_env)

    execute_run_task(
        runtime,
        spec_path=str(tmp_path / "spec.md"),
        run_dir=str(tmp_path / "run"),
        run_id="run-headless-custom-workers",
        headless=True,
    )

    assert captured_env["HEADLESS"] == "true"
    assert captured_env["PLAYWRIGHT_HEADLESS"] == "true"
    assert captured_env["PLAYWRIGHT_WORKERS"] == "4"


def test_execute_run_task_sets_headed_subprocess_env_for_vnc_runs(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("VNC_ENABLED", "true")
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("TEST_RUN_PLAYWRIGHT_WORKERS", "6")
    monkeypatch.setenv("PLAYWRIGHT_WORKERS", "6")
    captured_env = {}
    runtime = _fake_runtime(tmp_path, captured_env)

    execute_run_task(
        runtime,
        spec_path=str(tmp_path / "spec.md"),
        run_dir=str(tmp_path / "run"),
        run_id="run-headed-vnc",
        headless=False,
    )

    assert captured_env["HEADLESS"] == "false"
    assert captured_env["PLAYWRIGHT_HEADLESS"] == "false"
    assert captured_env["PLAYWRIGHT_WORKERS"] == "1"
    assert captured_env["CI"] == ""


def test_resolve_effective_browser_parallelism_clamps_only_headed_vnc_runs():
    effective_parallelism = getattr(
        test_run_runtime_support,
        "resolve_effective_browser_parallelism",
    )

    headed_vnc = effective_parallelism(
        requested_parallelism=5,
        env={"VNC_ENABLED": "true", "DISPLAY": ":99", "HEADLESS": "false"},
    )
    headless = effective_parallelism(
        requested_parallelism=5,
        env={"VNC_ENABLED": "true", "DISPLAY": ":99", "HEADLESS": "true"},
    )

    assert headed_vnc["headless"] is False
    assert headed_vnc["effective_parallelism"] == 1
    assert headed_vnc["parallelism_clamp_reason"] == "shared_vnc_display"
    assert headless["headless"] is True
    assert headless["effective_parallelism"] == 5
    assert headless["parallelism_clamp_reason"] is None
