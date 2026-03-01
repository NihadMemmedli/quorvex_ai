"""
TestRail Integration API — Config, connection test, push cases, mappings.

Stores TestRail credentials in Project.settings["integrations"]["testrail"]
with encrypted API key. Pushes specs as test cases via the TestRail REST API.
"""

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import Session, select

from .credentials import decrypt_credential, encrypt_credential, mask_credential
from .db import get_session
from .middleware.auth import get_current_user_optional
from .models_auth import User
from .models_db import Project, RegressionBatch, TestrailCaseMapping, TestrailRunMapping
from .models_db import TestRun as DBTestRun

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/testrail", tags=["testrail"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SPECS_DIR = BASE_DIR / "specs"

# TestRail status IDs
_STATUS_MAP = {"passed": 1, "completed": 1, "failed": 5, "stopped": 2}


# ── Request / Response Models ──────────────────────────────────


class TestrailConfigRequest(BaseModel):
    base_url: str
    email: str
    api_key: str | None = None  # None means keep existing key
    project_id: int | None = None
    suite_id: int | None = None


class TestrailConfigResponse(BaseModel):
    base_url: str
    email: str
    api_key_masked: str
    project_id: int | None = None
    suite_id: int | None = None


class PushCasesRequest(BaseModel):
    spec_names: list[str]
    testrail_project_id: int
    testrail_suite_id: int


class PushCasesResponse(BaseModel):
    pushed: int = 0
    updated: int = 0
    failed: int = 0
    errors: list[str] = []


class SyncResultsRequest(BaseModel):
    batch_id: str
    testrail_project_id: int
    testrail_suite_id: int


class SyncResultsResponse(BaseModel):
    testrail_run_id: int = 0
    testrail_run_url: str = ""
    synced: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = []
    already_synced: bool = False


class MappingResponse(BaseModel):
    id: int
    spec_name: str
    testrail_case_id: int
    testrail_suite_id: int
    testrail_section_id: int
    testrail_project_id: int
    sync_direction: str
    last_pushed_at: str | None = None
    created_at: str


# ── Helpers ────────────────────────────────────────────────────


def _get_testrail_config(project: Project) -> dict[str, Any] | None:
    """Read the TestRail config block from project settings."""
    if not project.settings:
        return None
    return (project.settings.get("integrations") or {}).get("testrail")


def _save_testrail_config(project: Project, config: dict[str, Any], session: Session):
    """Write the TestRail config block into project settings and persist."""
    if not project.settings:
        project.settings = {}
    integrations = project.settings.setdefault("integrations", {})
    integrations["testrail"] = config
    flag_modified(project, "settings")
    session.add(project)
    session.commit()


def _require_project(project_id: str, session: Session) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _build_client(project: Project):
    """Build a TestrailClient from the project config. Raises 400 if not configured."""
    from services.testrail_client import TestrailClient

    config = _get_testrail_config(project)
    if not config:
        raise HTTPException(status_code=400, detail="TestRail not configured for this project")

    api_key = decrypt_credential(config.get("api_key_encrypted", ""))
    if not api_key:
        raise HTTPException(status_code=400, detail="TestRail API key could not be decrypted")

    return TestrailClient(
        base_url=config["base_url"],
        email=config["email"],
        api_key=api_key,
    )


# ── Config Endpoints ───────────────────────────────────────────


@router.get("/{project_id}/config")
def get_config(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Get TestRail config for a project (API key masked)."""
    project = _require_project(project_id, session)
    config = _get_testrail_config(project)
    if not config:
        return {"configured": False}

    api_key = decrypt_credential(config.get("api_key_encrypted", ""))
    return {
        "configured": True,
        "base_url": config.get("base_url", ""),
        "email": config.get("email", ""),
        "api_key_masked": mask_credential(api_key),
        "project_id": config.get("project_id"),
        "suite_id": config.get("suite_id"),
    }


@router.post("/{project_id}/config")
def save_config(
    project_id: str,
    request: TestrailConfigRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Save TestRail config for a project."""
    project = _require_project(project_id, session)

    if not request.base_url or not request.email:
        raise HTTPException(status_code=400, detail="base_url and email are required")

    # Build config, preserving existing encrypted key if no new key provided
    existing = _get_testrail_config(project)

    if request.api_key:
        api_key_encrypted = encrypt_credential(request.api_key)
    elif existing and existing.get("api_key_encrypted"):
        api_key_encrypted = existing["api_key_encrypted"]
    else:
        raise HTTPException(status_code=400, detail="API key is required for initial setup")

    config = {
        "base_url": request.base_url.rstrip("/"),
        "email": request.email,
        "api_key_encrypted": api_key_encrypted,
        "project_id": request.project_id,
        "suite_id": request.suite_id,
    }
    _save_testrail_config(project, config, session)
    return {"status": "ok"}


@router.delete("/{project_id}/config")
def delete_config(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Remove TestRail config from a project."""
    project = _require_project(project_id, session)
    if project.settings and "integrations" in project.settings:
        project.settings["integrations"].pop("testrail", None)
        flag_modified(project, "settings")
        session.add(project)
        session.commit()
    return {"status": "ok"}


# ── Connection Test ────────────────────────────────────────────


@router.post("/{project_id}/test-connection")
async def test_connection(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Test the TestRail connection using stored credentials."""
    project = _require_project(project_id, session)
    client = await _build_client(project)
    try:
        user_info = await client.test_connection()
        return {
            "status": "ok",
            "user": user_info.get("name", user_info.get("email", "Unknown")),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Connection failed: {e}")
    finally:
        await client.close()


# ── Remote Browse ──────────────────────────────────────────────


@router.get("/{project_id}/remote-projects")
async def list_remote_projects(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """List TestRail projects accessible with stored credentials."""
    project = _require_project(project_id, session)
    client = await _build_client(project)
    try:
        projects = await client.get_projects()
        return [
            {"id": p["id"], "name": p.get("name", ""), "is_completed": p.get("is_completed", False)} for p in projects
        ]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        await client.close()


@router.get("/{project_id}/remote-suites/{tr_project_id}")
async def list_remote_suites(
    project_id: str,
    tr_project_id: int,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """List suites in a TestRail project."""
    project = _require_project(project_id, session)
    client = await _build_client(project)
    try:
        suites = await client.get_suites(tr_project_id)
        return [{"id": s["id"], "name": s.get("name", "")} for s in suites]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        await client.close()


# ── Push Cases ─────────────────────────────────────────────────


@router.post("/{project_id}/push-cases", response_model=PushCasesResponse)
async def push_cases(
    project_id: str,
    request: PushCasesRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Push selected specs to TestRail as test cases."""
    from utils.spec_parser import parse_spec_file

    from .models_db import TestrailCaseMapping

    project = _require_project(project_id, session)
    client = await _build_client(project)

    tr_project_id = request.testrail_project_id
    tr_suite_id = request.testrail_suite_id

    pushed = 0
    updated = 0
    failed = 0
    errors: list[str] = []

    try:
        # 0. Find the "Test Case (Steps)" template for separated steps
        steps_template_id = None
        try:
            templates = await client.get_templates(tr_project_id)
            for tmpl in templates:
                name = (tmpl.get("name") or "").lower()
                if "steps" in name:
                    steps_template_id = tmpl["id"]
                    break
        except Exception:
            pass  # Fallback: don't set template_id

        # 1. Fetch existing sections for caching
        existing_sections = await client.get_sections(tr_project_id, tr_suite_id)
        section_cache: dict[tuple, int] = {}
        for sec in existing_sections:
            key = (sec.get("parent_id"), sec["name"])
            section_cache[key] = sec["id"]

        # 2. Load existing mappings for this project+suite
        stmt = select(TestrailCaseMapping).where(
            TestrailCaseMapping.project_id == project_id,
            TestrailCaseMapping.testrail_suite_id == tr_suite_id,
        )
        existing_mappings = {m.spec_name: m for m in session.exec(stmt).all()}

        # 3. Process each spec
        for spec_name in request.spec_names:
            spec_path = SPECS_DIR / spec_name
            if not spec_path.exists():
                errors.append(f"Spec not found: {spec_name}")
                failed += 1
                continue

            try:
                cases = parse_spec_file(spec_path, specs_dir=SPECS_DIR)
            except Exception as e:
                errors.append(f"Parse error for {spec_name}: {e}")
                failed += 1
                continue

            if not cases:
                errors.append(f"No test cases in {spec_name}")
                failed += 1
                continue

            # Use first case as the representative (most specs have one primary case)
            tc = cases[0]

            try:
                # Find or create section hierarchy
                section_id = await _ensure_section_hierarchy(
                    client,
                    tr_project_id,
                    tr_suite_id,
                    tc.section_path or ["Imported"],
                    section_cache,
                )

                # Build TestRail case fields
                case_fields = _build_case_fields(tc, steps_template_id)
                content_hash = _hash_spec(spec_path)

                mapping = existing_mappings.get(spec_name)
                if mapping:
                    # Update existing case
                    await client.update_case(mapping.testrail_case_id, case_fields)
                    mapping.testrail_section_id = section_id
                    mapping.last_pushed_at = datetime.utcnow()
                    mapping.local_hash = content_hash
                    mapping.updated_at = datetime.utcnow()
                    session.add(mapping)
                    updated += 1
                else:
                    # Create new case
                    result = await client.add_case(section_id, tc.title, case_fields)
                    new_mapping = TestrailCaseMapping(
                        project_id=project_id,
                        spec_name=spec_name,
                        testrail_case_id=result["id"],
                        testrail_suite_id=tr_suite_id,
                        testrail_section_id=section_id,
                        testrail_project_id=tr_project_id,
                        sync_direction="push",
                        last_pushed_at=datetime.utcnow(),
                        local_hash=content_hash,
                    )
                    session.add(new_mapping)
                    pushed += 1

            except Exception as e:
                errors.append(f"Failed to push {spec_name}: {e}")
                failed += 1

        session.commit()

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Push failed: {e}")
    finally:
        await client.close()

    return PushCasesResponse(pushed=pushed, updated=updated, failed=failed, errors=errors)


async def _ensure_section_hierarchy(
    client,
    tr_project_id: int,
    tr_suite_id: int,
    path: list[str],
    cache: dict[tuple, int],
) -> int:
    """Find or create nested sections for a path like ["Folder", "Subfolder"].
    Returns the leaf section ID."""
    parent_id: int | None = None

    for part in path:
        key = (parent_id, part)
        if key in cache:
            parent_id = cache[key]
        else:
            result = await client.add_section(tr_project_id, tr_suite_id, part, parent_id=parent_id)
            section_id = result["id"]
            cache[key] = section_id
            parent_id = section_id

    return parent_id  # type: ignore[return-value]


def _build_case_fields(tc, steps_template_id: int | None = None) -> dict[str, Any]:
    """Transform a ParsedTestCase into TestRail case API fields."""
    fields: dict[str, Any] = {}

    # Use the "Test Case (Steps)" template for separated steps
    if steps_template_id:
        fields["template_id"] = steps_template_id

    # Preconditions
    preconds = tc.preconditions or tc.description
    if preconds:
        fields["custom_preconds"] = preconds

    # Steps — send both formats for compatibility
    if tc.steps:
        # Separated steps (for "Test Case (Steps)" template)
        steps_separated = []
        for step in tc.steps:
            steps_separated.append(
                {
                    "content": step.content,
                    "expected": step.expected or "",
                }
            )
        # Add expected outcome as a final verification step
        if tc.expected_outcome:
            steps_separated.append(
                {
                    "content": "Verify expected outcomes",
                    "expected": tc.expected_outcome,
                }
            )
        fields["custom_steps_separated"] = steps_separated

        # Plain text steps (for "Test Case (Text)" template fallback)
        step_lines = [f"{s.index}. {s.content}" for s in tc.steps]
        fields["custom_steps"] = "\n".join(step_lines)

    # Expected outcome (plain text for "Text" template)
    if tc.expected_outcome:
        fields["custom_expected"] = tc.expected_outcome

    # References (test_id + tags)
    refs_parts = []
    if tc.test_id:
        refs_parts.append(tc.test_id)
    if tc.tags:
        refs_parts.extend(tc.tags)
    if refs_parts:
        fields["refs"] = ", ".join(refs_parts)

    return fields


def _hash_spec(spec_path: Path) -> str:
    """SHA-256 hash of the spec file content for change detection."""
    content = spec_path.read_bytes()
    return hashlib.sha256(content).hexdigest()[:16]


# ── Mappings ───────────────────────────────────────────────────


@router.get("/{project_id}/mappings")
def list_mappings(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """List all spec ↔ TestRail case mappings for a project."""
    _require_project(project_id, session)
    stmt = (
        select(TestrailCaseMapping)
        .where(TestrailCaseMapping.project_id == project_id)
        .order_by(TestrailCaseMapping.spec_name)
    )
    mappings = session.exec(stmt).all()
    return [
        {
            "id": m.id,
            "spec_name": m.spec_name,
            "testrail_case_id": m.testrail_case_id,
            "testrail_suite_id": m.testrail_suite_id,
            "testrail_section_id": m.testrail_section_id,
            "testrail_project_id": m.testrail_project_id,
            "sync_direction": m.sync_direction,
            "last_pushed_at": m.last_pushed_at.isoformat() if m.last_pushed_at else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in mappings
    ]


@router.delete("/{project_id}/mappings/{mapping_id}")
def delete_mapping(
    project_id: str,
    mapping_id: int,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Remove a spec ↔ TestRail case mapping."""
    mapping = session.get(TestrailCaseMapping, mapping_id)
    if not mapping or mapping.project_id != project_id:
        raise HTTPException(status_code=404, detail="Mapping not found")
    session.delete(mapping)
    session.commit()
    return {"status": "ok"}


# ── Result Sync (Phase 2b) ────────────────────────────────────


def _format_elapsed(started_at, completed_at) -> str | None:
    """Convert run timestamps to TestRail elapsed format (e.g. '2m 15s')."""
    if not started_at or not completed_at:
        return None
    delta = completed_at - started_at
    total = int(delta.total_seconds())
    if total <= 0:
        return "1s"
    mins, secs = divmod(total, 60)
    if mins > 0:
        return f"{mins}m {secs}s"
    return f"{secs}s"


@router.get("/{project_id}/sync-preview/{batch_id}")
def sync_preview(
    project_id: str,
    batch_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Preview what a batch→TestRail sync would look like."""
    project = _require_project(project_id, session)
    config = _get_testrail_config(project)
    if not config or not config.get("project_id") or not config.get("suite_id"):
        raise HTTPException(status_code=400, detail="TestRail not fully configured")

    config["project_id"]
    tr_suite_id = config["suite_id"]

    batch = session.get(RegressionBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Check if already synced
    existing = session.exec(
        select(TestrailRunMapping).where(
            TestrailRunMapping.project_id == project_id,
            TestrailRunMapping.batch_id == batch_id,
        )
    ).first()

    # Load case mappings for this project+suite
    case_mappings = session.exec(
        select(TestrailCaseMapping).where(
            TestrailCaseMapping.project_id == project_id,
            TestrailCaseMapping.testrail_suite_id == tr_suite_id,
        )
    ).all()
    case_lookup = {m.spec_name: m.testrail_case_id for m in case_mappings}

    # Load runs in terminal state
    runs = session.exec(
        select(DBTestRun).where(
            DBTestRun.batch_id == batch_id,
            DBTestRun.status.in_(["passed", "completed", "failed", "stopped"]),
        )
    ).all()

    mapped = 0
    unmapped = 0
    for run in runs:
        if run.spec_name in case_lookup:
            mapped += 1
        else:
            unmapped += 1

    result: dict[str, Any] = {
        "total_runs": len(runs),
        "mapped": mapped,
        "unmapped": unmapped,
        "already_synced": existing is not None,
        "batch_status": batch.status,
    }
    if existing:
        base_url = config.get("base_url", "")
        result["previous_sync"] = {
            "testrail_run_id": existing.testrail_run_id,
            "synced_at": existing.synced_at.isoformat() if existing.synced_at else None,
            "results_count": existing.results_count,
            "testrail_run_url": f"{base_url}/index.php?/runs/view/{existing.testrail_run_id}",
        }
    return result


@router.post("/{project_id}/sync-results", response_model=SyncResultsResponse)
async def sync_results(
    project_id: str,
    request: SyncResultsRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Sync batch run results to TestRail — creates a run and posts results."""
    project = _require_project(project_id, session)
    client = await _build_client(project)
    config = _get_testrail_config(project)

    tr_project_id = request.testrail_project_id
    tr_suite_id = request.testrail_suite_id
    batch_id = request.batch_id

    try:
        # 1. Verify batch exists and is completed
        batch = session.get(RegressionBatch, batch_id)
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")
        if batch.status != "completed":
            raise HTTPException(status_code=400, detail="Batch is not yet completed")

        # 2. Check if already synced
        existing = session.exec(
            select(TestrailRunMapping).where(
                TestrailRunMapping.project_id == project_id,
                TestrailRunMapping.batch_id == batch_id,
            )
        ).first()
        if existing:
            base_url = (config or {}).get("base_url", "")
            return SyncResultsResponse(
                testrail_run_id=existing.testrail_run_id,
                testrail_run_url=f"{base_url}/index.php?/runs/view/{existing.testrail_run_id}",
                synced=existing.results_count,
                already_synced=True,
            )

        # 3. Load case mappings → {spec_name: case_id}
        case_mappings = session.exec(
            select(TestrailCaseMapping).where(
                TestrailCaseMapping.project_id == project_id,
                TestrailCaseMapping.testrail_suite_id == tr_suite_id,
            )
        ).all()
        case_lookup = {m.spec_name: m.testrail_case_id for m in case_mappings}

        # 4. Load terminal runs for this batch
        runs = session.exec(
            select(DBTestRun).where(
                DBTestRun.batch_id == batch_id,
                DBTestRun.status.in_(["passed", "completed", "failed", "stopped"]),
            )
        ).all()

        # 5. Build results array
        results = []
        synced = 0
        skipped = 0
        errors: list[str] = []
        case_ids_used = set()

        for run in runs:
            case_id = case_lookup.get(run.spec_name)
            if not case_id:
                skipped += 1
                continue

            status_id = _STATUS_MAP.get(run.status)
            if not status_id:
                skipped += 1
                continue

            result_entry: dict[str, Any] = {
                "case_id": case_id,
                "status_id": status_id,
            }

            elapsed = _format_elapsed(run.started_at, run.completed_at)
            if elapsed:
                result_entry["elapsed"] = elapsed

            comment_parts = []
            if run.error_message:
                comment_parts.append(f"Error: {run.error_message}")
            comment_parts.append(f"Run ID: {run.id}")
            result_entry["comment"] = "\n".join(comment_parts)

            results.append(result_entry)
            case_ids_used.add(case_id)
            synced += 1

        if not results:
            return SyncResultsResponse(
                skipped=skipped,
                errors=["No runs could be mapped to TestRail cases. Push specs to TestRail first."],
            )

        # 6. Create TestRail run
        batch_name = batch.name or batch.id
        run_name = f"Batch: {batch_name}"
        run_desc = f"Synced from batch {batch.id}\nTotal: {len(runs)} | Mapped: {synced} | Skipped: {skipped}"

        tr_run = await client.add_run(
            project_id=tr_project_id,
            suite_id=tr_suite_id,
            name=run_name,
            description=run_desc,
            case_ids=list(case_ids_used),
        )
        tr_run_id = tr_run["id"]

        # 7. Post results in chunks of 50
        failed_count = 0
        chunk_size = 50
        for i in range(0, len(results), chunk_size):
            chunk = results[i : i + chunk_size]
            try:
                await client.add_results_for_cases(tr_run_id, chunk)
            except Exception as e:
                failed_count += len(chunk)
                synced -= len(chunk)
                errors.append(f"Chunk {i // chunk_size + 1} failed: {e}")

        # 8. Close the run
        try:
            await client.close_run(tr_run_id)
        except Exception as e:
            errors.append(f"Warning: could not close run: {e}")

        # 9. Create mapping record
        mapping = TestrailRunMapping(
            project_id=project_id,
            batch_id=batch_id,
            testrail_run_id=tr_run_id,
            testrail_project_id=tr_project_id,
            synced_at=datetime.utcnow(),
            results_count=synced,
        )
        session.add(mapping)
        session.commit()

        base_url = (config or {}).get("base_url", "")
        return SyncResultsResponse(
            testrail_run_id=tr_run_id,
            testrail_run_url=f"{base_url}/index.php?/runs/view/{tr_run_id}",
            synced=synced,
            skipped=skipped,
            failed=failed_count,
            errors=errors,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {e}")
    finally:
        await client.close()
