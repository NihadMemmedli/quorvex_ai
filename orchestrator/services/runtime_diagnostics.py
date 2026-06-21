"""Runtime identity diagnostics for long-running AutoPilot processes."""

from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROCESS_START_TIME = datetime.now(timezone.utc)


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _linux_process_start_time(pid: int) -> str | None:
    stat_path = Path(f"/proc/{pid}/stat")
    if not stat_path.exists():
        return None
    try:
        boot_time = None
        for line in Path("/proc/stat").read_text().splitlines():
            if line.startswith("btime "):
                boot_time = int(line.split()[1])
                break
        if boot_time is None:
            return None
        parts = stat_path.read_text().split()
        start_ticks = int(parts[21])
        ticks_per_second = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        return _iso(boot_time + (start_ticks / ticks_per_second))
    except Exception:
        return None


def _process_one_start_time() -> str | None:
    return _linux_process_start_time(1)


def _current_process_start_time() -> str:
    return _linux_process_start_time(os.getpid()) or PROCESS_START_TIME.isoformat()


def _git_revision(root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def source_file_mtimes(paths: list[Path]) -> dict[str, str | None]:
    mtimes: dict[str, str | None] = {}
    for path in paths:
        try:
            mtimes[str(path)] = _iso(path.stat().st_mtime)
        except OSError:
            mtimes[str(path)] = None
    return mtimes


def autopilot_runtime_diagnostics() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    source_paths = [
        root / "orchestrator" / "workflows" / "autopilot_pipeline.py",
        root / "orchestrator" / "workflows" / "native_planner.py",
        root / "orchestrator" / "workflows" / "native_generator.py",
        root / "orchestrator" / "workflows" / "full_native_pipeline.py",
        root / "orchestrator" / "utils" / "agent_runner.py",
        root / "orchestrator" / "services" / "autopilot_agent_reliability.py",
    ]
    source_mtimes = source_file_mtimes(source_paths)
    newest_source_mtime = max(
        (value for value in source_mtimes.values() if value),
        default=None,
    )
    process_started_at = _current_process_start_time()
    return {
        "container_start_time": _process_one_start_time(),
        "process_start_time": process_started_at,
        "module_import_time": PROCESS_START_TIME.isoformat(),
        "git_revision": _git_revision(root),
        "source_root": str(root),
        "source_file_mtimes": source_mtimes,
        "newest_source_mtime": newest_source_mtime,
        "runtime_stale": bool(newest_source_mtime and newest_source_mtime > process_started_at),
        "pid": os.getpid(),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "monotonic_seconds": round(time.monotonic(), 3),
    }
