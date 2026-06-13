import json
from pathlib import Path

from orchestrator.services.handoff_manifest import (
    init_manifest,
    load_manifest,
    record_artifact,
    record_consumption,
    record_stage,
    validate_artifact,
)


def test_manifest_records_stage_artifact_and_consumption(tmp_path: Path):
    manifest_path = init_manifest(tmp_path, pipeline_type="browser")
    artifact = tmp_path / "plan.md"
    artifact.write_text("# Test Plan: Checkout\n")

    record_stage(manifest_path, "planner", status="ready", metadata={"selector_count": 2})
    recorded = record_artifact(
        manifest_path,
        "planner_plan",
        artifact,
        kind="planner_markdown_plan",
        producer_stage="planner",
        consumers=["generator"],
    )
    record_consumption(manifest_path, "generator", "planner_plan", status="used")

    data = load_manifest(tmp_path)

    assert data["schema_version"] == "handoff_manifest.v1"
    assert data["stages"]["planner"]["status"] == "ready"
    assert data["stages"]["planner"]["metadata"]["selector_count"] == 2
    assert len(recorded["hash"]) == 64
    assert data["stages"]["generator"]["artifacts_consumed"]["planner_plan"]["status"] == "used"
    assert "generator" in data["artifacts"]["planner_plan"]["consumers"]


def test_manifest_validation_reports_missing_invalid_stale_and_valid(tmp_path: Path):
    manifest_path = init_manifest(tmp_path)
    missing = tmp_path / "missing.md"
    invalid = tmp_path / "invalid.md"
    invalid.write_text("not a plan")
    stale = tmp_path / "stale.md"
    stale.write_text("old")
    valid = tmp_path / "valid.md"
    valid.write_text("# Test Plan: Valid\n")

    record_artifact(
        manifest_path,
        "missing",
        missing,
        kind="markdown",
        producer_stage="planner",
        required=True,
    )
    record_artifact(
        manifest_path,
        "invalid",
        invalid,
        kind="markdown",
        producer_stage="planner",
    )
    record_artifact(
        manifest_path,
        "stale",
        stale,
        kind="markdown",
        producer_stage="planner",
    )
    record_artifact(
        manifest_path,
        "valid",
        valid,
        kind="markdown",
        producer_stage="planner",
    )
    stale.write_text("new")

    validator = lambda path: ("# Test Plan:" in path.read_text(), "missing test plan header")

    assert validate_artifact(manifest_path, "missing")["validation_status"] == "missing"
    invalid_result = validate_artifact(manifest_path, "invalid", validator=validator)
    assert invalid_result["validation_status"] == "invalid"
    assert invalid_result["failure_reason"] == "missing test plan header"
    assert validate_artifact(manifest_path, "stale")["validation_status"] == "stale"
    assert validate_artifact(manifest_path, "valid", validator=validator)["validation_status"] == "valid"

    data = json.loads(manifest_path.read_text())
    assert [event["validation_status"] for event in data["events"][-4:]] == [
        "missing",
        "invalid",
        "stale",
        "valid",
    ]


def test_manifest_optional_missing_artifact_is_explicit(tmp_path: Path):
    manifest_path = init_manifest(tmp_path)
    record_artifact(
        manifest_path,
        "planner_draft_script",
        tmp_path / "plan.draft.spec.ts",
        kind="planner_draft_playwright",
        producer_stage="planner",
        required=False,
        validation_status="optional_missing",
    )

    result = validate_artifact(manifest_path, "planner_draft_script")

    assert result["validation_status"] == "optional_missing"
