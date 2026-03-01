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
import signal
import subprocess

logger = logging.getLogger(__name__)

# Process name fragments that indicate browser/MCP processes we should clean up
_BROWSER_PROCESS_NAMES = {"chromium", "chrome", "node", "npx"}


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
    import time

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

    import time

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
