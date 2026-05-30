import os
import sys
from pathlib import Path

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-api-tests")
os.environ.setdefault("REQUIRE_AUTH", "false")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.services import test_run_subprocess_retry as retry_module


def test_startup_import_deadlock_retry_classifier_is_narrow(tmp_path):
    log = (
        "Traceback (most recent call last):\n"
        "  File \"/app/orchestrator/ai/prompt_registry.py\", line 1, in <module>\n"
        "OSError: [Errno 35] Resource deadlock avoided\n"
    )

    assert retry_module.is_retryable_startup_import_deadlock(
        tmp_path,
        returncode=1,
        elapsed_seconds=0.5,
        log_text=log,
    )
    assert not retry_module.is_retryable_startup_import_deadlock(
        tmp_path,
        returncode=0,
        elapsed_seconds=0.5,
        log_text=log,
    )
    assert not retry_module.is_retryable_startup_import_deadlock(
        tmp_path,
        returncode=1,
        elapsed_seconds=30,
        log_text=log,
    )
    assert not retry_module.is_retryable_startup_import_deadlock(
        tmp_path,
        returncode=1,
        elapsed_seconds=0.5,
        log_text="Error: expect(locator).toBeVisible failed",
    )

    (tmp_path / "status.txt").write_text("running")
    assert not retry_module.is_retryable_startup_import_deadlock(
        tmp_path,
        returncode=1,
        elapsed_seconds=0.5,
        log_text=log,
    )


def test_test_cli_subprocess_retries_once_and_succeeds(monkeypatch, tmp_path):
    attempts = []

    class _FakeProcess:
        def __init__(self, *args, **kwargs):
            self.pid = 10000 + len(attempts)
            self.returncode = None
            self.index = len(attempts)
            attempts.append(self)
            stdout = kwargs["stdout"]
            if self.index == 0:
                stdout.write(
                    "Traceback (most recent call last):\n"
                    "OSError: [Errno 35] Resource deadlock avoided: "
                    "'/app/orchestrator/ai/prompt_registry.py'\n"
                )
            else:
                stdout.write("runner started successfully\n")

        def wait(self, timeout):
            self.returncode = 1 if self.index == 0 else 0
            return self.returncode

    monkeypatch.setattr(retry_module.subprocess, "Popen", _FakeProcess)
    monkeypatch.setattr(retry_module, "startup_import_deadlock_retries", lambda: 1)
    monkeypatch.setattr(retry_module.time, "sleep", lambda _seconds: None)

    events = []
    active = {}
    returncode = retry_module.run_test_cli_subprocess_with_retry(
        cmd=["python", "orchestrator/cli.py"],
        cwd=tmp_path,
        env={},
        run_id="run-retry",
        run_dir_path=tmp_path,
        spec_name="spec.md",
        batch_id=None,
        append_workflow_log=lambda message, **payload: events.append((message, payload)),
        register_process=lambda run_id, process: active.setdefault(run_id, process),
        unregister_process=lambda run_id: active.pop(run_id, None),
        record_startup_import_failure=lambda *args, **kwargs: None,
        timeout_seconds=10,
    )

    assert returncode == 0
    assert len(attempts) == 2
    log = (tmp_path / "execution.log").read_text()
    assert "CLI attempt 1/2" in log
    assert "CLI attempt 2/2" in log
    assert "retrying CLI" in log
    assert any("retrying CLI" in message for message, _payload in events)


def test_test_cli_subprocess_does_not_retry_normal_failure(monkeypatch, tmp_path):
    attempts = []

    class _FakeProcess:
        def __init__(self, *args, **kwargs):
            self.pid = 11000 + len(attempts)
            self.returncode = None
            attempts.append(self)
            kwargs["stdout"].write("Error: expect(locator).toBeVisible failed\n")

        def wait(self, timeout):
            self.returncode = 1
            return self.returncode

    monkeypatch.setattr(retry_module.subprocess, "Popen", _FakeProcess)
    monkeypatch.setattr(retry_module, "startup_import_deadlock_retries", lambda: 1)

    active = {}
    returncode = retry_module.run_test_cli_subprocess_with_retry(
        cmd=["python", "orchestrator/cli.py"],
        cwd=tmp_path,
        env={},
        run_id="run-no-retry",
        run_dir_path=tmp_path,
        spec_name="spec.md",
        batch_id=None,
        append_workflow_log=lambda *_args, **_kwargs: None,
        register_process=lambda run_id, process: active.setdefault(run_id, process),
        unregister_process=lambda run_id: active.pop(run_id, None),
        record_startup_import_failure=lambda *args, **kwargs: None,
        timeout_seconds=10,
    )

    assert returncode == 1
    assert len(attempts) == 1
