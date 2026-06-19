import asyncio
import json
import os
import re
import time as time_module
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from logging_config import get_logger

from .models import FolderNode
from .models_db import SpecMetadata as DBSpecMetadata
from .models_db import get_or_create_spec_metadata
from .spec_metadata import clean_metadata_tags, merge_metadata_tags

logger = get_logger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SPECS_DIR = BASE_DIR / "specs"
RUNS_DIR = BASE_DIR / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)
METADATA_FILE = SPECS_DIR / "spec-metadata.json"

# Spec info cache: path -> (mtime, spec_info_dict)
_spec_info_cache: dict[str, tuple] = {}
_MAX_SPEC_CACHE_SIZE = 5000

# Code path cache: spec_name -> (code_path, timestamp)
_code_path_cache: dict[str, tuple] = {}
_CODE_PATH_CACHE_TTL = 300
_MAX_CODE_CACHE_SIZE = 200


def sync_spec_metadata_from_file(session: Session, metadata_file: Path = METADATA_FILE) -> int:
    """Sync repo-owned metadata seed into SpecMetadata without clobbering user edits."""
    if not metadata_file.exists():
        return 0

    try:
        meta_dict = json.loads(metadata_file.read_text())
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON in metadata file {metadata_file}: {e}")
        return 0
    except OSError as e:
        logger.warning(f"Cannot read metadata file {metadata_file}: {e}")
        return 0

    if not isinstance(meta_dict, dict):
        logger.warning(f"Metadata file {metadata_file} must contain an object keyed by spec name")
        return 0

    changed = 0
    for spec_name, data in meta_dict.items():
        if not isinstance(spec_name, str) or not isinstance(data, dict):
            logger.warning(f"Skipping invalid metadata entry for {spec_name!r}")
            continue

        seed_tags = clean_metadata_tags(data.get("tags", []), lowercase=True)
        metas = session.exec(select(DBSpecMetadata).where(DBSpecMetadata.spec_name == spec_name)).all()
        if not metas:
            meta = get_or_create_spec_metadata(session, spec_name)
            meta = DBSpecMetadata(
                spec_name=spec_name,
                project_id=meta.project_id,
                tags_json=json.dumps(seed_tags),
                description=data.get("description"),
                author=data.get("author"),
            )
            lm = data.get("lastModified")
            if lm:
                try:
                    meta.last_modified = datetime.fromisoformat(lm)
                except ValueError:
                    logger.warning(f"Invalid lastModified date format for {spec_name}: {lm}")
            session.add(meta)
            changed += 1
            continue

        for meta in metas:
            merged_tags = merge_metadata_tags(meta.tags, seed_tags)
            if merged_tags != meta.tags:
                meta.tags = merged_tags
                changed += 1

            if not meta.description and data.get("description"):
                meta.description = data.get("description")
                changed += 1
            if not meta.author and data.get("author"):
                meta.author = data.get("author")
                changed += 1
            if not meta.last_modified and data.get("lastModified"):
                try:
                    meta.last_modified = datetime.fromisoformat(data["lastModified"])
                    changed += 1
                except ValueError:
                    logger.warning(f"Invalid lastModified date format for {spec_name}: {data['lastModified']}")

            session.add(meta)

    return changed


class SpecCache:
    """Cache for spec metadata list, invalidated when specs directory changes."""

    def __init__(self, specs_dir: Path):
        self._specs_dir = specs_dir
        self._cache: list[dict] | None = None
        self._last_mtime: float = 0
        self._lock = asyncio.Lock()

    def _get_dir_mtime(self) -> float:
        """Get the latest mtime of the specs directory tree."""
        try:
            max_mtime = self._specs_dir.stat().st_mtime
            for p in self._specs_dir.rglob("*.md"):
                max_mtime = max(max_mtime, p.stat().st_mtime)
            return max_mtime
        except OSError:
            return 0

    def invalidate(self):
        """Force cache invalidation."""
        self._cache = None
        self._last_mtime = 0

    async def get_specs(self, builder_fn) -> list[dict]:
        """Get cached spec list, rebuilding if directory changed."""
        current_mtime = self._get_dir_mtime()
        if self._cache is not None and current_mtime == self._last_mtime:
            return self._cache

        async with self._lock:
            current_mtime = self._get_dir_mtime()
            if self._cache is not None and current_mtime == self._last_mtime:
                return self._cache

            self._cache = builder_fn()
            self._last_mtime = current_mtime
            return self._cache


_spec_cache = SpecCache(SPECS_DIR)


def get_try_code_path_fast(spec_path: Path) -> str | None:
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


def get_cached_spec_info(spec_path: Path) -> dict:
    """Get spec info with caching based on file modification time."""
    from utils.spec_detector import SpecDetector

    path_str = str(spec_path)
    try:
        current_mtime = spec_path.stat().st_mtime
    except OSError:
        current_mtime = 0

    if path_str in _spec_info_cache:
        cached_mtime, cached_info = _spec_info_cache[path_str]
        if cached_mtime == current_mtime:
            return cached_info

    try:
        spec_info = SpecDetector.get_spec_info(spec_path)
        result = {
            "type": spec_info["type"],
            "test_count": spec_info["test_count"],
            "categories": spec_info["categories"],
        }
    except Exception:
        result = {"type": "standard", "test_count": 1, "categories": []}

    if len(_spec_info_cache) >= _MAX_SPEC_CACHE_SIZE:
        keys = list(_spec_info_cache.keys())
        for k in keys[: len(keys) // 2]:
            del _spec_info_cache[k]
    _spec_info_cache[path_str] = (current_mtime, result)
    return result


def build_folder_tree(
    specs_dir: Path,
    project_spec_names: set | None = None,
    excluded_spec_names: set | None = None,
    cache_key: str | None = None,
) -> tuple[list[FolderNode], int]:
    """Build folder tree with automated spec counts using O(n) construction."""
    if cache_key and cache_key in _folder_tree_cache:
        cached_tree, cached_total, cached_time = _folder_tree_cache[cache_key]
        if time_module.time() - cached_time < _FOLDER_TREE_CACHE_TTL:
            return cached_tree, cached_total

    folder_counts: dict[str, int] = {}
    total_specs = 0

    if specs_dir.exists():
        for f in specs_dir.glob("**/*.md"):
            code_path = get_try_code_path_fast(f)
            if not code_path:
                continue

            spec_name = str(f.relative_to(specs_dir))
            if project_spec_names is not None and spec_name not in project_spec_names:
                continue
            if excluded_spec_names and spec_name in excluded_spec_names:
                continue

            total_specs += 1
            rel_path = f.relative_to(specs_dir)
            parts = list(rel_path.parts[:-1])
            for i in range(len(parts)):
                folder_path = "/".join(parts[: i + 1])
                folder_counts[folder_path] = folder_counts.get(folder_path, 0) + 1

    children_by_parent: dict[str, list[str]] = {}
    for folder_path in folder_counts:
        parent_path = folder_path.rsplit("/", 1)[0] if "/" in folder_path else ""
        children_by_parent.setdefault(parent_path, []).append(folder_path)

    def build_node(folder_path: str) -> FolderNode:
        name = folder_path.rsplit("/", 1)[-1] if "/" in folder_path else folder_path
        child_paths = children_by_parent.get(folder_path, [])
        children = [build_node(cp) for cp in sorted(child_paths, key=str.lower)]
        return FolderNode(name=name, path=folder_path, spec_count=folder_counts.get(folder_path, 0), children=children)

    root_paths = children_by_parent.get("", [])
    root_nodes = [build_node(rp) for rp in sorted(root_paths, key=str.lower)]

    if cache_key:
        _folder_tree_cache[cache_key] = (root_nodes, total_specs, time_module.time())

    return root_nodes, total_specs


_folder_tree_cache: dict[str, tuple] = {}
_FOLDER_TREE_CACHE_TTL = 60


def _read_text_if_exists(path_value: str | None) -> str:
    if not path_value:
        return ""
    try:
        path = Path(path_value)
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8")
    except Exception:
        return ""
    return ""


def required_test_data_refs_for_spec(spec_path: Path, code_path: str | None = None) -> list[str]:
    from orchestrator.services.test_data_resolver import extract_test_data_refs_from_sources

    markdown = _read_text_if_exists(str(spec_path))
    generated_code = _read_text_if_exists(code_path)
    return extract_test_data_refs_from_sources(markdown=markdown, generated_code=generated_code)


def get_try_code_path(spec_name: str, spec_path: Path) -> str | None:
    """Get the generated test file path for a spec."""
    if spec_name in _code_path_cache:
        cached_path, cached_time = _code_path_cache[spec_name]
        if time_module.time() - cached_time < _CODE_PATH_CACHE_TTL:
            if cached_path and Path(cached_path).exists():
                return cached_path

    try_code_path = get_try_code_path_fast(spec_path)
    if try_code_path:
        _cache_code_path(spec_name, try_code_path)
        return try_code_path

    spec_test_name = None
    if spec_path.exists():
        content = spec_path.read_text()
        for line in content.split("\n"):
            if line.startswith("# "):
                spec_test_name = line.replace("# ", "").replace("Test:", "").strip()
                break

    if RUNS_DIR.exists():
        run_dirs = sorted(
            [d for d in RUNS_DIR.iterdir() if d.is_dir()], key=lambda x: os.path.getmtime(x), reverse=True
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
                except json.JSONDecodeError as e:
                    logger.debug(f"Invalid JSON in {plan_file} or {export_file}: {e}")
                except OSError as e:
                    logger.debug(f"Cannot read {plan_file} or {export_file}: {e}")
            if try_code_path:
                break

    if not try_code_path and spec_test_name:
        test_slug = re.sub(r"[^a-z0-9]+", "-", spec_test_name.lower()).strip("-")
        candidates = [
            f"tests/templates/{test_slug}.spec.ts",
            f"tests/generated/{test_slug}.spec.ts",
        ]
        for c in candidates:
            if (BASE_DIR / c).exists():
                try_code_path = str(BASE_DIR / c)
                break

    _cache_code_path(spec_name, try_code_path)
    return try_code_path


def _cache_code_path(spec_name: str, code_path: str | None) -> None:
    if len(_code_path_cache) >= _MAX_CODE_CACHE_SIZE:
        keys = list(_code_path_cache.keys())
        for k in keys[: len(keys) // 2]:
            del _code_path_cache[k]
    _code_path_cache[spec_name] = (code_path, time_module.time())


def invalidate_code_path_cache(spec_name: str | None = None):
    """Invalidate code path cache for a spec or all specs."""
    if spec_name:
        _code_path_cache.pop(spec_name, None)
    else:
        _code_path_cache.clear()
