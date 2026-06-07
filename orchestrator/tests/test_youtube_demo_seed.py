import os
import shutil
import sys
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-youtube-demo")
os.environ.setdefault("REQUIRE_AUTH", "false")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlmodel import Session, select

from orchestrator.api.db import engine
from orchestrator.api.models_db import (
    AgentRun,
    AgentRunEvent,
    Project,
    RegressionBatch,
    Requirement,
    RtmEntry,
    SpecMetadata,
    TestRun,
)
from orchestrator.scripts.seed_youtube_demo import seed_youtube_demo


def _cleanup(project_id: str) -> None:
    root = project_id.replace("_", "-")
    with Session(engine) as session:
        for event in session.exec(select(AgentRunEvent).where(AgentRunEvent.project_id == project_id)).all():
            session.delete(event)
        for run in session.exec(select(AgentRun).where(AgentRun.project_id == project_id)).all():
            session.delete(run)
        for test_run in session.exec(select(TestRun).where(TestRun.project_id == project_id)).all():
            session.delete(test_run)
        for batch in session.exec(select(RegressionBatch).where(RegressionBatch.project_id == project_id)).all():
            session.delete(batch)
        for entry in session.exec(select(RtmEntry).where(RtmEntry.project_id == project_id)).all():
            session.delete(entry)
        for req in session.exec(select(Requirement).where(Requirement.project_id == project_id)).all():
            session.delete(req)
        for meta in session.exec(select(SpecMetadata).where(SpecMetadata.project_id == project_id)).all():
            session.delete(meta)
        project = session.get(Project, project_id)
        if project:
            session.delete(project)
        session.commit()

    repo_root = Path(__file__).resolve().parents[2]
    shutil.rmtree(repo_root / "specs" / root, ignore_errors=True)
    shutil.rmtree(repo_root / "tests" / "generated" / root, ignore_errors=True)
    runs_dir = repo_root / "runs"
    for run_dir in runs_dir.glob(f"{root}-*"):
        shutil.rmtree(run_dir, ignore_errors=True)


def test_youtube_demo_seed_is_idempotent_and_api_visible():
    project_id = f"youtube-demo-{uuid4().hex[:8]}"
    _cleanup(project_id)

    try:
        first = seed_youtube_demo(project_id=project_id, include_database=False)
        second = seed_youtube_demo(project_id=project_id, include_database=False)

        assert first["project_id"] == project_id
        assert second["runs"] == first["runs"]
        assert len(second["specs"]) >= 6
        assert second["agent_run_id"] == f"{project_id}-agent-checkout-triage"

        with Session(engine) as session:
            project = session.get(Project, project_id)
            assert project is not None
            assert project.name.startswith("Quorvex Demo Shop")

            runs = session.exec(select(TestRun).where(TestRun.project_id == project_id)).all()
            assert len(runs) == 10
            assert sum(1 for run in runs if run.status == "failed") == 5
            assert any(run.agentic_summary and run.agentic_summary.get("healed") for run in runs)

            run_dir = Path(__file__).resolve().parents[2] / "runs" / f"{project_id}-checkout-selector-drift"
            export = run_dir / "export.json"
            assert export.exists()
            assert f"tests/generated/{project_id}/checkout-payment-validation.spec.ts" in export.read_text()

            agent = session.get(AgentRun, second["agent_run_id"])
            assert agent is not None
            assert agent.result is not None
            report = agent.result["structured_report"]
            assert len(report["findings"]) == 3
            assert len(report["test_ideas"]) == 2

            events = session.exec(select(AgentRunEvent).where(AgentRunEvent.run_id == agent.id)).all()
            assert len(events) == 5

            requirements = session.exec(select(Requirement).where(Requirement.project_id == project_id)).all()
            assert len(requirements) == 5
    finally:
        _cleanup(project_id)
