"""
Batch executor service: creates regression batches from spec configurations.

Extracts the shared batch creation logic so both the API endpoint
(/runs/bulk) and the scheduler can create batches without duplication.
"""

import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from orchestrator.api.models_db import (
    RegressionBatch,
)
from orchestrator.api.models_db import (
    SpecMetadata as DBSpecMetadata,
)
from orchestrator.api.models_db import (
    TestRun as DBTestRun,
)

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SPECS_DIR = BASE_DIR / "specs"
RUNS_DIR = BASE_DIR / "runs"


# ---------------------------------------------------------------------------
# Inline helpers (avoid circular import from orchestrator.api.main)
# ---------------------------------------------------------------------------


def _get_try_code_path_fast(spec_path: Path) -> str | None:
    """Fast code path check - only checks filename patterns without scanning runs."""
    stem = spec_path.stem
    stem_slug = stem.replace("_", "-")
    candidates = [
        f"tests/generated/{stem}.spec.ts",
        f"tests/generated/{stem_slug}.spec.ts",
        f"tests/templates/{stem}.spec.ts",
        f"tests/templates/{stem_slug}.spec.ts",
        f"tests/{stem}.spec.ts",
    ]
    for c in candidates:
        if (BASE_DIR / c).exists():
            return str(BASE_DIR / c)
    return None


def _get_try_code_path(spec_name: str, spec_path: Path) -> str | None:
    """
    Get the generated test file path for a spec.

    Tries the fast filename-pattern check first, then falls back to scanning
    recent run directories for matching plan/export metadata.
    """
    # Fast path
    try_code_path = _get_try_code_path_fast(spec_path)
    if try_code_path:
        return try_code_path

    # Extract test name from spec content for fuzzy matching
    spec_test_name: str | None = None
    if spec_path.exists():
        content = spec_path.read_text()
        for line in content.split("\n"):
            if line.startswith("# "):
                spec_test_name = line.replace("# ", "").replace("Test:", "").strip()
                break

    # Slow path: scan recent run directories
    if RUNS_DIR.exists():
        run_dirs = sorted(
            [d for d in RUNS_DIR.iterdir() if d.is_dir()],
            key=lambda x: os.path.getmtime(x),
            reverse=True,
        )[:100]

        for r_dir in run_dirs:
            plan_file = r_dir / "plan.json"
            export_file = r_dir / "export.json"
            if plan_file.exists() and export_file.exists():
                try:
                    plan = json.loads(plan_file.read_text())
                    match = False
                    if plan.get("specFileName") == spec_name:
                        match = True
                    elif spec_test_name and plan.get("testName"):
                        t1 = plan.get("testName").lower().strip()
                        t2 = spec_test_name.lower().strip()
                        if t1 == t2 or t1 in t2 or t2 in t1:
                            match = True
                    if match:
                        export = json.loads(export_file.read_text())
                        path_str = export.get("testFilePath")
                        if path_str:
                            candidate = BASE_DIR / path_str
                            if not candidate.exists():
                                candidate = r_dir / path_str
                            if candidate.exists():
                                try_code_path = str(candidate)
                                break
                except (json.JSONDecodeError, OSError) as e:
                    logger.debug("Cannot read %s or %s: %s", plan_file, export_file, e)
            if try_code_path:
                break

    # Additional patterns using test name slug
    if not try_code_path and spec_test_name:
        test_slug = re.sub(r"[^a-z0-9]+", "-", spec_test_name.lower()).strip("-")
        slug_candidates = [
            f"tests/templates/{test_slug}.spec.ts",
            f"tests/generated/{test_slug}.spec.ts",
        ]
        for c in slug_candidates:
            if (BASE_DIR / c).exists():
                try_code_path = str(BASE_DIR / c)
                break

    return try_code_path


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class BatchConfig:
    """Configuration for creating a regression batch."""

    project_id: str
    browser: str = "chromium"
    hybrid_mode: bool = False
    max_iterations: int = 20
    tags: list[str] | None = None
    automated_only: bool = True
    spec_names: list[str] | None = None
    triggered_by: str | None = None
    batch_name: str | None = None


@dataclass
class BatchResult:
    """Result of creating a regression batch (before task execution)."""

    batch_id: str
    run_ids: list[str] = field(default_factory=list)
    tasks_to_start: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------


def create_regression_batch(config: BatchConfig, session: Session) -> BatchResult:
    """
    Create a regression batch: discover specs, create DB records, prepare tasks.

    This function does NOT start the actual test executions -- that is the
    caller's responsibility (API creates asyncio tasks, scheduler enqueues
    to Redis, etc.).

    Raises:
        ValueError: If no specs match the specified filters.
    """
    # ------------------------------------------------------------------
    # 1. Determine which specs to run
    # ------------------------------------------------------------------
    spec_names_to_run: list[str] = []

    if config.spec_names:
        spec_names_to_run = list(config.spec_names)
    elif config.automated_only:
        if SPECS_DIR.exists():
            for f in SPECS_DIR.glob("**/*.md"):
                code_path = _get_try_code_path_fast(f)
                if code_path:
                    spec_names_to_run.append(str(f.relative_to(SPECS_DIR)))

    # Apply tag filter (OR logic)
    if config.tags and len(config.tags) > 0:
        filtered: list[str] = []
        for spec_name in spec_names_to_run:
            meta = session.get(DBSpecMetadata, spec_name)
            if meta and meta.tags:
                if any(tag in meta.tags for tag in config.tags):
                    filtered.append(spec_name)
        spec_names_to_run = filtered

    # Apply automated_only filter even when explicit spec_names were given
    if config.automated_only and config.spec_names:
        filtered = []
        for spec_name in spec_names_to_run:
            spec_path = SPECS_DIR / spec_name
            if spec_path.exists():
                code_path = _get_try_code_path_fast(spec_path)
                if code_path:
                    filtered.append(spec_name)
        spec_names_to_run = filtered

    if not spec_names_to_run:
        raise ValueError("No specs match the specified filters (automated_only, tags)")

    # ------------------------------------------------------------------
    # 2. Create the RegressionBatch record
    # ------------------------------------------------------------------
    now = datetime.utcnow()
    batch_id = f"batch_{now.strftime('%Y-%m-%d_%H-%M-%S')}_{uuid.uuid4().hex[:8]}"

    batch_name = config.batch_name or f"Regression Run - {now.strftime('%Y-%m-%d %H:%M')}"

    batch = RegressionBatch(
        id=batch_id,
        name=batch_name,
        triggered_by=config.triggered_by,
        created_at=now,
        browser=config.browser,
        tags_used_json=json.dumps(config.tags or []),
        hybrid_mode=config.hybrid_mode,
        project_id=config.project_id,
        total_tests=len(spec_names_to_run),
        queued=len(spec_names_to_run),
        status="pending",
    )
    session.add(batch)

    # ------------------------------------------------------------------
    # 3. Create DBTestRun records and prepare task dicts
    # ------------------------------------------------------------------
    queued_runs = session.exec(select(DBTestRun).where(DBTestRun.status == "queued")).all()
    base_queue_position = len(queued_runs) + 1

    run_ids: list[str] = []
    tasks_to_start: list[dict] = []

    for i, spec_name in enumerate(spec_names_to_run):
        spec_path = SPECS_DIR / spec_name
        if not spec_path.exists():
            logger.warning("Spec file not found, skipping: %s", spec_path)
            continue

        run_id = now.strftime("%Y-%m-%d_%H-%M-%S") + f"_{uuid.uuid4().hex[:8]}_{spec_name.replace('/', '_')}"
        run_dir = RUNS_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "spec.md").write_text(spec_path.read_text())
        (run_dir / "status.txt").write_text("queued")

        try_code_path = _get_try_code_path(spec_name, spec_path)

        run = DBTestRun(
            id=run_id,
            spec_name=spec_name,
            test_name=spec_name,
            status="queued",
            browser=config.browser,
            queued_at=now,
            queue_position=base_queue_position + i,
            batch_id=batch_id,
            project_id=config.project_id,
        )
        session.add(run)

        tasks_to_start.append(
            {
                "spec_path": str(spec_path),
                "run_dir": str(run_dir),
                "run_id": run_id,
                "try_code_path": try_code_path,
                "browser": config.browser,
                "hybrid": config.hybrid_mode,
                "max_iterations": config.max_iterations,
                "batch_id": batch_id,
                "spec_name": spec_name,
                "project_id": config.project_id,
            }
        )
        run_ids.append(run_id)

    session.commit()

    logger.info(
        "Created batch %s with %d runs (project=%s, triggered_by=%s)",
        batch_id,
        len(run_ids),
        config.project_id,
        config.triggered_by,
    )

    return BatchResult(
        batch_id=batch_id,
        run_ids=run_ids,
        tasks_to_start=tasks_to_start,
    )
