"""Helpers for Playwright codegen recording sessions."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_codegen_command(target_url: str, code_path: Path, config: dict[str, Any]) -> list[str]:
    command = [
        "npx",
        "playwright",
        "codegen",
        "--target",
        "playwright-test",
        "--output",
        str(code_path),
    ]
    if config.get("device"):
        command.extend(["--device", config["device"]])
    elif config.get("viewport_size"):
        command.extend(["--viewport-size", config["viewport_size"]])
    if config.get("load_storage_path"):
        command.extend(["--load-storage", config["load_storage_path"]])
    if config.get("save_storage_path"):
        command.extend(["--save-storage", config["save_storage_path"]])
    if config.get("save_har_path"):
        command.extend(["--save-har", config["save_har_path"]])
    command.append(target_url)
    return command


def has_usable_codegen_output(code_path: Path) -> bool:
    if not code_path.exists() or code_path.stat().st_size == 0:
        return False
    try:
        code = code_path.read_text(encoding="utf-8")
    except OSError:
        return False

    action_lines = [
        line.strip()
        for line in code.splitlines()
        if line.strip().startswith("await page.") or line.strip().startswith("await expect(")
    ]
    if not action_lines:
        return False
    return any("page.goto(" not in line or "about:blank" not in line for line in action_lines)


def read_codegen_failure(code_path: Path | None, fallback: str = "Playwright recorder exited before producing code") -> str:
    if not code_path:
        return fallback
    stderr_path = code_path.with_name("codegen.err.log")
    try:
        message = stderr_path.read_text(encoding="utf-8").strip()
    except OSError:
        message = ""
    if not message:
        return fallback
    if len(message) > 1200:
        return f"{message[:1200].rstrip()}..."
    return message
