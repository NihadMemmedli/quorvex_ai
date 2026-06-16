"""Proposal-only coding agent helpers.

Coding runs may inspect the current repository and return unified diffs, but
tracked file mutation is centralized in the explicit apply endpoint.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
except ImportError:  # pragma: no cover - SDK optional in tests
    PermissionResultAllow = None
    PermissionResultDeny = None


CODING_ARTIFACT_PATCH = "proposed.patch"
CODING_ARTIFACT_REVIEW = "review.md"
CODING_ARTIFACT_SUMMARY = "summary.md"

DEFAULT_REPO_ROOT = Path("/Users/nihadmammadli/Documents/projects/quorvex_ai")

WRITE_TOOLS = {"Edit", "MultiEdit", "Write", "NotebookEdit"}
READ_PATH_TOOLS = {"Read", "Grep", "Glob", "LS"}
SAFE_BASH_PREFIXES = (
    "pytest",
    "python -m pytest",
    "python3 -m pytest",
    "npm test",
    "npm run test",
    "npm run typecheck",
    "npm run lint",
    "npx vitest",
    "pnpm test",
    "pnpm run test",
    "pnpm run typecheck",
    "pnpm run lint",
    "yarn test",
    "yarn typecheck",
    "yarn lint",
)
UNSAFE_BASH_TOKENS = (
    ">",
    ">>",
    "tee ",
    "sed -i",
    "perl -i",
    "rm ",
    "mv ",
    "cp ",
    "touch ",
    "cat >",
    "python -c",
    "python3 -c",
    "node -e",
)
SECRET_PATH_PATTERNS = (
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    ".secrets/**",
    "**/.secrets/**",
    "*token*",
    "*secret*",
    "*credential*",
    "*credentials*",
    "*private_key*",
    "*id_rsa*",
)


@dataclass(frozen=True)
class PatchValidationResult:
    paths: tuple[str, ...]


def coding_agent_allowed_tools() -> list[str]:
    """Parent tools for proposal-mode coding runs."""

    return ["Task", "Read", "Grep", "Glob", "LS", "AskUserQuestion"]


def coding_agent_subagents() -> dict[str, dict[str, Any]]:
    """Claude Agent SDK subagent definitions for coding workflow roles."""

    return {
        "planner": {
            "description": "Inspects the repository and produces a concrete coding plan.",
            "prompt": (
                "You are the Planner for a Quorvex coding task. Inspect only the current "
                "repository. Identify relevant files, constraints, and a short ordered plan. "
                "Do not modify files."
            ),
            "tools": ["Read", "Grep", "Glob", "LS", "AskUserQuestion"],
        },
        "coder": {
            "description": "Prepares proposed code changes as a unified diff without writing files.",
            "prompt": (
                "You are the Coder for a Quorvex coding task. Read relevant files and produce "
                "a unified diff only. Do not call Edit, MultiEdit, Write, or shell commands that "
                "write to disk. Repository changes are applied later by an approval endpoint."
            ),
            "tools": ["Read", "Grep", "Glob", "LS"],
        },
        "reviewer": {
            "description": "Reviews proposed diffs and may run safe tests.",
            "prompt": (
                "You are the Reviewer for a Quorvex coding task. Review the proposed diff for "
                "risks, missing tests, and likely regressions. You may run only safe test or "
                "typecheck commands."
            ),
            "tools": ["Read", "Grep", "Glob", "LS", "Bash"],
        },
    }


def build_coding_agent_prompt(task: str, repo_root: Path | str = DEFAULT_REPO_ROOT) -> str:
    """Build a proposal-only coding prompt with explicit artifact contract."""

    return "\n".join(
        [
            "You are a Quorvex coding agent running in proposal-only mode.",
            f"Repository scope: {Path(repo_root)}",
            "",
            "Non-negotiable rules:",
            "- Inspect files as needed, but do not directly modify repository files.",
            "- Do not use Edit, MultiEdit, Write, NotebookEdit, or shell redirection.",
            "- Do not touch .env files, .secrets, tokens, credentials, or private keys.",
            "- Prepare a unified diff that can be applied from the repository root.",
            "- If no code change is safe, explain why and leave the patch section empty.",
            "",
            "Use the Planner/Coder/Reviewer team:",
            "1. Planner: inspect and create a concrete plan.",
            "2. Coder: prepare the unified diff.",
            "3. Reviewer: review risks and test commands attempted or recommended.",
            "",
            "Return exactly these sections:",
            "## Summary",
            "Brief factual summary.",
            "",
            "## Affected Files",
            "One file per line, or `None`.",
            "",
            "## Tests",
            "Commands attempted with outcomes, or recommended commands.",
            "",
            "## Review",
            "Risks, assumptions, and follow-up notes.",
            "",
            "## Proposed Patch",
            "A fenced ```diff block containing a unified diff, or an empty diff block.",
            "",
            f"Task:\n{task.strip()}",
        ]
    )


def build_coding_tool_permission_guard():
    """Deny direct writes and unsafe shell commands during proposal mode."""

    async def guard(tool_name: str, tool_input: dict[str, Any], _context: Any):
        short_name = str(tool_name).split("__")[-1] if "__" in str(tool_name) else str(tool_name)
        if short_name in WRITE_TOOLS:
            return _deny(f"{short_name} is blocked. Coding agents must return a proposed.patch artifact for approval.")
        if short_name in READ_PATH_TOOLS:
            blocked_path = _blocked_tool_path(tool_input)
            if blocked_path:
                return _deny(f"{short_name} cannot access out-of-scope or protected path: {blocked_path}")
        if short_name == "Bash":
            command = str(tool_input.get("command") or tool_input.get("cmd") or "").strip()
            if not is_safe_bash_command(command):
                return _deny("Only safe test/typecheck/lint shell commands are allowed in proposal mode.")
        return _allow()

    return guard


def is_safe_bash_command(command: str) -> bool:
    normalized = " ".join(command.strip().split())
    lowered = normalized.lower()
    if not normalized:
        return False
    if any(token in lowered for token in UNSAFE_BASH_TOKENS):
        return False
    return any(lowered == prefix or lowered.startswith(f"{prefix} ") for prefix in SAFE_BASH_PREFIXES)


def extract_unified_diff(output: str) -> str:
    """Extract the first diff fence or raw diff body from model output."""

    text = output or ""
    fence = re.search(r"```(?:diff|patch)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if fence and _looks_like_patch(fence.group(1)):
        return fence.group(1).strip() + "\n"
    marker = re.search(r"(?m)^(diff --git |\+\+\+ |--- )", text)
    if not marker:
        return ""
    return text[marker.start() :].strip() + "\n"


def split_coding_sections(output: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current = "Summary"
    chunks: dict[str, list[str]] = {current: []}
    for line in (output or "").splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            current = match.group(1).strip()
            chunks.setdefault(current, [])
            continue
        chunks.setdefault(current, []).append(line)
    for key, lines in chunks.items():
        sections[key] = "\n".join(lines).strip()
    return sections


def write_coding_artifacts(run_dir: Path, output: str) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    sections = split_coding_sections(output)
    patch = extract_unified_diff(sections.get("Proposed Patch") or output)
    summary = sections.get("Summary") or (output or "").strip()[:2000]
    review = sections.get("Review") or ""

    (run_dir / CODING_ARTIFACT_SUMMARY).write_text(summary.strip() + "\n", encoding="utf-8")
    (run_dir / CODING_ARTIFACT_REVIEW).write_text(review.strip() + "\n", encoding="utf-8")
    if patch:
        (run_dir / CODING_ARTIFACT_PATCH).write_text(patch, encoding="utf-8")

    affected_files = sorted(extract_patch_paths(patch)) if patch else []
    return {
        "summary": summary.strip(),
        "review": review.strip(),
        "patch_path": CODING_ARTIFACT_PATCH if patch else None,
        "patch_bytes": len(patch.encode("utf-8")) if patch else 0,
        "affected_files": affected_files,
        "tests": sections.get("Tests") or "",
    }


def validate_patch_for_repo(patch_text: str, repo_root: Path | str = DEFAULT_REPO_ROOT) -> PatchValidationResult:
    paths = extract_patch_paths(patch_text)
    if not paths:
        raise ValueError("Patch does not contain any file paths")
    repo = Path(repo_root).resolve()
    for rel in paths:
        path = Path(rel)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Patch path escapes repository: {rel}")
        candidate = (repo / path).resolve()
        if repo != candidate and repo not in candidate.parents:
            raise ValueError(f"Patch path escapes repository: {rel}")
        if is_secret_path(rel):
            raise ValueError(f"Patch touches a protected secret path: {rel}")
    return PatchValidationResult(paths=tuple(sorted(paths)))


def apply_patch_to_repo(
    patch_text: str,
    repo_root: Path | str = DEFAULT_REPO_ROOT,
    *,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    validation = validate_patch_for_repo(patch_text, repo_root)
    repo = Path(repo_root)
    check = subprocess.run(
        ["git", "apply", "--check", "--whitespace=nowarn", "-"],
        input=patch_text,
        text=True,
        cwd=repo,
        capture_output=True,
        timeout=timeout_seconds,
    )
    if check.returncode != 0:
        raise RuntimeError(check.stderr.strip() or check.stdout.strip() or "Patch validation failed")
    applied = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        input=patch_text,
        text=True,
        cwd=repo,
        capture_output=True,
        timeout=timeout_seconds,
    )
    if applied.returncode != 0:
        raise RuntimeError(applied.stderr.strip() or applied.stdout.strip() or "Patch apply failed")
    return {"affected_files": list(validation.paths), "stdout": applied.stdout.strip()}


def extract_patch_paths(patch_text: str) -> set[str]:
    paths: set[str] = set()
    for line in (patch_text or "").splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                for raw in parts[2:4]:
                    rel = _normalize_patch_path(raw)
                    if rel:
                        paths.add(rel)
        elif line.startswith("--- ") or line.startswith("+++ "):
            rel = _normalize_patch_path(line[4:].split("\t", 1)[0].strip())
            if rel:
                paths.add(rel)
    return paths


def is_secret_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("/")
    basename = normalized.rsplit("/", 1)[-1]
    candidates = {normalized, basename}
    return any(
        fnmatch.fnmatch(candidate.lower(), pattern.lower())
        for candidate in candidates
        for pattern in SECRET_PATH_PATTERNS
    )


def _blocked_tool_path(tool_input: dict[str, Any]) -> str | None:
    for key in ("file_path", "path", "directory", "glob"):
        value = tool_input.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        normalized = value.replace("\\", "/")
        if normalized.startswith("/") and not _path_is_inside_repo(normalized):
            return value
        if ".." in Path(normalized).parts:
            return value
        if is_secret_path(normalized):
            return value
    return None


def _path_is_inside_repo(path: str) -> bool:
    repo = DEFAULT_REPO_ROOT.resolve()
    candidate = Path(path).resolve()
    return candidate == repo or repo in candidate.parents


def _normalize_patch_path(raw: str) -> str | None:
    value = raw.strip().strip('"')
    if value in {"/dev/null", "dev/null"}:
        return None
    if value.startswith("a/") or value.startswith("b/"):
        value = value[2:]
    return value or None


def _looks_like_patch(text: str) -> bool:
    return bool(re.search(r"(?m)^(diff --git |\+\+\+ |--- )", text or ""))


def _allow():
    if PermissionResultAllow is not None:
        return PermissionResultAllow()
    return True


def _deny(message: str):
    if PermissionResultDeny is not None:
        return PermissionResultDeny(message=message)
    return False
