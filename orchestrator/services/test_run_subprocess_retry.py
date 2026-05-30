from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

IMPORT_DEADLOCK_MARKERS = ("Resource deadlock avoided", "Errno 35")
STARTUP_ARTIFACTS = (
    "status.txt",
    "plan.json",
    "run.json",
    "test-results.json",
    "pipeline_error.json",
)


def startup_import_deadlock_retries() -> int:
    raw = os.environ.get("TEST_RUN_STARTUP_IMPORT_RETRIES", "1")
    try:
        return max(0, min(2, int(raw)))
    except ValueError:
        return 1


def read_log_tail(path: Path, max_chars: int = 20000) -> str:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return ""
    if len(text) > max_chars:
        return text[-max_chars:]
    return text


def native_pipeline_started(run_dir_path: Path) -> bool:
    return any((run_dir_path / name).exists() for name in STARTUP_ARTIFACTS)


def is_retryable_startup_import_deadlock(
    run_dir_path: Path,
    *,
    returncode: int | None,
    elapsed_seconds: float,
    log_text: str | None = None,
) -> bool:
    """Return True only for early Docker bind-mount import deadlocks."""
    if returncode in (None, 0):
        return False
    if elapsed_seconds > 15:
        return False
    if native_pipeline_started(run_dir_path):
        return False
    text = (
        log_text
        if log_text is not None
        else read_log_tail(run_dir_path / "execution.log")
    )
    return any(marker in text for marker in IMPORT_DEADLOCK_MARKERS)


def run_test_cli_subprocess_with_retry(
    *,
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
    run_id: str,
    run_dir_path: Path,
    spec_name: str,
    batch_id: str | None,
    append_workflow_log: Callable[..., None],
    register_process: Callable[[str, subprocess.Popen], None],
    unregister_process: Callable[[str], subprocess.Popen | None],
    process_manager: Any = None,
    logger: Any = None,
    record_startup_import_failure: Callable[..., None] | None = None,
    timeout_seconds: int = 3600,
    max_retries: int | None = None,
) -> int | None:
    """Run the CLI subprocess, retrying only early Errno 35 import failures."""
    log_file = run_dir_path / "execution.log"
    retry_limit = (
        startup_import_deadlock_retries()
        if max_retries is None
        else max(0, min(2, max_retries))
    )
    attempt = 0
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("", encoding="utf-8")

    while True:
        attempt += 1
        with log_file.open("a", encoding="utf-8") as f:
            if attempt > 1:
                f.write("\n\n")
            f.write(f"=== CLI attempt {attempt}/{retry_limit + 1} ===\n")
            f.flush()

            started = time.monotonic()
            process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=f,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
            )

            try:
                pgid = os.getpgid(process.pid)
            except (ProcessLookupError, OSError):
                pgid = process.pid

            register_process(run_id, process)
            if process_manager:
                process_manager.register(
                    run_id=run_id,
                    pid=process.pid,
                    pgid=pgid,
                    spec_name=spec_name,
                    batch_id=batch_id,
                )

            if logger:
                logger.info(
                    "Started process for %s: pid=%s, pgid=%s, attempt=%s",
                    run_id,
                    process.pid,
                    pgid,
                    attempt,
                )
            append_workflow_log("Subprocess spawned.", pid=process.pid, pgid=pgid, attempt=attempt)

            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                if logger:
                    logger.warning(
                        "Process for %s timed out after %ss, killing process group",
                        run_id,
                        timeout_seconds,
                    )
                append_workflow_log("Subprocess timed out; killing process group.", pid=process.pid, attempt=attempt)
                import signal as _signal

                try:
                    os.killpg(os.getpgid(process.pid), _signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    try:
                        process.kill()
                    except (ProcessLookupError, OSError):
                        pass
                process.wait(timeout=10)
            finally:
                unregister_process(run_id)
                if process_manager:
                    process_manager.unregister(run_id)

            elapsed = time.monotonic() - started
            if logger:
                logger.info(
                    "Process completed for %s: exit_code=%s, attempt=%s",
                    run_id,
                    process.returncode,
                    attempt,
                )
            append_workflow_log(
                "Subprocess completed.",
                exit_code=process.returncode,
                attempt=attempt,
                elapsed_seconds=round(elapsed, 3),
            )

        log_tail = read_log_tail(log_file)
        retryable = is_retryable_startup_import_deadlock(
            run_dir_path,
            returncode=process.returncode,
            elapsed_seconds=elapsed,
            log_text=log_tail,
        )
        if retryable and attempt <= retry_limit:
            if record_startup_import_failure:
                record_startup_import_failure(run_id, run_dir_path, retrying=True)
            append_workflow_log(
                "Transient Docker bind-mount import failure detected; retrying CLI.",
                attempt=attempt,
                max_retries=retry_limit,
            )
            with log_file.open("a", encoding="utf-8") as f:
                f.write(
                    "\n=== Transient Docker bind-mount import failure detected; retrying CLI ===\n"
                )
            time.sleep(min(2.0, 0.5 * attempt))
            continue
        if retryable:
            if record_startup_import_failure:
                record_startup_import_failure(run_id, run_dir_path, retrying=False)
            append_workflow_log(
                "Transient Docker bind-mount import failure exhausted retries.",
                attempt=attempt,
                max_retries=retry_limit,
            )
        return process.returncode
