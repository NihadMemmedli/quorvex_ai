import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.utils.agent_runner import AgentResult
from orchestrator.workflows.native_healer import NativeHealer, truncate_middle


@pytest.mark.asyncio
async def test_native_healer_uses_agent_runner_with_tool_deep(monkeypatch):
    captured = {}

    class FakeResult:
        output = "healed"
        messages_received = 2
        tool_calls = ["test_run"]
        duration_seconds = 0.2
        timed_out = False
        success = True
        error = None

    class FakeRunner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def run(self, prompt):
            captured["prompt"] = prompt
            return FakeResult()

    monkeypatch.setattr("orchestrator.workflows.native_healer.AgentRunner", FakeRunner)

    healer = NativeHealer(
        on_tool_use=lambda *_args: None,
        on_progress=lambda *_args: None,
        on_task_enqueued=lambda *_args: None,
        owner_type="test_run",
        owner_id="run-1",
        owner_label="Run 1",
        model_tier="tool_deep",
    )

    output = await healer._query_healer_agent("fix this", timeout_seconds=123)

    assert output == "healed"
    assert healer.last_tool_calls == [{"name": "test_run"}]
    assert captured["timeout_seconds"] == 123
    assert captured["model_tier"] == "tool_deep"
    assert captured["owner_type"] == "test_run"
    assert captured["owner_id"] == "run-1"
    assert captured["memory_agent_type"] == "NativeHealer"
    assert captured["inject_memory"] is False
    assert captured["preserve_browser_on_failure"] is True
    assert "test_run" in ",".join(captured["allowed_tools"])
    assert "test_debug" in ",".join(captured["allowed_tools"])
    assert "browser_close" not in ",".join(captured["allowed_tools"])


@pytest.mark.asyncio
async def test_healer_format_retry_uses_clean_artifact_turn_without_browser_tools(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    monkeypatch.setenv("HEALER_SCHEMA_MAX_ATTEMPTS", "2")
    captured: list[dict] = []
    test_file = tmp_path / "broken.spec.ts"
    original = (
        "import { test, expect } from '@playwright/test';\n"
        "test('broken', async ({ page }) => {\n"
        "  await expect(page.locator('body')).toBeVisible();\n"
        "});\n"
    )
    fixed = original.replace("broken", "fixed")
    test_file.write_text(original)

    class FakeRunner:
        def __init__(self, **kwargs):
            captured.append(kwargs)

        async def run(self, prompt):
            if len(captured) == 1:
                return AgentResult(
                    success=True,
                    output="strategy: unclear",
                    session_id="heal-session-1",
                )
            return AgentResult(
                success=True,
                output=f"```typescript\n{fixed}```",
                session_id="heal-session-1",
            )

    monkeypatch.setattr("orchestrator.workflows.native_healer.AgentRunner", FakeRunner)
    healer = NativeHealer()

    healed = await healer.heal_test(str(test_file), error_log="Timeout")

    assert healed == fixed.rstrip() + "\n"
    assert test_file.read_text() == fixed.rstrip() + "\n"
    assert len(captured) == 2
    retry_kwargs = captured[1]
    assert retry_kwargs["allowed_tools"] == []
    assert retry_kwargs["tools"] == []
    assert retry_kwargs["requires_live_browser"] is False
    assert retry_kwargs["force_direct_execution"] is True
    assert retry_kwargs["resume_session_id"] is None
    assert retry_kwargs["continue_conversation"] is False


def test_truncate_middle_keeps_head_and_tail():
    text = "HEAD-MARKER " + ("x" * 20000) + " TAIL-MARKER"
    truncated = truncate_middle(text, head=4500, tail=4500)

    assert len(truncated) < len(text)
    assert truncated.startswith("HEAD-MARKER")
    assert truncated.endswith("TAIL-MARKER")
    assert "[truncated" in truncated


def test_truncate_middle_leaves_short_text_untouched():
    assert truncate_middle("short error", head=4500, tail=4500) == "short error"


def test_healer_prompt_includes_attempt_context_and_number(monkeypatch):
    monkeypatch.delenv("MEMORY_PROJECT_ID", raising=False)
    monkeypatch.delenv("PROJECT_ID", raising=False)

    healer = NativeHealer()
    long_error = "FIRST-SECTION " + ("x" * 20000) + " STDOUT-TAIL"
    prompt = healer._build_healer_prompt(
        test_file="tests/generated/foo.spec.ts",
        test_content="test('foo', async ({ page }) => {});",
        error_log=long_error,
        attempt_context="Attempt 1: changed the test file (+3 -1); still failed [selector].",
        attempt_number=2,
    )

    assert "This is healing attempt 2 of 3." in prompt
    assert "## Prior Healing Attempts (do not repeat failed fixes)" in prompt
    assert "Attempt 1: changed the test file" in prompt
    # Head+tail truncation must preserve both ends of the structured failure context
    assert "FIRST-SECTION" in prompt
    assert "STDOUT-TAIL" in prompt


def test_healer_prompt_omits_attempt_section_on_first_attempt(monkeypatch):
    monkeypatch.delenv("MEMORY_PROJECT_ID", raising=False)
    monkeypatch.delenv("PROJECT_ID", raising=False)

    healer = NativeHealer()
    prompt = healer._build_healer_prompt(
        test_file="tests/generated/foo.spec.ts",
        test_content="test('foo', async ({ page }) => {});",
        error_log="boom",
        attempt_context=None,
        attempt_number=1,
    )

    assert "This is healing attempt 1 of 3." in prompt
    assert "## Prior Healing Attempts" not in prompt


def test_healer_prompt_includes_failed_test_metadata(monkeypatch):
    monkeypatch.delenv("MEMORY_PROJECT_ID", raising=False)
    monkeypatch.delenv("PROJECT_ID", raising=False)

    healer = NativeHealer()
    prompt = healer._build_healer_prompt(
        test_file="tests/generated/foo.spec.ts",
        test_content="test('foo', async ({ page }) => {});",
        error_log="boom",
        browser="chromium",
        failure_metadata={
            "title": "can submit form",
            "file": "tests/generated/foo.spec.ts",
            "project": "chromium",
            "retry": 1,
            "primary_error": "Timeout waiting for locator",
        },
    )

    assert "## Failed Test Target" in prompt
    assert "Browser/project: `chromium`" in prompt
    assert "Title: `can submit form`" in prompt
    assert "call `test_debug` scoped to this file" in prompt
    assert "Only after `test_debug` has paused" in prompt
    assert "`test_run` for final pass/fail confirmation" in prompt
    assert "Do not call `browser_close`" in prompt


def test_healer_prompt_uses_failed_code_frame_by_default(monkeypatch):
    monkeypatch.delenv("MEMORY_PROJECT_ID", raising=False)
    monkeypatch.delenv("PROJECT_ID", raising=False)
    monkeypatch.delenv("HEALER_FULL_FILE_CONTEXT", raising=False)
    healer = NativeHealer()
    content = "\n".join(f"line {idx}" for idx in range(1, 120))

    prompt = healer._build_healer_prompt(
        test_file="/tmp/test.spec.ts",
        test_content=content,
        error_log="/tmp/test.spec.ts:80:12 Error: failed",
    )

    assert "Compact healer context" in prompt
    assert "80: line 80" in prompt
    assert not re.search(r"(?m)^1: line 1$", prompt)

    monkeypatch.setenv("HEALER_FULL_FILE_CONTEXT", "1")
    full_prompt = healer._build_healer_prompt(
        test_file="/tmp/test.spec.ts",
        test_content=content,
        error_log="/tmp/test.spec.ts:80:12 Error: failed",
    )
    assert "Compact healer context" not in full_prompt
    assert "line 1" in full_prompt
