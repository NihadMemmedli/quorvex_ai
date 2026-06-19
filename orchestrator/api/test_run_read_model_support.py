"""Read-model support for legacy test-run helpers exposed from main."""

from __future__ import annotations

import json
from typing import Any


def sync_data_from_files(runtime: Any) -> None:
    """Sync existing file-based runs and metadata to DB on startup."""
    runtime.logger.info("Syncing data from files to DB...")
    with runtime.Session(runtime.engine) as session:
        runs_with_null_name = session.exec(
            runtime.select(runtime.DBTestRun).where(runtime.DBTestRun.test_name == None)  # noqa: E711
        ).all()
        for run in runs_with_null_name:
            run.test_name = run.spec_name
        session.commit()
        if runs_with_null_name:
            runtime.logger.info(f"Fixed {len(runs_with_null_name)} runs with null test_name")

        if runtime.RUNS_DIR.exists():
            for d in runtime.RUNS_DIR.iterdir():
                if not d.is_dir():
                    continue
                run_id = d.name

                if session.get(runtime.DBTestRun, run_id):
                    continue

                plan_file = d / "plan.json"
                run_file = d / "run.json"
                status_file = d / "status.txt"
                execution_log = d / "execution.log"

                test_name = None
                steps_completed = 0
                total_steps = 0
                browser = "chromium"
                status = "unknown"

                if plan_file.exists():
                    try:
                        plan_data = json.loads(plan_file.read_text())
                        test_name = plan_data.get("testName")
                        total_steps = len(plan_data.get("steps", []))
                        browser = plan_data.get("browser", "chromium")
                    except json.JSONDecodeError as e:
                        runtime.logger.warning(f"Invalid JSON in plan file {plan_file}: {e}")
                    except OSError as e:
                        runtime.logger.warning(f"Cannot read plan file {plan_file}: {e}")

                if run_file.exists():
                    try:
                        run_data = json.loads(run_file.read_text())
                        status = run_data.get("finalState", "completed")
                        steps_completed = len(run_data.get("steps", []))
                    except json.JSONDecodeError as e:
                        runtime.logger.warning(f"Invalid JSON in run file {run_file}: {e}")
                        status = "completed"
                    except OSError as e:
                        runtime.logger.warning(f"Cannot read run file {run_file}: {e}")
                        status = "completed"
                elif status_file.exists():
                    status = status_file.read_text().strip()
                elif plan_file.exists() or execution_log.exists():
                    status = "failed"

                validation_file = d / "validation.json"
                if validation_file.exists():
                    try:
                        val_data = json.loads(validation_file.read_text())
                        if val_data.get("status") == "success":
                            status = "passed"
                        elif val_data.get("status") == "failed" and status not in ["passed"]:
                            status = "failed"
                    except json.JSONDecodeError as e:
                        runtime.logger.warning(f"Invalid JSON in validation file {validation_file}: {e}")
                    except OSError as e:
                        runtime.logger.warning(f"Cannot read validation file {validation_file}: {e}")

                spec_name = "unknown"
                if (d / "spec.md").exists():
                    spec_name = "restored_run"

                mtime = runtime.datetime.utcfromtimestamp(runtime.os.path.getmtime(d))

                run = runtime.DBTestRun(
                    id=run_id,
                    spec_name=spec_name,
                    status=status,
                    created_at=mtime,
                    test_name=test_name or spec_name,
                    steps_completed=steps_completed,
                    total_steps=total_steps,
                    browser=browser,
                )
                session.add(run)

        runtime.sync_spec_metadata_from_file(session)

        session.commit()
    runtime.logger.info("Sync complete.")
