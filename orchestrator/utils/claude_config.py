"""Helpers for preparing run-local Claude project configuration."""

from __future__ import annotations

import shutil
from pathlib import Path


RUN_LOCAL_CLAUDE_EXCLUDES = (
    Path("settings.local.json"),
    Path("settings.json"),
    Path("memory"),
)


def _is_excluded_claude_path(relative_path: Path) -> bool:
    normalized = Path(*relative_path.parts)
    return any(
        normalized == excluded or excluded in normalized.parents
        for excluded in RUN_LOCAL_CLAUDE_EXCLUDES
    )


def _remove_if_exists(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return


def copy_claude_project_config(source: Path, destination: Path) -> bool:
    """Copy project Claude artifacts into a run sandbox without local settings.

    Returns True when the source directory exists and copy/cleanup completed.
    """
    if not source.exists():
        return False

    source = source.resolve()

    def ignore(directory: str, names: list[str]) -> set[str]:
        directory_path = Path(directory).resolve()
        ignored: set[str] = set()
        for name in names:
            candidate = directory_path / name
            try:
                relative = candidate.relative_to(source)
            except ValueError:
                continue
            if _is_excluded_claude_path(relative):
                ignored.add(name)
        return ignored

    shutil.copytree(source, destination, dirs_exist_ok=True, ignore=ignore)
    for excluded in RUN_LOCAL_CLAUDE_EXCLUDES:
        _remove_if_exists(destination / excluded)
    return True
