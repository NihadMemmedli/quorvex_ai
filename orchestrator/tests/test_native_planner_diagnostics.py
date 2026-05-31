import sys
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.utils.agent_runner import AgentResult, AgentRunner, ToolCall
from orchestrator.workflows.native_planner import NativePlanner, SpecGenerationError


VALID_PLAN = """# Test Plan: Checkout

### TC-001: Complete checkout
**Description:** User completes checkout.
**Preconditions:** User has items in the cart.
**Steps:**
1. Navigate to the checkout page.
2. Fill required shipping details.
3. Submit payment.
**Expected Result:** The order confirmation appears.
"""

INVALID_PLAN_WITH_EVIDENCE = """# Test Plan: Checkout

### TC-001: Complete checkout
The checkout button was seen after cart review. The user can submit payment and see confirmation.
"""


def _planner(tmp_path: Path) -> NativePlanner:
    planner = object.__new__(NativePlanner)
    planner.project_id = "project"
    planner.on_tool_use = None
    planner.on_progress = None
    planner.on_task_enqueued = None
    planner.owner_type = None
    planner.owner_id = None
    planner.owner_label = None
    planner.model_tier = "tool_deep"
    planner.session_dir = tmp_path / "run"
    planner.cwd = planner.session_dir
    planner.specs_dir = tmp_path / "specs"
    planner.specs_dir.mkdir(parents=True)
    planner.session_dir.mkdir(parents=True)
    planner.memory_manager = SimpleNamespace(
        vector_store=SimpleNamespace(
            search_prd_context=lambda **_kwargs: [
                {"content": "Checkout requirements", "metadata": {"feature": "Checkout"}}
            ]
        )
    )
    return planner


def _patch_agent(monkeypatch: pytest.MonkeyPatch, planner: NativePlanner, result: AgentResult) -> None:
    async def fake_query(_prompt: str, target_url: str | None = None) -> AgentResult:
        return result

    monkeypatch.setattr(planner, "_query_planner_agent", fake_query)


def _patch_repair_agent(monkeypatch: pytest.MonkeyPatch, planner: NativePlanner, result: AgentResult) -> None:
    async def fake_repair(_prompt: str) -> AgentResult:
        return result

    monkeypatch.setattr(planner, "_query_repair_agent", fake_repair)


@pytest.mark.asyncio
async def test_empty_agent_result_raises_diagnostic_error(tmp_path, monkeypatch):
    planner = _planner(tmp_path)
    _patch_agent(
        monkeypatch,
        planner,
        AgentResult(success=True, output="", messages_received=0, text_blocks_received=0, tool_calls=[]),
    )

    with pytest.raises(SpecGenerationError) as exc_info:
        await planner.generate_spec_for_feature("Checkout", "prd-project")

    message = str(exc_info.value)
    assert "agent produced no output" in message
    assert "messages=0" in message
    assert "tool_calls=0" in message
    assert "planner_save_plan_observed=False" in message
    assert "expected_output_path=" in message
    assert exc_info.value.diagnostics["valid_saved_plan_observed"] is False


@pytest.mark.asyncio
async def test_timed_out_agent_result_surfaces_timeout(tmp_path, monkeypatch):
    planner = _planner(tmp_path)
    _patch_agent(
        monkeypatch,
        planner,
        AgentResult(success=False, output="", timed_out=True, messages_received=2, text_blocks_received=1),
    )

    with pytest.raises(SpecGenerationError) as exc_info:
        await planner.generate_spec_for_feature("Checkout", "prd-project")

    assert "timed out" in str(exc_info.value)
    assert exc_info.value.diagnostics["timed_out"] is True
    assert "longer planner timeout" in exc_info.value.diagnostics["next_action"]


@pytest.mark.asyncio
async def test_errored_agent_result_surfaces_agent_error(tmp_path, monkeypatch):
    planner = _planner(tmp_path)
    _patch_agent(
        monkeypatch,
        planner,
        AgentResult(success=False, output="", error="queue unavailable", messages_received=1),
    )

    with pytest.raises(SpecGenerationError) as exc_info:
        await planner.generate_spec_for_feature("Checkout", "prd-project")

    assert "queue unavailable" in str(exc_info.value)
    assert exc_info.value.diagnostics["agent_error"] == "queue unavailable"
    assert "SDK/queue" in exc_info.value.diagnostics["next_action"]


@pytest.mark.asyncio
async def test_valid_saved_plan_recovered_from_expected_output_path(tmp_path, monkeypatch):
    planner = _planner(tmp_path)
    expected = planner.specs_dir / "prd-project" / "checkout.md"
    expected.parent.mkdir(parents=True)
    expected.write_text(VALID_PLAN)
    _patch_agent(monkeypatch, planner, AgentResult(success=True, output=""))

    path = await planner.generate_spec_for_feature("Checkout", "prd-project")

    assert path == expected
    assert path.read_text().strip() == VALID_PLAN.strip()


@pytest.mark.asyncio
async def test_valid_saved_plan_recovered_from_session_artifact(tmp_path, monkeypatch):
    planner = _planner(tmp_path)
    artifact = planner.session_dir / "nested" / "planner-output.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(VALID_PLAN)
    _patch_agent(monkeypatch, planner, AgentResult(success=True, output=""))

    path = await planner.generate_spec_for_feature("Checkout", "prd-project")

    assert path == planner.specs_dir / "prd-project" / "checkout.md"
    assert path.read_text() == VALID_PLAN


@pytest.mark.asyncio
async def test_invalid_saved_plan_without_test_case_structure_fails(tmp_path, monkeypatch):
    planner = _planner(tmp_path)
    expected = planner.specs_dir / "prd-project" / "checkout.md"
    expected.parent.mkdir(parents=True)
    expected.write_text("# Checkout Summary\n\nI created a plan in the workspace.")
    _patch_agent(monkeypatch, planner, AgentResult(success=True, output=""))
    _patch_repair_agent(monkeypatch, planner, AgentResult(success=True, output="# Checkout Summary\n\nStill invalid."))

    with pytest.raises(SpecGenerationError) as exc_info:
        await planner.generate_spec_for_feature("Checkout", "prd-project")

    assert "repair did not produce a valid test plan" in str(exc_info.value)


@pytest.mark.asyncio
async def test_invalid_saved_markdown_with_save_plan_evidence_invokes_repair(tmp_path, monkeypatch):
    planner = _planner(tmp_path)
    expected = planner.specs_dir / "prd-project" / "checkout.md"
    expected.parent.mkdir(parents=True)
    expected.write_text(INVALID_PLAN_WITH_EVIDENCE)
    _patch_agent(
        monkeypatch,
        planner,
        AgentResult(
            success=True,
            output="I created checkout coverage.",
            tool_calls=[
                ToolCall(
                    name="mcp__playwright-test__planner_save_plan",
                    timestamp=datetime.now(),
                    input={"content": INVALID_PLAN_WITH_EVIDENCE},
                )
            ],
        ),
    )
    _patch_repair_agent(monkeypatch, planner, AgentResult(success=True, output=VALID_PLAN))

    path = await planner.generate_spec_for_feature("Checkout", "prd-project")

    assert path == expected
    assert path.read_text().strip() == VALID_PLAN.strip()
    attempt = json.loads((planner.session_dir / "planner_repair_attempt.json").read_text())
    assert attempt["attempted"] is True
    assert attempt["accepted"] is True
    assert attempt["rejected_artifacts"][0]["path"] == str(expected)
    assert attempt["rejected_save_plan_payloads"][0]["length"] == len(INVALID_PLAN_WITH_EVIDENCE)


@pytest.mark.asyncio
async def test_repair_not_attempted_when_no_useful_evidence_exists(tmp_path, monkeypatch):
    planner = _planner(tmp_path)
    _patch_agent(
        monkeypatch,
        planner,
        AgentResult(success=True, output="", messages_received=0, text_blocks_received=0, tool_calls=[]),
    )

    async def fail_if_called(_prompt: str) -> AgentResult:
        raise AssertionError("repair should not be attempted without evidence")

    monkeypatch.setattr(planner, "_query_repair_agent", fail_if_called)

    with pytest.raises(SpecGenerationError):
        await planner.generate_spec_for_feature("Checkout", "prd-project")

    attempt = json.loads((planner.session_dir / "planner_repair_attempt.json").read_text())
    assert attempt["attempted"] is False
    assert attempt["accepted"] is False
    assert attempt["useful_evidence"] is False


@pytest.mark.asyncio
async def test_repair_failure_raises_with_diagnostics_and_artifact_metadata(tmp_path, monkeypatch):
    planner = _planner(tmp_path)
    expected = planner.specs_dir / "prd-project" / "checkout.md"
    expected.parent.mkdir(parents=True)
    expected.write_text(INVALID_PLAN_WITH_EVIDENCE)
    _patch_agent(
        monkeypatch,
        planner,
        AgentResult(
            success=True,
            output="I found checkout evidence.",
            tool_calls=[
                ToolCall(
                    name="mcp__playwright-test__planner_save_plan",
                    timestamp=datetime.now(),
                    input={"content": INVALID_PLAN_WITH_EVIDENCE},
                )
            ],
        ),
    )
    _patch_repair_agent(
        monkeypatch,
        planner,
        AgentResult(success=True, output="# Test Plan: Checkout\n\n### TC-001: Still missing fields\n"),
    )

    with pytest.raises(SpecGenerationError) as exc_info:
        await planner.generate_spec_for_feature("Checkout", "prd-project")

    assert "repair did not produce a valid test plan" in str(exc_info.value)
    assert exc_info.value.diagnostics["planner_repair_attempted"] is True
    assert exc_info.value.diagnostics["planner_repair_accepted"] is False
    assert exc_info.value.diagnostics["rejected_artifact_count"] == 1
    assert exc_info.value.diagnostics["rejected_save_plan_payload_count"] == 1
    assert exc_info.value.diagnostics["planner_repair_artifact_path"].endswith("planner_repair_attempt.json")
    attempt = json.loads((planner.session_dir / "planner_repair_attempt.json").read_text())
    assert attempt["attempted"] is True
    assert attempt["accepted"] is False
    assert "missing required fields" in attempt["validation_failure_reason"]


@pytest.mark.asyncio
async def test_flow_context_generation_uses_same_repair_recovery(tmp_path, monkeypatch):
    planner = _planner(tmp_path)
    output_dir = planner.specs_dir / "flows"
    _patch_agent(
        monkeypatch,
        planner,
        AgentResult(
            success=True,
            output="Saved a rough plan.",
            tool_calls=[
                ToolCall(
                    name="mcp__playwright-test__planner_setup_page",
                    timestamp=datetime.now(),
                    input={"seedFile": "tests/seed.spec.ts"},
                ),
                ToolCall(
                    name="mcp__playwright-test__browser_navigate",
                    timestamp=datetime.now(),
                    input={"url": "https://example.test/checkout"},
                ),
                ToolCall(
                    name="mcp__playwright-test__browser_snapshot",
                    timestamp=datetime.now(),
                    input={},
                ),
                ToolCall(
                    name="mcp__playwright-test__planner_save_plan",
                    timestamp=datetime.now(),
                    input={"content": INVALID_PLAN_WITH_EVIDENCE},
                ),
            ],
        ),
    )
    _patch_repair_agent(monkeypatch, planner, AgentResult(success=True, output=VALID_PLAN))

    path = await planner.generate_spec_from_flow_context(
        "Checkout",
        "Flow context",
        "https://example.test/checkout",
        output_dir=output_dir,
    )

    assert path == output_dir / "checkout.md"
    assert path.read_text().strip() == VALID_PLAN.strip()


def test_extract_plan_content_ignores_unstructured_save_plan_tool_call():
    result = AgentResult(
        success=True,
        output="",
        tool_calls=[
            ToolCall(
                name="mcp__playwright-test__planner_save_plan",
                timestamp=datetime.now(),
                input={"content": "# Checkout Summary\n\nI created the plan."},
            )
        ],
    )

    assert NativePlanner._extract_plan_content(result) is None


def test_extract_plan_content_requires_required_schema_fields():
    result = AgentResult(
        success=True,
        output="",
        tool_calls=[
            ToolCall(
                name="mcp__playwright-test__planner_save_plan",
                timestamp=datetime.now(),
                input={"content": INVALID_PLAN_WITH_EVIDENCE},
            )
        ],
    )

    assert NativePlanner._extract_plan_content(result) is None


def test_repair_evidence_preview_redacts_sensitive_text(tmp_path):
    planner = _planner(tmp_path)
    expected = planner.specs_dir / "prd-project" / "checkout.md"
    expected.parent.mkdir(parents=True)
    expected.write_text("# Test Plan: Checkout\n\npassword: do-not-store\nAuthorization: Bearer abc123")

    evidence = planner._collect_repair_evidence(AgentResult(success=True, output="token=raw-output-secret"), expected)

    assert "do-not-store" not in evidence["rejected_artifacts"][0]["preview"]
    assert "abc123" not in evidence["rejected_artifacts"][0]["preview"]
    assert "raw-output-secret" not in evidence["raw_output"]["preview"]
    assert "[REDACTED]" in evidence["rejected_artifacts"][0]["preview"]


def test_tool_call_debug_output_includes_redacted_truncated_input_metadata(tmp_path):
    runner = AgentRunner(session_dir=tmp_path)
    long_content = "# Test Plan: Checkout\n" + ("A" * 1500)
    runner._save_debug_output(
        "raw output",
        [
            ToolCall(
                name="mcp__playwright-test__planner_save_plan",
                timestamp=datetime.now(),
                duration_ms=12,
                success=True,
                input={
                    "content": long_content,
                    "password": "super-secret",
                    "nested": {"api_key": "abc123"},
                },
            )
        ],
        messages_received=1,
    )

    tool_calls = json.loads((tmp_path / "tool_calls.json").read_text())
    first = tool_calls[0]
    assert first["name"] == "mcp__playwright-test__planner_save_plan"
    assert first["success"] is True
    assert first["input_content_length"] == len(long_content)
    assert len(first["content_hash"]) == 64
    assert first["input_preview"]["password"] == "[REDACTED]"
    assert first["input_preview"]["nested"]["api_key"] == "[REDACTED]"
    assert "truncated" in first["input_preview"]["content"]


def test_live_plan_rejected_when_saved_before_target_navigation():
    result = AgentResult(
        success=True,
        output=VALID_PLAN,
        tool_calls=[
            ToolCall(
                name="mcp__playwright-test__planner_setup_page",
                timestamp=datetime.now(),
                input={"seedFile": "tests/seed.spec.ts"},
            ),
            ToolCall(
                name="mcp__playwright-test__planner_save_plan",
                timestamp=datetime.now(),
                input={"content": VALID_PLAN},
            ),
            ToolCall(
                name="mcp__playwright-test__browser_navigate",
                timestamp=datetime.now(),
                input={"url": "https://example.test/checkout"},
            ),
        ],
    )

    with pytest.raises(SpecGenerationError) as exc_info:
        NativePlanner._validate_live_plan_tool_sequence(result, "https://example.test/checkout")

    assert "before navigating" in str(exc_info.value)
    assert exc_info.value.diagnostics["target_navigation_observed"] is False


def test_live_plan_accepted_after_setup_target_navigation_snapshot_and_save():
    result = AgentResult(
        success=True,
        output=VALID_PLAN,
        tool_calls=[
            ToolCall(
                name="mcp__playwright-test__planner_setup_page",
                timestamp=datetime.now(),
                input={"seedFile": "tests/seed.spec.ts"},
            ),
            ToolCall(
                name="mcp__playwright-test__browser_navigate",
                timestamp=datetime.now(),
                input={"url": "https://example.test/checkout/"},
            ),
            ToolCall(
                name="mcp__playwright-test__browser_snapshot",
                timestamp=datetime.now(),
                input={},
            ),
            ToolCall(
                name="mcp__playwright-test__planner_save_plan",
                timestamp=datetime.now(),
                input={"content": VALID_PLAN},
            ),
        ],
    )

    NativePlanner._validate_live_plan_tool_sequence(result, "https://example.test/checkout")
