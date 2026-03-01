"""
API Testing Router

Provides endpoints for managing API test specifications, generating tests,
importing OpenAPI specs, running tests with self-healing, and tracking background jobs.
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import and_, func
from sqlmodel import Session, select

from .db import engine, get_session
from .models_db import OpenApiImportHistory, SpecMetadata
from .models_db import TestRun as DBTestRun

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.spec_detector import SpecDetector, SpecType
from utils.test_counter import count_tests_in_file

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SPECS_DIR = BASE_DIR / "specs"
TESTS_DIR = BASE_DIR / "tests" / "generated"
RUNS_DIR = BASE_DIR / "runs"

router = APIRouter(prefix="/api-testing", tags=["api-testing"])

# ========== Spec Cache (mtime-based invalidation) ==========
# keyed by file path → (mtime, spec_dict)
_api_spec_cache: dict[str, tuple] = {}

# ========== In-Memory Job Tracking ==========
_api_jobs: dict[str, dict] = {}
MAX_TRACKED_JOBS = 200


def _cleanup_old_jobs():
    """Remove completed/failed jobs older than 1 hour."""
    now = time.time()
    to_remove = []
    for job_id, job in _api_jobs.items():
        if job["status"] in ("completed", "failed"):
            completed_at = job.get("completed_at", 0)
            if now - completed_at > 3600:
                to_remove.append(job_id)
    for job_id in to_remove:
        del _api_jobs[job_id]
    # Also enforce hard cap - never evict running jobs
    if len(_api_jobs) > MAX_TRACKED_JOBS:
        evictable = sorted(
            [(jid, j) for jid, j in _api_jobs.items() if j["status"] != "running"],
            key=lambda x: x[1].get("started_at", 0),
        )
        for job_id, _ in evictable[: len(_api_jobs) - MAX_TRACKED_JOBS]:
            del _api_jobs[job_id]


# ========== Pydantic Models ==========


class CreateApiSpecRequest(BaseModel):
    name: str
    content: str
    project_id: str | None = "default"


class UpdateApiSpecRequest(BaseModel):
    content: str


class GenerateTestRequest(BaseModel):
    spec_name: str
    project_id: str | None = "default"


class ImportOpenApiRequest(BaseModel):
    url: str | None = None
    feature_filter: str | None = None
    project_id: str | None = "default"


class RunApiTestRequest(BaseModel):
    spec_path: str  # relative path like "specs/api/test.md"
    project_id: str | None = "default"


class EdgeCaseRequest(BaseModel):
    spec_path: str
    project_id: str | None = "default"


class RunDirectRequest(BaseModel):
    test_path: str  # relative path like "tests/generated/my-api.api.spec.ts"
    spec_name: str | None = None
    project_id: str | None = "default"


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    stage: str | None = None
    message: str | None = None
    result: dict | None = None


class UpdateTagsRequest(BaseModel):
    tags: list[str]
    project_id: str | None = "default"


class BulkRunRequest(BaseModel):
    spec_paths: list[str]
    project_id: str | None = "default"


class BulkGenerateRequest(BaseModel):
    spec_names: list[str]
    project_id: str | None = "default"


class CreateFolderRequest(BaseModel):
    folder_name: str
    project_id: str | None = "default"


# ========== Helper Functions ==========

# --- Regexes for counting HTTP endpoint definitions in API specs ---

# Format 1 (standard): numbered steps starting with HTTP method
#   1. GET /health
#   7. POST /users with body ...
_HTTP_STEP_RE = re.compile(
    r"^\s*\d+\.\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+\S",
    re.IGNORECASE | re.MULTILINE,
)

# Format 2 (exploration-generated): markdown heading starting with HTTP method
#   ### GET /ssoauth/api/v1/qr-logins/{id}/status
#   ### POST /ssoauth/api/v1/person-login
_HTTP_HEADING_RE = re.compile(
    r"^#{2,4}\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+\S",
    re.IGNORECASE | re.MULTILINE,
)

# Format 3 (exploration-generated): bold Endpoint label with backtick-wrapped method
#   **Endpoint**: `POST https://api.example.com/v1/resource`
#   **Endpoint:** `GET https://api.example.com/v1/resource`
_HTTP_BOLD_ENDPOINT_RE = re.compile(
    r"\*\*Endpoint\*{0,2}:?\*{0,2}:?\s*`(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+",
    re.IGNORECASE,
)


def count_defined_cases(spec_path: str) -> int:
    """Count the number of HTTP endpoint definitions in an API spec file.

    Supports three formats:
    - Numbered steps:   1. GET /health
    - Heading methods:  ### GET /path
    - Bold endpoints:   **Endpoint**: `POST https://...`
    """
    try:
        content = Path(spec_path).read_text(errors="replace")
        return (
            len(_HTTP_STEP_RE.findall(content))
            + len(_HTTP_HEADING_RE.findall(content))
            + len(_HTTP_BOLD_ENDPOINT_RE.findall(content))
        )
    except Exception:
        return 0


def _get_specs_dir(project_id: str = "default") -> Path:
    """Get specs directory, optionally scoped by project."""
    if project_id and project_id != "default":
        project_dir = SPECS_DIR / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir
    return SPECS_DIR


def _get_tests_dir(project_id: str = "default") -> Path:
    """Get tests/generated directory, optionally scoped by project."""
    if project_id and project_id != "default":
        project_dir = TESTS_DIR / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir
    return TESTS_DIR


def _scan_api_specs(
    project_id: str = "default",
    search: str | None = None,
    limit: int = 20,
    offset: int = 0,
    sort: str = "name",
    status_filter: str | None = None,
    folder: str | None = None,
    tags: str | None = None,
) -> dict:
    """Scan specs directory for API-type specs with caching, enrichment, filtering, and sorting."""
    global _api_spec_cache

    specs_dir = _get_specs_dir(project_id)
    if not specs_dir.exists():
        return {
            "items": [],
            "total": 0,
            "has_more": False,
            "folders": [],
            "summary": {"total_specs": 0, "with_tests": 0, "passed": 0, "failed": 0, "not_run": 0, "no_tests": 0},
        }

    detector = SpecDetector()
    api_specs = []

    for md_file in sorted(specs_dir.rglob("*.md")):
        # Skip templates
        if "templates" in md_file.parts:
            continue

        file_key = str(md_file)
        try:
            current_mtime = md_file.stat().st_mtime
        except OSError:
            continue

        # Check cache
        cached = _api_spec_cache.get(file_key)
        if cached and cached[0] == current_mtime:
            api_specs.append(cached[1])
            continue

        try:
            spec_type = detector.detect_spec_type(md_file)
            if spec_type != SpecType.API:
                # Remove stale cache entry if type changed
                _api_spec_cache.pop(file_key, None)
                continue

            stem = md_file.stem
            generated_tests = []
            seen_paths = set()
            tests_dir = _get_tests_dir(project_id)
            globs = [
                tests_dir.glob(f"{stem}*.api.spec.ts"),
                tests_dir.glob(f"openapi-{stem}*.api.spec.ts"),
                tests_dir.glob(f"{stem}*.spec.ts"),
                tests_dir.glob(f"openapi-{stem}*.spec.ts"),
            ]
            api_sub = tests_dir / "api"
            if api_sub.exists():
                globs.append(api_sub.glob(f"{stem}*.spec.ts"))
                globs.append(api_sub.glob(f"openapi-{stem}*.spec.ts"))
            for glob_iter in globs:
                for ts_file in sorted(glob_iter):
                    rel = str(ts_file.relative_to(BASE_DIR))
                    if rel not in seen_paths:
                        seen_paths.add(rel)
                        file_test_count = count_tests_in_file(str(ts_file))
                        generated_tests.append({"path": rel, "name": ts_file.name, "test_count": file_test_count})

            total_test_count = sum(t["test_count"] for t in generated_tests)

            # Extract folder from relative path
            rel_path = md_file.relative_to(specs_dir)
            spec_folder = str(rel_path.parent) if str(rel_path.parent) != "." else ""

            # Extract base_url from spec content
            base_url = None
            try:
                content = md_file.read_text(errors="replace")
                url_match = re.search(r"##\s+Base\s+URL:\s*(\S+)", content)
                if url_match:
                    base_url = url_match.group(1)
            except Exception:
                pass

            modified_at = datetime.fromtimestamp(current_mtime).isoformat()

            defined_cases = count_defined_cases(str(md_file))

            spec_dict = {
                "name": md_file.name,
                "path": str(md_file.relative_to(BASE_DIR)),
                "spec_type": "api",
                "has_generated_test": len(generated_tests) > 0,
                "generated_test_path": generated_tests[0]["path"] if generated_tests else None,
                "generated_tests": generated_tests,
                "file_count": len(generated_tests),
                "test_count": total_test_count,
                "defined_cases": defined_cases,
                "folder": spec_folder,
                "base_url": base_url,
                "modified_at": modified_at,
                # Placeholders for enrichment below
                "last_run_status": None,
                "last_run_at": None,
                "tags": [],
            }

            _api_spec_cache[file_key] = (current_mtime, spec_dict)
            api_specs.append(spec_dict)
        except Exception as e:
            logger.warning(f"Error scanning {md_file}: {e}")

    # --- Enrich with latest run status from DB ---
    latest_run_map: dict[str, dict] = {}
    try:
        with Session(engine) as session:
            subq = select(
                DBTestRun.spec_name,
                func.max(DBTestRun.created_at).label("max_created"),
            ).where(DBTestRun.test_type == "api")
            if project_id == "default":
                subq = subq.where((DBTestRun.project_id == "default") | (DBTestRun.project_id == None))
            else:
                subq = subq.where(DBTestRun.project_id == project_id)
            subq = subq.group_by(DBTestRun.spec_name).subquery()

            run_query = (
                select(DBTestRun)
                .join(
                    subq,
                    and_(
                        DBTestRun.spec_name == subq.c.spec_name,
                        DBTestRun.created_at == subq.c.max_created,
                    ),
                )
                .where(DBTestRun.test_type == "api")
            )
            runs = session.exec(run_query).all()
            for r in runs:
                latest_run_map[r.spec_name] = {
                    "status": r.status,
                    "completed_at": (r.completed_at.isoformat() + "Z") if r.completed_at else None,
                }
    except Exception as e:
        logger.warning(f"Failed to fetch latest runs for spec enrichment: {e}")

    # --- Enrich with tags from SpecMetadata ---
    tags_map: dict[str, list[str]] = {}
    try:
        with Session(engine) as session:
            meta_query = select(SpecMetadata)
            if project_id == "default":
                meta_query = meta_query.where(
                    (SpecMetadata.project_id == "default") | (SpecMetadata.project_id == None)
                )
            else:
                meta_query = meta_query.where(SpecMetadata.project_id == project_id)
            metas = session.exec(meta_query).all()
            for m in metas:
                tags_map[m.spec_name] = m.tags
    except Exception as e:
        logger.warning(f"Failed to fetch spec metadata for enrichment: {e}")

    # Apply enrichment to each spec
    for spec in api_specs:
        run_info = latest_run_map.get(spec["name"])
        if run_info:
            spec["last_run_status"] = run_info["status"]
            spec["last_run_at"] = run_info["completed_at"]
        spec["tags"] = tags_map.get(spec["name"], [])

    # Collect all folders (before filtering)
    all_folders = sorted({s["folder"] for s in api_specs if s["folder"]})

    # Build summary (before filtering)
    total_defined_cases = sum(s.get("defined_cases", 0) for s in api_specs)
    total_generated_tests = sum(
        min(s.get("test_count", 0), s.get("defined_cases", 0)) for s in api_specs if s.get("defined_cases", 0) > 0
    )
    coverage_pct = round(total_generated_tests / total_defined_cases * 100) if total_defined_cases > 0 else 0

    summary = {
        "total_specs": len(api_specs),
        "with_tests": sum(1 for s in api_specs if s["has_generated_test"]),
        "passed": sum(1 for s in api_specs if s.get("last_run_status") == "passed"),
        "failed": sum(1 for s in api_specs if s.get("last_run_status") == "failed"),
        "not_run": sum(1 for s in api_specs if s["has_generated_test"] and s.get("last_run_status") is None),
        "no_tests": sum(1 for s in api_specs if not s["has_generated_test"]),
        "total_defined_cases": total_defined_cases,
        "total_generated_tests": total_generated_tests,
        "coverage_pct": coverage_pct,
    }

    # --- Apply filters ---
    if search:
        search_lower = search.lower()
        api_specs = [s for s in api_specs if search_lower in s["name"].lower()]

    if folder is not None:
        api_specs = [s for s in api_specs if s["folder"] == folder]

    if status_filter:
        if status_filter == "passed":
            api_specs = [s for s in api_specs if s.get("last_run_status") == "passed"]
        elif status_filter == "failed":
            api_specs = [s for s in api_specs if s.get("last_run_status") == "failed"]
        elif status_filter == "not_run":
            api_specs = [s for s in api_specs if s["has_generated_test"] and s.get("last_run_status") is None]
        elif status_filter == "no_tests":
            api_specs = [s for s in api_specs if not s["has_generated_test"]]

    if tags:
        filter_tags = set(t.strip() for t in tags.split(",") if t.strip())
        if filter_tags:
            api_specs = [s for s in api_specs if filter_tags & set(s.get("tags", []))]

    # --- Sort ---
    if sort == "status":
        status_order = {"failed": 0, "running": 1, "passed": 2, None: 3}
        api_specs = sorted(api_specs, key=lambda x: (status_order.get(x.get("last_run_status"), 3), x["name"].lower()))
    elif sort == "last_run":
        api_specs = sorted(api_specs, key=lambda x: x.get("last_run_at") or "", reverse=True)
    elif sort == "test_count":
        api_specs = sorted(api_specs, key=lambda x: x.get("test_count", 0), reverse=True)
    elif sort == "modified":
        api_specs = sorted(api_specs, key=lambda x: x.get("modified_at") or "", reverse=True)
    else:  # "name" (default)
        api_specs = sorted(api_specs, key=lambda x: x["name"].lower())

    total = len(api_specs)
    sliced = api_specs[offset : offset + limit]
    return {
        "items": sliced,
        "total": total,
        "has_more": (offset + limit) < total,
        "folders": all_folders,
        "summary": summary,
    }


def _scan_generated_tests(
    search: str | None = None,
    limit: int = 20,
    offset: int = 0,
    sort: str = "modified",
    status_filter: str | None = None,
    project_id: str = "default",
) -> dict:
    """Scan for generated API test files with pagination, search, status enrichment, and sorting."""
    tests = []
    tests_dir = _get_tests_dir(project_id)
    if not tests_dir.exists():
        return {"items": [], "total": 0, "has_more": False}

    # Fetch latest runs from DB for status enrichment
    latest_run_map: dict[str, dict] = {}
    try:
        with Session(engine) as session:
            subq = select(
                DBTestRun.spec_name,
                func.max(DBTestRun.created_at).label("max_created"),
            ).where(DBTestRun.test_type == "api")
            if project_id == "default":
                subq = subq.where((DBTestRun.project_id == "default") | (DBTestRun.project_id == None))
            else:
                subq = subq.where(DBTestRun.project_id == project_id)
            subq = subq.group_by(DBTestRun.spec_name).subquery()

            run_query = (
                select(DBTestRun)
                .join(
                    subq,
                    and_(
                        DBTestRun.spec_name == subq.c.spec_name,
                        DBTestRun.created_at == subq.c.max_created,
                    ),
                )
                .where(DBTestRun.test_type == "api")
            )
            runs = session.exec(run_query).all()
            for r in runs:
                latest_run_map[r.spec_name] = {
                    "status": r.status,
                    "completed_at": (r.completed_at.isoformat() + "Z") if r.completed_at else None,
                }
    except Exception as e:
        logger.warning(f"Failed to fetch latest runs for enrichment: {e}")

    # Scan filesystem for test files
    patterns = [
        tests_dir.glob("*.api.spec.ts"),
        (tests_dir / "api").glob("*.spec.ts") if (tests_dir / "api").exists() else [],
    ]

    for pattern in patterns:
        for ts_file in pattern:
            stat = ts_file.stat()
            base_name = ts_file.stem  # e.g. "test_api.api.spec"
            spec_stem = base_name.split(".")[0]  # "test_api"

            # Determine folder from path relative to tests_dir
            rel_path = ts_file.relative_to(tests_dir)
            folder = str(rel_path.parent) if str(rel_path.parent) != "." else ""

            # Find source spec path (check project-scoped dir first, then global)
            source_spec_path = None
            specs_dir_for_project = _get_specs_dir(project_id)
            search_dirs = [specs_dir_for_project, specs_dir_for_project / "api"]
            if project_id and project_id != "default":
                search_dirs.extend([SPECS_DIR, SPECS_DIR / "api"])
            for sd in search_dirs:
                candidate = sd / f"{spec_stem}.md"
                if candidate.exists():
                    source_spec_path = str(candidate.relative_to(BASE_DIR))
                    break

            # Look up last run status - try multiple possible spec_name matches
            last_run = None
            for candidate_name in [base_name, ts_file.name, f"{spec_stem}.md", spec_stem]:
                if candidate_name in latest_run_map:
                    last_run = latest_run_map[candidate_name]
                    break

            tests.append(
                {
                    "name": ts_file.name,
                    "path": str(ts_file.relative_to(BASE_DIR)),
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "source_spec": f"{spec_stem}.md",
                    "source_spec_path": source_spec_path,
                    "test_count": count_tests_in_file(str(ts_file)),
                    "folder": folder,
                    "last_run_status": last_run["status"] if last_run else None,
                    "last_run_at": last_run["completed_at"] if last_run else None,
                }
            )

    # Apply status filter
    if status_filter:
        if status_filter == "not_run":
            tests = [t for t in tests if t["last_run_status"] is None]
        else:
            tests = [t for t in tests if t.get("last_run_status") == status_filter]

    # Apply search filter
    if search:
        search_lower = search.lower()
        tests = [t for t in tests if search_lower in t["name"].lower()]

    # Sort
    if sort == "name":
        tests = sorted(tests, key=lambda x: x["name"].lower())
    elif sort == "status":
        status_order = {"failed": 0, "running": 1, "passed": 2, None: 3}
        tests = sorted(tests, key=lambda x: (status_order.get(x.get("last_run_status"), 3), x["name"].lower()))
    elif sort == "last_run":
        tests = sorted(tests, key=lambda x: x.get("last_run_at") or "", reverse=True)
    elif sort == "size":
        tests = sorted(tests, key=lambda x: x["size_bytes"], reverse=True)
    else:  # "modified" (default)
        tests = sorted(tests, key=lambda x: x["modified_at"], reverse=True)

    total = len(tests)
    sliced = tests[offset : offset + limit]
    return {"items": sliced, "total": total, "has_more": (offset + limit) < total}


# ========== Background Job Runners ==========


async def _run_generate_test(job_id: str, spec_path: str, project_id: str):
    """Background task to generate an API test from a spec."""
    _api_jobs[job_id] = {
        "status": "running",
        "message": "Generating API test...",
        "started_at": time.time(),
        "result": None,
        "completed_at": None,
        "project_id": project_id,
    }
    try:
        from workflows.native_api_generator import NativeApiGenerator

        generator = NativeApiGenerator(project_id=project_id)
        result_path = await generator.generate_test(spec_path)
        _api_jobs[job_id].update(
            {
                "status": "completed",
                "message": "Test generated successfully",
                "result": {"test_path": str(result_path)},
                "completed_at": time.time(),
            }
        )
    except Exception as e:
        logger.error(f"API test generation failed for job {job_id}: {e}")
        _api_jobs[job_id].update(
            {
                "status": "failed",
                "message": str(e),
                "completed_at": time.time(),
            }
        )


async def _run_import_openapi(job_id: str, url: str, feature_filter: str | None, project_id: str):
    """Background task to import from OpenAPI spec URL."""
    import uuid as _uuid

    history_id = f"oai-{str(_uuid.uuid4())[:8]}"

    _api_jobs[job_id] = {
        "status": "running",
        "message": "Importing OpenAPI specification...",
        "started_at": time.time(),
        "result": None,
        "completed_at": None,
        "project_id": project_id,
    }

    # Create DB history record
    try:
        with Session(engine) as session:
            history = OpenApiImportHistory(
                id=history_id,
                project_id=project_id,
                source_type="url",
                source_url=url,
                feature_filter=feature_filter,
                status="running",
            )
            session.add(history)
            session.commit()
    except Exception as e:
        logger.warning(f"Failed to create import history record: {e}")

    try:
        from workflows.openapi_processor import OpenApiProcessor

        processor = OpenApiProcessor(project_id=project_id)
        result_paths = await processor.process(url, feature_filter=feature_filter)
        file_paths = [str(p) for p in result_paths]
        _api_jobs[job_id].update(
            {
                "status": "completed",
                "message": f"Generated {len(result_paths)} test file(s)",
                "result": {"files": file_paths},
                "completed_at": time.time(),
            }
        )
        # Update history record
        try:
            with Session(engine) as session:
                h = session.get(OpenApiImportHistory, history_id)
                if h:
                    h.status = "completed"
                    h.files_generated = len(result_paths)
                    h.generated_paths_json = json.dumps(file_paths)
                    h.completed_at = datetime.utcnow()
                    session.add(h)
                    session.commit()
        except Exception as e:
            logger.warning(f"Failed to update import history on success: {e}")
    except Exception as e:
        logger.error(f"OpenAPI import failed for job {job_id}: {e}")
        _api_jobs[job_id].update(
            {
                "status": "failed",
                "message": str(e),
                "completed_at": time.time(),
            }
        )
        # Update history record on failure
        try:
            with Session(engine) as session:
                h = session.get(OpenApiImportHistory, history_id)
                if h:
                    h.status = "failed"
                    h.error_message = str(e)
                    h.completed_at = datetime.utcnow()
                    session.add(h)
                    session.commit()
        except Exception as he:
            logger.warning(f"Failed to update import history on failure: {he}")


async def _run_import_openapi_file(
    job_id: str, file_path: str, feature_filter: str | None, project_id: str, original_filename: str | None = None
):
    """Background task to import from uploaded OpenAPI file."""
    import uuid as _uuid

    history_id = f"oai-{str(_uuid.uuid4())[:8]}"

    _api_jobs[job_id] = {
        "status": "running",
        "message": "Processing uploaded OpenAPI file...",
        "started_at": time.time(),
        "result": None,
        "completed_at": None,
        "project_id": project_id,
    }

    # Create DB history record
    try:
        with Session(engine) as session:
            history = OpenApiImportHistory(
                id=history_id,
                project_id=project_id,
                source_type="file",
                source_filename=original_filename or Path(file_path).name,
                feature_filter=feature_filter,
                status="running",
            )
            session.add(history)
            session.commit()
    except Exception as e:
        logger.warning(f"Failed to create import history record: {e}")

    try:
        from workflows.openapi_processor import OpenApiProcessor

        processor = OpenApiProcessor(project_id=project_id)
        result_paths = await processor.process(file_path, feature_filter=feature_filter)
        file_paths = [str(p) for p in result_paths]
        _api_jobs[job_id].update(
            {
                "status": "completed",
                "message": f"Generated {len(result_paths)} test file(s)",
                "result": {"files": file_paths},
                "completed_at": time.time(),
            }
        )
        # Update history record
        try:
            with Session(engine) as session:
                h = session.get(OpenApiImportHistory, history_id)
                if h:
                    h.status = "completed"
                    h.files_generated = len(result_paths)
                    h.generated_paths_json = json.dumps(file_paths)
                    h.completed_at = datetime.utcnow()
                    session.add(h)
                    session.commit()
        except Exception as e:
            logger.warning(f"Failed to update import history on success: {e}")
    except Exception as e:
        logger.error(f"OpenAPI file import failed for job {job_id}: {e}")
        _api_jobs[job_id].update(
            {
                "status": "failed",
                "message": str(e),
                "completed_at": time.time(),
            }
        )
        # Update history record on failure
        try:
            with Session(engine) as session:
                h = session.get(OpenApiImportHistory, history_id)
                if h:
                    h.status = "failed"
                    h.error_message = str(e)
                    h.completed_at = datetime.utcnow()
                    session.add(h)
                    session.commit()
        except Exception as he:
            logger.warning(f"Failed to update import history on failure: {he}")
    finally:
        # Clean up temp file
        try:
            Path(file_path).unlink(missing_ok=True)
        except Exception:
            pass


async def _run_edge_cases(job_id: str, spec_path: str, project_id: str):
    """Background task to generate edge case tests."""
    _api_jobs[job_id] = {
        "status": "running",
        "message": "Generating edge case tests...",
        "started_at": time.time(),
        "result": None,
        "completed_at": None,
        "project_id": project_id,
    }
    try:
        from workflows.api_edge_case_generator import ApiEdgeCaseGenerator

        generator = ApiEdgeCaseGenerator(project_id=project_id)
        result_paths = await generator.generate(spec_path)
        _api_jobs[job_id].update(
            {
                "status": "completed",
                "message": f"Generated {len(result_paths)} edge case file(s)",
                "result": {"files": [str(p) for p in result_paths]},
                "completed_at": time.time(),
            }
        )
    except Exception as e:
        logger.error(f"Edge case generation failed for job {job_id}: {e}")
        _api_jobs[job_id].update(
            {
                "status": "failed",
                "message": str(e),
                "completed_at": time.time(),
            }
        )


def _run_api_test_sync(job_id: str, spec_path: str, project_id: str):
    """Synchronous function to run an API test through the full pipeline.

    Uses subprocess to call cli.py, same pattern as the main runs endpoint.
    Captures logs to run directory for streaming.
    """

    run_id = f"api-{job_id}"
    run_dir = str(RUNS_DIR / run_id)
    run_dir_path = Path(run_dir)
    run_dir_path.mkdir(parents=True, exist_ok=True)

    _api_jobs[job_id].update(
        {
            "stage": "starting",
            "message": "Starting API test pipeline...",
            "result": {"run_id": run_id, "run_dir": run_dir},
        }
    )

    # Persist to DB
    try:
        with Session(engine) as session:
            db_run = DBTestRun(
                id=run_id,
                spec_name=Path(spec_path).name,
                status="running",
                test_type="api",
                test_name=Path(spec_path).name,
                project_id=project_id,
                current_stage="pipeline",
                stage_message="Starting API test pipeline...",
                started_at=datetime.utcnow(),
            )
            session.add(db_run)
            session.commit()
    except Exception as e:
        logger.warning(f"Failed to create DBTestRun for {run_id}: {e}")

    cmd = [
        sys.executable,
        "orchestrator/cli.py",
        spec_path,
        "--run-dir",
        run_dir,
        "--browser",
        "chromium",
    ]

    env = os.environ.copy()
    env["HEADLESS"] = "true"
    env["PLAYWRIGHT_HEADLESS"] = "true"
    if project_id:
        env["PROJECT_ID"] = project_id

    log_file = run_dir_path / "execution.log"

    try:
        with open(log_file, "w") as f:
            process = subprocess.Popen(
                cmd,
                cwd=BASE_DIR,
                stdout=f,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
            )

            _api_jobs[job_id].update(
                {
                    "stage": "running",
                    "message": "Pipeline running (generate + test + heal)...",
                }
            )

            try:
                process.wait(timeout=3600)
            except subprocess.TimeoutExpired:
                logger.warning(f"API test job {job_id} timed out, killing")
                import signal as _signal

                try:
                    os.killpg(os.getpgid(process.pid), _signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    process.kill()
                process.wait(timeout=10)

        # Read the result from status.txt / execution.log
        status_file = run_dir_path / "status.txt"
        final_status = "unknown"
        if status_file.exists():
            final_status = status_file.read_text().strip()

        # Parse log for healing info
        log_content = ""
        if log_file.exists():
            log_content = log_file.read_text(errors="replace")

        healed = "healed" in log_content.lower() or "healing attempt" in log_content.lower()
        healing_attempts = log_content.lower().count("healing attempt")

        # Parse structured test results
        first_failure = None
        json_results_path = run_dir_path / "test-results.json"
        try:
            from utils.test_results_parser import get_first_failure_message

            first_failure = get_first_failure_message(str(json_results_path))
        except Exception:
            pass

        # Find generated test path (check project-scoped dir first)
        test_path = None
        tests_dir_for_run = _get_tests_dir(project_id)
        search_patterns = [tests_dir_for_run / "api", tests_dir_for_run]
        if project_id and project_id != "default":
            search_patterns.extend([TESTS_DIR / "api", TESTS_DIR])
        for pattern in search_patterns:
            if pattern.exists():
                for ts in pattern.glob("*.spec.ts"):
                    # Check if recently modified (within last 5 min)
                    if time.time() - ts.stat().st_mtime < 300:
                        test_path = str(ts.relative_to(BASE_DIR))
                        break
                if test_path:
                    break

        passed = final_status in ("passed", "success", "completed")

        _api_jobs[job_id].update(
            {
                "status": "completed",
                "stage": "done",
                "message": f"Test {'passed' if passed else 'failed'}"
                + (f" (healed after {healing_attempts} attempt(s))" if healed else ""),
                "result": {
                    "run_id": run_id,
                    "run_dir": run_dir,
                    "test_path": test_path,
                    "passed": passed,
                    "healed": healed,
                    "healing_attempts": healing_attempts,
                    "exit_code": process.returncode,
                    "final_status": final_status,
                    "first_failure": first_failure,
                },
                "completed_at": time.time(),
            }
        )

        # Persist job summary to run dir for recovery after restart
        try:
            import json as _json

            job_result_file = run_dir_path / "job_result.json"
            job_result_file.write_text(
                _json.dumps(
                    {
                        "job_id": job_id,
                        "status": _api_jobs[job_id]["status"],
                        "stage": _api_jobs[job_id].get("stage"),
                        "message": _api_jobs[job_id].get("message"),
                        "result": _api_jobs[job_id].get("result"),
                        "started_at": _api_jobs[job_id].get("started_at"),
                        "completed_at": _api_jobs[job_id].get("completed_at"),
                        "spec_path": _api_jobs[job_id].get("spec_path"),
                    },
                    indent=2,
                )
            )
        except Exception:
            pass

        # Update DB record
        try:
            with Session(engine) as session:
                db_run = session.get(DBTestRun, run_id)
                if db_run:
                    db_run.status = "passed" if passed else "failed"
                    db_run.completed_at = datetime.utcnow()
                    db_run.current_stage = "done"
                    db_run.stage_message = _api_jobs[job_id].get("message", "")
                    if not passed:
                        db_run.error_message = first_failure or _api_jobs[job_id].get("message", "Test failed")
                    session.add(db_run)
                    session.commit()
        except Exception as e:
            logger.warning(f"Failed to update DBTestRun for {run_id}: {e}")

    except Exception as e:
        logger.error(f"API test run failed for job {job_id}: {e}")
        _api_jobs[job_id].update(
            {
                "status": "failed",
                "stage": "error",
                "message": str(e),
                "completed_at": time.time(),
            }
        )
        # Update DB record on failure
        try:
            with Session(engine) as session:
                db_run = session.get(DBTestRun, run_id)
                if db_run:
                    db_run.status = "failed"
                    db_run.completed_at = datetime.utcnow()
                    db_run.current_stage = "error"
                    db_run.error_message = str(e)
                    session.add(db_run)
                    session.commit()
        except Exception as db_err:
            logger.warning(f"Failed to update DBTestRun on error for {run_id}: {db_err}")


def _run_direct_test_sync(job_id: str, run_id: str, test_path: str, spec_name: str, project_id: str):
    """Run an already-generated test file directly with npx playwright test."""
    run_dir_path = RUNS_DIR / run_id
    run_dir_path.mkdir(parents=True, exist_ok=True)

    # Create DB record
    try:
        with Session(engine) as session:
            db_run = DBTestRun(
                id=run_id,
                spec_name=spec_name,
                status="running",
                test_type="api",
                test_name=spec_name,
                project_id=project_id,
                current_stage="executing",
                stage_message="Running test directly...",
                started_at=datetime.utcnow(),
            )
            session.add(db_run)
            session.commit()
    except Exception as e:
        logger.warning(f"Failed to create DBTestRun for direct run {run_id}: {e}")

    json_results_file = run_dir_path / "test-results.json"

    cmd = [
        "npx",
        "playwright",
        "test",
        test_path,
        "--reporter=list,html,json",
        "--project",
        "chromium",
        "--timeout=120000",
    ]

    env = os.environ.copy()
    env["HEADLESS"] = "true"
    env["PLAYWRIGHT_HEADLESS"] = "true"
    env["PLAYWRIGHT_JSON_OUTPUT_FILE"] = str(json_results_file)

    log_file = run_dir_path / "execution.log"

    try:
        with open(log_file, "w") as f:
            process = subprocess.Popen(
                cmd,
                cwd=BASE_DIR,
                stdout=f,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
            )

            _api_jobs[job_id].update(
                {
                    "stage": "executing",
                    "message": "Running test...",
                }
            )

            try:
                process.wait(timeout=300)
            except subprocess.TimeoutExpired:
                logger.warning(f"Direct test job {job_id} timed out")
                import signal as _signal

                try:
                    os.killpg(os.getpgid(process.pid), _signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    process.kill()
                process.wait(timeout=10)

        initial_passed = process.returncode == 0

        # Parse structured test results
        first_failure = None
        try:
            from utils.test_results_parser import get_first_failure_message

            first_failure = get_first_failure_message(str(json_results_file))
        except Exception:
            pass

        # === HEALING LOOP ===
        # If test failed, attempt up to 3 healing iterations
        passed = initial_passed
        healing_attempts = 0
        healing_history = []

        if not passed:
            max_heal = 3
            error_log = ""
            try:
                error_log = log_file.read_text(errors="replace")
            except Exception:
                pass

            for attempt in range(1, max_heal + 1):
                _api_jobs[job_id].update(
                    {
                        "stage": "healing",
                        "message": f"Healing attempt {attempt}/{max_heal}...",
                    }
                )
                # Update DB stage
                try:
                    with Session(engine) as session:
                        db_run = session.get(DBTestRun, run_id)
                        if db_run:
                            db_run.current_stage = "healing"
                            db_run.stage_message = f"Healing attempt {attempt}/{max_heal}..."
                            db_run.healing_attempt = attempt
                            session.add(db_run)
                            session.commit()
                except Exception:
                    pass

                error_before = first_failure or "Test failed"
                code_changed = False
                heal_result_status = "failed"

                try:
                    from workflows.native_api_healer import NativeApiHealer

                    healer = NativeApiHealer()
                    # Read spec content for healing context
                    spec_content = ""
                    spec_file_path = run_dir_path / "spec.md"
                    if not spec_file_path.exists():
                        # Try to find spec from the test file path
                        test_file = Path(BASE_DIR) / test_path
                        spec_stem = test_file.stem.split(".")[0]
                        for specs_dir in [SPECS_DIR, SPECS_DIR / "api"]:
                            candidate = specs_dir / f"{spec_stem}.md"
                            if candidate.exists():
                                spec_content = candidate.read_text(errors="replace")
                                break
                    else:
                        spec_content = spec_file_path.read_text(errors="replace")

                    test_file_abs = str(Path(BASE_DIR) / test_path)
                    fixed_code = asyncio.run(healer.heal_test(test_file_abs, error_log, spec_content))
                    code_changed = bool(fixed_code)
                except Exception as heal_err:
                    logger.warning(f"Healing attempt {attempt} error: {heal_err}")
                    healing_history.append(
                        {
                            "attempt": attempt,
                            "error_before": error_before,
                            "code_changed": False,
                            "result": "error",
                        }
                    )
                    continue

                if not code_changed:
                    healing_history.append(
                        {
                            "attempt": attempt,
                            "error_before": error_before,
                            "code_changed": False,
                            "result": "no_change",
                        }
                    )
                    continue

                # Re-run the test
                _api_jobs[job_id].update(
                    {
                        "stage": "retesting",
                        "message": f"Re-running test after healing attempt {attempt}...",
                    }
                )

                rerun_log = run_dir_path / f"execution_heal_{attempt}.log"
                try:
                    with open(rerun_log, "w") as rf:
                        rerun_proc = subprocess.Popen(
                            cmd,
                            cwd=BASE_DIR,
                            stdout=rf,
                            stderr=subprocess.STDOUT,
                            env=env,
                            start_new_session=True,
                        )
                        rerun_proc.wait(timeout=300)
                except subprocess.TimeoutExpired:
                    try:
                        import signal as _signal

                        os.killpg(os.getpgid(rerun_proc.pid), _signal.SIGKILL)
                    except (ProcessLookupError, OSError):
                        rerun_proc.kill()
                    rerun_proc.wait(timeout=10)

                passed = rerun_proc.returncode == 0
                healing_attempts = attempt

                # Re-parse failure message
                try:
                    first_failure = get_first_failure_message(str(json_results_file))
                except Exception:
                    pass

                heal_result_status = "passed" if passed else "failed"
                healing_history.append(
                    {
                        "attempt": attempt,
                        "error_before": error_before,
                        "code_changed": True,
                        "result": heal_result_status,
                    }
                )

                if passed:
                    logger.info(f"Direct test healed after {attempt} attempt(s)")
                    break

                # Update error_log for next healing attempt
                try:
                    error_log = rerun_log.read_text(errors="replace")
                except Exception:
                    pass

            # Save healing history
            if healing_history:
                try:
                    (run_dir_path / "healing_history.json").write_text(json.dumps(healing_history, indent=2))
                except Exception:
                    pass

        healed = passed and healing_attempts > 0

        _api_jobs[job_id].update(
            {
                "status": "completed",
                "stage": "done",
                "message": f"Test {'passed' if passed else 'failed'}"
                + (f" (healed after {healing_attempts} attempt(s))" if healed else ""),
                "result": {
                    "run_id": run_id,
                    "run_dir": str(run_dir_path),
                    "test_path": test_path,
                    "passed": passed,
                    "healed": healed,
                    "healing_attempts": healing_attempts,
                    "exit_code": 0 if passed else process.returncode,
                    "first_failure": first_failure,
                },
                "completed_at": time.time(),
            }
        )

        # Update DB record
        try:
            with Session(engine) as session:
                db_run = session.get(DBTestRun, run_id)
                if db_run:
                    db_run.status = "passed" if passed else "failed"
                    db_run.completed_at = datetime.utcnow()
                    db_run.current_stage = "done"
                    db_run.stage_message = f"Test {'passed' if passed else 'failed'}" + (
                        f" (healed after {healing_attempts} attempt(s))" if healed else ""
                    )
                    db_run.healing_attempt = healing_attempts if healing_attempts > 0 else None
                    if not passed:
                        db_run.error_message = first_failure or f"Test failed with exit code {process.returncode}"
                    session.add(db_run)
                    session.commit()
        except Exception as e:
            logger.warning(f"Failed to update DBTestRun for direct run {run_id}: {e}")

    except Exception as e:
        logger.error(f"Direct test run failed for job {job_id}: {e}")
        _api_jobs[job_id].update(
            {
                "status": "failed",
                "stage": "error",
                "message": str(e),
                "completed_at": time.time(),
            }
        )
        try:
            with Session(engine) as session:
                db_run = session.get(DBTestRun, run_id)
                if db_run:
                    db_run.status = "failed"
                    db_run.completed_at = datetime.utcnow()
                    db_run.current_stage = "error"
                    db_run.error_message = str(e)
                    session.add(db_run)
                    session.commit()
        except Exception as db_err:
            logger.warning(f"Failed to update DBTestRun on error for direct run {run_id}: {db_err}")


# ========== Endpoints ==========


@router.get("/specs")
async def list_api_specs(
    project_id: str = Query("default"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None),
    sort: str = Query("name"),
    status_filter: str | None = Query(None),
    folder: str | None = Query(None),
    tags: str | None = Query(None),
):
    """List all API-type test specifications with pagination, search, filtering, and sorting."""
    return _scan_api_specs(
        project_id,
        search=search,
        limit=limit,
        offset=offset,
        sort=sort,
        status_filter=status_filter,
        folder=folder,
        tags=tags,
    )


@router.get("/specs/{name:path}")
async def get_api_spec(name: str, project_id: str = Query("default")):
    """Get a single API spec content."""
    # Search for the spec file in project-scoped directory first, then global
    target = None
    for specs_dir in [_get_specs_dir(project_id), SPECS_DIR]:
        for md_file in specs_dir.rglob("*.md"):
            if md_file.name == name:
                target = md_file
                break
        if target:
            break

    if not target or not target.exists():
        raise HTTPException(status_code=404, detail=f"Spec '{name}' not found")

    content = target.read_text(encoding="utf-8")
    return {
        "name": target.name,
        "path": str(target.relative_to(BASE_DIR)),
        "content": content,
    }


@router.post("/specs")
async def create_api_spec(req: CreateApiSpecRequest):
    """Create a new API spec file."""
    # Ensure name ends with .md
    name = req.name if req.name.endswith(".md") else f"{req.name}.md"

    # Write to specs/[project]/api/ subfolder
    specs_base = _get_specs_dir(req.project_id)
    api_dir = specs_base / "api"
    api_dir.mkdir(parents=True, exist_ok=True)
    target = api_dir / name

    if target.exists():
        raise HTTPException(status_code=409, detail=f"Spec '{name}' already exists")

    # Auto-add Type: API if missing
    content = req.content
    if "## Type: API" not in content and "## Type: api" not in content:
        # Insert after the first heading
        lines = content.split("\n")
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.startswith("# "):
                insert_idx = i + 1
                break
        lines.insert(insert_idx, "\n## Type: API\n")
        content = "\n".join(lines)

    target.write_text(content, encoding="utf-8")
    logger.info(f"Created API spec: {target}")
    return {
        "name": target.name,
        "path": str(target.relative_to(BASE_DIR)),
        "message": "API spec created successfully",
    }


@router.put("/specs/{name:path}/tags")
async def update_spec_tags(name: str, req: UpdateTagsRequest):
    """Update tags for an API spec using SpecMetadata."""
    try:
        with Session(engine) as session:
            meta = session.get(SpecMetadata, name)
            if meta:
                meta.tags = req.tags
                meta.project_id = req.project_id
            else:
                meta = SpecMetadata(
                    spec_name=name,
                    tags_json=json.dumps(req.tags),
                    project_id=req.project_id,
                )
            session.add(meta)
            session.commit()
            session.refresh(meta)
            return {"spec_name": name, "tags": meta.tags}
    except Exception as e:
        logger.error(f"Failed to update tags for {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/specs/{name:path}")
async def update_api_spec(name: str, req: UpdateApiSpecRequest, project_id: str = Query("default")):
    """Update an existing API spec."""
    target = None
    for specs_dir in [_get_specs_dir(project_id), SPECS_DIR]:
        for md_file in specs_dir.rglob("*.md"):
            if md_file.name == name:
                target = md_file
                break
        if target:
            break

    if not target or not target.exists():
        raise HTTPException(status_code=404, detail=f"Spec '{name}' not found")

    target.write_text(req.content, encoding="utf-8")
    return {"name": target.name, "path": str(target.relative_to(BASE_DIR)), "message": "Spec updated"}


@router.post("/generate")
async def generate_api_test(req: GenerateTestRequest, background_tasks: BackgroundTasks):
    """Generate a Playwright API test from a spec. Returns job ID for polling."""
    _cleanup_old_jobs()

    # Find the spec file
    specs_dir = _get_specs_dir()
    target = None
    for md_file in specs_dir.rglob("*.md"):
        if md_file.name == req.spec_name:
            target = md_file
            break

    if not target or not target.exists():
        raise HTTPException(status_code=404, detail=f"Spec '{req.spec_name}' not found")

    import uuid

    job_id = str(uuid.uuid4())[:8]
    background_tasks.add_task(_run_generate_test, job_id, str(target), req.project_id)
    return {"job_id": job_id, "status": "running", "message": "API test generation started"}


@router.post("/import-openapi")
async def import_openapi(req: ImportOpenApiRequest, background_tasks: BackgroundTasks):
    """Import OpenAPI spec from URL and generate tests."""
    _cleanup_old_jobs()

    if not req.url:
        raise HTTPException(status_code=400, detail="URL is required")

    import uuid

    job_id = str(uuid.uuid4())[:8]
    background_tasks.add_task(_run_import_openapi, job_id, req.url, req.feature_filter, req.project_id)
    return {"job_id": job_id, "status": "running", "message": "OpenAPI import started"}


@router.post("/import-openapi-file")
async def import_openapi_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    feature_filter: str | None = Query(None),
    project_id: str = Query("default"),
):
    """Import OpenAPI spec from uploaded file and generate tests."""
    _cleanup_old_jobs()

    # Save uploaded file to temp location
    import tempfile

    suffix = ".json" if file.filename and file.filename.endswith(".json") else ".yaml"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    import uuid

    job_id = str(uuid.uuid4())[:8]
    background_tasks.add_task(_run_import_openapi_file, job_id, tmp_path, feature_filter, project_id, file.filename)
    return {"job_id": job_id, "status": "running", "message": "OpenAPI file import started"}


@router.post("/edge-cases")
async def generate_edge_cases(req: EdgeCaseRequest, background_tasks: BackgroundTasks):
    """Generate edge case and security tests from an API spec."""
    _cleanup_old_jobs()

    spec_path = BASE_DIR / req.spec_path
    if not spec_path.exists():
        raise HTTPException(status_code=404, detail=f"Spec file not found: {req.spec_path}")

    import uuid

    job_id = str(uuid.uuid4())[:8]
    background_tasks.add_task(_run_edge_cases, job_id, str(spec_path), req.project_id)
    return {"job_id": job_id, "status": "running", "message": "Edge case generation started"}


@router.post("/run")
async def run_api_test(req: RunApiTestRequest, background_tasks: BackgroundTasks):
    """Run an API test spec through generate + run + heal pipeline."""
    _cleanup_old_jobs()

    spec_path = BASE_DIR / req.spec_path
    if not spec_path.exists():
        raise HTTPException(status_code=404, detail=f"Spec file not found: {req.spec_path}")

    # Check for placeholder URLs before launching the pipeline
    import re
    from urllib.parse import urlparse

    PLACEHOLDER_DOMAINS = {"api.example.com", "example.com", "localhost:0"}
    try:
        spec_content = spec_path.read_text(errors="replace")
        url_match = re.search(r"##\s+Base\s+URL:\s*(\S+)", spec_content)
        if url_match:
            parsed = urlparse(url_match.group(1))
            host = parsed.hostname or ""
            netloc = parsed.netloc or ""
            if host in PLACEHOLDER_DOMAINS or netloc in PLACEHOLDER_DOMAINS:
                import uuid

                job_id = str(uuid.uuid4())[:8]
                _api_jobs[job_id] = {
                    "status": "failed",
                    "stage": "validation",
                    "message": f"Base URL '{url_match.group(1)}' is a placeholder. Edit the spec to set a real API endpoint before running.",
                    "started_at": time.time(),
                    "completed_at": time.time(),
                    "result": None,
                    "spec_path": req.spec_path,
                    "project_id": req.project_id,
                }
                return {"job_id": job_id, "status": "failed", "message": _api_jobs[job_id]["message"]}
    except Exception:
        pass  # If we can't read/parse, proceed with the run

    import uuid

    job_id = str(uuid.uuid4())[:8]
    _api_jobs[job_id] = {
        "status": "running",
        "stage": "queued",
        "message": "Queuing API test run...",
        "started_at": time.time(),
        "result": None,
        "completed_at": None,
        "spec_path": req.spec_path,
        "project_id": req.project_id,
    }

    # Run in executor since the subprocess blocks
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_api_test_sync, job_id, str(spec_path), req.project_id)

    return {"job_id": job_id, "status": "running", "message": "API test run started"}


@router.post("/run-direct")
async def run_direct_test(req: RunDirectRequest):
    """Run an already-generated test file directly (no generation/healing pipeline)."""
    _cleanup_old_jobs()

    test_file = BASE_DIR / req.test_path
    if not test_file.exists():
        raise HTTPException(status_code=404, detail=f"Test file not found: {req.test_path}")

    import uuid

    job_id = str(uuid.uuid4())[:8]
    run_id = f"api-direct-{job_id}"
    spec_name = req.spec_name or test_file.stem

    _api_jobs[job_id] = {
        "status": "running",
        "stage": "queued",
        "message": "Queuing direct test run...",
        "started_at": time.time(),
        "result": {"run_id": run_id, "test_path": req.test_path, "run_dir": str(RUNS_DIR / run_id)},
        "completed_at": None,
        "spec_path": req.test_path,
        "project_id": req.project_id,
    }

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_direct_test_sync, job_id, run_id, req.test_path, spec_name, req.project_id)

    return {"job_id": job_id, "run_id": run_id, "status": "running", "message": "Direct test run started"}


@router.get("/jobs")
async def list_jobs(status: str | None = Query(None), project_id: str | None = Query(None)):
    """List all tracked API test jobs (for recovery on page refresh)."""
    _cleanup_old_jobs()
    jobs = []
    for job_id, job in _api_jobs.items():
        if status and job["status"] != status:
            continue
        if project_id and job.get("project_id") and job["project_id"] != project_id:
            continue
        jobs.append(
            {
                "job_id": job_id,
                "status": job["status"],
                "stage": job.get("stage"),
                "message": job.get("message"),
                "result": job.get("result"),
                "started_at": job.get("started_at"),
                "completed_at": job.get("completed_at"),
                "spec_path": job.get("spec_path"),
                "project_id": job.get("project_id"),
            }
        )
    return sorted(jobs, key=lambda x: x.get("started_at") or 0, reverse=True)


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Get the status of a background job."""
    job = _api_jobs.get(job_id)
    if not job:
        # Fallback: check DB for completed runs that match the job_id
        # The run_id is typically "api-{job_id}" or "api-direct-{job_id}"
        try:
            with Session(engine) as session:
                for candidate_run_id in [f"api-{job_id}", f"api-direct-{job_id}", job_id]:
                    db_run = session.get(DBTestRun, candidate_run_id)
                    if db_run:
                        return JobStatusResponse(
                            job_id=job_id,
                            status=db_run.status,
                            stage=db_run.current_stage,
                            message=db_run.stage_message or db_run.error_message,
                            result={
                                "run_id": db_run.id,
                                "passed": db_run.status == "passed",
                            },
                        )
        except Exception as e:
            logger.warning(f"DB fallback lookup failed for job {job_id}: {e}")
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return JobStatusResponse(
        job_id=job_id,
        status=job["status"],
        stage=job.get("stage"),
        message=job.get("message"),
        result=job.get("result"),
    )


@router.get("/jobs/{job_id}/logs")
async def get_job_logs(job_id: str, tail: int = Query(200, ge=1, le=5000)):
    """Get execution logs for a running or completed job."""
    job = _api_jobs.get(job_id)
    if not job:
        # Fallback: try to find run directory from DB
        run_dir = None
        try:
            with Session(engine) as session:
                for candidate_run_id in [f"api-{job_id}", f"api-direct-{job_id}", job_id]:
                    db_run = session.get(DBTestRun, candidate_run_id)
                    if db_run:
                        run_dir = str(RUNS_DIR / db_run.id)
                        break
        except Exception as e:
            logger.warning(f"DB fallback lookup for logs failed for job {job_id}: {e}")
        if not run_dir:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
        # Use the DB-derived run_dir below
        log_file = Path(run_dir) / "execution.log"
        if not log_file.exists():
            return {"job_id": job_id, "logs": "", "line_count": 0}
        try:
            content = log_file.read_text(errors="replace")
            lines = content.splitlines()
            total = len(lines)
            tail_lines = lines[-tail:] if len(lines) > tail else lines
            return {
                "job_id": job_id,
                "logs": "\n".join(tail_lines),
                "line_count": total,
                "truncated": total > tail,
            }
        except Exception as e:
            return {"job_id": job_id, "logs": f"Error reading logs: {e}", "line_count": 0}

    run_dir = job.get("result", {}).get("run_dir") if job.get("result") else None
    if not run_dir:
        return {"job_id": job_id, "logs": "", "line_count": 0}

    log_file = Path(run_dir) / "execution.log"
    if not log_file.exists():
        return {"job_id": job_id, "logs": "", "line_count": 0}

    try:
        content = log_file.read_text(errors="replace")
        lines = content.splitlines()
        total = len(lines)
        # Return last N lines
        tail_lines = lines[-tail:] if len(lines) > tail else lines
        return {
            "job_id": job_id,
            "logs": "\n".join(tail_lines),
            "line_count": total,
            "truncated": total > tail,
        }
    except Exception as e:
        return {"job_id": job_id, "logs": f"Error reading logs: {e}", "line_count": 0}


@router.get("/generated-tests")
async def list_generated_tests(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None),
    sort: str = Query("modified"),
    status_filter: str | None = Query(None),
    project_id: str = Query("default"),
):
    """List all generated API test files with pagination, search, sorting, and status."""
    return _scan_generated_tests(
        search=search,
        limit=limit,
        offset=offset,
        sort=sort,
        status_filter=status_filter,
        project_id=project_id,
    )


@router.get("/generated-tests/summary")
async def generated_tests_summary(project_id: str = Query("default")):
    """Get aggregate status counts for generated API tests."""
    data = _scan_generated_tests(limit=9999, project_id=project_id)
    tests = data["items"]

    total_files = len(tests)
    total_tests = sum(t.get("test_count", 0) for t in tests)
    passed = sum(1 for t in tests if t.get("last_run_status") == "passed")
    failed = sum(1 for t in tests if t.get("last_run_status") == "failed")
    not_run = sum(1 for t in tests if t.get("last_run_status") is None)

    return {
        "total_files": total_files,
        "total_tests": total_tests,
        "passed": passed,
        "failed": failed,
        "not_run": not_run,
    }


@router.get("/generated-tests/{name:path}")
async def get_generated_test(name: str, project_id: str = Query("default")):
    """Read a generated API test file."""
    tests_dir = _get_tests_dir(project_id)
    # Search in project-scoped dir first, then fallback to global
    search_bases = [tests_dir, tests_dir / "api"]
    if project_id and project_id != "default":
        search_bases.extend([TESTS_DIR, TESTS_DIR / "api"])
    for base in search_bases:
        target = base / name
        if target.exists():
            content = target.read_text(encoding="utf-8")
            return {
                "name": target.name,
                "path": str(target.relative_to(BASE_DIR)),
                "content": content,
            }

    raise HTTPException(status_code=404, detail=f"Generated test '{name}' not found")


class UpdateGeneratedTestRequest(BaseModel):
    content: str


@router.put("/generated-tests/{name:path}")
async def update_generated_test(name: str, req: UpdateGeneratedTestRequest, project_id: str = Query("default")):
    """Save edited content to an existing generated API test file."""
    tests_dir = _get_tests_dir(project_id)
    search_bases = [tests_dir, tests_dir / "api"]
    if project_id and project_id != "default":
        search_bases.extend([TESTS_DIR, TESTS_DIR / "api"])
    for base in search_bases:
        target = base / name
        if target.exists():
            target.write_text(req.content, encoding="utf-8")
            return {
                "name": target.name,
                "path": str(target.relative_to(BASE_DIR)),
                "message": "Test file updated",
            }

    raise HTTPException(status_code=404, detail=f"Generated test '{name}' not found")


@router.delete("/generated-tests/{name:path}")
async def delete_generated_test(name: str, project_id: str = Query("default")):
    """Delete a generated API test file."""
    tests_dir = _get_tests_dir(project_id)
    search_bases = [tests_dir, tests_dir / "api"]
    if project_id and project_id != "default":
        search_bases.extend([TESTS_DIR, TESTS_DIR / "api"])
    for base in search_bases:
        target = base / name
        if target.exists():
            target.unlink()
            logger.info(f"Deleted generated test: {target}")
            return {"message": f"Test file '{name}' deleted"}

    raise HTTPException(status_code=404, detail=f"Generated test '{name}' not found")


@router.get("/runs")
async def list_api_runs(
    project_id: str | None = Query(None),
    spec_name: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    """List API test runs from DB with pagination and filters."""
    query = select(DBTestRun).where(DBTestRun.test_type == "api")

    if project_id:
        if project_id == "default":
            query = query.where((DBTestRun.project_id == "default") | (DBTestRun.project_id == None))
        else:
            query = query.where(DBTestRun.project_id == project_id)
    if spec_name:
        query = query.where(DBTestRun.spec_name == spec_name)
    if status:
        query = query.where(DBTestRun.status == status)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = session.exec(count_query).one()

    # Paginate
    query = query.order_by(DBTestRun.created_at.desc())
    query = query.offset(offset).limit(limit)
    runs = session.exec(query).all()

    return {
        "runs": [
            {
                "id": r.id,
                "spec_name": r.spec_name,
                "status": r.status,
                "test_type": r.test_type,
                "current_stage": r.current_stage,
                "stage_message": r.stage_message,
                "error_message": r.error_message,
                "created_at": (r.created_at.isoformat() + "Z") if r.created_at else None,
                "started_at": (r.started_at.isoformat() + "Z") if r.started_at else None,
                "completed_at": (r.completed_at.isoformat() + "Z") if r.completed_at else None,
                "project_id": r.project_id,
            }
            for r in runs
        ],
        "total": total,
        "has_more": (offset + limit) < total,
    }


@router.get("/runs/latest-by-spec")
async def latest_runs_by_spec(
    project_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    session: Session = Depends(get_session),
):
    """Get the latest API test run for each spec_name."""
    # Subquery: max created_at per spec_name among api test runs
    subq = select(
        DBTestRun.spec_name,
        func.max(DBTestRun.created_at).label("max_created"),
    ).where(DBTestRun.test_type == "api")
    if project_id:
        if project_id == "default":
            subq = subq.where((DBTestRun.project_id == "default") | (DBTestRun.project_id == None))
        else:
            subq = subq.where(DBTestRun.project_id == project_id)
    subq = subq.group_by(DBTestRun.spec_name).subquery()

    query = (
        select(DBTestRun)
        .join(
            subq,
            and_(
                DBTestRun.spec_name == subq.c.spec_name,
                DBTestRun.created_at == subq.c.max_created,
            ),
        )
        .where(DBTestRun.test_type == "api")
        .limit(limit)
    )
    runs = session.exec(query).all()

    result = {}
    for r in runs:
        result[r.spec_name] = {
            "id": r.id,
            "status": r.status,
            "current_stage": r.current_stage,
            "stage_message": r.stage_message,
            "error_message": r.error_message,
            "created_at": (r.created_at.isoformat() + "Z") if r.created_at else None,
            "started_at": (r.started_at.isoformat() + "Z") if r.started_at else None,
            "completed_at": (r.completed_at.isoformat() + "Z") if r.completed_at else None,
        }

    return {"specs": result}


@router.get("/runs/{run_id}")
async def get_api_run_detail(run_id: str, session: Session = Depends(get_session)):
    """Get rich details for a single API test run."""
    db_run = session.get(DBTestRun, run_id)
    if not db_run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    run_dir = RUNS_DIR / run_id

    # Parse test results
    test_results = None
    json_results_path = run_dir / "test-results.json"
    if json_results_path.exists():
        from utils.test_results_parser import parse_test_results

        test_results = parse_test_results(str(json_results_path))

    # Read generated code
    generated_code = None
    export_path = run_dir / "export.json"
    if export_path.exists():
        try:
            export_data = json.loads(export_path.read_text(errors="replace"))
            test_file_path = export_data.get("testFilePath")
            if test_file_path and Path(test_file_path).exists():
                generated_code = Path(test_file_path).read_text(errors="replace")
            elif export_data.get("code"):
                generated_code = export_data["code"]
        except Exception:
            pass

    # Read validation data
    validation = None
    validation_path = run_dir / "validation.json"
    if validation_path.exists():
        try:
            validation = json.loads(validation_path.read_text(errors="replace"))
        except Exception:
            pass

    # Read healing history
    healing_history = None
    history_path = run_dir / "healing_history.json"
    if history_path.exists():
        try:
            healing_history = json.loads(history_path.read_text(errors="replace"))
        except Exception:
            pass

    # Read spec content
    spec_content = None
    spec_path = run_dir / "spec.md"
    if spec_path.exists():
        try:
            spec_content = spec_path.read_text(errors="replace")
        except Exception:
            pass

    # Read execution log (last 500 lines)
    execution_log = None
    log_path = run_dir / "execution.log"
    if log_path.exists():
        try:
            lines = log_path.read_text(errors="replace").splitlines()
            execution_log = "\n".join(lines[-500:])
        except Exception:
            pass

    return {
        "id": db_run.id,
        "spec_name": db_run.spec_name,
        "status": db_run.status,
        "test_type": db_run.test_type,
        "created_at": (db_run.created_at.isoformat() + "Z") if db_run.created_at else None,
        "started_at": (db_run.started_at.isoformat() + "Z") if db_run.started_at else None,
        "completed_at": (db_run.completed_at.isoformat() + "Z") if db_run.completed_at else None,
        "project_id": db_run.project_id,
        "error_message": db_run.error_message,
        "current_stage": db_run.current_stage,
        "stage_message": db_run.stage_message,
        "healing_attempt": db_run.healing_attempt,
        "test_results": test_results,
        "generated_code": generated_code,
        "spec_content": spec_content,
        "execution_log": execution_log,
        "validation": validation,
        "healing_history": healing_history,
    }


@router.post("/runs/{run_id}/retry")
async def retry_api_run(run_id: str, session: Session = Depends(get_session)):
    """Retry a failed API test run by creating a new job."""
    db_run = session.get(DBTestRun, run_id)
    if not db_run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    if db_run.status == "running":
        raise HTTPException(status_code=409, detail="Run is still in progress")

    _cleanup_old_jobs()

    # Find the original spec
    spec_name = db_run.spec_name
    spec_path = None

    # Check run directory for spec
    run_dir = RUNS_DIR / run_id
    spec_in_run = run_dir / "spec.md"
    if spec_in_run.exists():
        spec_path = str(spec_in_run)
    else:
        # Search in specs directories
        for search_dir in [SPECS_DIR, SPECS_DIR / "api", _get_specs_dir(db_run.project_id or "default")]:
            candidate = search_dir / spec_name
            if candidate.exists():
                spec_path = str(candidate)
                break
            # Try without extension variations
            for md_file in search_dir.rglob("*.md"):
                if md_file.name == spec_name or md_file.stem == Path(spec_name).stem:
                    spec_path = str(md_file)
                    break
            if spec_path:
                break

    if not spec_path or not Path(spec_path).exists():
        raise HTTPException(status_code=404, detail=f"Original spec '{spec_name}' not found for retry")

    import uuid

    job_id = str(uuid.uuid4())[:8]
    project_id = db_run.project_id or "default"

    _api_jobs[job_id] = {
        "status": "running",
        "stage": "queued",
        "message": f"Retrying test run (original: {run_id})...",
        "started_at": time.time(),
        "result": None,
        "completed_at": None,
        "spec_path": spec_path,
    }

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_api_test_sync, job_id, spec_path, project_id)

    return {
        "job_id": job_id,
        "status": "running",
        "message": f"Retry started for {spec_name}",
        "original_run_id": run_id,
    }


@router.post("/specs/bulk-run")
async def bulk_run_specs(req: BulkRunRequest):
    """Run multiple API specs. Returns a batch job_id grouping individual jobs."""
    _cleanup_old_jobs()
    import uuid

    batch_id = f"batch-{str(uuid.uuid4())[:8]}"
    child_job_ids = []

    for spec_path in req.spec_paths:
        abs_path = BASE_DIR / spec_path
        if not abs_path.exists():
            logger.warning(f"Bulk run: spec not found, skipping: {spec_path}")
            continue

        job_id = str(uuid.uuid4())[:8]
        _api_jobs[job_id] = {
            "status": "running",
            "stage": "queued",
            "message": f"Queuing API test run for {spec_path}...",
            "started_at": time.time(),
            "result": None,
            "completed_at": None,
            "spec_path": spec_path,
            "project_id": req.project_id,
            "batch_id": batch_id,
        }
        child_job_ids.append(job_id)

        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, _run_api_test_sync, job_id, str(abs_path), req.project_id)

    _api_jobs[batch_id] = {
        "status": "running",
        "stage": "batch",
        "message": f"Batch run started with {len(child_job_ids)} spec(s)",
        "started_at": time.time(),
        "result": {"child_job_ids": child_job_ids},
        "completed_at": None,
        "project_id": req.project_id,
    }

    return {
        "job_id": batch_id,
        "child_job_ids": child_job_ids,
        "status": "running",
        "message": f"Batch run started for {len(child_job_ids)} spec(s)",
    }


@router.post("/specs/bulk-generate")
async def bulk_generate_specs(req: BulkGenerateRequest, background_tasks: BackgroundTasks):
    """Generate tests for multiple API specs. Returns a batch job_id."""
    _cleanup_old_jobs()
    import uuid

    batch_id = f"batch-gen-{str(uuid.uuid4())[:8]}"
    child_job_ids = []
    specs_dir = _get_specs_dir(req.project_id)

    for spec_name in req.spec_names:
        # Find the spec file
        target = None
        for md_file in specs_dir.rglob("*.md"):
            if md_file.name == spec_name:
                target = md_file
                break
        if not target:
            logger.warning(f"Bulk generate: spec not found, skipping: {spec_name}")
            continue

        job_id = str(uuid.uuid4())[:8]
        child_job_ids.append(job_id)
        background_tasks.add_task(_run_generate_test, job_id, str(target), req.project_id)

    _api_jobs[batch_id] = {
        "status": "running",
        "stage": "batch",
        "message": f"Batch generation started with {len(child_job_ids)} spec(s)",
        "started_at": time.time(),
        "result": {"child_job_ids": child_job_ids},
        "completed_at": None,
        "project_id": req.project_id,
    }

    return {
        "job_id": batch_id,
        "child_job_ids": child_job_ids,
        "status": "running",
        "message": f"Batch generation started for {len(child_job_ids)} spec(s)",
    }


@router.post("/specs/folder")
async def create_spec_folder(req: CreateFolderRequest):
    """Create a subdirectory under the project's specs/api/ directory."""
    specs_base = _get_specs_dir(req.project_id)
    api_dir = specs_base / "api"
    api_dir.mkdir(parents=True, exist_ok=True)

    folder_path = api_dir / req.folder_name
    if folder_path.exists():
        raise HTTPException(status_code=409, detail=f"Folder '{req.folder_name}' already exists")

    folder_path.mkdir(parents=True, exist_ok=True)
    logger.info(f"Created spec folder: {folder_path}")
    return {"folder": req.folder_name, "path": str(folder_path.relative_to(BASE_DIR)), "message": "Folder created"}


@router.delete("/specs/{name:path}")
async def delete_api_spec(name: str, project_id: str = Query("default")):
    """Delete an API spec file."""
    target = None
    for specs_dir in [_get_specs_dir(project_id), SPECS_DIR]:
        for md_file in specs_dir.rglob("*.md"):
            if md_file.name == name or str(md_file.relative_to(BASE_DIR)) == name:
                target = md_file
                break
        if target:
            break

    if not target or not target.exists():
        raise HTTPException(status_code=404, detail=f"Spec '{name}' not found")

    rel_path = str(target.relative_to(BASE_DIR))
    target.unlink()
    # Remove from cache
    _api_spec_cache.pop(str(target), None)
    logger.info(f"Deleted API spec: {rel_path}")
    return {"message": f"Spec '{name}' deleted", "path": rel_path}


@router.get("/import-history")
async def list_import_history(
    project_id: str = Query("default"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    """List OpenAPI import history with pagination."""
    query = select(OpenApiImportHistory)

    if project_id == "default":
        query = query.where((OpenApiImportHistory.project_id == "default") | (OpenApiImportHistory.project_id == None))
    else:
        query = query.where(OpenApiImportHistory.project_id == project_id)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = session.exec(count_query).one()

    # Paginate, newest first
    query = query.order_by(OpenApiImportHistory.created_at.desc())
    query = query.offset(offset).limit(limit)
    records = session.exec(query).all()

    return {
        "items": [
            {
                "id": r.id,
                "source_type": r.source_type,
                "source_url": r.source_url,
                "source_filename": r.source_filename,
                "feature_filter": r.feature_filter,
                "status": r.status,
                "files_generated": r.files_generated,
                "generated_paths": r.generated_paths,
                "error_message": r.error_message,
                "created_at": (r.created_at.isoformat() + "Z") if r.created_at else None,
                "completed_at": (r.completed_at.isoformat() + "Z") if r.completed_at else None,
            }
            for r in records
        ],
        "total": total,
        "has_more": (offset + limit) < total,
    }
