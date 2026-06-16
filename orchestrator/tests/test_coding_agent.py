import subprocess

import pytest

from orchestrator.services.coding_agent import (
    apply_patch_to_repo,
    build_coding_tool_permission_guard,
    extract_unified_diff,
    is_safe_bash_command,
    validate_patch_for_repo,
    write_coding_artifacts,
)


VALID_PATCH = """diff --git a/example.txt b/example.txt
--- a/example.txt
+++ b/example.txt
@@ -1 +1 @@
-old
+new
"""


def test_extract_unified_diff_from_fenced_output():
    output = f"""## Proposed Patch
```diff
{VALID_PATCH}```
"""

    assert extract_unified_diff(output).startswith("diff --git a/example.txt b/example.txt")


def test_patch_validation_rejects_secret_paths(tmp_path):
    patch = """diff --git a/.env b/.env
--- a/.env
+++ b/.env
@@ -1 +1 @@
-A=1
+A=2
"""

    with pytest.raises(ValueError, match="protected secret path"):
        validate_patch_for_repo(patch, tmp_path)


def test_patch_validation_rejects_out_of_repo_paths(tmp_path):
    patch = """diff --git a/../outside.txt b/../outside.txt
--- a/../outside.txt
+++ b/../outside.txt
@@ -1 +1 @@
-old
+new
"""

    with pytest.raises(ValueError, match="escapes repository"):
        validate_patch_for_repo(patch, tmp_path)


@pytest.mark.asyncio
async def test_coding_permission_guard_blocks_writes_and_unsafe_bash():
    guard = build_coding_tool_permission_guard()

    denied_write = await guard("Write", {"file_path": "app.py"}, None)
    assert denied_write is False or getattr(denied_write, "behavior", None) == "deny"

    denied_bash = await guard("Bash", {"command": "python -c \"open('x', 'w').write('bad')\""}, None)
    assert denied_bash is False or getattr(denied_bash, "behavior", None) == "deny"

    denied_read = await guard("Read", {"file_path": ".env"}, None)
    assert denied_read is False or getattr(denied_read, "behavior", None) == "deny"

    allowed = await guard("Bash", {"command": "pytest orchestrator/tests/test_coding_agent.py"}, None)
    assert allowed is True or getattr(allowed, "behavior", None) == "allow"


def test_safe_bash_policy_allows_tests_and_rejects_writes():
    assert is_safe_bash_command("npm test -- --runInBand")
    assert is_safe_bash_command("python -m pytest orchestrator/tests")
    assert not is_safe_bash_command("pytest tests > result.txt")


def test_write_coding_artifacts_creates_patch_summary_and_review(tmp_path):
    info = write_coding_artifacts(
        tmp_path,
        f"""## Summary
Changed example.

## Tests
pytest

## Review
Looks contained.

## Proposed Patch
```diff
{VALID_PATCH}```
""",
    )

    assert (tmp_path / "summary.md").read_text().strip() == "Changed example."
    assert (tmp_path / "review.md").read_text().strip() == "Looks contained."
    assert (tmp_path / "proposed.patch").exists()
    assert info["affected_files"] == ["example.txt"]


def test_apply_patch_uses_git_apply_after_validation(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("orchestrator.services.coding_agent.subprocess.run", fake_run)

    result = apply_patch_to_repo(VALID_PATCH, tmp_path)

    assert result["affected_files"] == ["example.txt"]
    assert calls[0][0][:3] == ["git", "apply", "--check"]
    assert calls[1][0][:2] == ["git", "apply"]
