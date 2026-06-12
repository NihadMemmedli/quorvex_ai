#!/usr/bin/env python3
"""Opt-in benchmark harness for running spec suites through orchestrator/cli.py."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_NAMES = (
    "status.txt",
    "validation.json",
    "agentic_summary.json",
    "healing_attempts.json",
)
VALIDATION_FALLBACKS = (
    "validation.json",
    "hybrid_validation.json",
    "native_healer_validation.json",
    "ralph_validation.json",
)

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")
    return slug[:120] or "spec"


def discover_specs(specs_dir: Path) -> list[Path]:
    """Return benchmark markdown specs in deterministic order."""
    if not specs_dir.exists():
        raise FileNotFoundError(f"Specs directory not found: {specs_dir}")
    if not specs_dir.is_dir():
        raise NotADirectoryError(f"Specs path is not a directory: {specs_dir}")
    return sorted(path for path in specs_dir.rglob("*.md") if path.is_file())


def _materialize_target_spec(spec_path: Path, target_url: str, run_dir: Path) -> Path:
    """Create a run-local spec copy with the benchmark target URL made unambiguous."""
    input_dir = run_dir / "benchmark-input"
    input_dir.mkdir(parents=True, exist_ok=True)
    target_spec = input_dir / spec_path.name
    content = spec_path.read_text(encoding="utf-8")
    replaced = re.sub(r"https?://[^\s'\"`)>\]]+", target_url, content)
    if replaced == content:
        replaced = f"Navigate to {target_url}\n\n{content}"
    else:
        replaced = f"Navigate to {target_url}\n\n{replaced}"
    target_spec.write_text(replaced, encoding="utf-8")
    return target_spec


def _load_validation(run_dir: Path) -> tuple[dict[str, Any] | None, str | None]:
    for name in VALIDATION_FALLBACKS:
        payload = _read_json(run_dir / name)
        if isinstance(payload, dict):
            return payload, name
    return None, None


def _infer_cost_usd(run_dir: Path, agentic_summary: dict[str, Any] | None = None) -> float | None:
    """Read total cost from the native summary or its backing JSONL artifact."""
    if isinstance(agentic_summary, dict):
        total = (agentic_summary.get("costs") or {}).get("total_usd")
        if isinstance(total, (int, float)):
            return round(float(total), 6)

    total = 0.0
    found = False
    cost_log = run_dir / "agent_costs.jsonl"
    try:
        for line in cost_log.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or row.get("cost_usd") is None:
                continue
            total += float(row["cost_usd"])
            found = True
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return round(total, 6) if found else None


def _infer_planner_success(run_dir: Path, pipeline_error: dict[str, Any] | None) -> bool | None:
    stage = str((pipeline_error or {}).get("stage") or "").lower()
    if "plan" in stage:
        return False
    if (run_dir / "plan.json").exists() or (run_dir / "planner_repair_attempt.json").exists():
        return True
    return None


def _infer_generation_success(run_dir: Path, pipeline_error: dict[str, Any] | None) -> bool | None:
    stage = str((pipeline_error or {}).get("stage") or "").lower()
    if "generation" in stage or "generator" in stage:
        return False
    export = _read_json(run_dir / "export.json")
    if isinstance(export, dict) and (export.get("testFilePath") or export.get("code")):
        return True
    return None


def parse_run_artifacts(
    spec_path: Path,
    run_dir: Path,
    *,
    returncode: int | None = None,
    wall_time_seconds: float | None = None,
    spec_root: Path | None = None,
) -> dict[str, Any]:
    """Parse one run directory into a benchmark row."""
    status_text = _read_text(run_dir / "status.txt")
    if not status_text:
        if returncode == 0:
            status_text = "passed"
        elif returncode is not None:
            status_text = "error"
        else:
            status_text = "unknown"

    validation, validation_file = _load_validation(run_dir)
    agentic_summary = _read_json(run_dir / "agentic_summary.json")
    healing = _read_json(run_dir / "healing_attempts.json")
    pipeline_error = _read_json(run_dir / "pipeline_error.json")

    attempts = healing.get("attempts", []) if isinstance(healing, dict) else []
    attempts = attempts if isinstance(attempts, list) else []
    heal_attempts = len(attempts)
    validation_iterations = None
    validation_status = None
    if isinstance(validation, dict):
        validation_status = validation.get("status")
        raw_iterations = validation.get("iterations", validation.get("attempts"))
        if isinstance(raw_iterations, (int, float)):
            validation_iterations = int(raw_iterations)
            heal_attempts = max(heal_attempts, validation_iterations)

    passed = status_text == "passed" or validation_status == "success"
    healed = heal_attempts > 0
    first_pass = passed and not healed
    heal_rescued = passed and healed

    artifact_presence = {name: (run_dir / name).exists() for name in ARTIFACT_NAMES}
    relative_spec = str(spec_path)
    if spec_root:
        try:
            relative_spec = str(spec_path.relative_to(spec_root))
        except ValueError:
            relative_spec = str(spec_path)

    row: dict[str, Any] = {
        "spec": relative_spec,
        "spec_path": str(spec_path),
        "run_dir": str(run_dir),
        "status": status_text,
        "passed": passed,
        "returncode": returncode,
        "wall_time_seconds": round(wall_time_seconds, 3) if wall_time_seconds is not None else None,
        "planner_success": _infer_planner_success(run_dir, pipeline_error if isinstance(pipeline_error, dict) else None),
        "generation_success": _infer_generation_success(run_dir, pipeline_error if isinstance(pipeline_error, dict) else None),
        "first_pass": first_pass,
        "healing_started": healed,
        "heal_rescued": heal_rescued,
        "heal_attempts": heal_attempts,
        "validation_status": validation_status,
        "validation_iterations": validation_iterations,
        "validation_file": validation_file,
        "cost_usd": _infer_cost_usd(run_dir, agentic_summary if isinstance(agentic_summary, dict) else None),
        "artifacts": artifact_presence,
    }

    if isinstance(agentic_summary, dict):
        row["agentic"] = {
            "flake_risk": (agentic_summary.get("design") or {}).get("flake_risk"),
            "testability": (agentic_summary.get("design") or {}).get("testability"),
            "critic_risk": (agentic_summary.get("critic") or {}).get("risk_level"),
            "stability_status": (agentic_summary.get("stability") or {}).get("status"),
        }
    if isinstance(pipeline_error, dict):
        row["pipeline_error_stage"] = pipeline_error.get("stage")
        row["pipeline_error"] = pipeline_error.get("error") or pipeline_error.get("message")
    return row


def _rate(rows: list[dict[str, Any]], key: str) -> float | None:
    inferred = [row for row in rows if row.get(key) is not None]
    if not inferred:
        return None
    return round(sum(1 for row in inferred if row.get(key) is True) / len(inferred), 4)


def aggregate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_specs = len(rows)
    passed = sum(1 for row in rows if row.get("passed"))
    healing_rows = [row for row in rows if row.get("healing_started")]
    rescued = sum(1 for row in healing_rows if row.get("heal_rescued"))
    costs = [float(row["cost_usd"]) for row in rows if isinstance(row.get("cost_usd"), (int, float))]
    wall_times = [
        float(row["wall_time_seconds"])
        for row in rows
        if isinstance(row.get("wall_time_seconds"), (int, float))
    ]

    return {
        "total_specs": total_specs,
        "passed_specs": passed,
        "failed_specs": total_specs - passed,
        "pass_rate": round(passed / total_specs, 4) if total_specs else None,
        "planner_success_rate": _rate(rows, "planner_success"),
        "generation_success_rate": _rate(rows, "generation_success"),
        "first_pass_rate": round(sum(1 for row in rows if row.get("first_pass")) / total_specs, 4)
        if total_specs
        else None,
        "healing_started_count": len(healing_rows),
        "heal_rescue_rate": round(rescued / len(healing_rows), 4) if healing_rows else None,
        "mean_heal_attempts": round(
            sum(int(row.get("heal_attempts") or 0) for row in rows) / total_specs, 4
        )
        if total_specs
        else None,
        "total_cost_usd": round(sum(costs), 6) if costs else None,
        "mean_cost_usd": round(sum(costs) / len(costs), 6) if costs else None,
        "total_wall_time_seconds": round(sum(wall_times), 3) if wall_times else None,
        "mean_wall_time_seconds": round(sum(wall_times) / len(wall_times), 3) if wall_times else None,
    }


def compare_reports(current: dict[str, Any], old_report_path: Path) -> dict[str, Any]:
    old = _read_json(old_report_path)
    if not isinstance(old, dict):
        raise ValueError(f"Could not parse comparison report: {old_report_path}")
    old_aggregates = old.get("aggregates") if isinstance(old.get("aggregates"), dict) else {}
    new_aggregates = current.get("aggregates") if isinstance(current.get("aggregates"), dict) else {}
    deltas: dict[str, float] = {}
    for key, new_value in new_aggregates.items():
        old_value = old_aggregates.get(key)
        if isinstance(new_value, (int, float)) and isinstance(old_value, (int, float)):
            deltas[key] = round(float(new_value) - float(old_value), 6)
    return {
        "baseline": str(old_report_path),
        "baseline_label": old.get("label"),
        "aggregate_deltas": deltas,
    }


def build_report(
    *,
    specs_dir: Path,
    target_url: str,
    out_path: Path,
    label: str | None,
    rows: list[dict[str, Any]],
    compare_path: Path | None = None,
) -> dict[str, Any]:
    report = {
        "schema_version": "1.0",
        "generated_at": _utc_now(),
        "label": label,
        "specs_dir": str(specs_dir),
        "target_url": target_url,
        "rows": rows,
        "aggregates": aggregate_rows(rows),
    }
    if compare_path:
        report["compare"] = compare_reports(report, compare_path)
    _write_json(out_path, report)
    return report


def run_spec(spec_path: Path, *, target_url: str, run_dir: Path) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    effective_spec = _materialize_target_spec(spec_path, target_url, run_dir)
    env = os.environ.copy()
    env.update(
        {
            "BENCHMARK_TARGET_URL": target_url,
            "TARGET_URL": target_url,
            "QUORVEX_TARGET_URL": target_url,
        }
    )
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "orchestrator" / "cli.py"),
        str(effective_spec),
        "--run-dir",
        str(run_dir),
    ]
    started = time.monotonic()
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env, capture_output=True, text=True)
    wall_time = time.monotonic() - started
    (run_dir / "benchmark_command.json").write_text(
        json.dumps({"cmd": cmd, "returncode": proc.returncode}, indent=2),
        encoding="utf-8",
    )
    (run_dir / "subprocess_stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
    (run_dir / "subprocess_stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
    return parse_run_artifacts(
        spec_path,
        run_dir,
        returncode=proc.returncode,
        wall_time_seconds=wall_time,
    )


def run_benchmark(
    *,
    specs_dir: Path,
    target_url: str,
    out_path: Path,
    label: str | None,
    compare_path: Path | None = None,
) -> dict[str, Any]:
    specs = discover_specs(specs_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    runs_root = out_path.parent / f"{out_path.stem}_runs_{timestamp}"
    rows: list[dict[str, Any]] = []
    for index, spec in enumerate(specs, start=1):
        run_dir = runs_root / f"{index:03d}_{_slug(spec.relative_to(specs_dir).with_suffix('').as_posix())}"
        row = run_spec(spec, target_url=target_url, run_dir=run_dir)
        try:
            row["spec"] = str(spec.relative_to(specs_dir))
        except ValueError:
            pass
        rows.append(row)
        _write_json(out_path, {
            "schema_version": "1.0",
            "generated_at": _utc_now(),
            "label": label,
            "specs_dir": str(specs_dir),
            "target_url": target_url,
            "rows": rows,
            "aggregates": aggregate_rows(rows),
            "incomplete": index < len(specs),
        })
    return build_report(
        specs_dir=specs_dir,
        target_url=target_url,
        out_path=out_path,
        label=label,
        rows=rows,
        compare_path=compare_path,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run benchmark specs through orchestrator/cli.py.")
    parser.add_argument("--specs-dir", required=True, type=Path, help="Directory containing benchmark .md specs.")
    parser.add_argument("--target-url", required=True, help="Target URL to inject into each benchmark run.")
    parser.add_argument("--out", required=True, type=Path, help="Path to write the benchmark report JSON.")
    parser.add_argument("--label", help="Optional label for this run, e.g. v4.")
    parser.add_argument("--compare", type=Path, help="Optional previous report JSON to diff aggregate metrics against.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_benchmark(
        specs_dir=args.specs_dir,
        target_url=args.target_url,
        out_path=args.out,
        label=args.label,
        compare_path=args.compare,
    )
    print(f"Wrote benchmark report: {args.out}")
    print(json.dumps(report["aggregates"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
