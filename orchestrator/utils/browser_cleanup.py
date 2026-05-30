"""
Browser Cleanup Utilities - Kill orphaned Chromium/Node processes after agent queries.

When the Claude Agent SDK spawns a Playwright MCP server, it launches Chromium
via launchPersistentContext(). If the SDK throws "cancel scope" errors during
cleanup (a known issue), the MCP server and its browser process may not be shut
down properly. This module provides utilities to detect and kill those orphans.

Usage:
    from orchestrator.utils.browser_cleanup import snapshot_child_pids, kill_new_children

    pids_before = snapshot_child_pids()
    try:
        # ... run agent query ...
    finally:
        kill_new_children(pids_before)
"""

import logging
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Process name fragments that indicate browser/MCP processes we should clean up
_BROWSER_PROCESS_NAMES = {"chromium", "chrome", "node", "npx"}
_AUTOPILOT_PROCESS_NAMES = {"claude", "chromium", "chrome", "node", "npx"}
_TEST_RUN_PROCESS_NAMES = {
    "claude",
    "chromium",
    "chrome",
    "node",
    "npx",
    "ffmpeg",
}


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    ppid: int
    comm: str
    args: str


def _get_child_pids(parent_pid: int = None) -> set[int]:
    """Get all child PIDs of the given process (default: current process).

    Uses `pgrep -P <pid>` which is available on Linux and macOS.
    Returns an empty set on failure.
    """
    if parent_pid is None:
        parent_pid = os.getpid()

    try:
        result = subprocess.run(
            ["pgrep", "-P", str(parent_pid)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return {int(pid) for pid in result.stdout.strip().split("\n") if pid.strip()}
    except Exception:
        pass
    return set()


def _get_descendant_pids(parent_pid: int = None) -> set[int]:
    """Get all descendant PIDs (children, grandchildren, etc.) recursively."""
    if parent_pid is None:
        parent_pid = os.getpid()

    descendants = set()
    to_visit = [parent_pid]

    while to_visit:
        pid = to_visit.pop()
        children = _get_child_pids(pid)
        for child in children:
            if child not in descendants:
                descendants.add(child)
                to_visit.append(child)

    return descendants


def _is_browser_or_mcp_process(pid: int) -> bool:
    """Check if a PID corresponds to a Chromium, Chrome, Node, or npx process."""
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            comm = result.stdout.strip().lower()
            return any(name in comm for name in _BROWSER_PROCESS_NAMES)
    except Exception:
        pass
    return False


def _process_table() -> dict[int, ProcessInfo]:
    """Return process table entries keyed by PID."""
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid=,ppid=,comm=,args="],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return {}

    if result.returncode != 0:
        return {}

    processes: dict[int, ProcessInfo] = {}
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        comm = parts[2]
        args = parts[3] if len(parts) > 3 else ""
        processes[pid] = ProcessInfo(pid=pid, ppid=ppid, comm=comm, args=args)
    return processes


def _descendants_from_table(processes: dict[int, ProcessInfo], root_pid: int) -> set[int]:
    descendants: set[int] = set()
    to_visit = [root_pid]
    while to_visit:
        current = to_visit.pop()
        children = [pid for pid, proc in processes.items() if proc.ppid == current]
        for child in children:
            if child not in descendants:
                descendants.add(child)
                to_visit.append(child)
    return descendants


def _is_autopilot_cleanup_process(proc: ProcessInfo) -> bool:
    comm = proc.comm.lower()
    return any(name in comm for name in _AUTOPILOT_PROCESS_NAMES)


def _is_autopilot_process_root(proc: ProcessInfo, marker: str) -> bool:
    if marker not in proc.args:
        return False
    comm = proc.comm.lower()
    args = proc.args.lower()
    if "claude" in comm:
        return True
    if "node" in comm or "npx" in comm:
        return "playwright" in args or "mcp" in args
    if "chrome" in comm or "chromium" in comm:
        return "playwright" in args or "user-data-dir" in args
    return False


def _is_test_run_cleanup_process(proc: ProcessInfo) -> bool:
    comm = proc.comm.lower()
    return any(name in comm for name in _TEST_RUN_PROCESS_NAMES)


def _is_test_run_process_root(proc: ProcessInfo, run_id: str) -> bool:
    if not run_id or run_id not in proc.args:
        return False
    comm = proc.comm.lower()
    args = proc.args.lower()
    if "claude" in comm:
        return True
    if "node" in comm or "npx" in comm:
        return "playwright" in args or "mcp" in args
    if "chrome" in comm or "chromium" in comm:
        return "playwright" in args or "user-data-dir" in args
    if "python" in comm:
        return "orchestrator/cli.py" in args or "/app/runs/" in args
    return False


def find_autopilot_process_tree(session_id: str | None = None) -> set[int]:
    """Find AutoPilot-owned Claude/MCP/browser process trees by session marker.

    The marker is intentionally session-scoped. Browser child processes usually
    do not include the session id in their own argv, so this matches root Claude
    or MCP processes that reference the run directory and then includes their
    descendants.
    """
    marker = session_id or "autopilot_"
    if not marker:
        return set()

    processes = _process_table()
    roots = {
        pid
        for pid, proc in processes.items()
        if _is_autopilot_process_root(proc, marker)
    }
    targets = set(roots)
    for pid in roots:
        targets.update(_descendants_from_table(processes, pid))

    return {
        pid
        for pid in targets
        if pid != os.getpid()
        and pid in processes
        and _is_autopilot_cleanup_process(processes[pid])
    }


def find_test_run_process_tree(run_id: str | None = None) -> set[int]:
    """Find Claude/MCP/browser process trees tied to a test run id.

    Browser child processes do not always carry the run id in argv, so this
    matches run-scoped root processes first and then includes cleanup-eligible
    descendants.
    """
    if not run_id:
        return set()

    processes = _process_table()
    roots = {
        pid
        for pid, proc in processes.items()
        if _is_test_run_process_root(proc, run_id)
    }
    targets = set(roots)
    for pid in roots:
        targets.update(_descendants_from_table(processes, pid))

    return {
        pid
        for pid in targets
        if pid != os.getpid()
        and pid in processes
        and _is_test_run_cleanup_process(processes[pid])
    }


def find_autopilot_session_ids_in_processes() -> set[str]:
    """Return AutoPilot session ids visible in process command lines."""
    pattern = re.compile(r"autopilot_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}")
    session_ids: set[str] = set()
    for proc in _process_table().values():
        if _is_autopilot_cleanup_process(proc):
            session_ids.update(pattern.findall(proc.args))
    return session_ids


def find_test_run_ids_in_processes() -> set[str]:
    """Return test run ids visible in cleanup-eligible process command lines."""
    pattern = re.compile(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}")
    run_ids: set[str] = set()
    for proc in _process_table().values():
        comm = proc.comm.lower()
        args = proc.args.lower()
        if _is_test_run_cleanup_process(proc) or (
            "python" in comm and ("orchestrator/cli.py" in args or "/app/runs/" in args)
        ):
            run_ids.update(pattern.findall(proc.args))
    return run_ids


def kill_test_run_process_tree(run_id: str, grace_seconds: float = 2.0) -> dict[str, object]:
    """Kill Claude/MCP/browser process trees tied to one test run id."""
    targets = find_test_run_process_tree(run_id)
    if not targets:
        return {"run_id": run_id, "matched": 0, "terminated": 0, "killed": 0, "pids": []}

    logger.info("Killing %d test-run process(es) for %s: %s", len(targets), run_id, sorted(targets))
    terminated = 0
    for pid in sorted(targets, reverse=True):
        try:
            os.kill(pid, signal.SIGTERM)
            terminated += 1
        except (ProcessLookupError, PermissionError):
            pass

    time.sleep(grace_seconds)

    killed = 0
    for pid in sorted(targets, reverse=True):
        try:
            os.kill(pid, 0)
            os.kill(pid, signal.SIGKILL)
            killed += 1
        except (ProcessLookupError, PermissionError):
            pass

    return {
        "run_id": run_id,
        "matched": len(targets),
        "terminated": terminated,
        "killed": killed,
        "pids": sorted(targets),
    }


def kill_autopilot_process_tree(session_id: str, grace_seconds: float = 2.0) -> dict[str, object]:
    """Kill process trees tied to one AutoPilot session id."""
    targets = find_autopilot_process_tree(session_id)
    if not targets:
        return {"session_id": session_id, "matched": 0, "terminated": 0, "killed": 0, "pids": []}

    logger.info("Killing %d AutoPilot process(es) for %s: %s", len(targets), session_id, sorted(targets))
    terminated = 0
    for pid in sorted(targets, reverse=True):
        try:
            os.kill(pid, signal.SIGTERM)
            terminated += 1
        except (ProcessLookupError, PermissionError):
            pass

    time.sleep(grace_seconds)

    killed = 0
    for pid in sorted(targets, reverse=True):
        try:
            os.kill(pid, 0)
            os.kill(pid, signal.SIGKILL)
            killed += 1
        except (ProcessLookupError, PermissionError):
            pass

    return {
        "session_id": session_id,
        "matched": len(targets),
        "terminated": terminated,
        "killed": killed,
        "pids": sorted(targets),
    }


def snapshot_child_pids() -> set[int]:
    """Capture all descendant PIDs before a query() call.

    Call this immediately before invoking the agent SDK query().
    The returned set is passed to kill_new_children() after the query completes.
    """
    pids = _get_descendant_pids()
    logger.debug(f"Snapshot: {len(pids)} existing child PIDs")
    return pids


def kill_new_children(before_pids: set[int], grace_seconds: float = 2.0) -> int:
    """Kill browser/MCP child processes that appeared after the snapshot.

    Args:
        before_pids: Set of PIDs captured by snapshot_child_pids() before the query
        grace_seconds: Time to wait after SIGTERM before sending SIGKILL

    Returns:
        Number of processes killed
    """
    current_pids = _get_descendant_pids()
    new_pids = current_pids - before_pids

    if not new_pids:
        logger.debug("No new child processes to clean up")
        return 0

    # Filter to only browser/MCP processes
    targets = {pid for pid in new_pids if _is_browser_or_mcp_process(pid)}

    if not targets:
        logger.debug(f"No browser/MCP processes among {len(new_pids)} new children")
        return 0

    logger.info(f"Cleaning up {len(targets)} orphaned browser/MCP processes: {targets}")
    killed = 0

    # Phase 1: SIGTERM (graceful shutdown)
    for pid in targets:
        try:
            os.kill(pid, signal.SIGTERM)
            killed += 1
            logger.debug(f"Sent SIGTERM to PID {pid}")
        except ProcessLookupError:
            pass  # Already exited
        except PermissionError:
            logger.debug(f"Permission denied for PID {pid}")

    if killed == 0:
        return 0

    # Wait for graceful shutdown
    time.sleep(grace_seconds)

    # Phase 2: SIGKILL for stragglers
    for pid in targets:
        try:
            # Check if still alive
            os.kill(pid, 0)
            # Still alive, force kill
            os.kill(pid, signal.SIGKILL)
            logger.debug(f"Sent SIGKILL to PID {pid}")
        except ProcessLookupError:
            pass  # Already exited (good)
        except PermissionError:
            pass

    logger.info(f"Cleaned up {killed} orphaned process(es)")
    return killed


def cleanup_orphaned_browsers() -> int:
    """Emergency cleanup: kill ALL browser/MCP child processes of the current process.

    Use this as a safety net between pipeline stages or in exception handlers.
    Unlike kill_new_children(), this doesn't use a before-snapshot - it kills
    all matching descendants unconditionally.

    Returns:
        Number of processes killed
    """
    all_descendants = _get_descendant_pids()
    targets = {pid for pid in all_descendants if _is_browser_or_mcp_process(pid)}

    if not targets:
        return 0

    logger.info(f"Emergency cleanup: killing {len(targets)} browser/MCP processes")
    killed = 0

    # SIGTERM first
    for pid in targets:
        try:
            os.kill(pid, signal.SIGTERM)
            killed += 1
        except (ProcessLookupError, PermissionError):
            pass

    if killed == 0:
        return 0

    time.sleep(2.0)

    # SIGKILL stragglers
    for pid in targets:
        try:
            os.kill(pid, 0)
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    logger.info(f"Emergency cleanup: killed {killed} process(es)")
    return killed
