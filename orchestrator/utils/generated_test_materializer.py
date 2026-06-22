"""Utilities for copying reused generated tests into an active run directory."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MaterializedGeneratedTest:
    test_file_path: Path
    source_test_file_path: Path


def _resolve_source_path(source_path: str | Path, base_dir: str | Path | None = None) -> Path:
    source = Path(source_path).expanduser()
    if not source.is_absolute():
        source = Path(base_dir or Path.cwd()) / source
    return source.resolve()


def _run_local_generated_name(source: Path) -> str:
    stem = source.name
    if stem.endswith(".spec.ts"):
        return stem
    if stem.endswith(".ts"):
        stem = stem[:-3]
    else:
        stem = source.stem
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", stem).strip(".-") or "reused"
    if stem.endswith(".spec"):
        return f"{stem}.ts"
    return f"{stem}.spec.ts"


def materialize_generated_test_for_run(
    source_path: str | Path,
    run_dir: str | Path,
    *,
    base_dir: str | Path | None = None,
) -> MaterializedGeneratedTest:
    """Copy a generated test into ``run_dir/tests/generated`` for execution.

    Reused tests from older runs or repository-level generated directories must
    execute under the active run-local Playwright config. This helper preserves
    the original source path for metadata while ensuring all later reads, heals,
    preflight checks, and Playwright invocations use the active run-local copy.
    """
    source = _resolve_source_path(source_path, base_dir=base_dir)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Generated test file not found: {source_path}")

    run_dir_path = Path(run_dir).resolve()
    destination_dir = run_dir_path / "tests" / "generated"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / _run_local_generated_name(source)

    if source != destination.resolve():
        shutil.copy2(source, destination)

    return MaterializedGeneratedTest(
        test_file_path=destination,
        source_test_file_path=source,
    )
