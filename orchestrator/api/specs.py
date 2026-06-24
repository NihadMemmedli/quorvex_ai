"""Spec file and spec metadata API routes."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from logging_config import get_logger

from .db import engine, get_session
from .models import (
    CreateFolderRequest,
    CreateFolderResponse,
    CreateSpecRequest,
    FolderTreeResponse,
    MovedItemInfo,
    MoveSpecRequest,
    MoveSpecResponse,
    RenameRequest,
    RenameResponse,
    UpdateGeneratedCodeRequest,
    UpdateMetadataRequest,
    UpdateSpecRequest,
)
from .models_db import SpecMetadata as DBSpecMetadata
from .models_db import TestrailCaseMapping, normalize_project_id
from .models_db import TestRun as DBTestRun
from .models_db import get_spec_metadata as get_db_spec_metadata
from .spec_files import (
    BASE_DIR,
    RUNS_DIR,
    SPECS_DIR,
    _spec_cache,
    _spec_info_cache,
    build_folder_tree,
    build_generated_test_index,
    get_cached_spec_info,
    get_try_code_path,
    get_try_code_path_fast,
    required_test_data_refs_for_spec,
    resolve_generated_code_path,
)

logger = get_logger(__name__)
router = APIRouter(tags=["specs"])

# ========= Specs =========


@router.get("/specs/list")
def list_specs_lightweight(
    project_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: str | None = None,
    tags: str | None = None,
    automated_only: bool = False,
    templates_only: bool = False,
    session: Session = Depends(get_session),
):
    """Lightweight spec listing with server-side pagination and filtering.

    Performance optimizations:
    - No file content loaded (saves ~80% response size)
    - Fast filename-based code path check (avoids scanning all run directories)
    - Cached spec type detection (avoids re-parsing files)
    - Server-side search, tag filtering, and automated-only filtering
    - Paginated response with summary stats

    Query params:
    - limit: Page size (1-200, default 50)
    - offset: Pagination offset (default 0)
    - search: Case-insensitive name search
    - tags: Comma-separated tag filter (matches specs with any of the given tags)
    - automated_only: Only return specs with generated code
    - templates_only: Return only specs stored under templates/
    """
    # Get spec names for this project if filtering
    project_spec_names = None
    excluded_spec_names = set()  # Specs explicitly assigned to other projects

    if project_id:
        if project_id == "default":
            # For default project: get specs explicitly assigned to OTHER projects (to exclude them)
            other_project_query = select(DBSpecMetadata.spec_name).where(
                (DBSpecMetadata.project_id != None) & (DBSpecMetadata.project_id != "default")
            )
            excluded_spec_names = set(session.exec(other_project_query).all())
            # project_spec_names stays None = don't filter by inclusion, use exclusion instead
        else:
            # For other projects: only include specs explicitly assigned to this project
            query = select(DBSpecMetadata.spec_name).where(DBSpecMetadata.project_id == project_id)
            project_spec_names = set(session.exec(query).all())

    # Parse tag filter
    tag_filter = set()
    if tags:
        tag_filter = {t.strip() for t in tags.split(",") if t.strip()}

    # Pre-fetch all metadata for tag lookup (single DB query)
    metadata_by_name: dict[str, list] = {}
    if tag_filter:
        meta_query = select(DBSpecMetadata.spec_name, DBSpecMetadata.tags_json)
        if project_id:
            if project_id == "default":
                meta_query = meta_query.where(
                    (DBSpecMetadata.project_id == project_id) | (DBSpecMetadata.project_id == None)
                )
            else:
                meta_query = meta_query.where(DBSpecMetadata.project_id == project_id)
        for row in session.exec(meta_query).all():
            try:
                parsed_tags = json.loads(row[1]) if row[1] else []
            except (json.JSONDecodeError, TypeError):
                parsed_tags = []
            metadata_by_name[row[0]] = parsed_tags

    search_lower = search.lower().strip() if search else None

    # Collect all matching specs with early filtering
    matching_specs = []
    total_all = 0  # Total specs in the requested listing mode (unfiltered)
    automated_count = 0  # Automated count across all specs in the requested listing mode
    all_tags_set: set = set()
    generated_test_index = build_generated_test_index(BASE_DIR, RUNS_DIR)

    if SPECS_DIR.exists():
        for f in SPECS_DIR.glob("**/*.md"):
            name = str(f.relative_to(SPECS_DIR))
            is_template = name.startswith("templates/")

            # Default listing excludes templates. Template consumers opt in with templates_only.
            if templates_only != is_template:
                continue

            # Apply project filter if specified
            if project_spec_names is not None and name not in project_spec_names:
                continue

            # For default project: exclude specs explicitly assigned to other projects
            if name in excluded_spec_names:
                continue

            # Fast direct path check first, then request-scoped generated test index.
            code_path = resolve_generated_code_path(f, generated_test_index, BASE_DIR)
            is_automated = bool(code_path)

            # Count totals before applying user filters
            total_all += 1
            if is_automated:
                automated_count += 1

            # Collect tags from metadata for summary (need all tags even for non-matching specs)
            spec_tags = metadata_by_name.get(name, []) if metadata_by_name else []

            # If we didn't pre-fetch metadata (no tag filter), we still need tags for summary
            # We'll collect them from DB after the loop to avoid N+1 queries
            # For now, skip tag collection during iteration if no tag filter

            # Apply search filter
            if search_lower and search_lower not in name.lower():
                continue

            # Apply tag filter
            if tag_filter:
                if not spec_tags or not tag_filter.intersection(spec_tags):
                    continue

            # Apply automated-only filter
            if automated_only and not is_automated:
                continue

            # Cached spec info detection
            spec_info = get_cached_spec_info(f)

            matching_specs.append(
                {
                    "name": name,
                    "path": str(f.absolute()),
                    "is_automated": is_automated,
                    "code_path": code_path,
                    "spec_type": spec_info["type"],
                    "test_count": spec_info["test_count"],
                    "categories": spec_info["categories"],
                }
            )

    # Collect all unique tags for summary (single DB query)
    all_tags_query = select(DBSpecMetadata.tags_json)
    if templates_only:
        all_tags_query = all_tags_query.where(DBSpecMetadata.spec_name.like("templates/%"))
    else:
        all_tags_query = all_tags_query.where(~DBSpecMetadata.spec_name.like("templates/%"))
    if project_id:
        if project_id == "default":
            all_tags_query = all_tags_query.where(
                (DBSpecMetadata.project_id == project_id) | (DBSpecMetadata.project_id == None)
            )
        else:
            all_tags_query = all_tags_query.where(DBSpecMetadata.project_id == project_id)
    for tags_json_val in session.exec(all_tags_query).all():
        if tags_json_val:
            try:
                tag_list = json.loads(tags_json_val)
                if isinstance(tag_list, list):
                    all_tags_set.update(tag_list)
            except (json.JSONDecodeError, TypeError):
                pass

    # Sort by name for consistent pagination
    matching_specs.sort(key=lambda s: s["name"].lower())

    total = len(matching_specs)
    paginated = matching_specs[offset : offset + limit]
    has_more = (offset + limit) < total

    return {
        "items": paginated,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "summary": {"total_all": total_all, "automated_count": automated_count, "all_tags": sorted(all_tags_set)},
    }


@router.get("/specs/folders", response_model=FolderTreeResponse)
def get_spec_folders(project_id: str | None = None, session: Session = Depends(get_session)):
    """Return folder tree structure with automated test counts.

    Only includes folders containing automated specs (with .spec.ts files).
    Optionally filtered by project_id to show only folders with specs from that project.
    """
    # Get project-filtered spec names if filtering
    project_spec_names = None
    excluded_spec_names = set()

    if project_id:
        if project_id == "default":
            # For default project: get specs explicitly assigned to OTHER projects (to exclude them)
            other_project_query = select(DBSpecMetadata.spec_name).where(
                (DBSpecMetadata.project_id != None) & (DBSpecMetadata.project_id != "default")
            )
            excluded_spec_names = set(session.exec(other_project_query).all())
            # project_spec_names stays None = don't filter by inclusion, use exclusion instead
        else:
            # For other projects: only include specs explicitly assigned to this project
            query = select(DBSpecMetadata.spec_name).where(DBSpecMetadata.project_id == project_id)
            project_spec_names = set(session.exec(query).all())

    generated_test_index = build_generated_test_index(BASE_DIR, RUNS_DIR)
    folders, total_specs = build_folder_tree(
        SPECS_DIR,
        project_spec_names,
        excluded_spec_names,
        generated_test_index=generated_test_index,
        base_dir=BASE_DIR,
    )
    return FolderTreeResponse(folders=folders, total_specs=total_specs)


@router.get("/specs/automated")
def list_automated_specs(
    tags: str | None = None,
    folder: str | None = None,
    search: str | None = None,
    project_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    """List only automated specs (with generated .spec.ts files).

    Returns specs with metadata for regression testing.

    Query parameters:
    - tags: Comma-separated tag filter (OR logic)
    - folder: Filter by folder path prefix
    - search: Case-insensitive spec name search
    - project_id: Filter by project ID
    - limit: Page size (default 50, max 100)
    - offset: Starting position for pagination
    """
    # Clamp limit
    limit = min(max(1, limit), 100)
    offset = max(0, offset)

    # Batch fetch all last runs in a single query instead of N+1 queries
    # Uses subquery to get the latest run for each spec
    from sqlalchemy import text

    last_runs_query = text("""
        SELECT t1.spec_name, t1.id, t1.status, t1.created_at
        FROM testrun t1
        INNER JOIN (
            SELECT spec_name, MAX(created_at) as max_created_at
            FROM testrun
            GROUP BY spec_name
        ) t2 ON t1.spec_name = t2.spec_name AND t1.created_at = t2.max_created_at
    """)

    last_runs_results = session.exec(last_runs_query).all()
    last_runs_map: dict[str, dict] = {
        row[0]: {"id": row[1], "status": row[2], "created_at": row[3]} for row in last_runs_results
    }

    # Batch fetch all spec metadata in a single query (safety cap at 10000)
    all_meta = session.exec(select(DBSpecMetadata).limit(10000)).all()
    meta_map: dict[str, DBSpecMetadata] = {m.spec_name: m for m in all_meta}

    all_specs = []
    tag_filter = tags.split(",") if tags else []
    search_lower = search.lower().strip() if search else None
    generated_test_index = build_generated_test_index(BASE_DIR, RUNS_DIR)

    if SPECS_DIR.exists():
        for f in SPECS_DIR.glob("**/*.md"):
            code_path = resolve_generated_code_path(f, generated_test_index, BASE_DIR)
            if not code_path:
                continue

            name = str(f.relative_to(SPECS_DIR))

            # Apply folder filter if specified
            if folder:
                if not name.startswith(folder + "/"):
                    continue

            if search_lower and search_lower not in name.lower():
                continue

            # Get metadata from pre-fetched map (O(1) lookup instead of DB query)
            meta = meta_map.get(name)
            spec_tags = meta.tags if meta else []

            # Apply project filter if specified
            # Specs with null project_id are treated as belonging to the "default" project
            if project_id:
                spec_project_id = meta.project_id if meta else None
                # Include specs that either match the project_id OR have no project (null) when filtering for default
                if spec_project_id != project_id:
                    if not (project_id == "default" and spec_project_id is None):
                        continue

            # Apply tag filter (OR logic) if specified
            if tag_filter and not any(tag in spec_tags for tag in tag_filter):
                continue

            # Cached spec info detection
            spec_info = get_cached_spec_info(f)

            # Get last run from pre-fetched map (O(1) lookup instead of DB query)
            last_run = last_runs_map.get(name)

            all_specs.append(
                {
                    "name": name,
                    "path": str(f.absolute()),
                    "code_path": code_path,
                    "required_test_data_refs": required_test_data_refs_for_spec(f, code_path),
                    "spec_type": spec_info["type"],
                    "test_count": spec_info["test_count"],
                    "categories": spec_info["categories"],
                    "tags": spec_tags,
                    "last_run_status": last_run["status"] if last_run else None,
                    "last_run_id": last_run["id"] if last_run else None,
                    "last_run_at": last_run["created_at"].isoformat() if last_run else None,
                }
            )

    # Sort by name for consistent pagination
    all_specs.sort(key=lambda x: x["name"].lower())

    # Apply pagination
    total = len(all_specs)
    paginated_specs = all_specs[offset : offset + limit]
    has_more = offset + limit < total

    return {
        "specs": paginated_specs,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "filtered_folder": folder,
        "filtered_search": search,
        "filtered_by_tags": tag_filter if tag_filter else None,
        "filtered_by_project": project_id,
    }


@router.get("/specs")
def list_specs(
    limit: int = Query(default=50, ge=1, le=200, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    project_id: str | None = Query(default=None, description="Project ID filter"),
    session: Session = Depends(get_session),
):
    """
    Paginated spec listing with metadata only (no content).

    For backward compatibility, returns specs array.
    Content removed to prevent memory issues at scale (100k+ specs).
    Use GET /specs/{name}/content to fetch individual spec content.
    """
    all_specs = []

    # Get project-filtered spec names if filtering by non-default project
    project_spec_names = None
    excluded_spec_names = set()

    if project_id:
        if project_id == "default":
            # For default project: exclude specs assigned to other projects
            other_project_query = select(DBSpecMetadata.spec_name).where(
                (DBSpecMetadata.project_id != None) & (DBSpecMetadata.project_id != "default")
            )
            excluded_spec_names = set(session.exec(other_project_query).all())
        else:
            # For other projects: only include specs explicitly assigned
            query = select(DBSpecMetadata.spec_name).where(DBSpecMetadata.project_id == project_id)
            project_spec_names = set(session.exec(query).all())

    if SPECS_DIR.exists():
        for f in SPECS_DIR.glob("**/*.md"):
            name = str(f.relative_to(SPECS_DIR))

            # Apply project filter
            if project_spec_names is not None and name not in project_spec_names:
                continue
            if name in excluded_spec_names:
                continue

            # Fast code path check - no run scanning
            code_path = get_try_code_path_fast(f)

            # Cached spec info detection
            spec_info = get_cached_spec_info(f)

            all_specs.append(
                {
                    "name": name,
                    "path": str(f.absolute()),
                    "is_automated": bool(code_path),
                    "code_path": code_path,
                    "spec_type": spec_info["type"],
                    "test_count": spec_info["test_count"],
                    "categories": spec_info["categories"],
                }
            )

    # Sort for consistent pagination
    all_specs.sort(key=lambda x: x["name"].lower())

    # Apply pagination
    total = len(all_specs)
    paginated = all_specs[offset : offset + limit]

    return {"specs": paginated, "total": total, "limit": limit, "offset": offset, "has_more": offset + limit < total}


@router.get("/specs/{name:path}/generated-code")
def get_generated_code(
    name: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
):
    """Get the generated test code for a spec."""
    spec_path = SPECS_DIR / name
    if not spec_path.exists():
        raise HTTPException(status_code=404, detail="Spec not found")

    # Filter by project_id if provided
    if project_id:
        meta = get_db_spec_metadata(session, name, project_id)
        if meta and meta.project_id:
            if project_id == "default":
                if meta.project_id not in (None, "default"):
                    raise HTTPException(status_code=404, detail="Spec not found")
            elif meta.project_id != project_id:
                raise HTTPException(status_code=404, detail="Spec not found")

    code_path = get_try_code_path(name, spec_path, BASE_DIR, RUNS_DIR)
    if not code_path or not Path(code_path).exists():
        raise HTTPException(status_code=404, detail="No generated test found")

    code_file = Path(code_path)
    return {
        "code_path": str(code_file.relative_to(BASE_DIR)),
        "content": code_file.read_text(),
        "last_modified": code_file.stat().st_mtime,
    }


@router.put("/specs/{name:path}/generated-code")
def update_generated_code(
    name: str,
    request: UpdateGeneratedCodeRequest,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    """Update the generated test code for a spec."""
    spec_path = SPECS_DIR / name
    if not spec_path.exists():
        raise HTTPException(status_code=404, detail="Spec not found")

    # Verify project ownership if project_id is provided
    if project_id:
        meta = get_db_spec_metadata(session, name, project_id)
        if meta and meta.project_id:
            # If spec has a project_id, it must match (unless checking default project with legacy data)
            if project_id == "default":
                if meta.project_id not in (None, "default"):
                    raise HTTPException(status_code=404, detail="Spec not found")
            elif meta.project_id != project_id:
                raise HTTPException(status_code=404, detail="Spec not found")

    code_path = get_try_code_path(name, spec_path, BASE_DIR, RUNS_DIR)
    if not code_path or not Path(code_path).exists():
        raise HTTPException(status_code=404, detail="No generated test found")

    Path(code_path).write_text(request.content)
    return {"status": "updated", "code_path": code_path}


class SplitSpecJobStatusResponse(BaseModel):
    job_id: str
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None
    project_id: str | None = None
    temporal_workflow_id: str | None = None
    temporal_run_id: str | None = None


@router.get("/specs/split-jobs/{job_id}", response_model=SplitSpecJobStatusResponse)
async def get_split_spec_job(job_id: str):
    """Poll a durable split job."""
    from orchestrator.services.domain_jobs import domain_job_to_dict, get_domain_job

    job = get_domain_job(job_id)
    if not job or job.job_type != "spec_split":
        raise HTTPException(status_code=404, detail="Job not found")
    return domain_job_to_dict(job)


@router.get("/specs/{name:path}")
def get_spec(
    name: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
):
    f = SPECS_DIR / name
    if not f.exists():
        raise HTTPException(status_code=404, detail="Spec not found")

    # Filter by project_id if provided
    if project_id:
        meta = get_db_spec_metadata(session, name, project_id)
        if meta and meta.project_id:
            if project_id == "default":
                if meta.project_id not in (None, "default"):
                    raise HTTPException(status_code=404, detail="Spec not found")
            elif meta.project_id != project_id:
                raise HTTPException(status_code=404, detail="Spec not found")

    code_path = get_try_code_path(name, f, BASE_DIR, RUNS_DIR)
    return {
        "name": str(f.relative_to(SPECS_DIR)),
        "path": str(f.absolute()),
        "content": f.read_text(),
        "is_automated": bool(code_path),
        "code_path": code_path,
    }


@router.post("/specs")
def create_spec(request: CreateSpecRequest, session: Session = Depends(get_session)):
    name = request.name
    if not name.endswith(".md"):
        name += ".md"
    f = SPECS_DIR / name
    if f.exists():
        raise HTTPException(status_code=400, detail="Spec already exists")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(request.content)

    # Register spec in database with project association
    if request.project_id:
        existing = get_db_spec_metadata(session, name, request.project_id)
        if not existing:
            meta = DBSpecMetadata(spec_name=name, project_id=request.project_id, tags_json="[]")
            session.add(meta)
        else:
            existing.project_id = request.project_id
        session.commit()

    _spec_cache.invalidate()
    return {"status": "created", "path": str(f.absolute())}


@router.put("/specs/{name:path}")
def update_spec(
    name: str,
    request: UpdateSpecRequest,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    f = SPECS_DIR / name
    if not f.exists():
        raise HTTPException(status_code=404, detail="Spec not found")

    # Verify project ownership if project_id is provided
    if project_id:
        meta = get_db_spec_metadata(session, name, project_id)
        if meta and meta.project_id:
            if project_id == "default":
                if meta.project_id not in (None, "default"):
                    raise HTTPException(status_code=404, detail="Spec not found")
            elif meta.project_id != project_id:
                raise HTTPException(status_code=404, detail="Spec not found")

    f.write_text(request.content)
    _spec_cache.invalidate()
    return {"status": "updated", "path": str(f.absolute())}


@router.delete("/specs/folder/{folder_path:path}")
def delete_folder(
    folder_path: str,
    delete_generated_tests: bool = False,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    """Delete a folder and all specs inside it."""
    import shutil

    folder = SPECS_DIR / folder_path
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=404, detail="Folder not found")

    deleted_specs = []
    deleted_tests = []

    # Collect all spec files in folder recursively
    spec_files = list(folder.glob("**/*.md"))

    # If project_id is provided, verify all specs in folder belong to project
    if project_id:
        for spec_path in spec_files:
            spec_name = str(spec_path.relative_to(SPECS_DIR))
            meta = get_db_spec_metadata(session, spec_name, project_id)
            if meta and meta.project_id:
                if project_id == "default":
                    if meta.project_id not in (None, "default"):
                        raise HTTPException(
                            status_code=403, detail="Folder contains specs from other projects. Cannot delete."
                        )
                elif meta.project_id != project_id:
                    raise HTTPException(
                        status_code=403, detail="Folder contains specs from other projects. Cannot delete."
                    )

    for spec_path in spec_files:
        spec_name = str(spec_path.relative_to(SPECS_DIR))
        deleted_specs.append(spec_name)

        # Optionally delete generated tests
        if delete_generated_tests:
            code_path = get_try_code_path_fast(spec_path)
            if code_path and Path(code_path).exists():
                Path(code_path).unlink()
                deleted_tests.append(code_path)

        # Delete metadata from DB
        meta = get_db_spec_metadata(session, spec_name, project_id)
        if meta:
            session.delete(meta)

        # Clear cache
        _spec_info_cache.pop(str(spec_path), None)

    session.commit()

    # Delete folder and all contents
    shutil.rmtree(folder)

    _spec_cache.invalidate()
    return {"status": "deleted", "folder": folder_path, "deleted_specs": deleted_specs, "deleted_tests": deleted_tests}


@router.delete("/specs/{name:path}")
def delete_spec(
    name: str,
    delete_generated_test: bool = False,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    """Delete a spec file and optionally its generated test."""
    spec_path = SPECS_DIR / name
    if not spec_path.exists():
        raise HTTPException(status_code=404, detail="Spec not found")

    # Verify project ownership if project_id is provided
    if project_id:
        meta = get_db_spec_metadata(session, name, project_id)
        if meta and meta.project_id:
            if project_id == "default":
                if meta.project_id not in (None, "default"):
                    raise HTTPException(status_code=404, detail="Spec not found")
            elif meta.project_id != project_id:
                raise HTTPException(status_code=404, detail="Spec not found")

    code_path = get_try_code_path_fast(spec_path)
    deleted_files = [str(spec_path)]

    # Delete spec file
    spec_path.unlink()

    # Optionally delete generated test
    if delete_generated_test and code_path:
        code_file = Path(code_path)
        if code_file.exists():
            code_file.unlink()
            deleted_files.append(code_path)

    # Delete metadata from DB
    meta = get_db_spec_metadata(session, name, project_id)
    if meta:
        session.delete(meta)
        session.commit()

    # Clear cache
    _spec_info_cache.pop(str(spec_path), None)
    _spec_cache.invalidate()

    return {"status": "deleted", "deleted_files": deleted_files}


@router.post("/specs/move", response_model=MoveSpecResponse)
def move_spec(request: MoveSpecRequest, session: Session = Depends(get_session)):
    """Move a spec file or folder to a new location.

    Moves specs and their associated generated test files.
    Updates database metadata entries accordingly.

    Args:
        request: MoveSpecRequest with source_path, destination_folder, is_folder flag

    Returns:
        MoveSpecResponse with details of moved specs and tests
    """
    source = SPECS_DIR / request.source_path
    is_template = request.source_path.startswith("templates/")

    # Validate source exists
    if request.is_folder:
        if not source.exists() or not source.is_dir():
            raise HTTPException(status_code=404, detail=f"Source folder not found: {request.source_path}")
    else:
        if not source.exists() or not source.is_file():
            raise HTTPException(status_code=404, detail=f"Source spec not found: {request.source_path}")

    # For templates, destination must also be within templates/ or be root (which means templates/)
    if is_template:
        if request.destination_folder:
            if not request.destination_folder.startswith("templates/"):
                raise HTTPException(status_code=400, detail="Cannot move templates outside of templates folder")
            dest_folder = SPECS_DIR / request.destination_folder
        else:
            # Empty destination for templates means templates/ root
            dest_folder = SPECS_DIR / "templates"
    else:
        # For regular specs, prevent moving into templates
        if request.destination_folder.startswith("templates/"):
            raise HTTPException(status_code=400, detail="Cannot move specs into templates folder")
        dest_folder = SPECS_DIR / request.destination_folder if request.destination_folder else SPECS_DIR

    # Prevent moving folder into itself
    if request.is_folder:
        source_abs = source.resolve()
        dest_abs = dest_folder.resolve()
        if str(dest_abs).startswith(str(source_abs)):
            raise HTTPException(status_code=400, detail="Cannot move a folder into itself")

    # Create destination folder if it doesn't exist
    dest_folder.mkdir(parents=True, exist_ok=True)

    # Determine new path
    source_name = source.name
    new_path = dest_folder / source_name

    # Check for conflicts
    if new_path.exists():
        raise HTTPException(status_code=409, detail=f"Destination already exists: {new_path.relative_to(SPECS_DIR)}")

    moved_specs: list[MovedItemInfo] = []
    moved_tests: list[MovedItemInfo] = []

    if request.is_folder:
        # Collect all spec files in folder before moving
        spec_files = list(source.glob("**/*.md"))

        # Verify project ownership if project_id is provided
        if request.project_id:
            for spec_path in spec_files:
                spec_name = str(spec_path.relative_to(SPECS_DIR))
                meta = get_db_spec_metadata(session, spec_name, request.project_id)
                if meta and meta.project_id:
                    if request.project_id == "default":
                        if meta.project_id not in (None, "default"):
                            raise HTTPException(status_code=403, detail="Folder contains specs from other projects")
                    elif meta.project_id != request.project_id:
                        raise HTTPException(status_code=403, detail="Folder contains specs from other projects")

        # Move the folder
        shutil.move(str(source), str(new_path))

        # Update metadata for all specs in the moved folder
        for spec_path in spec_files:
            old_spec_name = str(spec_path.relative_to(SPECS_DIR))
            # Calculate new spec name
            relative_to_source = spec_path.relative_to(source)
            new_spec_path = new_path / relative_to_source
            new_spec_name = str(new_spec_path.relative_to(SPECS_DIR))

            moved_specs.append(MovedItemInfo(old_path=old_spec_name, new_path=new_spec_name))

            # Update DB metadata (delete old, create new if exists)
            old_meta = get_db_spec_metadata(session, old_spec_name, request.project_id)
            if old_meta:
                # Copy metadata to new key
                new_meta = DBSpecMetadata(
                    spec_name=new_spec_name,
                    tags_json=old_meta.tags_json,
                    description=old_meta.description,
                    author=old_meta.author,
                    last_modified=old_meta.last_modified,
                    project_id=old_meta.project_id,
                )
                session.delete(old_meta)
                session.add(new_meta)

            # Move associated generated test if exists
            old_code_path = get_try_code_path_fast(spec_path)
            if old_code_path:
                old_code_file = Path(old_code_path)
                if old_code_file.exists():
                    # Generate new test path based on new spec name
                    new_stem = new_spec_path.stem.replace("_", "-")
                    new_code_path = BASE_DIR / "tests" / "generated" / f"{new_stem}.spec.ts"
                    new_code_path.parent.mkdir(parents=True, exist_ok=True)
                    if not new_code_path.exists():
                        shutil.move(str(old_code_file), str(new_code_path))
                        moved_tests.append(MovedItemInfo(old_path=str(old_code_file), new_path=str(new_code_path)))

            # Clear cache for old path
            _spec_info_cache.pop(str(spec_path), None)

    else:
        # Single file move
        old_spec_name = request.source_path
        new_spec_name = str(new_path.relative_to(SPECS_DIR))

        # Verify project ownership if project_id is provided
        if request.project_id:
            meta = get_db_spec_metadata(session, old_spec_name, request.project_id)
            if meta and meta.project_id:
                if request.project_id == "default":
                    if meta.project_id not in (None, "default"):
                        raise HTTPException(status_code=404, detail="Spec not found")
                elif meta.project_id != request.project_id:
                    raise HTTPException(status_code=404, detail="Spec not found")

        # Move the file
        shutil.move(str(source), str(new_path))
        moved_specs.append(MovedItemInfo(old_path=old_spec_name, new_path=new_spec_name))

        # Update DB metadata
        old_meta = get_db_spec_metadata(session, old_spec_name, request.project_id)
        if old_meta:
            new_meta = DBSpecMetadata(
                spec_name=new_spec_name,
                tags_json=old_meta.tags_json,
                description=old_meta.description,
                author=old_meta.author,
                last_modified=old_meta.last_modified,
                project_id=old_meta.project_id,
            )
            session.delete(old_meta)
            session.add(new_meta)

        # Move associated generated test if exists
        old_code_path = get_try_code_path_fast(source)
        if old_code_path:
            old_code_file = Path(old_code_path)
            if old_code_file.exists():
                # Generate new test path based on new spec name
                new_stem = new_path.stem.replace("_", "-")
                new_code_path = BASE_DIR / "tests" / "generated" / f"{new_stem}.spec.ts"
                new_code_path.parent.mkdir(parents=True, exist_ok=True)
                if not new_code_path.exists():
                    shutil.move(str(old_code_file), str(new_code_path))
                    moved_tests.append(MovedItemInfo(old_path=str(old_code_file), new_path=str(new_code_path)))

        # Clear cache
        _spec_info_cache.pop(str(source), None)

    session.commit()
    _spec_cache.invalidate()

    return MoveSpecResponse(
        status="moved",
        old_path=request.source_path,
        new_path=str(new_path.relative_to(SPECS_DIR)),
        moved_specs=moved_specs,
        moved_tests=moved_tests,
    )


@router.post("/specs/rename", response_model=RenameResponse)
def rename_spec(request: RenameRequest, session: Session = Depends(get_session)):
    """Rename a spec file or folder in-place.

    Unlike move, rename keeps the item in the same parent directory but changes its name.
    Also updates TestRun.spec_name and TestrailCaseMapping.spec_name cross-references.

    Args:
        request: RenameRequest with old_path, new_name, is_folder flag

    Returns:
        RenameResponse with details of renamed specs and tests
    """
    # Validate new_name format: lowercase alphanumeric, hyphens, underscores, dots
    name_pattern = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
    if not name_pattern.match(request.new_name):
        raise HTTPException(
            status_code=400, detail="Name must be lowercase alphanumeric with hyphens, underscores, or dots only"
        )

    source = SPECS_DIR / request.old_path

    # Validate source exists
    if request.is_folder:
        if not source.exists() or not source.is_dir():
            raise HTTPException(status_code=404, detail=f"Source folder not found: {request.old_path}")
    else:
        if not source.exists() or not source.is_file():
            raise HTTPException(status_code=404, detail=f"Source spec not found: {request.old_path}")
        # Ensure new_name ends with .md for files
        if not request.new_name.endswith(".md"):
            request.new_name = request.new_name + ".md"

    # Compute new path (same parent, different name)
    new_path = source.parent / request.new_name

    # Check destination doesn't already exist
    if new_path.exists():
        raise HTTPException(status_code=409, detail=f"Already exists: {new_path.relative_to(SPECS_DIR)}")

    renamed_specs: list[MovedItemInfo] = []
    renamed_tests: list[MovedItemInfo] = []

    if request.is_folder:
        # Collect all spec files in folder before renaming
        spec_files = list(source.glob("**/*.md"))

        # Verify project ownership if project_id is provided
        if request.project_id:
            for spec_path in spec_files:
                spec_name = str(spec_path.relative_to(SPECS_DIR))
                meta = get_db_spec_metadata(session, spec_name, request.project_id)
                if meta and meta.project_id:
                    if request.project_id == "default":
                        if meta.project_id not in (None, "default"):
                            raise HTTPException(status_code=403, detail="Folder contains specs from other projects")
                    elif meta.project_id != request.project_id:
                        raise HTTPException(status_code=403, detail="Folder contains specs from other projects")

        # Rename the folder
        shutil.move(str(source), str(new_path))

        # Update metadata and cross-references for all specs
        for spec_path in spec_files:
            old_spec_name = str(spec_path.relative_to(SPECS_DIR))
            relative_to_source = spec_path.relative_to(source)
            new_spec_path = new_path / relative_to_source
            new_spec_name = str(new_spec_path.relative_to(SPECS_DIR))

            renamed_specs.append(MovedItemInfo(old_path=old_spec_name, new_path=new_spec_name))

            # Update DB metadata (delete old, create new)
            old_meta = get_db_spec_metadata(session, old_spec_name, request.project_id)
            if old_meta:
                new_meta = DBSpecMetadata(
                    spec_name=new_spec_name,
                    tags_json=old_meta.tags_json,
                    description=old_meta.description,
                    author=old_meta.author,
                    last_modified=old_meta.last_modified,
                    project_id=old_meta.project_id,
                )
                session.delete(old_meta)
                session.add(new_meta)

            # Update TestRun references
            runs_to_update = session.exec(select(DBTestRun).where(DBTestRun.spec_name == old_spec_name)).all()
            for run in runs_to_update:
                run.spec_name = new_spec_name
                session.add(run)

            # Update TestrailCaseMapping references
            mappings_to_update = session.exec(
                select(TestrailCaseMapping).where(TestrailCaseMapping.spec_name == old_spec_name)
            ).all()
            for mapping in mappings_to_update:
                mapping.spec_name = new_spec_name
                session.add(mapping)

            # Move associated generated test if exists
            old_code_path = get_try_code_path_fast(spec_path)
            if old_code_path:
                old_code_file = Path(old_code_path)
                if old_code_file.exists():
                    new_stem = new_spec_path.stem.replace("_", "-")
                    new_code_path = BASE_DIR / "tests" / "generated" / f"{new_stem}.spec.ts"
                    new_code_path.parent.mkdir(parents=True, exist_ok=True)
                    if not new_code_path.exists():
                        shutil.move(str(old_code_file), str(new_code_path))
                        renamed_tests.append(MovedItemInfo(old_path=str(old_code_file), new_path=str(new_code_path)))

            # Clear cache
            _spec_info_cache.pop(str(spec_path), None)

    else:
        # Single file rename
        old_spec_name = request.old_path
        new_spec_name = str(new_path.relative_to(SPECS_DIR))

        # Verify project ownership
        if request.project_id:
            meta = get_db_spec_metadata(session, old_spec_name, request.project_id)
            if meta and meta.project_id:
                if request.project_id == "default":
                    if meta.project_id not in (None, "default"):
                        raise HTTPException(status_code=404, detail="Spec not found")
                elif meta.project_id != request.project_id:
                    raise HTTPException(status_code=404, detail="Spec not found")

        # Rename the file
        shutil.move(str(source), str(new_path))
        renamed_specs.append(MovedItemInfo(old_path=old_spec_name, new_path=new_spec_name))

        # Update DB metadata
        old_meta = get_db_spec_metadata(session, old_spec_name, request.project_id)
        if old_meta:
            new_meta = DBSpecMetadata(
                spec_name=new_spec_name,
                tags_json=old_meta.tags_json,
                description=old_meta.description,
                author=old_meta.author,
                last_modified=old_meta.last_modified,
                project_id=old_meta.project_id,
            )
            session.delete(old_meta)
            session.add(new_meta)

        # Update TestRun references
        runs_to_update = session.exec(select(DBTestRun).where(DBTestRun.spec_name == old_spec_name)).all()
        for run in runs_to_update:
            run.spec_name = new_spec_name
            session.add(run)

        # Update TestrailCaseMapping references
        mappings_to_update = session.exec(
            select(TestrailCaseMapping).where(TestrailCaseMapping.spec_name == old_spec_name)
        ).all()
        for mapping in mappings_to_update:
            mapping.spec_name = new_spec_name
            session.add(mapping)

        # Move associated generated test if exists
        old_code_path = get_try_code_path_fast(source)
        if old_code_path:
            old_code_file = Path(old_code_path)
            if old_code_file.exists():
                new_stem = new_path.stem.replace("_", "-")
                new_code_path = BASE_DIR / "tests" / "generated" / f"{new_stem}.spec.ts"
                new_code_path.parent.mkdir(parents=True, exist_ok=True)
                if not new_code_path.exists():
                    shutil.move(str(old_code_file), str(new_code_path))
                    renamed_tests.append(MovedItemInfo(old_path=str(old_code_file), new_path=str(new_code_path)))

        # Clear cache
        _spec_info_cache.pop(str(source), None)

    session.commit()
    _spec_cache.invalidate()

    return RenameResponse(
        status="renamed",
        old_path=request.old_path,
        new_path=str(new_path.relative_to(SPECS_DIR)),
        renamed_specs=renamed_specs,
        renamed_tests=renamed_tests,
    )


@router.post("/specs/create-folder", response_model=CreateFolderResponse)
def create_folder(request: CreateFolderRequest):
    """Create an empty folder in the specs directory.

    Args:
        request: CreateFolderRequest with folder_name and optional parent_path

    Returns:
        CreateFolderResponse with created path
    """
    # Validate folder name format
    name_pattern = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
    if not name_pattern.match(request.folder_name):
        raise HTTPException(
            status_code=400, detail="Folder name must be lowercase alphanumeric with hyphens or underscores only"
        )

    # Resolve target path
    if request.parent_path:
        parent = SPECS_DIR / request.parent_path
        if not parent.exists() or not parent.is_dir():
            raise HTTPException(status_code=404, detail=f"Parent folder not found: {request.parent_path}")
    else:
        parent = SPECS_DIR

    target = parent / request.folder_name

    # Check target doesn't already exist
    if target.exists():
        raise HTTPException(status_code=409, detail=f"Folder already exists: {target.relative_to(SPECS_DIR)}")

    target.mkdir(parents=False, exist_ok=False)

    return CreateFolderResponse(status="created", path=str(target.relative_to(SPECS_DIR)))


@router.post("/specs/register-folder")
def register_folder_specs(folder: str, project_id: str, session: Session = Depends(get_session)):
    """
    Register all specs in a folder to a project.

    This endpoint is useful for migrating existing unregistered specs
    (created before project support) to a specific project.

    Args:
        folder: Folder path relative to specs directory (e.g., "explorer-my-auth-flow")
        project_id: Project ID to associate specs with

    Returns:
        Count and list of registered spec names
    """
    folder_path = SPECS_DIR / folder
    if not folder_path.exists():
        raise HTTPException(status_code=404, detail=f"Folder not found: {folder}")

    if not folder_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Path is not a folder: {folder}")

    # Verify project exists (unless it's "default")
    if project_id and project_id != "default":
        from orchestrator.api.models_db import Project

        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    registered = []
    updated = []

    for f in folder_path.glob("**/*.md"):
        spec_name = str(f.relative_to(SPECS_DIR))
        existing = get_db_spec_metadata(session, spec_name, project_id)

        if not existing:
            # Create new metadata record
            meta = DBSpecMetadata(spec_name=spec_name, project_id=normalize_project_id(project_id), tags_json="[]")
            session.add(meta)
            registered.append(spec_name)

    session.commit()

    return {
        "registered": len(registered),
        "updated": len(updated),
        "specs": registered + updated,
        "folder": folder,
        "project_id": project_id,
    }


# ========= PRD Spec Detection & Splitting =========


class SpecInfoResponse(BaseModel):
    name: str
    type: str  # "standard", "prd", or "template"
    test_count: int
    categories: list[str]
    test_cases: list[dict[str, Any]]


class SplitSpecRequest(BaseModel):
    spec_name: str
    output_dir: str | None = None
    project_id: str | None = None  # Project to assign split specs to
    mode: str | None = "individual"  # "individual" or "grouped"
    extraction_method: Literal["ai", "regex"] = "ai"


class SplitSpecResponse(BaseModel):
    count: int
    files: list[str]
    output_dir: str
    groups: list[dict[str, Any]] | None = None  # AI grouping suggestions
    extraction_method: str
    ai_used: bool
    warning: str | None = None


class SplitSpecJobStartResponse(BaseModel):
    job_id: str
    status: str
    temporal_workflow_id: str | None = None
    temporal_run_id: str | None = None


def _sanitize_ai_split_error(error: Exception) -> str:
    """Return an actionable provider error without exposing credentials."""
    message = str(error).strip() or error.__class__.__name__
    patterns = (
        r"(sk-ant-[A-Za-z0-9._:/+=-]{8,})",
        r"(sk-[A-Za-z0-9._:/+=-]{8,})",
        r"(Bearer\s+)[A-Za-z0-9._:/+=-]+",
        r"((?:api[-_]?key|x-api-key|authorization)['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9._:/+=-]+",
    )
    for pattern in patterns:
        message = re.sub(
            pattern,
            lambda match: f"{match.group(1)}[redacted]"
            if match.group(0).lower().startswith("bearer ")
            or re.match(r"(?i)(?:api[-_]?key|x-api-key|authorization)", match.group(0))
            else "[redacted]",
            message,
            flags=re.IGNORECASE,
        )
    return message[:1200]


def _split_prd_spec_impl(request: SplitSpecRequest, session: Session) -> SplitSpecResponse:
    """Split a spec and return the public response shape used by sync and async flows."""
    from utils.prd_spec_splitter import PRDSpecSplitter
    from utils.spec_detector import SpecDetector, SpecType

    spec_path = SPECS_DIR / request.spec_name
    if not spec_path.exists():
        raise HTTPException(status_code=404, detail="Spec not found")

    spec_type = SpecDetector.detect_spec_type(spec_path)
    is_splittable = spec_type in (SpecType.PRD, SpecType.NATIVE_PLAN, SpecType.STANDARD_MULTI)

    if not is_splittable:
        content = spec_path.read_text()
        pattern_count = SpecDetector.count_test_patterns(content)
        if pattern_count < 2:
            raise HTTPException(status_code=400, detail=f"Spec is not a multi-test spec (detected type: {spec_type})")

    output_dir = SPECS_DIR / request.output_dir if request.output_dir else None

    from orchestrator.api.settings import runtime_env_vars

    use_ai = request.extraction_method == "ai"
    if request.mode == "grouped" and not use_ai:
        raise HTTPException(status_code=400, detail="Smart Groups requires AI extraction.")

    split_files, groups, metadata = PRDSpecSplitter.split_spec(
        spec_path,
        output_dir,
        use_ai=use_ai,
        mode=request.mode or "individual",
        runtime_env_vars=runtime_env_vars(session) if use_ai else None,
        ai_fallback=False if use_ai else True,
        return_metadata=True,
    )

    file_names = [str(f.relative_to(SPECS_DIR)) for f in split_files]

    if request.project_id and file_names:
        for spec_name in file_names:
            existing = get_db_spec_metadata(session, spec_name, request.project_id)

            if existing:
                session.add(existing)
            else:
                new_metadata = DBSpecMetadata(spec_name=spec_name, project_id=request.project_id)
                session.add(new_metadata)

        session.commit()

    return SplitSpecResponse(
        count=len(split_files),
        files=file_names,
        output_dir=str(split_files[0].parent.relative_to(SPECS_DIR)) if split_files else "",
        groups=groups,
        extraction_method=str(metadata.get("extraction_method") or request.extraction_method),
        ai_used=bool(metadata.get("ai_used")),
        warning=metadata.get("warning"),
    )


def _request_payload(request: SplitSpecRequest) -> dict[str, Any]:
    return request.model_dump() if hasattr(request, "model_dump") else request.dict()


def _split_response_payload(response: SplitSpecResponse) -> dict[str, Any]:
    return response.model_dump() if hasattr(response, "model_dump") else response.dict()


def _http_exception_detail(error: HTTPException) -> str:
    detail = error.detail
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
        return detail["message"]
    return str(detail or error.status_code)


async def _run_spec_split_job(job_id: str, payload: dict[str, Any]) -> None:
    """Execute a durable spec split job and persist the terminal result."""
    await asyncio.to_thread(_run_spec_split_job_blocking, job_id, payload)


def _run_spec_split_job_blocking(job_id: str, payload: dict[str, Any]) -> None:
    """Blocking split implementation run from the Temporal activity thread."""
    from orchestrator.services.domain_jobs import update_domain_job

    update_domain_job(job_id, status="running", progress={"status": "running"}, started=True)
    try:
        request = SplitSpecRequest(**payload)
        with Session(engine) as session:
            response = _split_prd_spec_impl(request, session)
        update_domain_job(
            job_id,
            status="completed",
            progress={"status": "completed"},
            result=_split_response_payload(response),
            completed=True,
        )
    except HTTPException as exc:
        detail = _http_exception_detail(exc)
        logger.warning("Spec split job %s failed: %s", job_id, detail)
        update_domain_job(job_id, status="failed", progress={"status": "failed"}, error=detail, completed=True)
    except RuntimeError as exc:
        detail = _sanitize_ai_split_error(exc)
        logger.warning("Spec split job %s failed: %s", job_id, detail)
        update_domain_job(job_id, status="failed", progress={"status": "failed"}, error=detail, completed=True)
    except Exception as exc:
        logger.error("Spec split job %s failed: %s", job_id, exc, exc_info=True)
        update_domain_job(
            job_id,
            status="failed",
            progress={"status": "failed"},
            error="Internal server error",
            completed=True,
        )


@router.get("/specs/{name:path}/info", response_model=SpecInfoResponse)
def get_spec_info(name: str):
    """Get information about a spec, including PRD detection."""
    from utils.spec_detector import SpecDetector

    spec_path = SPECS_DIR / name
    if not spec_path.exists():
        raise HTTPException(status_code=404, detail="Spec not found")

    info = SpecDetector.get_spec_info(spec_path)

    return SpecInfoResponse(
        name=name,
        type=info["type"],
        test_count=info["test_count"],
        categories=info["categories"],
        test_cases=info["test_cases"],
    )


@router.post("/specs/split", response_model=SplitSpecResponse)
def split_prd_spec(request: SplitSpecRequest, session: Session = Depends(get_session)):
    """Split a multi-test spec (PRD, Native Plan, or multi-test) into individual test specs."""
    try:
        return _split_prd_spec_impl(request, session)
    except HTTPException:
        raise
    except RuntimeError as e:
        detail = _sanitize_ai_split_error(e)
        logger.warning(f"Failed to split spec with {request.extraction_method} extraction: {detail}")
        raise HTTPException(status_code=502, detail=detail)
    except Exception as e:
        logger.error(f"Failed to split spec: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/specs/split-jobs", response_model=SplitSpecJobStartResponse)
async def create_split_spec_job(request: SplitSpecRequest):
    """Queue a durable split job and return immediately."""
    job_id = str(uuid.uuid4())
    payload = _request_payload(request)

    from orchestrator.services.domain_jobs import create_domain_job, update_domain_job

    create_domain_job(
        job_id=job_id,
        job_type="spec_split",
        project_id=request.project_id,
        payload=payload,
        progress={"status": "queued"},
    )

    try:
        from orchestrator.services.temporal_client import start_domain_job_workflow

        temporal = await start_domain_job_workflow("spec_split", job_id, payload)
        update_domain_job(
            job_id,
            temporal_workflow_id=temporal.workflow_id,
            temporal_run_id=temporal.run_id,
        )
        return SplitSpecJobStartResponse(
            job_id=job_id,
            status="queued",
            temporal_workflow_id=temporal.workflow_id,
            temporal_run_id=temporal.run_id,
        )
    except Exception as exc:
        error = f"Temporal start failed: {exc}"
        update_domain_job(job_id, status="failed", progress={"status": "failed"}, error=error, completed=True)
        raise HTTPException(status_code=503, detail=f"Temporal is required for spec splitting: {exc}") from exc


# ========= Metadata =========


@router.get("/spec-metadata")
def get_all_metadata(
    project_id: str | None = None,
    limit: int = Query(default=1000, ge=1, le=5000, description="Max items to return"),
    offset: int = Query(default=0, ge=0, description="Items to skip"),
    session: Session = Depends(get_session),
):
    # Build query with optional project filter
    query = select(DBSpecMetadata)
    if project_id:
        if project_id == "default":
            query = query.where((DBSpecMetadata.project_id == project_id) | (DBSpecMetadata.project_id == None))
        else:
            query = query.where(DBSpecMetadata.project_id == project_id)

    # Safety cap: apply limit/offset to prevent unbounded result sets
    metas = session.exec(query.offset(offset).limit(limit)).all()
    # Convert list to dict keyed by spec_name to match original API
    result = {}
    for m in metas:
        result[m.spec_name] = {
            "tags": m.tags,
            "description": m.description,
            "author": m.author,
            "lastModified": m.last_modified.isoformat() if m.last_modified else None,
        }
    return result


@router.get("/spec-metadata/{spec_name:path}")
def get_spec_metadata(
    spec_name: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
):
    m = get_db_spec_metadata(session, spec_name, project_id)
    if not m:
        return {"tags": [], "description": None, "author": None, "lastModified": None}

    return {
        "tags": m.tags,
        "description": m.description,
        "author": m.author,
        "lastModified": m.last_modified.isoformat() if m.last_modified else None,
    }


@router.put("/spec-metadata/{spec_name:path}")
def update_spec_metadata(spec_name: str, request: UpdateMetadataRequest, session: Session = Depends(get_session)):
    m = get_db_spec_metadata(session, spec_name, request.project_id)
    if not m:
        m = DBSpecMetadata(spec_name=spec_name, project_id=normalize_project_id(request.project_id))

    if request.tags is not None:
        m.tags = request.tags
    if request.description is not None:
        m.description = request.description
    if request.author is not None:
        m.author = request.author
    m.last_modified = datetime.utcnow()

    session.add(m)
    session.commit()
    session.refresh(m)

    return {
        "status": "success",
        "metadata": {
            "tags": m.tags,
            "description": m.description,
            "author": m.author,
            "lastModified": m.last_modified.isoformat(),
            "project_id": m.project_id,
        },
    }
