"""PR test-impact analysis and conservative test selection."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from orchestrator.api.models_db import (
    PrChangedFile,
    PrImpactAnalysis,
    PrSelectedTest,
    RepoIndexedFile,
    RepoIndexSnapshot,
    SpecMetadata,
    TestExecutionHistory,
    TestImpactMap,
)
from orchestrator.api.models_db import TestRun as DBTestRun

try:
    from orchestrator.utils.spec_detector import SpecDetector
except Exception:
    SpecDetector = None


BASE_DIR = Path(__file__).resolve().parent.parent.parent
SPECS_DIR = BASE_DIR / "specs"
TESTS_DIR = BASE_DIR / "tests" / "generated"

LOW_CONFIDENCE_PATHS = (
    "package-lock.json",
    "package.json",
    "requirements",
    "pyproject.toml",
    "playwright.config",
    "docker-compose",
    "Dockerfile",
    "alembic.ini",
    "nginx/",
    "k8s/",
    ".github/",
)

ALWAYS_RUN_TAGS = {"smoke", "critical", "auth", "login", "security", "regression"}


@dataclass
class ChangedFileInput:
    path: str
    status: str = "modified"
    additions: int = 0
    deletions: int = 0
    changes: int = 0
    previous_filename: str | None = None


@dataclass
class TestInventoryItem:
    spec_name: str
    spec_path: Path
    test_path: str | None = None
    tags: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    project_id: str | None = None
    last_status: str | None = None
    last_duration_seconds: int | None = None
    recent_failures: int = 0
    flaky: bool = False


@dataclass
class SelectedTest:
    spec_name: str
    test_path: str | None
    reason: str
    confidence: str
    risk_level: str
    selection_source: str
    estimated_duration_seconds: int | None
    tags: list[str]
    categories: list[str]


@dataclass
class ImpactResult:
    analysis_id: str
    changed_files: list[dict[str, Any]]
    selected_tests: list[SelectedTest]
    total_candidate_tests: int
    risk_level: str
    confidence: str
    summary: str
    fallback_reason: str | None
    category_summary: dict[str, Any]
    estimated_duration_seconds: int | None
    saved_tests_count: int | None


@dataclass
class RepoFileInput:
    path: str
    sha: str | None = None
    size: int | None = None
    content: str | None = None


@dataclass
class RepoIndexResult:
    snapshot: RepoIndexSnapshot
    derived_impact_maps: int


def normalize_changed_files(files: list[dict[str, Any]]) -> list[ChangedFileInput]:
    normalized: list[ChangedFileInput] = []
    for item in files:
        path = item.get("filename") or item.get("path")
        if not path:
            continue
        normalized.append(
            ChangedFileInput(
                path=path,
                status=item.get("status") or "modified",
                additions=int(item.get("additions") or 0),
                deletions=int(item.get("deletions") or 0),
                changes=int(item.get("changes") or 0),
                previous_filename=item.get("previous_filename"),
            )
        )
    return normalized


def analyze_pr_changes(
    *,
    project_id: str,
    owner: str,
    repo: str,
    pr_number: int,
    pr_data: dict[str, Any],
    changed_files: list[dict[str, Any]],
    session: Session,
    snapshot_id: str | None = None,
) -> PrImpactAnalysis:
    sync_execution_history(project_id, session)
    files = normalize_changed_files(changed_files)
    inventory = build_test_inventory(project_id, session)
    impact_maps = load_impact_maps(project_id, session)
    if snapshot_id:
        enrich_impact_maps_from_repo_index(project_id, snapshot_id, inventory, session)
        impact_maps = load_impact_maps(project_id, session)
    result = select_impacted_tests(files, inventory, impact_maps)

    analysis = PrImpactAnalysis(
        id=result.analysis_id,
        project_id=project_id,
        provider="github",
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        title=pr_data.get("title"),
        base_ref=(pr_data.get("base") or {}).get("ref"),
        head_ref=(pr_data.get("head") or {}).get("ref"),
        head_sha=(pr_data.get("head") or {}).get("sha"),
        author=(pr_data.get("user") or {}).get("login"),
        status="completed",
        risk_level=result.risk_level,
        confidence=result.confidence,
        summary=result.summary,
        fallback_reason=result.fallback_reason,
        changed_files_count=len(files),
        selected_tests_count=len(result.selected_tests),
        total_candidate_tests=result.total_candidate_tests,
        estimated_duration_seconds=result.estimated_duration_seconds,
        saved_tests_count=result.saved_tests_count,
        category_summary=result.category_summary,
        ai_notes=f"repository_index_snapshot={snapshot_id}" if snapshot_id else None,
        completed_at=datetime.utcnow(),
    )
    session.add(analysis)
    # PostgreSQL enforces the child-row FK immediately. Flush the parent before
    # later queries in this request can trigger an autoflush of child rows.
    session.flush()

    for file_info in result.changed_files:
        session.add(
            PrChangedFile(
                analysis_id=analysis.id,
                path=file_info["path"],
                status=file_info["status"],
                additions=file_info["additions"],
                deletions=file_info["deletions"],
                changes=file_info["changes"],
                previous_filename=file_info.get("previous_filename"),
                area=file_info["area"],
                risk_level=file_info["risk_level"],
                reason=file_info["reason"],
            )
        )

    for selected in result.selected_tests:
        session.add(
            PrSelectedTest(
                analysis_id=analysis.id,
                spec_name=selected.spec_name,
                test_path=selected.test_path,
                reason=selected.reason,
                confidence=selected.confidence,
                risk_level=selected.risk_level,
                selection_source=selected.selection_source,
                estimated_duration_seconds=selected.estimated_duration_seconds,
                tags=selected.tags,
                categories=selected.categories,
            )
        )

    refresh_impact_maps(project_id, inventory, session)
    session.commit()
    session.refresh(analysis)
    return analysis


def index_repository_snapshot(
    *,
    project_id: str,
    owner: str,
    repo: str,
    ref: str,
    commit_sha: str | None,
    files: list[RepoFileInput],
    session: Session,
) -> RepoIndexResult:
    """Persist a parsed repository snapshot and derive impact maps from it."""
    snapshot = RepoIndexSnapshot(
        id=f"ridx_{uuid.uuid4().hex[:12]}",
        project_id=project_id,
        provider="github",
        owner=owner,
        repo=repo,
        ref=ref,
        commit_sha=commit_sha,
        status="completed",
    )
    session.add(snapshot)
    session.flush()

    indexed_rows: list[RepoIndexedFile] = []
    for repo_file in files:
        parsed = parse_repo_file(repo_file.path, repo_file.content or "", repo_file.size, repo_file.sha)
        row = RepoIndexedFile(
            snapshot_id=snapshot.id,
            project_id=project_id,
            path=repo_file.path,
            file_type=parsed["file_type"],
            area=parsed["area"],
            language=parsed["language"],
            size=repo_file.size,
            sha=repo_file.sha,
            imports=parsed["imports"],
            imported_by=[],
            routes=parsed["routes"],
            symbols=parsed["symbols"],
            keywords=parsed["keywords"],
            risk_flags=parsed["risk_flags"],
        )
        session.add(row)
        indexed_rows.append(row)

    session.flush()
    reverse_imports = build_reverse_imports(indexed_rows)
    for row in indexed_rows:
        row.imported_by = reverse_imports.get(row.path, [])
        session.add(row)

    inventory = build_test_inventory(project_id, session)
    derived = enrich_impact_maps_from_index_rows(project_id, snapshot.id, indexed_rows, inventory, session)

    snapshot.indexed_files_count = len(indexed_rows)
    snapshot.source_files_count = sum(1 for row in indexed_rows if row.file_type == "source")
    snapshot.test_files_count = sum(1 for row in indexed_rows if row.file_type == "test")
    snapshot.route_count = sum(len(row.routes or []) for row in indexed_rows)
    snapshot.summary = (
        f"Indexed {snapshot.indexed_files_count} files, "
        f"{snapshot.source_files_count} source files, {snapshot.test_files_count} tests/specs, "
        f"and {derived} impact maps."
    )
    snapshot.completed_at = datetime.utcnow()
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)
    return RepoIndexResult(snapshot=snapshot, derived_impact_maps=derived)


def latest_repo_index(
    project_id: str,
    owner: str,
    repo: str,
    ref: str,
    session: Session,
    commit_sha: str | None = None,
) -> RepoIndexSnapshot | None:
    stmt = (
        select(RepoIndexSnapshot)
        .where(
            RepoIndexSnapshot.project_id == project_id,
            RepoIndexSnapshot.owner == owner,
            RepoIndexSnapshot.repo == repo,
            RepoIndexSnapshot.ref == ref,
            RepoIndexSnapshot.status == "completed",
        )
        .order_by(RepoIndexSnapshot.created_at.desc())
    )
    if commit_sha:
        stmt = stmt.where(RepoIndexSnapshot.commit_sha == commit_sha)
    return session.exec(stmt).first()


def parse_repo_file(path: str, content: str, size: int | None, sha: str | None) -> dict[str, Any]:
    lower = path.lower()
    language = _language_for_path(lower)
    file_type = "source"
    if lower.endswith(".md") or lower.startswith("docs/"):
        file_type = "docs"
    if lower.startswith("specs/") or lower.startswith("tests/") or lower.startswith("orchestrator/tests/"):
        file_type = "test"
    if any(token in lower for token in LOW_CONFIDENCE_PATHS):
        file_type = "config"

    area = classify_changed_file(ChangedFileInput(path=path))["area"]
    imports = extract_imports(path, content)
    routes = extract_routes(path, content)
    symbols = extract_symbols(content)
    keywords = extract_keywords(path, content)
    risk_flags = []
    if file_type == "config":
        risk_flags.append("broad-impact")
    if size and size > 250_000:
        risk_flags.append("large-file")

    return {
        "file_type": file_type,
        "area": area,
        "language": language,
        "imports": imports,
        "routes": routes,
        "symbols": symbols,
        "keywords": keywords,
        "risk_flags": risk_flags,
    }


def extract_imports(path: str, content: str) -> list[str]:
    imports: set[str] = set()
    base_dir = str(Path(path).parent)
    patterns = [
        r"from\s+['\"]([^'\"]+)['\"]",
        r"import\s+[^'\"]*from\s+['\"]([^'\"]+)['\"]",
        r"import\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
        r"require\(\s*['\"]([^'\"]+)['\"]\s*\)",
    ]
    for pattern in patterns:
        for raw in re.findall(pattern, content):
            resolved = resolve_import_path(base_dir, raw)
            if resolved:
                imports.add(resolved)
    return sorted(imports)


def resolve_import_path(base_dir: str, raw: str) -> str | None:
    if raw.startswith("@/"):
        return f"web/src/{raw[2:]}".strip("/")
    if raw.startswith("./") or raw.startswith("../"):
        return str(Path(base_dir, raw).as_posix()).strip("/")
    if raw.startswith("orchestrator."):
        return raw.replace(".", "/")
    return None


def extract_routes(path: str, content: str) -> list[str]:
    routes: set[str] = set()
    route_hint = _route_hint_from_path(path)
    if route_hint:
        routes.add("/" if route_hint == "homepage" else f"/{route_hint}")
    for match in re.findall(r"['\"](/(?:[a-zA-Z0-9_./:-]+))['\"]", content):
        if len(match) <= 120 and not match.startswith(("/_", "/api/auth")):
            routes.add(match)
    return sorted(routes)[:50]


def extract_symbols(content: str) -> list[str]:
    symbols = set()
    for pattern in (
        r"export\s+(?:default\s+)?(?:function|class|const)\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"(?:function|class)\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        r"class\s+([A-Za-z_][A-Za-z0-9_]*)",
    ):
        symbols.update(re.findall(pattern, content))
    return sorted(symbols)[:80]


def extract_keywords(path: str, content: str) -> list[str]:
    text = f"{path} {content[:5000]}".lower()
    candidates = {
        "auth",
        "login",
        "checkout",
        "payment",
        "profile",
        "settings",
        "dashboard",
        "api",
        "database",
        "security",
        "search",
        "navigation",
        "upload",
        "admin",
        "report",
    }
    return sorted(token for token in candidates if token in text)


def build_reverse_imports(rows: list[RepoIndexedFile]) -> dict[str, list[str]]:
    paths = {row.path for row in rows}
    by_stem: dict[str, str] = {}
    for path in paths:
        stem = str(Path(path).with_suffix("").as_posix())
        by_stem[stem] = path
        if path.endswith("/index.ts") or path.endswith("/index.tsx"):
            by_stem[str(Path(path).parent.as_posix())] = path

    reverse: dict[str, list[str]] = {}
    for row in rows:
        for imported in row.imports or []:
            target = match_indexed_import(imported, paths, by_stem)
            if target:
                reverse.setdefault(target, []).append(row.path)
    return {path: sorted(set(importers)) for path, importers in reverse.items()}


def match_indexed_import(imported: str, paths: set[str], by_stem: dict[str, str]) -> str | None:
    candidates = [imported, imported.strip("/")]
    for ext in (".ts", ".tsx", ".js", ".jsx", ".py"):
        candidates.append(f"{imported}{ext}")
    for candidate in candidates:
        normalized = str(Path(candidate).as_posix()).strip("/")
        if normalized in paths:
            return normalized
        if normalized in by_stem:
            return by_stem[normalized]
    return None


def enrich_impact_maps_from_repo_index(
    project_id: str,
    snapshot_id: str,
    inventory: list[TestInventoryItem],
    session: Session,
) -> int:
    rows = list(session.exec(select(RepoIndexedFile).where(RepoIndexedFile.snapshot_id == snapshot_id)).all())
    return enrich_impact_maps_from_index_rows(project_id, snapshot_id, rows, inventory, session)


def enrich_impact_maps_from_index_rows(
    project_id: str,
    snapshot_id: str,
    rows: list[RepoIndexedFile],
    inventory: list[TestInventoryItem],
    session: Session,
) -> int:
    rows_by_path = {row.path: row for row in rows}
    existing = {
        row.spec_name: row
        for row in session.exec(select(TestImpactMap).where(TestImpactMap.project_id == project_id)).all()
    }
    derived = 0
    for item in inventory:
        linked_paths = set(infer_impacted_paths(item))
        item_tokens = set(re.split(r"[^a-z0-9]+", item.spec_name.lower()))
        item_tokens.add(Path(item.spec_name).stem.lower())
        item_tokens.update(t.lower() for t in item.tags + item.categories)
        item_tokens.discard("")
        for row in rows:
            row_tokens = {*(row.keywords or []), *(route.strip("/").lower() for route in (row.routes or []))}
            row_tokens.add(Path(row.path).stem.lower())
            if item_tokens.intersection(row_tokens):
                linked_paths.add(row.path)
                linked_paths.update(row.imports or [])
                linked_paths.update(row.imported_by or [])

        expanded = set(linked_paths)
        for _ in range(3):
            next_paths = set(expanded)
            for path in list(expanded):
                row = rows_by_path.get(path)
                if row:
                    next_paths.update(row.imported_by or [])
                    next_paths.update(resolve_indexed_imports(row.imports or [], rows_by_path))
            if next_paths == expanded:
                break
            expanded = next_paths

        if not expanded:
            continue
        impact = existing.get(item.spec_name)
        if impact:
            impact.impacted_paths = sorted(set(impact.impacted_paths or []).union(expanded))
            impact.source = "repository_index"
            impact.confidence = max_confidence(impact.confidence or "medium", "high")
            impact.updated_at = datetime.utcnow()
        else:
            impact = TestImpactMap(
                project_id=project_id,
                spec_name=item.spec_name,
                test_path=item.test_path,
                impacted_paths=sorted(expanded),
                tags=item.tags,
                categories=item.categories,
                source="repository_index",
                confidence="high",
            )
        session.add(impact)
        derived += 1
    session.flush()
    return derived


def resolve_indexed_imports(imports: list[str], rows_by_path: dict[str, RepoIndexedFile]) -> list[str]:
    paths = set(rows_by_path)
    by_stem: dict[str, str] = {str(Path(path).with_suffix("").as_posix()): path for path in paths}
    resolved = []
    for imported in imports:
        target = match_indexed_import(imported, paths, by_stem)
        if target:
            resolved.append(target)
    return sorted(set(resolved))


def _language_for_path(path: str) -> str | None:
    suffix = Path(path).suffix.lower()
    return {
        ".ts": "typescript",
        ".tsx": "typescript-react",
        ".js": "javascript",
        ".jsx": "javascript-react",
        ".py": "python",
        ".md": "markdown",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
    }.get(suffix)


def build_test_inventory(project_id: str, session: Session) -> list[TestInventoryItem]:
    metadata = {m.spec_name: m for m in session.exec(select(SpecMetadata)).all()}
    explicit_specs: set[str] | None = None
    if project_id and project_id != "default":
        explicit_specs = {
            name
            for name in session.exec(select(SpecMetadata.spec_name).where(SpecMetadata.project_id == project_id)).all()
        }

    latest_history = _latest_history_by_spec(project_id, session)
    inventory: list[TestInventoryItem] = []
    if not SPECS_DIR.exists():
        return inventory

    for spec_path in SPECS_DIR.glob("**/*.md"):
        spec_name = str(spec_path.relative_to(SPECS_DIR))
        meta = metadata.get(spec_name)
        if explicit_specs is not None and spec_name not in explicit_specs:
            continue
        if project_id == "default" and meta and meta.project_id not in (None, "default"):
            continue

        test_path = find_generated_test_path(spec_name, spec_path)
        if not test_path:
            continue
        categories = _detect_categories(spec_path)
        tags = meta.tags if meta else []
        hist = latest_history.get(spec_name)
        inventory.append(
            TestInventoryItem(
                spec_name=spec_name,
                spec_path=spec_path,
                test_path=test_path,
                tags=tags,
                categories=categories,
                project_id=meta.project_id if meta else None,
                last_status=hist.get("status") if hist else None,
                last_duration_seconds=hist.get("duration_seconds") if hist else None,
                recent_failures=int(hist.get("recent_failures") or 0) if hist else 0,
                flaky=bool(hist.get("flaky")) if hist else False,
            )
        )
    return inventory


def select_impacted_tests(
    changed_files: list[ChangedFileInput],
    inventory: list[TestInventoryItem],
    impact_maps: list[TestImpactMap] | None = None,
    repo_index: dict[str, Any] | None = None,
) -> ImpactResult:
    analysis_id = f"pria_{uuid.uuid4().hex[:12]}"
    file_summaries = [classify_changed_file(f) for f in changed_files]
    total = len(inventory)
    selected: dict[str, SelectedTest] = {}
    fallback_reason: str | None = None

    has_low_confidence_change = any(f["risk_level"] == "high" and f["area"] in {"config", "dependency", "infra"} for f in file_summaries)
    has_unknown_change = any(f["area"] == "unknown" for f in file_summaries)
    has_shared_source_change_without_index = any(
        f["area"] in {"frontend", "frontend_component", "backend", "backend_service"} for f in file_summaries
    ) and not repo_index and not impact_maps

    for item in inventory:
        if ALWAYS_RUN_TAGS.intersection({t.lower() for t in item.tags + item.categories}):
            _add_selection(selected, item, "Always-run smoke/critical/auth coverage", "high", "medium", "always_run")
        if item.recent_failures > 0 or item.flaky:
            _add_selection(selected, item, "Recently failed or flaky test", "high", "high", "history")

    for file_info in file_summaries:
        path = file_info["path"]
        for item in inventory:
            match = match_changed_file_to_test(path, file_info["area"], item, impact_maps or [], repo_index=repo_index)
            if match:
                reason, confidence, source = match
                risk = max_risk(file_info["risk_level"], "medium")
                _add_selection(selected, item, reason, confidence, risk, source)

    if has_low_confidence_change:
        fallback_reason = "Configuration, dependency, CI, or test infrastructure changed; full suite is safest."
    elif has_shared_source_change_without_index:
        fallback_reason = "Shared source changed but repository index is missing; full suite is safest."
    elif has_unknown_change and not selected:
        fallback_reason = "Changed files do not map to known test metadata or impact data."
    elif not selected and changed_files:
        fallback_reason = "No confident impacted tests found from current metadata."

    if fallback_reason:
        selected.clear()
        for item in inventory:
            _add_selection(selected, item, fallback_reason, "low", "high", "full_suite_fallback")

    selected_tests = sorted(selected.values(), key=lambda t: (_risk_rank(t.risk_level), t.spec_name), reverse=True)
    confidence = "low" if fallback_reason else _aggregate_confidence(selected_tests, bool(changed_files))
    risk_level = "high" if fallback_reason or has_low_confidence_change else _aggregate_risk(file_summaries, selected_tests)
    estimated = sum(t.estimated_duration_seconds or 0 for t in selected_tests) or None
    saved = max(total - len(selected_tests), 0) if total else None
    category_summary = summarize_categories(file_summaries, selected_tests)
    summary = build_summary(len(changed_files), len(selected_tests), total, confidence, fallback_reason)

    return ImpactResult(
        analysis_id=analysis_id,
        changed_files=file_summaries,
        selected_tests=selected_tests,
        total_candidate_tests=total,
        risk_level=risk_level,
        confidence=confidence,
        summary=summary,
        fallback_reason=fallback_reason,
        category_summary=category_summary,
        estimated_duration_seconds=estimated,
        saved_tests_count=saved,
    )


def classify_changed_file(file: ChangedFileInput) -> dict[str, Any]:
    path = file.path
    lower = path.lower()
    area = "unknown"
    risk = "medium"
    reason = "General source change"

    if lower.endswith(".md") or lower.startswith("docs/"):
        area, risk, reason = "docs", "low", "Documentation-only change"
    elif any(token in lower for token in LOW_CONFIDENCE_PATHS):
        area, risk, reason = "config", "high", "Configuration, dependency, CI, or infrastructure change"
        if "package" in lower or "requirements" in lower or "pyproject" in lower:
            area = "dependency"
        elif lower.startswith("k8s/") or "docker" in lower or lower.startswith("nginx/"):
            area = "infra"
    elif lower.startswith("web/src/app/"):
        area, reason = "frontend_route", "Next.js route/page change"
    elif lower.startswith("web/src/components/"):
        area, reason = "frontend_component", "Shared frontend component change"
    elif lower.startswith("web/"):
        area, reason = "frontend", "Frontend application change"
    elif lower.startswith("orchestrator/api/"):
        area, reason = "backend_api", "FastAPI endpoint change"
    elif lower.startswith("orchestrator/services/") or lower.startswith("orchestrator/workflows/"):
        area, reason = "backend_service", "Backend service/workflow change"
    elif lower.startswith("orchestrator/"):
        area, reason = "backend", "Backend application change"
    elif lower.startswith("tests/generated/") or lower.startswith("specs/"):
        area, risk, reason = "test", "low", "Test/spec change"
    elif lower.startswith("tests/") or lower.startswith("orchestrator/tests/"):
        area, risk, reason = "test_infra", "medium", "Test code change"

    if file.status in {"removed", "deleted", "renamed"}:
        risk = max_risk(risk, "medium")

    return {
        "path": path,
        "status": file.status,
        "additions": file.additions,
        "deletions": file.deletions,
        "changes": file.changes,
        "previous_filename": file.previous_filename,
        "area": area,
        "risk_level": risk,
        "reason": reason,
    }


def match_changed_file_to_test(
    changed_path: str,
    area: str,
    item: TestInventoryItem,
    impact_maps: list[TestImpactMap],
    repo_index: dict[str, Any] | None = None,
) -> tuple[str, str, str] | None:
    changed_lower = changed_path.lower()
    spec_lower = item.spec_name.lower()
    test_lower = (item.test_path or "").lower()
    tags = {t.lower() for t in item.tags + item.categories}

    if changed_lower.startswith("specs/") and changed_lower.endswith(".md"):
        rel = changed_path[len("specs/") :]
        if rel == item.spec_name:
            return ("Changed spec file maps directly to this generated test", "high", "direct_spec")
    if changed_lower.startswith("tests/generated/") and item.test_path and changed_lower.endswith(Path(item.test_path).name.lower()):
        return ("Changed generated test file maps directly to this spec", "high", "direct_test")
    if Path(changed_lower).stem and Path(changed_lower).stem in spec_lower:
        return ("Changed file name matches spec/test naming", "medium", "name_match")

    for impact in impact_maps:
        if impact.spec_name != item.spec_name:
            continue
        for impacted in impact.impacted_paths or []:
            impacted_lower = impacted.lower().strip("/")
            if impacted_lower and (changed_lower.startswith(impacted_lower) or impacted_lower in changed_lower):
                return ("Stored impact map links this path to the test", impact.confidence or "medium", "impact_map")

    repo_match = match_repo_index_to_test(changed_path, item, repo_index)
    if repo_match:
        return repo_match

    if area.startswith("frontend") and tags.intersection({"ui", "frontend", "browser", "e2e", "navigation", "homepage"}):
        return ("Frontend change matched browser/UI test metadata", "medium", "path_rule")
    if area == "frontend_route":
        route_hint = _route_hint_from_path(changed_path)
        if route_hint and route_hint in spec_lower:
            return (f"Route path '{route_hint}' matched spec name", "high", "route_rule")
    if area.startswith("backend") and tags.intersection({"api", "backend", "integration"}):
        return ("Backend change matched API/integration test metadata", "medium", "path_rule")
    if area == "test" and (spec_lower in changed_lower or Path(spec_lower).stem in changed_lower or Path(test_lower).name in changed_lower):
        return ("Changed test/spec artifact matched this test", "high", "direct_test")

    return None


def match_repo_index_to_test(
    changed_path: str,
    item: TestInventoryItem,
    repo_index: dict[str, Any] | None,
) -> tuple[str, str, str] | None:
    if not repo_index:
        return None
    impacted = impacted_paths_from_repo_index(changed_path, repo_index)
    if not impacted:
        return None
    route_tokens = {
        route.strip("/").lower()
        for file_info in impacted
        for route in _as_list(file_info.get("routes"))
        if route
    }
    keyword_tokens = {
        token.lower()
        for file_info in impacted
        for token in _as_list(file_info.get("keywords"))
        if token
    }
    path_tokens = {Path(str(file_info.get("path", ""))).stem.lower() for file_info in impacted}
    spec_tokens = set(re.split(r"[^a-z0-9]+", item.spec_name.lower()))
    tag_tokens = {token.lower() for token in item.tags + item.categories}
    all_test_tokens = spec_tokens.union(tag_tokens)
    if all_test_tokens.intersection(route_tokens.union(keyword_tokens, path_tokens)):
        return ("Repository index links changed file through imports/routes to this test", "high", "repo_index")
    return None


def impacted_paths_from_repo_index(changed_path: str, repo_index: dict[str, Any]) -> list[dict[str, Any]]:
    files = [_normalize_index_file(raw) for raw in repo_index.get("files", []) if isinstance(raw, dict)]
    by_path = {f["path"]: f for f in files if f.get("path")}
    reverse: dict[str, list[str]] = {}
    for f in files:
        importer = f.get("path")
        if not importer:
            continue
        for imported in _as_list(f.get("imports")):
            for target in _possible_import_targets(str(imported)):
                if target in by_path:
                    reverse.setdefault(target, []).append(importer)

    normalized_changed = changed_path.strip("/")
    queue = [normalized_changed]
    seen = set(queue)
    impacted: list[dict[str, Any]] = []
    while queue:
        current = queue.pop(0)
        row = by_path.get(current)
        if row:
            impacted.append(row)
        for importer in reverse.get(current, []):
            if importer not in seen:
                seen.add(importer)
                queue.append(importer)
    return impacted


def _normalize_index_file(raw: dict[str, Any]) -> dict[str, Any]:
    path = str(raw.get("path") or "").strip("/")
    imports = []
    for imported in _as_list(raw.get("imports")):
        imported_str = str(imported).strip("/")
        imports.extend(_possible_import_targets(imported_str))
    return {
        **raw,
        "path": path,
        "imports": sorted(set(imports)),
        "routes": _as_list(raw.get("routes")),
        "keywords": _as_list(raw.get("keywords")),
    }


def _possible_import_targets(imported: str) -> list[str]:
    base = imported.strip("/")
    if base.startswith("@/"):
        base = f"web/src/{base[2:]}"
    candidates = {base}
    for ext in ("", ".ts", ".tsx", ".js", ".jsx", ".py"):
        candidates.add(f"{base}{ext}")
    candidates.add(f"{base}/index.ts")
    candidates.add(f"{base}/index.tsx")
    return sorted(c.strip("/") for c in candidates if c)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def load_impact_maps(project_id: str, session: Session) -> list[TestImpactMap]:
    stmt = select(TestImpactMap)
    if project_id:
        stmt = stmt.where(TestImpactMap.project_id == project_id)
    return list(session.exec(stmt).all())


def refresh_impact_maps(project_id: str, inventory: list[TestInventoryItem], session: Session) -> None:
    existing = {
        row.spec_name: row
        for row in session.exec(select(TestImpactMap).where(TestImpactMap.project_id == project_id)).all()
    }
    for item in inventory:
        impacted_paths = infer_impacted_paths(item)
        row = existing.get(item.spec_name)
        if row:
            row.test_path = item.test_path
            row.tags = item.tags
            row.categories = item.categories
            row.impacted_paths = impacted_paths
            row.updated_at = datetime.utcnow()
            session.add(row)
        else:
            session.add(
                TestImpactMap(
                    project_id=project_id,
                    spec_name=item.spec_name,
                    test_path=item.test_path,
                    impacted_paths=impacted_paths,
                    tags=item.tags,
                    categories=item.categories,
                    source="metadata",
                    confidence="medium",
                )
            )


def sync_execution_history(project_id: str, session: Session) -> None:
    existing_run_ids = {
        r for r in session.exec(select(TestExecutionHistory.run_id).where(TestExecutionHistory.run_id != None)).all()
    }
    stmt = select(DBTestRun).where(DBTestRun.status.in_(["passed", "completed", "failed", "error", "stopped"]))
    if project_id:
        stmt = stmt.where(DBTestRun.project_id == project_id)
    for run in session.exec(stmt).all():
        if run.id in existing_run_ids:
            continue
        duration = None
        if run.started_at and run.completed_at:
            duration = max(0, int((run.completed_at - run.started_at).total_seconds()))
        session.add(
            TestExecutionHistory(
                project_id=run.project_id or project_id,
                spec_name=run.spec_name,
                test_name=run.test_name,
                browser=run.browser,
                status=run.status,
                duration_seconds=duration,
                failure_category=_failure_category(run.error_message),
                run_id=run.id,
                batch_id=run.batch_id,
                is_flaky=False,
                executed_at=run.completed_at or run.created_at or datetime.utcnow(),
            )
        )
    session.flush()


def find_generated_test_path(spec_name: str, spec_path: Path) -> str | None:
    stem = spec_path.stem
    full = spec_name[:-3] if spec_name.endswith(".md") else spec_name
    full_flat = full.replace("/", "_").replace("\\", "_")
    candidates = [
        f"{stem}.spec.ts",
        f"{stem.replace('_', '-')}.spec.ts",
        f"{stem.replace('-', '_')}.spec.ts",
        f"{full_flat}.spec.ts",
        f"{full_flat.replace('_', '-')}.spec.ts",
        f"{full_flat.replace('-', '_')}.spec.ts",
    ]
    for name in candidates:
        path = TESTS_DIR / name
        if path.exists():
            return str(path.relative_to(BASE_DIR))
    if TESTS_DIR.exists():
        for path in TESTS_DIR.glob(f"*{stem}*.spec.ts"):
            return str(path.relative_to(BASE_DIR))
    return None


def serialize_analysis(analysis: PrImpactAnalysis, session: Session, include_details: bool = True) -> dict[str, Any]:
    payload = {
        "id": analysis.id,
        "project_id": analysis.project_id,
        "provider": analysis.provider,
        "owner": analysis.owner,
        "repo": analysis.repo,
        "pr_number": analysis.pr_number,
        "title": analysis.title,
        "base_ref": analysis.base_ref,
        "head_ref": analysis.head_ref,
        "head_sha": analysis.head_sha,
        "author": analysis.author,
        "status": analysis.status,
        "risk_level": analysis.risk_level,
        "confidence": analysis.confidence,
        "summary": analysis.summary,
        "fallback_reason": analysis.fallback_reason,
        "changed_files_count": analysis.changed_files_count,
        "selected_tests_count": analysis.selected_tests_count,
        "total_candidate_tests": analysis.total_candidate_tests,
        "estimated_duration_seconds": analysis.estimated_duration_seconds,
        "saved_tests_count": analysis.saved_tests_count,
        "category_summary": analysis.category_summary or {},
        "batch_id": analysis.batch_id,
        "repository_index_snapshot": _parse_snapshot_note(analysis.ai_notes),
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        "completed_at": analysis.completed_at.isoformat() if analysis.completed_at else None,
    }
    if include_details:
        files = session.exec(select(PrChangedFile).where(PrChangedFile.analysis_id == analysis.id)).all()
        tests = session.exec(select(PrSelectedTest).where(PrSelectedTest.analysis_id == analysis.id)).all()
        payload["changed_files"] = [
            {
                "path": f.path,
                "status": f.status,
                "additions": f.additions,
                "deletions": f.deletions,
                "changes": f.changes,
                "previous_filename": f.previous_filename,
                "area": f.area,
                "risk_level": f.risk_level,
                "reason": f.reason,
            }
            for f in files
        ]
        payload["selected_tests"] = [
            {
                "spec_name": t.spec_name,
                "test_path": t.test_path,
                "reason": t.reason,
                "confidence": t.confidence,
                "risk_level": t.risk_level,
                "selection_source": t.selection_source,
                "estimated_duration_seconds": t.estimated_duration_seconds,
                "tags": t.tags or [],
                "categories": t.categories or [],
            }
            for t in tests
        ]
    return payload


def _add_selection(
    selected: dict[str, SelectedTest],
    item: TestInventoryItem,
    reason: str,
    confidence: str,
    risk_level: str,
    source: str,
) -> None:
    existing = selected.get(item.spec_name)
    candidate = SelectedTest(
        spec_name=item.spec_name,
        test_path=item.test_path,
        reason=reason if not existing else f"{existing.reason}; {reason}",
        confidence=max_confidence(existing.confidence if existing else confidence, confidence),
        risk_level=max_risk(existing.risk_level if existing else risk_level, risk_level),
        selection_source=source if not existing else f"{existing.selection_source},{source}",
        estimated_duration_seconds=item.last_duration_seconds,
        tags=item.tags,
        categories=item.categories,
    )
    selected[item.spec_name] = candidate


def _latest_history_by_spec(project_id: str, session: Session) -> dict[str, dict[str, Any]]:
    stmt = select(TestExecutionHistory)
    if project_id:
        stmt = stmt.where(TestExecutionHistory.project_id == project_id)
    rows = sorted(session.exec(stmt).all(), key=lambda r: r.executed_at or datetime.min, reverse=True)
    result: dict[str, dict[str, Any]] = {}
    failures: dict[str, int] = {}
    flaky: dict[str, bool] = {}
    statuses: dict[str, set[str]] = {}
    for row in rows:
        statuses.setdefault(row.spec_name, set()).add(row.status)
        if row.status in {"failed", "error", "stopped"}:
            failures[row.spec_name] = failures.get(row.spec_name, 0) + 1
        if len(statuses[row.spec_name].intersection({"passed", "completed"})) and len(
            statuses[row.spec_name].intersection({"failed", "error", "stopped"})
        ):
            flaky[row.spec_name] = True
        if row.spec_name not in result:
            result[row.spec_name] = {
                "status": row.status,
                "duration_seconds": row.duration_seconds,
                "recent_failures": 0,
                "flaky": False,
            }
    for spec_name, data in result.items():
        data["recent_failures"] = failures.get(spec_name, 0)
        data["flaky"] = flaky.get(spec_name, False)
    return result


def _detect_categories(spec_path: Path) -> list[str]:
    categories: set[str] = set()
    try:
        if SpecDetector:
            info = SpecDetector.get_spec_info(spec_path)
            categories.update(str(c) for c in info.get("categories", []) if c)
        text = spec_path.read_text(errors="replace").lower()
        for token in ("auth", "login", "api", "navigation", "search", "accessibility", "security", "database", "load"):
            if token in text:
                categories.add(token)
    except Exception:
        pass
    return sorted(categories)


def infer_impacted_paths(item: TestInventoryItem) -> list[str]:
    paths = set()
    text = ""
    try:
        text = item.spec_path.read_text(errors="replace").lower()
    except Exception:
        pass
    for match in re.findall(r"/[a-z0-9][a-z0-9_/\-.]*", text):
        if len(match) > 1 and not match.endswith((".png", ".jpg", ".svg")):
            paths.add(match.strip("/"))
    for tag in item.tags + item.categories:
        normalized = tag.lower().replace(" ", "-")
        if normalized:
            paths.add(normalized)
    return sorted(paths)[:25]


def summarize_categories(files: list[dict[str, Any]], tests: list[SelectedTest]) -> dict[str, Any]:
    file_areas: dict[str, int] = {}
    test_sources: dict[str, int] = {}
    for f in files:
        file_areas[f["area"]] = file_areas.get(f["area"], 0) + 1
    for t in tests:
        for source in t.selection_source.split(","):
            test_sources[source] = test_sources.get(source, 0) + 1
    return {"changed_file_areas": file_areas, "selection_sources": test_sources}


def build_summary(changed_count: int, selected_count: int, total: int, confidence: str, fallback_reason: str | None) -> str:
    if fallback_reason:
        return f"Analyzed {changed_count} changed files. Confidence is low, so all {total} automated tests are recommended."
    return f"Analyzed {changed_count} changed files and recommended {selected_count} of {total} automated tests with {confidence} confidence."


def max_risk(left: str, right: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    return left if order.get(left, 1) >= order.get(right, 1) else right


def max_confidence(left: str, right: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2}
    return left if order.get(left, 1) >= order.get(right, 1) else right


def _aggregate_confidence(tests: list[SelectedTest], has_changes: bool) -> str:
    if not has_changes:
        return "low"
    if not tests:
        return "low"
    if all(t.confidence == "high" for t in tests):
        return "high"
    if any(t.confidence == "low" for t in tests):
        return "low"
    return "medium"


def _aggregate_risk(files: list[dict[str, Any]], tests: list[SelectedTest]) -> str:
    risk = "low"
    for f in files:
        risk = max_risk(risk, f["risk_level"])
    for t in tests:
        risk = max_risk(risk, t.risk_level)
    return risk


def _risk_rank(risk: str) -> int:
    return {"low": 0, "medium": 1, "high": 2, "critical": 3}.get(risk, 1)


def _route_hint_from_path(path: str) -> str | None:
    marker = "web/src/app/"
    if marker not in path:
        return None
    rest = path.split(marker, 1)[1]
    parts = [p for p in rest.split("/") if p and not p.startswith("(") and p not in {"page.tsx", "layout.tsx"}]
    return parts[0].lower() if parts else "homepage"


def _failure_category(error_message: str | None) -> str | None:
    if not error_message:
        return None
    lower = error_message.lower()
    if "timeout" in lower:
        return "timeout"
    if "locator" in lower or "selector" in lower or "element" in lower:
        return "selector"
    if "expect" in lower or "assert" in lower:
        return "assertion"
    if "network" in lower or "navigation" in lower:
        return "navigation"
    return "unknown"


def to_json(value: Any) -> str:
    return json.dumps(value, default=str)


def _parse_snapshot_note(value: str | None) -> str | None:
    if not value:
        return None
    prefix = "repository_index_snapshot="
    if value.startswith(prefix):
        return value[len(prefix) :]
    return None
