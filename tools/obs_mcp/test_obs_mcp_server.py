from __future__ import annotations

import importlib.util
from pathlib import Path


SERVER_PATH = Path(__file__).with_name("server.py")
spec = importlib.util.spec_from_file_location("obs_mcp_server", SERVER_PATH)
server = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(server)


def test_prepare_recording_writes_dry_run_plan(monkeypatch) -> None:
    monkeypatch.setenv("OBS_DRY_RUN", "1")

    result = server.obs_prepare_recording("001")

    assert result["status"] == "dry_run_ready"
    plan_path = server.PROJECT_ROOT / result["plan_path"]
    assert plan_path.exists()
    assert result["plan"]["scene_sequence"]


def test_start_recording_without_confirm_is_blocked(monkeypatch) -> None:
    monkeypatch.setenv("OBS_DRY_RUN", "1")

    result = server.obs_start_recording("001", confirm=False)

    assert result["status"] == "dry_run_blocked"
    assert "OBS recording was not started" in result["message"]
