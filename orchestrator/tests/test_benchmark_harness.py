from __future__ import annotations

import json
from pathlib import Path

from scripts.benchmark_pipeline import aggregate_rows, build_report, parse_run_artifacts


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_parse_run_artifacts_detects_first_pass_and_inferable_stage_success(tmp_path):
    spec = tmp_path / "specs" / "checkout.md"
    spec.parent.mkdir()
    spec.write_text("# Checkout\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "status.txt").write_text("passed", encoding="utf-8")
    _write_json(run_dir / "plan.json", {"testName": "Checkout"})
    _write_json(run_dir / "export.json", {"testFilePath": "tests/generated/checkout.spec.ts"})
    _write_json(
        run_dir / "agentic_summary.json",
        {
            "design": {"flake_risk": "low", "testability": "high"},
            "critic": {"risk_level": "low"},
            "stability": {"status": "stable"},
            "costs": {"total_usd": 0.3},
        },
    )
    (run_dir / "agent_costs.jsonl").write_text(
        json.dumps({"stage": "native_generator", "cost_usd": 0.25}) + "\n",
        encoding="utf-8",
    )

    row = parse_run_artifacts(
        spec,
        run_dir,
        returncode=0,
        wall_time_seconds=12.3456,
        spec_root=spec.parent,
    )

    assert row["spec"] == "checkout.md"
    assert row["passed"] is True
    assert row["planner_success"] is True
    assert row["generation_success"] is True
    assert row["first_pass"] is True
    assert row["heal_attempts"] == 0
    assert row["cost_usd"] == 0.3
    assert row["wall_time_seconds"] == 12.346
    assert row["agentic"]["stability_status"] == "stable"


def test_parse_run_artifacts_detects_heal_rescue_from_attempt_history(tmp_path):
    spec = tmp_path / "login.md"
    spec.write_text("# Login\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "status.txt").write_text("passed", encoding="utf-8")
    _write_json(run_dir / "export.json", {"code": "test('login', async () => {})"})
    _write_json(
        run_dir / "validation.json",
        {"status": "success", "mode": "native_healer", "iterations": 2},
    )
    _write_json(
        run_dir / "healing_attempts.json",
        {
            "test_file": "tests/generated/login.spec.ts",
            "attempts": [
                {"attempt": 1, "passed_after": False, "error_category": "selector"},
                {"attempt": 2, "passed_after": True, "error_category": "passed"},
            ],
        },
    )

    row = parse_run_artifacts(spec, run_dir)

    assert row["passed"] is True
    assert row["first_pass"] is False
    assert row["healing_started"] is True
    assert row["heal_rescued"] is True
    assert row["heal_attempts"] == 2
    assert row["validation_status"] == "success"


def test_parse_run_artifacts_marks_generation_failure_from_pipeline_error(tmp_path):
    spec = tmp_path / "broken.md"
    spec.write_text("# Broken\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "status.txt").write_text("error", encoding="utf-8")
    _write_json(
        run_dir / "pipeline_error.json",
        {"stage": "generation", "error": "Native generator failed to create test file"},
    )

    row = parse_run_artifacts(spec, run_dir, returncode=1)

    assert row["passed"] is False
    assert row["generation_success"] is False
    assert row["pipeline_error_stage"] == "generation"
    assert row["artifacts"]["status.txt"] is True
    assert row["artifacts"]["validation.json"] is False


def test_aggregate_rows_computes_requested_rates_cost_and_wall_time():
    rows = [
        {
            "passed": True,
            "planner_success": True,
            "generation_success": True,
            "first_pass": True,
            "healing_started": False,
            "heal_rescued": False,
            "heal_attempts": 0,
            "cost_usd": 0.2,
            "wall_time_seconds": 10.0,
        },
        {
            "passed": True,
            "planner_success": True,
            "generation_success": True,
            "first_pass": False,
            "healing_started": True,
            "heal_rescued": True,
            "heal_attempts": 2,
            "cost_usd": 0.4,
            "wall_time_seconds": 20.0,
        },
        {
            "passed": False,
            "planner_success": None,
            "generation_success": False,
            "first_pass": False,
            "healing_started": True,
            "heal_rescued": False,
            "heal_attempts": 3,
            "cost_usd": None,
            "wall_time_seconds": 30.0,
        },
    ]

    aggregates = aggregate_rows(rows)

    assert aggregates["total_specs"] == 3
    assert aggregates["pass_rate"] == 0.6667
    assert aggregates["planner_success_rate"] == 1.0
    assert aggregates["generation_success_rate"] == 0.6667
    assert aggregates["first_pass_rate"] == 0.3333
    assert aggregates["heal_rescue_rate"] == 0.5
    assert aggregates["mean_heal_attempts"] == 1.6667
    assert aggregates["total_cost_usd"] == 0.6
    assert aggregates["mean_cost_usd"] == 0.3
    assert aggregates["total_wall_time_seconds"] == 60.0
    assert aggregates["mean_wall_time_seconds"] == 20.0


def test_build_report_adds_compare_deltas(tmp_path):
    old_report = tmp_path / "old.json"
    _write_json(
        old_report,
        {
            "label": "v3",
            "aggregates": {
                "pass_rate": 0.5,
                "total_cost_usd": 1.0,
                "total_specs": 2,
            },
        },
    )
    out = tmp_path / "new.json"

    report = build_report(
        specs_dir=tmp_path / "specs",
        target_url="http://localhost:3000",
        out_path=out,
        label="v4",
        rows=[
            {
                "passed": True,
                "planner_success": True,
                "generation_success": True,
                "first_pass": True,
                "healing_started": False,
                "heal_rescued": False,
                "heal_attempts": 0,
                "cost_usd": 0.25,
                "wall_time_seconds": 5.0,
            }
        ],
        compare_path=old_report,
    )

    assert out.exists()
    assert report["compare"]["baseline_label"] == "v3"
    assert report["compare"]["aggregate_deltas"]["pass_rate"] == 0.5
    assert report["compare"]["aggregate_deltas"]["total_cost_usd"] == -0.75
    assert report["compare"]["aggregate_deltas"]["total_specs"] == -1.0
