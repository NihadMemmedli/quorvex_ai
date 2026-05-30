import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.ai.context import SOURCE_FALLBACK, SOURCE_OBSERVED, ContextBundle
from orchestrator.ai.prompt_registry import attach_delivered_prompt_metadata, attach_prompt_metadata, build_prompt_metadata
from orchestrator.ai.validation import assess_exploration_quality, is_valid_flow, should_gate_exploration, validate_exploration_result


def test_prompt_metadata_is_stable_and_attached():
    prompt = "Generate a strict JSON object."
    metadata = build_prompt_metadata(
        prompt_id="unit.prompt",
        version="1",
        stage="unit",
        schema_name="unit_schema.v1",
        rendered_prompt=prompt,
    )

    wrapped = attach_prompt_metadata(prompt, metadata)

    assert metadata.prompt_id == "unit.prompt"
    assert len(metadata.rendered_prompt_hash) == 64
    assert '<prompt_metadata id="unit.prompt"' in wrapped
    assert prompt in wrapped


def test_delivered_prompt_metadata_hashes_augmented_prompt():
    prompt = "memory context\n---\nactual task"

    wrapped = attach_delivered_prompt_metadata(prompt, memory_injected=True)

    assert '<delivered_prompt_metadata hash="' in wrapped
    assert 'memory_injected="true"' in wrapped
    assert prompt in wrapped


def test_context_bundle_labels_source_type_and_confidence():
    bundle = ContextBundle(stage="requirements")
    bundle.add("summary", {"flows": []}, source_type=SOURCE_FALLBACK, confidence=1.5)

    data = bundle.to_dict()

    assert data["items"][0]["source_type"] == SOURCE_FALLBACK
    assert data["items"][0]["confidence"] == 1.0


@dataclass
class TransitionStub:
    action_type: str
    before_url: str = ""
    after_url: str = ""


@dataclass
class FlowStub:
    name: str
    start_url: str = ""
    end_url: str = ""
    category: str = ""
    steps: list[dict | str] | None = None


@dataclass
class IssueStub:
    issue_type: str
    description: str


@dataclass
class ResultStub:
    status: str = "completed"
    transitions: list[TransitionStub] = field(default_factory=list)
    flows: list[FlowStub] = field(default_factory=list)
    issues: list[IssueStub] = field(default_factory=list)
    api_endpoints: list[dict] = field(default_factory=list)
    pages_discovered: int = 0


def test_exploration_validation_reports_invalid_records():
    result = ResultStub(
        transitions=[TransitionStub(action_type="click", after_url="https://example.com"), TransitionStub(action_type="")],
        flows=[FlowStub(name="Browse", start_url="https://example.com"), FlowStub(name="No URLs")],
        issues=[IssueStub(issue_type="error_page", description="HTTP 500")],
    )

    summary = validate_exploration_result(result)

    assert summary["valid"] is False
    assert summary["valid_counts"]["transitions"] == 1
    assert summary["valid_counts"]["flows"] == 1
    assert {issue["record_type"] for issue in summary["invalid_records"]} == {"transition", "flow"}


def test_flow_validation_allows_nonstandard_categories():
    valid, reason = is_valid_flow(
        FlowStub(
            name="Search Within Entities",
            start_url="https://my.gov.az/en/entities",
            category="information-retrieval",
        )
    )

    assert valid is True
    assert reason is None


def test_flow_validation_still_rejects_structural_errors():
    valid, reason = is_valid_flow(FlowStub(name="Broken", start_url="https://example.com", steps="click login"))

    assert valid is False
    assert reason == "steps must be a list"


def test_quality_score_marks_fallback_as_degraded():
    result = ResultStub(
        transitions=[TransitionStub(action_type="navigate", after_url="https://example.com")],
        flows=[FlowStub(name="Homepage Browse", start_url="https://example.com")],
        pages_discovered=1,
    )

    quality = assess_exploration_quality(result, fallback_used=True, verified_tool_calls=0)

    assert quality["source_type"] == SOURCE_FALLBACK
    assert quality["fallback_used"] is True
    assert quality["quality_score"] < 50
    assert quality["degraded_mode"] is True


def test_quality_score_marks_verified_evidence_as_observed():
    result = ResultStub(
        transitions=[TransitionStub(action_type="click", before_url="https://example.com", after_url="https://example.com/a")],
        flows=[FlowStub(name="Browse A", start_url="https://example.com", end_url="https://example.com/a")],
        api_endpoints=[{"method": "GET", "url": "/api/a"}],
        pages_discovered=2,
    )

    quality = assess_exploration_quality(result, fallback_used=False, verified_tool_calls=10)

    assert quality["source_type"] == SOURCE_OBSERVED
    assert quality["quality_score"] >= 50
    assert quality["degraded_mode"] is False


def test_quality_gate_blocks_invalid_or_fallback_artifacts():
    gated, reason = should_gate_exploration(
        {"quality_score": 90, "source_type": SOURCE_OBSERVED},
        {"valid": False},
    )
    assert gated is True
    assert reason == "validation_failed"

    gated, reason = should_gate_exploration(
        {"quality_score": 90, "source_type": SOURCE_FALLBACK},
        {"valid": True},
    )
    assert gated is True
    assert reason == "fallback_source"


def test_quality_gate_allows_valid_observed_artifacts():
    gated, reason = should_gate_exploration(
        {"quality_score": 75, "source_type": SOURCE_OBSERVED},
        {"valid": True},
    )
    assert gated is False
    assert reason is None
