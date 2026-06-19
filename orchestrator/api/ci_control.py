"""Provider-neutral CI/CD control center API.

This router keeps the UI away from provider-specific endpoint differences while
the existing /github and /gitlab APIs remain available for compatibility.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from ..services.batch_executor import BASE_DIR, SPECS_DIR, _get_try_code_path
from ..services.github_client import GithubError
from .credentials import decrypt_credential
from .db import get_session
from .github_ci import (
    _build_client as _build_github_client,
)
from .github_ci import (
    _get_github_config,
    _require_project,
    _save_github_config,
    _update_mapping_from_run,
)
from .gitlab_ci import _build_client as _build_gitlab_client
from .gitlab_ci import _get_gitlab_config, _save_gitlab_config
from .middleware.auth import get_current_user_optional
from .middleware.permissions import EDIT_ROLES, VIEW_ROLES, check_project_access
from .models_auth import User
from .models_db import (
    CiAuditEvent,
    CiPipelineMapping,
    CiTestSubset,
    CiTestSubsetItem,
    CiWorkflowChangeRequest,
    SpecMetadata,
)
from .models_db import get_spec_metadata as get_db_spec_metadata

router = APIRouter(prefix="/projects/{project_id}/ci", tags=["ci-control"])

Provider = Literal["github", "gitlab"]

RUNNER_SUBSET_SUITES = {
    "auto",
    "python-unit",
    "python-integration",
    "frontend-typecheck",
    "frontend-lint",
    "playwright-generated",
    "playwright-e2e",
    "all-safe",
}
RUNNER_SUBSET_BROWSERS = {"chromium", "firefox", "webkit"}
RUNNER_SUBSET_MARKERS = {"not integration", "integration"}
RUNNER_SUBSET_INPUT_KEYS = {"suite", "browser", "pytest_marker", "test_path", "playwright_grep", "base_url"}
RUNNER_SUBSET_WORKFLOW_IDS = {
    "quorvex-subset-tests.yml",
    ".github/workflows/quorvex-subset-tests.yml",
    "runner-subset-tests",
}


class DispatchWorkflowRequest(BaseModel):
    provider: Provider = "github"
    workflow_id: str | None = None
    ref: str | None = None
    inputs: dict[str, str] | None = None


class RerunRunRequest(BaseModel):
    failed_only: bool = False


class SyncRunsRequest(BaseModel):
    provider: Provider | Literal["all"] = "all"
    workflow_id: str | None = None
    per_page: int = 20


class WorkflowGenerateRequest(BaseModel):
    provider: Provider = "github"
    workflow_name: str = "Quorvex Test Automation"
    template: Literal[
        "pr-quality-gate",
        "playwright-smoke",
        "nightly-regression",
        "release-gate",
        "runner-subset-tests",
    ] = "pr-quality-gate"
    quality_gate_mode: Literal["backend-async", "backend-blocking"] = "backend-async"
    prompt: str | None = None
    ref: str | None = None
    target_url_secret: str = "APP_BASE_URL"
    api_url_secret: str = "QUORVEX_API_URL"
    api_token_secret: str = "QUORVEX_API_TOKEN"
    project_id_variable: str = "QUORVEX_PROJECT_ID"
    branches: list[str] | None = None
    browsers: list[str] | None = None
    artifact_retention_days: int = 14
    wait_timeout_minutes: int = 120


class WorkflowPullRequestRequest(BaseModel):
    base_ref: str | None = None
    branch_name: str | None = None
    title: str | None = None
    body: str | None = None
    commit_message: str | None = None
    draft: bool = True


class TestSubsetItemRequest(BaseModel):
    spec_name: str
    target_path: str | None = None


class TestSubsetCreateRequest(BaseModel):
    name: str
    description: str | None = None
    mode: Literal["manual", "pr-impact", "both"] = "both"
    default_browser: Literal["chromium", "firefox", "webkit"] = "chromium"
    base_url_secret: str = "APP_BASE_URL"
    items: list[TestSubsetItemRequest]


class TestSubsetUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    mode: Literal["manual", "pr-impact", "both"] | None = None
    default_browser: Literal["chromium", "firefox", "webkit"] | None = None
    base_url_secret: str | None = None
    items: list[TestSubsetItemRequest] | None = None


class TestSubsetPullRequestRequest(WorkflowPullRequestRequest):
    workflow_name: str | None = None
    commit_message: str | None = None


class TestSubsetDispatchRequest(BaseModel):
    workflow_id: str | None = None
    ref: str | None = None
    browser: Literal["chromium", "firefox", "webkit"] | None = None
    base_url: str | None = None


class UpdateProviderDefaultsRequest(BaseModel):
    provider: Provider
    repository: str | None = None
    owner: str | None = None
    repo: str | None = None
    gitlab_project_id: int | None = None
    base_url: str | None = None
    default_ref: str | None = None
    default_workflow: str | None = None


def _actor(user: User | None) -> tuple[str | None, str | None]:
    if not user:
        return None, None
    return user.id, user.email


def _audit(
    session: Session,
    *,
    project_id: str,
    provider: str,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    status: str = "ok",
    user: User | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    actor_id, actor_email = _actor(user)
    session.add(
        CiAuditEvent(
            project_id=project_id,
            provider=provider,
            action=action,
            target_type=target_type,
            target_id=target_id,
            status=status,
            actor_id=actor_id,
            actor_email=actor_email,
            event_metadata=metadata,
        )
    )


async def _require_view(project_id: str, user: User | None, session: Session) -> None:
    await check_project_access(project_id, user, VIEW_ROLES, session)


async def _require_edit(project_id: str, user: User | None, session: Session) -> None:
    await check_project_access(project_id, user, EDIT_ROLES, session)


def _serialize_mapping(mapping: CiPipelineMapping, provider: str | None = None) -> dict[str, Any]:
    return {
        "id": mapping.id,
        "provider": provider or mapping.provider,
        "external_pipeline_id": mapping.external_pipeline_id,
        "external_project_id": mapping.external_project_id,
        "external_url": mapping.external_url,
        "ref": mapping.ref,
        "status": mapping.status,
        "triggered_from": mapping.triggered_from,
        "stages": mapping.stages,
        "name": mapping.external_pipeline_id,
        "total_tests": mapping.total_tests,
        "passed_tests": mapping.passed_tests,
        "failed_tests": mapping.failed_tests,
        "test_report_url": mapping.test_report_url,
        "artifacts": mapping.artifacts,
        "action_availability": _action_availability(mapping),
        "created_at": mapping.created_at.isoformat() if mapping.created_at else None,
        "started_at": mapping.started_at.isoformat() if mapping.started_at else None,
        "completed_at": mapping.completed_at.isoformat() if mapping.completed_at else None,
    }


def _github_repo(config: dict[str, Any]) -> tuple[str, str]:
    owner = config.get("owner", "")
    repo = config.get("repo", "")
    if not owner or not repo:
        raise HTTPException(status_code=400, detail="GitHub owner and repo must be configured")
    return owner, repo


def _gitlab_project(config: dict[str, Any]) -> int:
    project_id = config.get("project_id")
    if not project_id:
        raise HTTPException(status_code=400, detail="GitLab project ID must be configured")
    return int(project_id)


def _latest_run_after_dispatch(runs: list[dict[str, Any]], workflow_id: str, ref: str) -> dict[str, Any] | None:
    workflow_key = str(workflow_id)
    candidates = []
    for run in runs:
        if run.get("head_branch") != ref:
            continue
        run_workflow_id = str(run.get("workflow_id") or "")
        run_path = str(run.get("path") or "")
        if run_workflow_id == workflow_key or run_path.endswith(workflow_key) or workflow_key in run_path:
            candidates.append(run)
    return candidates[0] if candidates else (runs[0] if runs else None)


def _latest_sync_at(session: Session, project_id: str, provider: str) -> str | None:
    stmt = (
        select(CiPipelineMapping)
        .where(CiPipelineMapping.project_id == project_id, CiPipelineMapping.provider == provider)
        .order_by(CiPipelineMapping.created_at.desc())
        .limit(1)
    )
    mapping = session.exec(stmt).first()
    return mapping.created_at.isoformat() if mapping and mapping.created_at else None


def _action_availability(mapping: CiPipelineMapping) -> dict[str, Any]:
    status = (mapping.status or "").lower()
    has_provider_id = bool(mapping.external_pipeline_id) and not str(mapping.external_pipeline_id).startswith("pending-")
    active = status in {"pending", "running", "queued", "waiting", "in_progress"}
    failed = status in {"failed", "failure"}
    complete = status in {"success", "completed", "failed", "failure", "canceled", "cancelled", "skipped"}
    disabled_reason = None if has_provider_id else "Provider run ID is not available yet. Refresh after the provider creates the run."
    return {
        "can_open_details": True,
        "can_open_provider": bool(mapping.external_url),
        "can_cancel": has_provider_id and active,
        "can_rerun": has_provider_id and complete,
        "can_rerun_failed": has_provider_id and mapping.provider == "github" and failed,
        "can_fetch_logs": has_provider_id,
        "disabled_reason": disabled_reason,
    }


def _slugify_subset_name(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:64].strip("-") or "generated-tests"


def _validate_secret_name(value: str, *, label: str = "secret") -> str:
    secret = (value or "").strip() or "APP_BASE_URL"
    if not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,99}", secret):
        raise HTTPException(status_code=400, detail=f"{label} must be an uppercase GitHub secret or variable name")
    return secret


def _validate_ci_subset_target_path(value: str) -> str:
    path = value.strip()
    if not path:
        raise HTTPException(status_code=400, detail="target_path is required")
    if len(path) > 180:
        raise HTTPException(status_code=400, detail="target_path must be 180 characters or fewer")
    if path.startswith("/") or "\\" in path or "\n" in path or "\r" in path:
        raise HTTPException(status_code=400, detail="target_path must be a safe repo-relative path")
    if re.search(r"[;&|`$<>(){}]", path):
        raise HTTPException(status_code=400, detail="target_path contains unsupported shell characters")
    parts = [part for part in path.split("/") if part]
    if any(part == ".." for part in parts):
        raise HTTPException(status_code=400, detail="target_path must not contain parent directory segments")
    if not path.startswith(("tests/generated/", "tests/e2e/")):
        raise HTTPException(status_code=400, detail="target_path must be under tests/generated or tests/e2e")
    if not path.endswith((".spec.ts", ".test.ts")):
        raise HTTPException(status_code=400, detail="target_path must be a Playwright .spec.ts or .test.ts file")
    return path


def _default_target_path(code_path: Path) -> str:
    try:
        rel = code_path.resolve().relative_to(BASE_DIR.resolve()).as_posix()
    except ValueError:
        rel = f"tests/generated/{code_path.name}"
    if rel.startswith(("tests/generated/", "tests/e2e/")):
        return _validate_ci_subset_target_path(rel)
    return _validate_ci_subset_target_path(f"tests/generated/{code_path.name}")


def _spec_allowed_for_project(meta: SpecMetadata | None, project_id: str) -> bool:
    if not meta or not meta.project_id:
        return True
    if project_id == "default":
        return meta.project_id in (None, "default")
    return meta.project_id in (project_id, "default")


def _lookup_spec_metadata_for_project(session: Session, spec_name: str, project_id: str) -> SpecMetadata | None:
    return (
        get_db_spec_metadata(session, spec_name, project_id)
        or get_db_spec_metadata(session, spec_name, "default")
        or session.exec(select(SpecMetadata).where(SpecMetadata.spec_name == spec_name)).first()
    )


def _resolve_generated_test(
    *,
    project_id: str,
    spec_name: str,
    target_path: str | None,
    session: Session,
) -> dict[str, Any]:
    cleaned = spec_name.strip()
    if not cleaned or cleaned.startswith("/") or ".." in Path(cleaned).parts:
        raise HTTPException(status_code=400, detail=f"Invalid spec name: {spec_name}")
    spec_path = SPECS_DIR / cleaned
    if not spec_path.exists() or not spec_path.is_file():
        raise HTTPException(status_code=404, detail=f"Spec not found: {cleaned}")
    meta = _lookup_spec_metadata_for_project(session, cleaned, project_id)
    if not _spec_allowed_for_project(meta, project_id):
        raise HTTPException(status_code=404, detail=f"Spec not found in this project: {cleaned}")
    code = _get_try_code_path(cleaned, spec_path)
    if not code:
        raise HTTPException(status_code=404, detail=f"No generated test found for spec: {cleaned}")
    code_path = Path(code)
    if not code_path.exists() or not code_path.is_file():
        raise HTTPException(status_code=404, detail=f"Generated test file is missing for spec: {cleaned}")
    content = code_path.read_text(encoding="utf-8", errors="replace")
    try:
        rel_code_path = code_path.resolve().relative_to(BASE_DIR.resolve()).as_posix()
    except ValueError:
        rel_code_path = code_path.name
    resolved_target = _validate_ci_subset_target_path(target_path) if target_path else _default_target_path(code_path)
    return {
        "spec_name": cleaned,
        "code_path": rel_code_path,
        "target_path": resolved_target,
        "content": content,
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "tags": meta.tags if meta else [],
        "categories": [],
        "last_modified": code_path.stat().st_mtime,
    }


def _generated_ci_tests(project_id: str, session: Session) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not SPECS_DIR.exists():
        return records
    for spec_path in sorted(SPECS_DIR.glob("**/*.md")):
        spec_name = spec_path.relative_to(SPECS_DIR).as_posix()
        meta = _lookup_spec_metadata_for_project(session, spec_name, project_id)
        if not _spec_allowed_for_project(meta, project_id):
            continue
        code = _get_try_code_path(spec_name, spec_path)
        if not code:
            continue
        code_path = Path(code)
        if not code_path.exists() or not code_path.is_file():
            continue
        content = code_path.read_text(encoding="utf-8", errors="replace")
        try:
            rel_code_path = code_path.resolve().relative_to(BASE_DIR.resolve()).as_posix()
        except ValueError:
            rel_code_path = code_path.name
        records.append(
            {
                "spec_name": spec_name,
                "code_path": rel_code_path,
                "target_path": _default_target_path(code_path),
                "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "tags": meta.tags if meta else [],
                "categories": [],
                "last_modified": code_path.stat().st_mtime,
            }
        )
    return records


def _serialize_subset_item(item: CiTestSubsetItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "spec_name": item.spec_name,
        "code_path": item.code_path,
        "target_path": item.target_path,
        "content_hash": item.content_hash,
        "tags": item.tags or [],
        "categories": item.categories or [],
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def _subset_items(session: Session, subset_id: str) -> list[CiTestSubsetItem]:
    return session.exec(
        select(CiTestSubsetItem)
        .where(CiTestSubsetItem.subset_id == subset_id)
        .order_by(CiTestSubsetItem.spec_name)
    ).all()


def _serialize_subset(subset: CiTestSubset, session: Session, *, include_items: bool = True) -> dict[str, Any]:
    items = _subset_items(session, subset.id) if include_items else []
    return {
        "id": subset.id,
        "project_id": subset.project_id,
        "name": subset.name,
        "slug": subset.slug,
        "description": subset.description,
        "mode": subset.mode,
        "default_browser": subset.default_browser,
        "base_url_secret": subset.base_url_secret,
        "item_count": len(items),
        "items": [_serialize_subset_item(item) for item in items] if include_items else None,
        "created_at": subset.created_at.isoformat() if subset.created_at else None,
        "updated_at": subset.updated_at.isoformat() if subset.updated_at else None,
    }


def _apply_subset_items(
    *,
    subset: CiTestSubset,
    project_id: str,
    item_requests: list[TestSubsetItemRequest],
    session: Session,
) -> list[CiTestSubsetItem]:
    if not item_requests:
        raise HTTPException(status_code=400, detail="At least one generated test must be selected")

    seen_specs: set[str] = set()
    seen_paths: set[str] = set()
    resolved: list[dict[str, Any]] = []
    for item_request in item_requests:
        item = _resolve_generated_test(
            project_id=project_id,
            spec_name=item_request.spec_name,
            target_path=item_request.target_path,
            session=session,
        )
        if item["spec_name"] in seen_specs:
            raise HTTPException(status_code=400, detail=f"Duplicate spec selected: {item['spec_name']}")
        if item["target_path"] in seen_paths:
            raise HTTPException(status_code=400, detail=f"Duplicate target path selected: {item['target_path']}")
        seen_specs.add(item["spec_name"])
        seen_paths.add(item["target_path"])
        resolved.append(item)

    for existing in _subset_items(session, subset.id):
        session.delete(existing)
    session.flush()

    rows: list[CiTestSubsetItem] = []
    for item in resolved:
        row = CiTestSubsetItem(
            subset_id=subset.id,
            spec_name=item["spec_name"],
            code_path=item["code_path"],
            target_path=item["target_path"],
            content_hash=item["content_hash"],
            tags=item["tags"],
            categories=item["categories"],
        )
        session.add(row)
        rows.append(row)
    return rows


def _subset_manifest(subset: CiTestSubset, items: list[CiTestSubsetItem]) -> str:
    manifest = {
        "schema_version": 1,
        "name": subset.name,
        "slug": subset.slug,
        "mode": subset.mode,
        "default_browser": subset.default_browser,
        "base_url_secret": subset.base_url_secret,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "tests": [
            {
                "spec_name": item.spec_name,
                "source_path": item.code_path,
                "target_path": item.target_path,
                "content_hash": item.content_hash,
                "tags": item.tags or [],
                "categories": item.categories or [],
            }
            for item in items
        ],
    }
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def _render_subset_workflow(subset: CiTestSubset, *, workflow_name: str | None = None) -> str:
    name = workflow_name or f"Quorvex {subset.name}"
    manifest_path = f".quorvex/test-subsets/{subset.slug}.json"
    return f"""name: {name}

on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
  workflow_dispatch:
    inputs:
      subset_slug:
        description: Quorvex subset slug
        required: false
        type: string
        default: {subset.slug}
      browser:
        description: Playwright browser
        required: true
        type: choice
        default: {subset.default_browser}
        options:
          - chromium
          - firefox
          - webkit
      base_url:
        description: Optional BASE_URL override
        required: false
        type: string

permissions:
  contents: read

jobs:
  quorvex-generated-subset:
    if: github.event_name != 'pull_request' || github.event.pull_request.draft == false
    runs-on: ubuntu-latest
    env:
      QUORVEX_API_URL: ${{{{ secrets.QUORVEX_API_URL }}}}
      QUORVEX_API_TOKEN: ${{{{ secrets.QUORVEX_API_TOKEN }}}}
      QUORVEX_PROJECT_ID: ${{{{ vars.QUORVEX_PROJECT_ID || 'default' }}}}
      BASE_URL: ${{{{ inputs.base_url || secrets.{subset.base_url_secret} }}}}
      BROWSER: ${{{{ inputs.browser || '{subset.default_browser}' }}}}
      SUBSET_MANIFEST: {manifest_path}
      SUBSET_MODE: {subset.mode}
      PR_NUMBER: ${{{{ github.event.pull_request.number || '' }}}}
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: 20

      - name: Install dependencies
        run: |
          set -euo pipefail
          if [ -f package-lock.json ]; then
            npm ci
          else
            npm install
          fi
          npx playwright install --with-deps "$BROWSER"

      - name: Select Quorvex generated tests
        run: |
          set -euo pipefail
          node <<'NODE'
          const fs = require('fs');
          const manifestPath = process.env.SUBSET_MANIFEST;
          const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
          const allTests = Array.isArray(manifest.tests) ? manifest.tests : [];
          let selected = allTests;
          const canAskQuorvex = process.env.GITHUB_EVENT_NAME === 'pull_request'
            && process.env.SUBSET_MODE !== 'manual'
            && process.env.QUORVEX_API_URL
            && process.env.QUORVEX_API_TOKEN
            && process.env.PR_NUMBER;

          async function main() {{
            if (canAskQuorvex) {{
              try {{
                const response = await fetch(`${{process.env.QUORVEX_API_URL.replace(/\\/$/, '')}}/github/${{process.env.QUORVEX_PROJECT_ID}}/pr-advisor/analyze`, {{
                  method: 'POST',
                  headers: {{
                    'Authorization': `Bearer ${{process.env.QUORVEX_API_TOKEN}}`,
                    'Content-Type': 'application/json',
                  }},
                  body: JSON.stringify({{ pr_number: Number(process.env.PR_NUMBER), ensure_indexed: true }}),
                }});
                if (response.ok) {{
                  const analysis = await response.json();
                  const recommended = new Set((analysis.selected_tests || []).flatMap((test) => [
                    test.spec_name,
                    test.test_path,
                    test.target_path,
                  ].filter(Boolean)));
                  const narrowed = allTests.filter((test) => recommended.has(test.spec_name) || recommended.has(test.target_path));
                  if (narrowed.length > 0) selected = narrowed;
                }} else {{
                  console.log(`Quorvex PR Advisor returned ${{response.status}}; falling back to saved subset.`);
                }}
              }} catch (error) {{
                console.log(`Quorvex PR Advisor unavailable; falling back to saved subset: ${{error.message}}`);
              }}
            }}
            if (selected.length === 0) {{
              throw new Error('The Quorvex subset manifest has no tests.');
            }}
            fs.writeFileSync('quorvex-selected-tests.txt', selected.map((test) => test.target_path).join('\\n') + '\\n');
            console.log(`Selected ${{selected.length}} Quorvex generated test file(s).`);
          }}

          main().catch((error) => {{
            console.error(error);
            process.exit(1);
          }});
          NODE

      - name: Run selected Playwright tests
        run: |
          set -euo pipefail
          mapfile -t tests < quorvex-selected-tests.txt
          npx playwright test --project="$BROWSER" "${{tests[@]}}"

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: quorvex-playwright-report-${{{{ env.BROWSER }}}}
          path: |
            playwright-report/
            test-results/
          retention-days: 14
"""


def _playwright_config_scaffold() -> str:
    return """import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  reporter: [['html', { open: 'never' }], ['list']],
  use: {
    baseURL: process.env.BASE_URL || process.env.APP_BASE_URL || 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
  ],
});
"""


def _package_json_scaffold() -> str:
    return json.dumps(
        {
            "scripts": {"test:e2e": "playwright test"},
            "devDependencies": {"@playwright/test": "^1.50.0"},
        },
        indent=2,
    ) + "\n"


def _subset_pr_body(subset: CiTestSubset, item_count: int) -> str:
    return (
        "This draft PR was generated from Quorvex AI's chat-controlled CI subset workflow.\n\n"
        f"Subset: `{subset.name}` (`{subset.slug}`)\n"
        f"Mode: `{subset.mode}`\n"
        f"Generated tests: `{item_count}`\n\n"
        "Before merging, confirm repository settings when PR-impact narrowing is desired:\n"
        "- `QUORVEX_API_URL` secret\n"
        "- `QUORVEX_API_TOKEN` secret\n"
        "- `QUORVEX_PROJECT_ID` repository variable when the project is not `default`\n"
        f"- `{subset.base_url_secret}` secret for the application base URL\n"
    )


async def _write_files_to_branch(
    *,
    client,
    owner: str,
    repo: str,
    branch_name: str,
    files: dict[str, str],
    message: str,
) -> list[dict[str, str]]:
    changed: list[dict[str, str]] = []
    for path, content in files.items():
        existing = await client.get_content_metadata(owner, repo, path, ref=branch_name)
        update = await client.create_or_update_file(
            owner,
            repo,
            path,
            content=content,
            message=message,
            branch=branch_name,
            sha=(existing or {}).get("sha"),
        )
        changed.append(
            {
                "path": path,
                "sha": ((update.get("content") or {}).get("sha") if isinstance(update, dict) else None) or "",
            }
        )
    return changed


def _upsert_pipeline_mapping(
    session: Session,
    *,
    project_id: str,
    provider: str,
    external_pipeline_id: str,
    defaults: dict[str, Any],
) -> tuple[CiPipelineMapping, bool]:
    stmt = select(CiPipelineMapping).where(
        CiPipelineMapping.project_id == project_id,
        CiPipelineMapping.provider == provider,
        CiPipelineMapping.external_pipeline_id == external_pipeline_id,
    )
    mapping = session.exec(stmt).first()
    created = mapping is None
    if mapping is None:
        mapping = CiPipelineMapping(
            project_id=project_id,
            provider=provider,
            external_pipeline_id=external_pipeline_id,
            **defaults,
        )
    else:
        for key, value in defaults.items():
            if key == "triggered_from":
                continue
            if value is not None:
                setattr(mapping, key, value)
    session.add(mapping)
    return mapping, created


def _apply_gitlab_pipeline(mapping: CiPipelineMapping, pipeline: dict[str, Any]) -> None:
    mapping.status = pipeline.get("status", mapping.status)
    mapping.external_url = pipeline.get("web_url", mapping.external_url)
    mapping.ref = pipeline.get("ref", mapping.ref)
    created_at = pipeline.get("created_at")
    if created_at:
        try:
            mapping.created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass
    updated_at = pipeline.get("updated_at") or pipeline.get("finished_at")
    if mapping.status in {"success", "failed", "canceled", "cancelled", "skipped"} and updated_at:
        try:
            mapping.completed_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass


def _provider_setup(
    *,
    provider: Provider,
    config: dict[str, Any],
    session: Session,
    project_id: str,
) -> dict[str, Any]:
    missing: list[str] = []
    recommended: dict[str, str] | None = None
    configured = bool(config)

    if provider == "github":
        if not configured:
            missing.append("connect_github")
            recommended = {"label": "Connect GitHub", "action": "open_settings", "href": "/settings"}
            status = "not_configured"
        elif not config.get("owner") or not config.get("repo"):
            missing.append("select_repository")
            recommended = {"label": "Select repository", "action": "open_settings", "href": "/settings"}
            status = "needs_repository"
        elif not config.get("default_workflow"):
            missing.append("select_or_generate_workflow")
            recommended = {"label": "Generate workflow draft", "action": "generate_workflow"}
            status = "needs_workflow"
        else:
            status = "ready"
            recommended = {"label": "Run default workflow", "action": "open_trigger"}
        if configured and not config.get("webhook_secret_encrypted"):
            missing.append("configure_webhook")
    else:
        if not configured:
            missing.append("connect_gitlab")
            recommended = {"label": "Connect GitLab", "action": "open_settings", "href": "/settings"}
            status = "not_configured"
        elif not config.get("project_id"):
            missing.append("select_project")
            recommended = {"label": "Select GitLab project", "action": "open_settings", "href": "/settings"}
            status = "needs_project"
        elif not config.get("trigger_token_encrypted"):
            missing.append("add_trigger_token")
            recommended = {"label": "Add trigger token", "action": "open_settings", "href": "/settings"}
            status = "needs_trigger_token"
        else:
            status = "ready"
            recommended = {"label": "Run GitLab pipeline", "action": "open_trigger"}
        if configured and not config.get("webhook_secret"):
            missing.append("configure_webhook")

    return {
        "setup_status": status,
        "missing_requirements": missing,
        "recommended_next_action": recommended,
        "last_sync_at": _latest_sync_at(session, project_id, provider),
    }


def _split_github_repository(repository: str | None) -> tuple[str | None, str | None]:
    if not repository:
        return None, None
    parts = [part.strip() for part in repository.strip().split("/") if part.strip()]
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="GitHub repository must use owner/repo format")
    return parts[0], parts[1]


def _require_existing_provider_config(provider: Provider, config: dict[str, Any] | None) -> dict[str, Any]:
    if not config or not config.get("token_encrypted"):
        label = "GitHub" if provider == "github" else "GitLab"
        raise HTTPException(
            status_code=400,
            detail=f"Add the {label} access token in Settings before chat can update non-secret CI defaults",
        )
    return dict(config)


@router.get("/providers")
async def list_providers(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_view(project_id, current_user, session)
    project = _require_project(project_id, session)
    github = _get_github_config(project) or {}
    gitlab = _get_gitlab_config(project) or {}
    return [
        {
            "provider": "github",
            "configured": bool(github),
            "repository": f"{github.get('owner', '')}/{github.get('repo', '')}".strip("/"),
            "default_ref": github.get("default_ref", "main"),
            "capabilities": ["workflows", "dispatch", "cancel", "rerun", "logs", "artifacts", "workflow_generation"],
            **_provider_setup(provider="github", config=github, session=session, project_id=project_id),
        },
        {
            "provider": "gitlab",
            "configured": bool(gitlab),
            "repository": str(gitlab.get("project_id") or ""),
            "base_url": gitlab.get("base_url", ""),
            "default_ref": gitlab.get("default_ref", "main"),
            "capabilities": ["dispatch", "cancel", "rerun", "jobs", "job_logs"],
            **_provider_setup(provider="gitlab", config=gitlab, session=session, project_id=project_id),
        },
    ]


@router.patch("/providers/defaults")
async def update_provider_defaults(
    project_id: str,
    request: UpdateProviderDefaultsRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Update non-secret provider defaults from chat or the control center.

    Secret material still has to be entered through Settings; this endpoint only
    accepts repository/project selection and default workflow/ref metadata.
    """
    await _require_edit(project_id, current_user, session)
    project = _require_project(project_id, session)

    if request.provider == "github":
        config = _require_existing_provider_config("github", _get_github_config(project))
        repo_owner, repo_name = _split_github_repository(request.repository)
        owner = request.owner or repo_owner
        repo = request.repo or repo_name
        if owner is not None:
            config["owner"] = owner
        if repo is not None:
            config["repo"] = repo
        if request.default_ref is not None:
            config["default_ref"] = request.default_ref or "main"
        if request.default_workflow is not None:
            config["default_workflow"] = request.default_workflow or None
        _save_github_config(project, config, session)
        provider_config = config
    else:
        config = _require_existing_provider_config("gitlab", _get_gitlab_config(project))
        if request.gitlab_project_id is not None:
            config["project_id"] = request.gitlab_project_id
        if request.base_url is not None:
            config["base_url"] = request.base_url.rstrip("/")
        if request.default_ref is not None:
            config["default_ref"] = request.default_ref or "main"
        _save_gitlab_config(project, config, session)
        provider_config = config

    _audit(
        session,
        project_id=project_id,
        provider=request.provider,
        action="update_defaults",
        target_type="provider",
        target_id=request.provider,
        user=current_user,
        metadata={
            "fields": sorted(
                key
                for key, value in request.model_dump(exclude={"provider"}).items()
                if value is not None
            )
        },
    )
    session.commit()
    return {
        "status": "updated",
        "provider": request.provider,
        **_provider_setup(provider=request.provider, config=provider_config, session=session, project_id=project_id),
    }


@router.get("/generated-tests")
async def list_generated_ci_tests(
    project_id: str,
    search: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """List generated Playwright tests that can be saved into a CI subset."""
    await _require_view(project_id, current_user, session)
    _require_project(project_id, session)
    records = _generated_ci_tests(project_id, session)
    if search:
        needle = search.lower().strip()
        records = [
            record
            for record in records
            if needle in record["spec_name"].lower()
            or needle in record["code_path"].lower()
            or needle in record["target_path"].lower()
        ]
    total = len(records)
    return {
        "tests": records[offset : offset + limit],
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + limit < total,
    }


@router.get("/test-subsets")
async def list_test_subsets(
    project_id: str,
    include_items: bool = Query(True),
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_view(project_id, current_user, session)
    _require_project(project_id, session)
    subsets = session.exec(
        select(CiTestSubset)
        .where(CiTestSubset.project_id == project_id)
        .order_by(CiTestSubset.updated_at.desc())
    ).all()
    return [_serialize_subset(subset, session, include_items=include_items) for subset in subsets]


@router.post("/test-subsets")
async def create_test_subset(
    project_id: str,
    request: TestSubsetCreateRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_edit(project_id, current_user, session)
    _require_project(project_id, session)
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Subset name is required")
    slug = _slugify_subset_name(name)
    existing = session.exec(
        select(CiTestSubset).where(CiTestSubset.project_id == project_id, CiTestSubset.slug == slug)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"A CI test subset named '{name}' already exists")
    actor_id, _actor_email = _actor(current_user)
    subset = CiTestSubset(
        project_id=project_id,
        name=name,
        slug=slug,
        description=request.description,
        mode=request.mode,
        default_browser=request.default_browser,
        base_url_secret=_validate_secret_name(request.base_url_secret, label="base_url_secret"),
        created_by=actor_id,
    )
    session.add(subset)
    session.flush()
    _apply_subset_items(subset=subset, project_id=project_id, item_requests=request.items, session=session)
    _audit(
        session,
        project_id=project_id,
        provider="github",
        action="create_test_subset",
        target_type="ci_test_subset",
        target_id=subset.id,
        user=current_user,
        metadata={"slug": subset.slug, "item_count": len(request.items), "mode": subset.mode},
    )
    session.commit()
    session.refresh(subset)
    return _serialize_subset(subset, session)


@router.get("/test-subsets/{subset_id}")
async def get_test_subset(
    project_id: str,
    subset_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_view(project_id, current_user, session)
    subset = session.get(CiTestSubset, subset_id)
    if not subset or subset.project_id != project_id:
        raise HTTPException(status_code=404, detail="CI test subset not found")
    return _serialize_subset(subset, session)


@router.patch("/test-subsets/{subset_id}")
async def update_test_subset(
    project_id: str,
    subset_id: str,
    request: TestSubsetUpdateRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_edit(project_id, current_user, session)
    subset = session.get(CiTestSubset, subset_id)
    if not subset or subset.project_id != project_id:
        raise HTTPException(status_code=404, detail="CI test subset not found")
    if request.name is not None:
        name = request.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Subset name is required")
        new_slug = _slugify_subset_name(name)
        if new_slug != subset.slug:
            conflict = session.exec(
                select(CiTestSubset).where(CiTestSubset.project_id == project_id, CiTestSubset.slug == new_slug)
            ).first()
            if conflict:
                raise HTTPException(status_code=409, detail=f"A CI test subset named '{name}' already exists")
            subset.slug = new_slug
        subset.name = name
    if request.description is not None:
        subset.description = request.description
    if request.mode is not None:
        subset.mode = request.mode
    if request.default_browser is not None:
        subset.default_browser = request.default_browser
    if request.base_url_secret is not None:
        subset.base_url_secret = _validate_secret_name(request.base_url_secret, label="base_url_secret")
    if request.items is not None:
        _apply_subset_items(subset=subset, project_id=project_id, item_requests=request.items, session=session)
    subset.updated_at = datetime.utcnow()
    session.add(subset)
    _audit(
        session,
        project_id=project_id,
        provider="github",
        action="update_test_subset",
        target_type="ci_test_subset",
        target_id=subset.id,
        user=current_user,
        metadata={"slug": subset.slug, "items_replaced": request.items is not None},
    )
    session.commit()
    session.refresh(subset)
    return _serialize_subset(subset, session)


@router.delete("/test-subsets/{subset_id}")
async def delete_test_subset(
    project_id: str,
    subset_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_edit(project_id, current_user, session)
    subset = session.get(CiTestSubset, subset_id)
    if not subset or subset.project_id != project_id:
        raise HTTPException(status_code=404, detail="CI test subset not found")
    for item in _subset_items(session, subset.id):
        session.delete(item)
    session.delete(subset)
    _audit(
        session,
        project_id=project_id,
        provider="github",
        action="delete_test_subset",
        target_type="ci_test_subset",
        target_id=subset_id,
        user=current_user,
    )
    session.commit()
    return {"status": "deleted"}


@router.post("/test-subsets/{subset_id}/preview")
async def preview_test_subset(
    project_id: str,
    subset_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_view(project_id, current_user, session)
    subset = session.get(CiTestSubset, subset_id)
    if not subset or subset.project_id != project_id:
        raise HTTPException(status_code=404, detail="CI test subset not found")
    items = _subset_items(session, subset.id)
    return {
        "subset": _serialize_subset(subset, session),
        "manifest_path": f".quorvex/test-subsets/{subset.slug}.json",
        "workflow_path": ".github/workflows/quorvex-subset-tests.yml",
        "files": [
            {"path": item.target_path, "source_path": item.code_path, "content_hash": item.content_hash}
            for item in items
        ],
    }


@router.post("/test-subsets/{subset_id}/pull-request")
async def open_test_subset_pull_request(
    project_id: str,
    subset_id: str,
    request: TestSubsetPullRequestRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_edit(project_id, current_user, session)
    project = _require_project(project_id, session)
    subset = session.get(CiTestSubset, subset_id)
    if not subset or subset.project_id != project_id:
        raise HTTPException(status_code=404, detail="CI test subset not found")
    items = _subset_items(session, subset.id)
    if not items:
        raise HTTPException(status_code=400, detail="CI test subset has no generated tests")

    config = _get_github_config(project)
    if not config:
        raise HTTPException(status_code=400, detail="GitHub is not configured")
    owner, repo = _github_repo(config)
    base_ref = (request.base_ref or config.get("default_ref") or "main").strip() or "main"
    branch_name = request.branch_name or f"quorvex/ci-subset-{_safe_branch_segment(subset.slug)}-{subset.id[:8]}"
    branch_name = _safe_branch_segment(branch_name)
    title = request.title or f"Add Quorvex CI subset: {subset.name}"
    commit_message = request.commit_message or f"Add Quorvex CI subset {subset.name}"
    body = request.body or _subset_pr_body(subset, len(items))

    files: dict[str, str] = {}
    for item in items:
        source = BASE_DIR / item.code_path
        if not source.exists() or not source.is_file():
            raise HTTPException(status_code=404, detail=f"Generated test file is missing: {item.code_path}")
        content = source.read_text(encoding="utf-8", errors="replace")
        files[item.target_path] = content
        new_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if new_hash != item.content_hash:
            item.content_hash = new_hash
            session.add(item)
    files[f".quorvex/test-subsets/{subset.slug}.json"] = _subset_manifest(subset, items)
    files[".github/workflows/quorvex-subset-tests.yml"] = _render_subset_workflow(
        subset,
        workflow_name=request.workflow_name,
    )

    client = await _build_github_client(project)
    changed_files: list[dict[str, str]] = []
    try:
        base = await client.get_ref(owner, repo, f"heads/{base_ref}")
        base_sha = ((base.get("object") or {}).get("sha") or "").strip()
        if not base_sha:
            raise HTTPException(status_code=502, detail="GitHub base branch did not return a commit SHA")
        try:
            await client.create_ref(owner, repo, f"heads/{branch_name}", base_sha)
        except GithubError as exc:
            if exc.status_code != 422:
                raise

        package_meta = await client.get_content_metadata(owner, repo, "package.json", ref=branch_name)
        if not package_meta:
            files["package.json"] = _package_json_scaffold()
        playwright_meta = await client.get_content_metadata(owner, repo, "playwright.config.ts", ref=branch_name)
        if not playwright_meta:
            files["playwright.config.ts"] = _playwright_config_scaffold()

        changed_files = await _write_files_to_branch(
            client=client,
            owner=owner,
            repo=repo,
            branch_name=branch_name,
            files=files,
            message=commit_message,
        )

        existing_prs = await client.list_pull_requests(owner, repo, head=f"{owner}:{branch_name}", base=base_ref)
        if existing_prs:
            pr = existing_prs[0]
        else:
            try:
                pr = await client.create_pull_request(
                    owner,
                    repo,
                    title=title,
                    head=branch_name,
                    base=base_ref,
                    body=body,
                    draft=request.draft,
                )
            except GithubError as exc:
                if exc.status_code != 422:
                    raise
                existing_prs = await client.list_pull_requests(owner, repo, head=f"{owner}:{branch_name}", base=base_ref)
                if not existing_prs:
                    raise
                pr = existing_prs[0]
    except GithubError as exc:
        detail = str(exc)
        if exc.status_code == 403:
            detail = "GitHub rejected the request. Check that the token can write repository contents and pull requests."
        elif exc.status_code == 404:
            detail = "GitHub repository, branch, or base ref was not found."
        elif exc.status_code == 422:
            detail = f"GitHub could not create the subset pull request: {exc}"
        _audit(
            session,
            project_id=project_id,
            provider="github",
            action="open_test_subset_pr",
            target_type="ci_test_subset",
            target_id=subset.id,
            status="failed",
            user=current_user,
            metadata={"error": detail, "branch": branch_name},
        )
        session.commit()
        raise HTTPException(status_code=502, detail=detail) from exc
    finally:
        await client.close()

    subset.updated_at = datetime.utcnow()
    session.add(subset)
    _audit(
        session,
        project_id=project_id,
        provider="github",
        action="open_test_subset_pr",
        target_type="ci_test_subset",
        target_id=subset.id,
        user=current_user,
        metadata={
            "branch": branch_name,
            "base_ref": base_ref,
            "pull_request_number": pr.get("number"),
            "changed_files": [item["path"] for item in changed_files],
        },
    )
    session.commit()
    return {
        "status": "opened",
        "subset": _serialize_subset(subset, session),
        "pull_request_url": pr.get("html_url"),
        "pull_request_number": pr.get("number"),
        "branch": branch_name,
        "base_ref": base_ref,
        "workflow_path": ".github/workflows/quorvex-subset-tests.yml",
        "manifest_path": f".quorvex/test-subsets/{subset.slug}.json",
        "changed_files": changed_files,
    }


@router.post("/test-subsets/{subset_id}/dispatch")
async def dispatch_test_subset_workflow(
    project_id: str,
    subset_id: str,
    request: TestSubsetDispatchRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_edit(project_id, current_user, session)
    project = _require_project(project_id, session)
    subset = session.get(CiTestSubset, subset_id)
    if not subset or subset.project_id != project_id:
        raise HTTPException(status_code=404, detail="CI test subset not found")
    config = _get_github_config(project)
    if not config:
        raise HTTPException(status_code=400, detail="GitHub is not configured")
    owner, repo = _github_repo(config)
    workflow_id = request.workflow_id or config.get("default_workflow") or "quorvex-subset-tests.yml"
    ref = request.ref or config.get("default_ref") or "main"
    inputs: dict[str, str] = {
        "subset_slug": subset.slug,
        "browser": request.browser or subset.default_browser,
    }
    base_url = request.base_url or project.base_url
    if base_url:
        inputs["base_url"] = _validate_runner_subset_base_url(base_url)
    client = await _build_github_client(project)
    try:
        await client.trigger_workflow(owner, repo, workflow_id, ref, inputs=inputs)
        runs = await client.get_workflow_runs(owner, repo, workflow_id=workflow_id, per_page=5)
        latest = _latest_run_after_dispatch(runs, workflow_id, ref)
        mapping = CiPipelineMapping(
            project_id=project_id,
            provider="github",
            external_pipeline_id=str((latest or {}).get("id") or f"pending-{workflow_id}-{ref}-{datetime.utcnow().timestamp()}"),
            external_project_id=f"{owner}/{repo}",
            external_url=(latest or {}).get("html_url", ""),
            ref=ref,
            triggered_from="dashboard",
            status="pending",
        )
        if latest:
            _update_mapping_from_run(mapping, latest)
        session.add(mapping)
        _audit(
            session,
            project_id=project_id,
            provider="github",
            action="dispatch_test_subset",
            target_type="ci_test_subset",
            target_id=subset.id,
            user=current_user,
            metadata={"workflow_id": workflow_id, "ref": ref, "subset_slug": subset.slug},
        )
        session.commit()
        session.refresh(mapping)
        return {"status": "triggered", "subset": _serialize_subset(subset, session, include_items=False), "run": _serialize_mapping(mapping)}
    finally:
        await client.close()


@router.get("/workflows")
async def list_workflows(
    project_id: str,
    provider: Provider = "github",
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_view(project_id, current_user, session)
    project = _require_project(project_id, session)
    if provider == "gitlab":
        config = _get_gitlab_config(project)
        if not config:
            return []
        return [
            {
                "id": "pipeline",
                "name": "GitLab Pipeline",
                "path": ".gitlab-ci.yml",
                "state": "active",
                "provider": "gitlab",
            }
        ]

    config = _get_github_config(project)
    if not config:
        return []
    owner, repo = _github_repo(config)
    client = await _build_github_client(project)
    try:
        workflows = await client.list_workflows(owner, repo)
        return [
            {
                "id": str(w.get("id")),
                "name": w.get("name", ""),
                "path": w.get("path", ""),
                "state": w.get("state", ""),
                "provider": "github",
            }
            for w in workflows
        ]
    finally:
        await client.close()


@router.get("/runs")
async def list_runs(
    project_id: str,
    provider: Provider | Literal["all"] = "all",
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_view(project_id, current_user, session)
    _require_project(project_id, session)
    stmt = select(CiPipelineMapping).where(CiPipelineMapping.project_id == project_id)
    if provider != "all":
        stmt = stmt.where(CiPipelineMapping.provider == provider)
    stmt = stmt.order_by(CiPipelineMapping.created_at.desc())
    return [_serialize_mapping(m) for m in session.exec(stmt).all()]


@router.post("/runs/sync")
async def sync_runs(
    project_id: str,
    request: SyncRunsRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_edit(project_id, current_user, session)
    project = _require_project(project_id, session)
    per_page = max(1, min(int(request.per_page or 20), 100))
    summary: dict[str, dict[str, int]] = {}

    if request.provider in {"all", "github"}:
        config = _get_github_config(project)
        if config:
            owner, repo = _github_repo(config)
            client = await _build_github_client(project)
            created = updated = 0
            try:
                runs = await client.get_workflow_runs(owner, repo, workflow_id=request.workflow_id, per_page=per_page)
                for run in runs:
                    run_id = str(run.get("id") or "")
                    if not run_id:
                        continue
                    mapping, is_created = _upsert_pipeline_mapping(
                        session,
                        project_id=project_id,
                        provider="github",
                        external_pipeline_id=run_id,
                        defaults={
                            "external_project_id": f"{owner}/{repo}",
                            "external_url": run.get("html_url", ""),
                            "ref": run.get("head_branch", ""),
                            "triggered_from": "sync",
                        },
                    )
                    _update_mapping_from_run(mapping, run)
                    created += 1 if is_created else 0
                    updated += 0 if is_created else 1
            finally:
                await client.close()
            summary["github"] = {"created": created, "updated": updated}

    if request.provider in {"all", "gitlab"}:
        config = _get_gitlab_config(project)
        if config:
            gitlab_project_id = _gitlab_project(config)
            client = await _build_gitlab_client(project)
            created = updated = 0
            try:
                pipelines = await client.list_pipelines(gitlab_project_id, per_page=per_page)
                for pipeline in pipelines:
                    pipeline_id = str(pipeline.get("id") or "")
                    if not pipeline_id:
                        continue
                    mapping, is_created = _upsert_pipeline_mapping(
                        session,
                        project_id=project_id,
                        provider="gitlab",
                        external_pipeline_id=pipeline_id,
                        defaults={
                            "external_project_id": str(gitlab_project_id),
                            "external_url": pipeline.get("web_url", ""),
                            "ref": pipeline.get("ref", ""),
                            "triggered_from": "sync",
                        },
                    )
                    _apply_gitlab_pipeline(mapping, pipeline)
                    created += 1 if is_created else 0
                    updated += 0 if is_created else 1
            finally:
                await client.close()
            summary["gitlab"] = {"created": created, "updated": updated}

    session.commit()
    _audit(
        session,
        project_id=project_id,
        provider=request.provider,
        action="sync_runs",
        target_type="pipeline",
        user=current_user,
        metadata=summary,
    )
    session.commit()
    return {"status": "ok", "providers": summary}


@router.post("/workflows/dispatch")
async def dispatch_workflow(
    project_id: str,
    request: DispatchWorkflowRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_edit(project_id, current_user, session)
    project = _require_project(project_id, session)

    if request.provider == "gitlab":
        config = _get_gitlab_config(project)
        if not config:
            raise HTTPException(status_code=400, detail="GitLab is not configured")
        gitlab_project_id = _gitlab_project(config)
        ref = request.ref or config.get("default_ref") or "main"
        client = await _build_gitlab_client(project)
        try:
            trigger_token = decrypt_credential(config.get("trigger_token_encrypted", ""))
            pipeline = await client.trigger_pipeline(
                project_id=gitlab_project_id,
                ref=ref,
                variables=request.inputs,
                trigger_token=trigger_token or None,
            )
            mapping = CiPipelineMapping(
                project_id=project_id,
                provider="gitlab",
                external_pipeline_id=str(pipeline["id"]),
                external_project_id=str(gitlab_project_id),
                external_url=pipeline.get("web_url", ""),
                ref=ref,
                triggered_from="dashboard",
                status=pipeline.get("status", "pending"),
            )
            session.add(mapping)
            _audit(
                session,
                project_id=project_id,
                provider="gitlab",
                action="dispatch",
                target_type="pipeline",
                target_id=str(pipeline.get("id")),
                user=current_user,
                metadata={"ref": ref, "variables": sorted((request.inputs or {}).keys())},
            )
            session.commit()
            session.refresh(mapping)
            return {"status": "triggered", "run": _serialize_mapping(mapping)}
        finally:
            await client.close()

    config = _get_github_config(project)
    if not config:
        raise HTTPException(status_code=400, detail="GitHub is not configured")
    owner, repo = _github_repo(config)
    workflow_id = request.workflow_id or config.get("default_workflow")
    ref = request.ref or config.get("default_ref") or "main"
    if not workflow_id:
        raise HTTPException(status_code=400, detail="workflow_id is required")
    workflow_inputs_raw = dict(request.inputs or {})
    if project.base_url and _is_runner_subset_workflow(workflow_id, workflow_inputs_raw) and not workflow_inputs_raw.get("base_url"):
        workflow_inputs_raw["base_url"] = project.base_url
    workflow_inputs = _validate_github_dispatch_inputs(workflow_id, workflow_inputs_raw or None)
    client = await _build_github_client(project)
    try:
        await client.trigger_workflow(owner, repo, workflow_id, ref, inputs=workflow_inputs)
        runs = await client.get_workflow_runs(owner, repo, workflow_id=workflow_id, per_page=5)
        latest = _latest_run_after_dispatch(runs, workflow_id, ref)
        mapping = CiPipelineMapping(
            project_id=project_id,
            provider="github",
            external_pipeline_id=str((latest or {}).get("id") or f"pending-{workflow_id}-{ref}-{datetime.utcnow().timestamp()}"),
            external_project_id=f"{owner}/{repo}",
            external_url=(latest or {}).get("html_url", ""),
            ref=ref,
            triggered_from="dashboard",
            status="pending",
        )
        if latest:
            _update_mapping_from_run(mapping, latest)
        session.add(mapping)
        _audit(
            session,
            project_id=project_id,
            provider="github",
            action="dispatch",
            target_type="workflow",
            target_id=str(workflow_id),
            user=current_user,
            metadata={
                "ref": ref,
                "input_keys": sorted((workflow_inputs or {}).keys()),
                "suite": (workflow_inputs or {}).get("suite"),
            },
        )
        session.commit()
        session.refresh(mapping)
        return {"status": "triggered", "run": _serialize_mapping(mapping)}
    finally:
        await client.close()


@router.get("/runs/{provider}/{mapping_id}")
async def get_run_detail(
    project_id: str,
    provider: Provider,
    mapping_id: int,
    refresh: bool = False,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_view(project_id, current_user, session)
    project = _require_project(project_id, session)
    mapping = session.get(CiPipelineMapping, mapping_id)
    if not mapping or mapping.project_id != project_id or mapping.provider != provider:
        raise HTTPException(status_code=404, detail="CI run not found")

    jobs: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []

    if refresh and mapping.external_pipeline_id and not mapping.external_pipeline_id.startswith("pending-"):
        if provider == "github":
            config = _get_github_config(project)
            if config:
                owner, repo = _github_repo(config)
                client = await _build_github_client(project)
                try:
                    run = await client.get_run(owner, repo, int(mapping.external_pipeline_id))
                    _update_mapping_from_run(mapping, run)
                    jobs = await client.get_run_jobs(owner, repo, int(mapping.external_pipeline_id))
                    artifacts = await client.list_run_artifacts(owner, repo, int(mapping.external_pipeline_id))
                    mapping.stages = [
                        {
                            "id": str(job.get("id", "")),
                            "name": job.get("name", ""),
                            "status": job.get("conclusion") or job.get("status", ""),
                            "started_at": job.get("started_at"),
                            "completed_at": job.get("completed_at"),
                            "html_url": job.get("html_url"),
                        }
                        for job in jobs
                    ]
                    mapping.artifacts = [
                        {
                            "id": str(item.get("id", "")),
                            "name": item.get("name", ""),
                            "size_in_bytes": item.get("size_in_bytes"),
                            "expired": item.get("expired", False),
                            "archive_download_url": item.get("archive_download_url"),
                        }
                        for item in artifacts
                    ]
                    session.add(mapping)
                    session.commit()
                    session.refresh(mapping)
                finally:
                    await client.close()
        else:
            config = _get_gitlab_config(project)
            if config:
                gitlab_project_id = _gitlab_project(config)
                client = await _build_gitlab_client(project)
                try:
                    pipeline = await client.get_pipeline(gitlab_project_id, int(mapping.external_pipeline_id))
                    mapping.status = pipeline.get("status", mapping.status)
                    mapping.external_url = pipeline.get("web_url", mapping.external_url)
                    jobs = await client.get_pipeline_jobs(gitlab_project_id, int(mapping.external_pipeline_id))
                    mapping.stages = [
                        {
                            "id": str(job.get("id", "")),
                            "name": job.get("name", ""),
                            "stage": job.get("stage", ""),
                            "status": job.get("status", ""),
                            "started_at": job.get("started_at"),
                            "completed_at": job.get("finished_at"),
                            "web_url": job.get("web_url"),
                            "artifacts": job.get("artifacts", []),
                        }
                        for job in jobs
                    ]
                    session.add(mapping)
                    session.commit()
                    session.refresh(mapping)
                finally:
                    await client.close()

    return {"run": _serialize_mapping(mapping), "jobs": jobs or mapping.stages, "artifacts": artifacts or mapping.artifacts}


@router.post("/runs/{provider}/{mapping_id}/cancel")
async def cancel_run(
    project_id: str,
    provider: Provider,
    mapping_id: int,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_edit(project_id, current_user, session)
    project = _require_project(project_id, session)
    mapping = session.get(CiPipelineMapping, mapping_id)
    if not mapping or mapping.project_id != project_id or mapping.provider != provider:
        raise HTTPException(status_code=404, detail="CI run not found")
    if mapping.external_pipeline_id.startswith("pending-"):
        raise HTTPException(status_code=400, detail="Provider run ID is not available yet")

    if provider == "github":
        config = _get_github_config(project)
        owner, repo = _github_repo(config or {})
        client = await _build_github_client(project)
        try:
            await client.cancel_run(owner, repo, int(mapping.external_pipeline_id))
        finally:
            await client.close()
    else:
        config = _get_gitlab_config(project)
        gitlab_project_id = _gitlab_project(config or {})
        client = await _build_gitlab_client(project)
        try:
            await client.cancel_pipeline(gitlab_project_id, int(mapping.external_pipeline_id))
        finally:
            await client.close()

    mapping.status = "canceled"
    session.add(mapping)
    _audit(
        session,
        project_id=project_id,
        provider=provider,
        action="cancel",
        target_type="run",
        target_id=mapping.external_pipeline_id,
        user=current_user,
    )
    session.commit()
    return {"status": "cancelled", "run": _serialize_mapping(mapping)}


@router.post("/runs/{provider}/{mapping_id}/rerun")
async def rerun_run(
    project_id: str,
    provider: Provider,
    mapping_id: int,
    request: RerunRunRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_edit(project_id, current_user, session)
    project = _require_project(project_id, session)
    mapping = session.get(CiPipelineMapping, mapping_id)
    if not mapping or mapping.project_id != project_id or mapping.provider != provider:
        raise HTTPException(status_code=404, detail="CI run not found")
    if mapping.external_pipeline_id.startswith("pending-"):
        raise HTTPException(status_code=400, detail="Provider run ID is not available yet")

    if provider == "github":
        config = _get_github_config(project)
        owner, repo = _github_repo(config or {})
        client = await _build_github_client(project)
        try:
            await client.rerun_run(owner, repo, int(mapping.external_pipeline_id), failed_only=request.failed_only)
        finally:
            await client.close()
    else:
        config = _get_gitlab_config(project)
        gitlab_project_id = _gitlab_project(config or {})
        client = await _build_gitlab_client(project)
        try:
            await client.retry_pipeline(gitlab_project_id, int(mapping.external_pipeline_id))
        finally:
            await client.close()

    _audit(
        session,
        project_id=project_id,
        provider=provider,
        action="rerun_failed" if request.failed_only else "rerun",
        target_type="run",
        target_id=mapping.external_pipeline_id,
        user=current_user,
    )
    session.commit()
    return {"status": "rerun_requested", "run": _serialize_mapping(mapping)}


@router.get("/runs/{provider}/{mapping_id}/logs")
async def get_run_logs(
    project_id: str,
    provider: Provider,
    mapping_id: int,
    job_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_view(project_id, current_user, session)
    project = _require_project(project_id, session)
    mapping = session.get(CiPipelineMapping, mapping_id)
    if not mapping or mapping.project_id != project_id or mapping.provider != provider:
        raise HTTPException(status_code=404, detail="CI run not found")

    if provider == "github":
        if mapping.external_pipeline_id.startswith("pending-"):
            return {"type": "message", "content": "Logs are not available until the provider run ID is known."}
        config = _get_github_config(project)
        owner, repo = _github_repo(config or {})
        client = await _build_github_client(project)
        try:
            logs_url = await client.get_run_logs_url(owner, repo, int(mapping.external_pipeline_id))
            return {"type": "archive_url", "url": logs_url}
        finally:
            await client.close()

    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required for GitLab job logs")
    config = _get_gitlab_config(project)
    gitlab_project_id = _gitlab_project(config or {})
    client = await _build_gitlab_client(project)
    try:
        trace = await client.get_job_trace(gitlab_project_id, int(job_id))
        return {"type": "text", "content": trace[-20000:]}
    finally:
        await client.close()


def _safe_workflow_slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
    return slug or "quorvex-ci"


def _safe_branch_segment(value: str) -> str:
    segment = re.sub(r"[^a-zA-Z0-9._/-]+", "-", value.strip().lower()).strip("-/.")
    segment = re.sub(r"/+", "/", segment)
    return segment or "workflow"


def _workflow_can_open_pr(change: CiWorkflowChangeRequest, github_config: dict[str, Any] | None) -> bool:
    return (
        change.provider == "github"
        and change.status != "opened"
        and not (change.validation_errors or [])
        and bool(github_config and github_config.get("owner") and github_config.get("repo"))
    )


def _serialize_workflow_change(change: CiWorkflowChangeRequest, github_config: dict[str, Any] | None = None) -> dict[str, Any]:
    can_open_pr = _workflow_can_open_pr(change, github_config)
    next_actions = [
        "Review the generated YAML.",
        "Open a draft pull request from Quorvex.",
        "Review and merge the pull request in GitHub.",
        "Set this workflow as the default workflow in Settings after it is merged.",
    ] if can_open_pr else [
        "Review the generated YAML.",
        f"Add it to {change.workflow_path} in your repository.",
        "Add the required Quorvex secrets and variables in GitHub.",
        "Set this workflow as the default workflow in Settings when it is merged.",
    ]
    return {
        "id": change.id,
        "provider": change.provider,
        "workflow_name": change.workflow_name,
        "workflow_path": change.workflow_path,
        "status": change.status,
        "install_status": "opened" if change.status == "opened" else "draft",
        "can_open_pr": can_open_pr,
        "pull_request_url": change.pull_request_url,
        "pull_request_number": change.pull_request_number,
        "branch": change.pull_request_branch,
        "base_ref": change.pull_request_base_ref,
        "commit_sha": change.commit_sha,
        "last_error": change.last_error,
        "next_actions": next_actions,
        "generated_yaml": change.generated_yaml,
        "validation_errors": change.validation_errors or [],
        "validation_warnings": change.validation_warnings or [],
        "created_at": change.created_at.isoformat() if change.created_at else None,
    }


def _workflow_pr_body(change: CiWorkflowChangeRequest) -> str:
    return (
        "This draft PR was generated from Quorvex AI's CI/CD workflow generator.\n\n"
        f"Workflow path: `{change.workflow_path}`\n\n"
        "Before merging, confirm these repository settings exist when the workflow needs them:\n"
        "- `APP_BASE_URL` secret for Playwright-based workflow templates\n"
        "- `QUORVEX_API_URL` secret for PR quality gate workflows\n"
        "- `QUORVEX_API_TOKEN` secret for PR quality gate workflows\n"
        "- `QUORVEX_PROJECT_ID` repository variable when the project is not `default`\n\n"
        "After this PR is merged, select the workflow as the project default in Quorvex Settings."
    )


def _branches(branches: list[str] | None) -> list[str]:
    cleaned = [b.strip() for b in branches or ["main"] if b and b.strip()]
    return cleaned[:8] or ["main"]


def _browsers(browsers: list[str] | None) -> list[str]:
    allowed = {"chromium", "firefox", "webkit"}
    cleaned = [b for b in browsers or ["chromium"] if b in allowed]
    return cleaned or ["chromium"]


def _is_runner_subset_workflow(workflow_id: str | None, inputs: dict[str, str] | None) -> bool:
    workflow_key = str(workflow_id or "").strip().lower()
    return workflow_key in RUNNER_SUBSET_WORKFLOW_IDS or bool((inputs or {}).keys() & RUNNER_SUBSET_INPUT_KEYS)


def _validate_runner_subset_path(value: str) -> str:
    path = value.strip()
    if not path:
        return ""
    if len(path) > 180:
        raise HTTPException(status_code=400, detail="test_path must be 180 characters or fewer")
    if path.startswith("/") or "\\" in path or "\n" in path or "\r" in path:
        raise HTTPException(status_code=400, detail="test_path must be a safe repo-relative path")
    if re.search(r"[;&|`$<>(){}]", path):
        raise HTTPException(status_code=400, detail="test_path contains unsupported shell characters")
    parts = [part for part in path.split("/") if part]
    if any(part == ".." for part in parts):
        raise HTTPException(status_code=400, detail="test_path must not contain parent directory segments")
    allowed_prefixes = ("orchestrator/tests/", "tests/generated/", "tests/e2e/")
    if not path.startswith(allowed_prefixes):
        raise HTTPException(
            status_code=400,
            detail="test_path must be under orchestrator/tests, tests/generated, or tests/e2e",
        )
    return path


def _validate_runner_subset_grep(value: str) -> str:
    grep = value.strip()
    if not grep:
        return ""
    if len(grep) > 120 or "\n" in grep or "\r" in grep:
        raise HTTPException(status_code=400, detail="playwright_grep must be a single line up to 120 characters")
    if re.search(r"[;&|`$<>(){}]", grep):
        raise HTTPException(status_code=400, detail="playwright_grep contains unsupported shell characters")
    return grep


def _validate_runner_subset_base_url(value: str) -> str:
    url = value.strip()
    if not url:
        return ""
    if len(url) > 200 or "\n" in url or "\r" in url:
        raise HTTPException(status_code=400, detail="base_url must be a single line up to 200 characters")
    if not re.fullmatch(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", url):
        raise HTTPException(status_code=400, detail="base_url must be an http or https URL")
    return url


def _validate_github_dispatch_inputs(workflow_id: str | None, inputs: dict[str, str] | None) -> dict[str, str] | None:
    if not inputs:
        return inputs
    for key, value in inputs.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", key):
            raise HTTPException(status_code=400, detail=f"Workflow input '{key}' has an unsupported name")
        if len(str(value)) > 500:
            raise HTTPException(status_code=400, detail=f"Workflow input '{key}' is too long")

    if not _is_runner_subset_workflow(workflow_id, inputs):
        return inputs

    unknown = sorted(set(inputs) - RUNNER_SUBSET_INPUT_KEYS)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unsupported runner subset workflow inputs: {', '.join(unknown)}")

    sanitized: dict[str, str] = {}
    suite = (inputs.get("suite") or "auto").strip()
    if suite not in RUNNER_SUBSET_SUITES:
        raise HTTPException(status_code=400, detail=f"Unsupported runner subset suite: {suite}")
    sanitized["suite"] = suite

    browser = (inputs.get("browser") or "chromium").strip()
    if browser not in RUNNER_SUBSET_BROWSERS:
        raise HTTPException(status_code=400, detail=f"Unsupported runner subset browser: {browser}")
    sanitized["browser"] = browser

    marker = (inputs.get("pytest_marker") or "not integration").strip()
    if marker not in RUNNER_SUBSET_MARKERS:
        raise HTTPException(status_code=400, detail=f"Unsupported pytest_marker: {marker}")
    sanitized["pytest_marker"] = marker

    if "test_path" in inputs:
        sanitized["test_path"] = _validate_runner_subset_path(inputs["test_path"])
    if "playwright_grep" in inputs:
        sanitized["playwright_grep"] = _validate_runner_subset_grep(inputs["playwright_grep"])
    if "base_url" in inputs:
        sanitized["base_url"] = _validate_runner_subset_base_url(inputs["base_url"])
    return sanitized


def _validate_workflow_request(request: WorkflowGenerateRequest) -> list[str]:
    errors: list[str] = []
    if "\n" in request.workflow_name or "\r" in request.workflow_name:
        errors.append("Workflow name must be a single line.")
    for label, value in {
        "target_url_secret": request.target_url_secret,
        "api_url_secret": request.api_url_secret,
        "api_token_secret": request.api_token_secret,
        "project_id_variable": request.project_id_variable,
    }.items():
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,99}", value or ""):
            errors.append(f"{label} must be an uppercase GitHub secret or variable name.")
    for branch in _branches(request.branches):
        if not re.fullmatch(r"[A-Za-z0-9._/\-]{1,128}", branch):
            errors.append(f"Branch '{branch}' contains unsupported characters.")
    return errors


def _render_runner_subset_workflow(name: str, branches: str, retention: int) -> str:
    return f"""name: {name}

on:
  pull_request:
    branches: [{branches}]
    types: [opened, synchronize, reopened, ready_for_review]
  workflow_dispatch:
    inputs:
      suite:
        description: Test subset to run
        required: true
        type: choice
        default: auto
        options:
          - auto
          - python-unit
          - python-integration
          - frontend-typecheck
          - frontend-lint
          - playwright-generated
          - playwright-e2e
          - all-safe
      browser:
        description: Playwright browser
        required: true
        type: choice
        default: chromium
        options:
          - chromium
          - firefox
          - webkit
      pytest_marker:
        description: Pytest marker expression
        required: true
        type: choice
        default: not integration
        options:
          - not integration
          - integration
      test_path:
        description: Optional safe repo-relative test path
        required: false
        type: string
      playwright_grep:
        description: Optional Playwright grep
        required: false
        type: string
      base_url:
        description: Optional BASE_URL for Playwright
        required: false
        type: string

permissions:
  contents: read

jobs:
  select-suite:
    runs-on: ubuntu-latest
    outputs:
      suite: ${{{{ steps.select.outputs.suite }}}}
      browser: ${{{{ steps.select.outputs.browser }}}}
      pytest_marker: ${{{{ steps.select.outputs.pytest_marker }}}}
      test_path: ${{{{ steps.select.outputs.test_path }}}}
      playwright_grep: ${{{{ steps.select.outputs.playwright_grep }}}}
      base_url: ${{{{ steps.select.outputs.base_url }}}}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - id: select
        env:
          EVENT_NAME: ${{{{ github.event_name }}}}
          BASE_SHA: ${{{{ github.event.pull_request.base.sha || '' }}}}
          HEAD_SHA: ${{{{ github.event.pull_request.head.sha || github.sha }}}}
          INPUT_SUITE: ${{{{ inputs.suite || '' }}}}
          INPUT_BROWSER: ${{{{ inputs.browser || '' }}}}
          INPUT_PYTEST_MARKER: ${{{{ inputs.pytest_marker || '' }}}}
          INPUT_TEST_PATH: ${{{{ inputs.test_path || '' }}}}
          INPUT_PLAYWRIGHT_GREP: ${{{{ inputs.playwright_grep || '' }}}}
          INPUT_BASE_URL: ${{{{ inputs.base_url || '' }}}}
        run: |
          set -euo pipefail

          suite="${{INPUT_SUITE:-auto}}"
          browser="${{INPUT_BROWSER:-chromium}}"
          pytest_marker="${{INPUT_PYTEST_MARKER:-not integration}}"
          test_path="${{INPUT_TEST_PATH:-}}"
          playwright_grep="${{INPUT_PLAYWRIGHT_GREP:-}}"
          base_url="${{INPUT_BASE_URL:-}}"

          case "$suite" in
            auto|python-unit|python-integration|frontend-typecheck|frontend-lint|playwright-generated|playwright-e2e|all-safe) ;;
            *) echo "Unsupported suite: $suite" >&2; exit 64 ;;
          esac
          case "$browser" in chromium|firefox|webkit) ;; *) echo "Unsupported browser: $browser" >&2; exit 64 ;; esac
          case "$pytest_marker" in "not integration"|integration) ;; *) echo "Unsupported pytest marker: $pytest_marker" >&2; exit 64 ;; esac

          if [ -n "$test_path" ]; then
            if [ "${{#test_path}}" -gt 180 ] || [[ "$test_path" == /* ]] || [[ "$test_path" == *..* ]] || [[ "$test_path" == *\\\\* ]] || [[ "$test_path" =~ [\\;\\&\\|\\`\\$\\<\\>\\(\\)\\{{\\}}] ]]; then
              echo "Unsafe test_path: $test_path" >&2
              exit 64
            fi
            case "$test_path" in
              orchestrator/tests/*|tests/generated/*|tests/e2e/*) ;;
              *) echo "test_path must be under orchestrator/tests, tests/generated, or tests/e2e" >&2; exit 64 ;;
            esac
          fi

          if [ -n "$playwright_grep" ]; then
            if [ "${{#playwright_grep}}" -gt 120 ] || [[ "$playwright_grep" =~ [\\;\\&\\|\\`\\$\\<\\>\\(\\)\\{{\\}}] ]]; then
              echo "Unsafe playwright_grep input" >&2
              exit 64
            fi
          fi

          if [ -n "$base_url" ]; then
            if [ "${{#base_url}}" -gt 200 ] || [[ ! "$base_url" =~ ^https?:// ]]; then
              echo "base_url must be an http or https URL up to 200 characters" >&2
              exit 64
            fi
          fi

          if [ "$suite" = "auto" ] && [ "$EVENT_NAME" = "pull_request" ]; then
            git diff --name-only "$BASE_SHA" "$HEAD_SHA" > /tmp/changed-files.txt || git diff --name-only HEAD^ HEAD > /tmp/changed-files.txt
            if grep -Eq '^(Dockerfile|docker-compose|package-lock.json|package.json|pyproject.toml|requirements|requirements\\.|orchestrator/requirements|playwright\\.config\\.ts|\\.github/workflows/)' /tmp/changed-files.txt; then
              suite="all-safe"
            elif grep -Eq '^(orchestrator/|alembic\\.ini)' /tmp/changed-files.txt; then
              suite="python-unit"
            elif grep -Eq '^web/' /tmp/changed-files.txt; then
              suite="frontend-typecheck"
            elif grep -Eq '^tests/generated/' /tmp/changed-files.txt; then
              suite="playwright-generated"
            elif grep -Eq '^tests/e2e/' /tmp/changed-files.txt; then
              suite="playwright-e2e"
            else
              suite="python-unit"
            fi
          elif [ "$suite" = "auto" ]; then
            suite="all-safe"
          fi

          {{
            echo "suite=$suite"
            echo "browser=$browser"
            echo "pytest_marker=$pytest_marker"
            echo "test_path=$test_path"
            echo "playwright_grep=$playwright_grep"
            echo "base_url=$base_url"
          }} >> "$GITHUB_OUTPUT"

  python-tests:
    needs: select-suite
    if: contains(fromJSON('["python-unit","python-integration","all-safe"]'), needs.select-suite.outputs.suite)
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: ./orchestrator
    env:
      JWT_SECRET_KEY: test-secret-key-for-ci
      REQUIRE_AUTH: "false"
      DATABASE_URL: sqlite:///./test.db
      SELECTED_SUITE: ${{{{ needs.select-suite.outputs.suite }}}}
      PYTEST_MARKER: ${{{{ needs.select-suite.outputs.pytest_marker }}}}
      TEST_PATH: ${{{{ needs.select-suite.outputs.test_path }}}}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"
      - run: python -m pip install --upgrade pip
      - run: if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
      - run: pip install pytest pytest-asyncio
      - name: Run pytest subset
        run: |
          set -euo pipefail
          marker="$PYTEST_MARKER"
          if [ "$SELECTED_SUITE" = "python-integration" ]; then
            marker="integration"
          elif [ "$SELECTED_SUITE" = "all-safe" ]; then
            marker="not integration"
          fi
          target="tests"
          if [[ "$TEST_PATH" == orchestrator/tests/* ]]; then
            target="${{TEST_PATH#orchestrator/}}"
          fi
          if [ "$marker" = "not integration" ]; then
            python -m pytest "$target" -v -m "$marker" --ignore=tests/integration
          else
            python -m pytest "$target" -v -m "$marker"
          fi

  frontend-checks:
    needs: select-suite
    if: contains(fromJSON('["frontend-typecheck","frontend-lint","all-safe"]'), needs.select-suite.outputs.suite)
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: ./web
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
          cache-dependency-path: web/package-lock.json
      - run: npm ci
      - name: Type check frontend
        if: contains(fromJSON('["frontend-typecheck","all-safe"]'), needs.select-suite.outputs.suite)
        run: npx tsc --noEmit
      - name: Lint frontend
        if: needs.select-suite.outputs.suite == 'frontend-lint'
        run: npm run lint

  playwright-tests:
    needs: select-suite
    if: contains(fromJSON('["playwright-generated","playwright-e2e","all-safe"]'), needs.select-suite.outputs.suite)
    runs-on: ubuntu-latest
    env:
      SELECTED_SUITE: ${{{{ needs.select-suite.outputs.suite }}}}
      BROWSER: ${{{{ needs.select-suite.outputs.browser }}}}
      TEST_PATH: ${{{{ needs.select-suite.outputs.test_path }}}}
      PLAYWRIGHT_GREP: ${{{{ needs.select-suite.outputs.playwright_grep }}}}
      BASE_URL: ${{{{ needs.select-suite.outputs.base_url }}}}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
      - run: npm ci
      - run: npx playwright install --with-deps "$BROWSER"
      - name: Run Playwright subset
        run: |
          set -euo pipefail
          cmd=(npx playwright test --project="$BROWSER")
          if [[ "$TEST_PATH" == tests/generated/* || "$TEST_PATH" == tests/e2e/* ]]; then
            cmd+=("$TEST_PATH")
          elif [ "$SELECTED_SUITE" = "playwright-generated" ]; then
            cmd+=(tests/generated)
          elif [ "$SELECTED_SUITE" = "playwright-e2e" ]; then
            cmd+=(tests/e2e)
          fi
          if [ -n "$PLAYWRIGHT_GREP" ]; then
            cmd+=(--grep "$PLAYWRIGHT_GREP")
          fi
          "${{cmd[@]}}"
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: playwright-subset-${{{{ needs.select-suite.outputs.browser }}}}
          path: |
            playwright-report/
            test-results/
          retention-days: {retention}
"""


def _render_github_workflow(request: WorkflowGenerateRequest) -> tuple[str, str]:
    name = request.workflow_name.strip() or "Quorvex Test Automation"
    path = ".github/workflows/quorvex-subset-tests.yml" if request.template == "runner-subset-tests" else f".github/workflows/{_safe_workflow_slug(name)}.yml"
    branches = ", ".join(_branches(request.branches))
    retention = max(1, min(int(request.artifact_retention_days), 90))
    if request.template == "pr-quality-gate":
        timeout_minutes = max(5, min(int(request.wait_timeout_minutes or 120), 720))
        if request.quality_gate_mode == "backend-blocking":
            yaml = f"""name: {name}

on:
  pull_request:
    branches: [{branches}]
    types: [opened, synchronize, reopened, ready_for_review]
  workflow_dispatch:

permissions:
  contents: read
  statuses: write
  pull-requests: write

jobs:
  quorvex-quality-gate:
    if: github.event_name != 'pull_request' || github.event.pull_request.draft == false
    runs-on: ubuntu-latest
    timeout-minutes: {timeout_minutes}
    steps:
      - name: Start and wait for Quorvex PR quality gate
        if: github.event_name == 'pull_request'
        env:
          QUORVEX_API_URL: ${{{{ secrets.{request.api_url_secret} }}}}
          QUORVEX_API_TOKEN: ${{{{ secrets.{request.api_token_secret} }}}}
          QUORVEX_PROJECT_ID: ${{{{ vars.{request.project_id_variable} || 'default' }}}}
          PR_NUMBER: ${{{{ github.event.pull_request.number }}}}
          HEAD_SHA: ${{{{ github.event.pull_request.head.sha }}}}
        run: |
          curl -fsS -X POST "$QUORVEX_API_URL/github/$QUORVEX_PROJECT_ID/quality-gates/pr/start" \\
            -H "Authorization: Bearer $QUORVEX_API_TOKEN" \\
            -H "Content-Type: application/json" \\
            -d '{{"pr_number": '${{PR_NUMBER}}', "head_sha": "'${{HEAD_SHA}}'", "ensure_indexed": true, "run_recommended": true, "post_feedback": true, "create_commit_status": true}}'

          deadline=$((SECONDS + {timeout_minutes} * 60))
          while true; do
            status_json=$(curl -fsS "$QUORVEX_API_URL/github/$QUORVEX_PROJECT_ID/quality-gates/pr/status?pr_number=$PR_NUMBER&head_sha=$HEAD_SHA" \\
              -H "Authorization: Bearer $QUORVEX_API_TOKEN")
            echo "$status_json"
            terminal=$(python -c 'import json,sys; print(str(json.load(sys.stdin).get("terminal", False)).lower())' <<< "$status_json")
            if [ "$terminal" = "true" ]; then
              exit_code=$(python -c 'import json,sys; print(json.load(sys.stdin).get("exit_code", 1))' <<< "$status_json")
              exit "$exit_code"
            fi
            if [ "$SECONDS" -ge "$deadline" ]; then
              echo "Timed out waiting for Quorvex quality gate."
              exit 1
            fi
            sleep 10
          done
"""
        else:
            yaml = f"""name: {name}

on:
  pull_request:
    branches: [{branches}]
    types: [opened, synchronize, reopened, ready_for_review]
  workflow_dispatch:

permissions:
  contents: read
  statuses: write
  pull-requests: write

jobs:
  quorvex-quality-gate:
    if: github.event_name != 'pull_request' || github.event.pull_request.draft == false
    runs-on: ubuntu-latest
    steps:
      - name: Start Quorvex PR quality gate
        if: github.event_name == 'pull_request'
        env:
          QUORVEX_API_URL: ${{{{ secrets.{request.api_url_secret} }}}}
          QUORVEX_API_TOKEN: ${{{{ secrets.{request.api_token_secret} }}}}
          QUORVEX_PROJECT_ID: ${{{{ vars.{request.project_id_variable} || 'default' }}}}
        run: |
          curl -fsS -X POST "$QUORVEX_API_URL/github/$QUORVEX_PROJECT_ID/quality-gates/pr/start" \\
            -H "Authorization: Bearer $QUORVEX_API_TOKEN" \\
            -H "Content-Type: application/json" \\
            -d '{{"pr_number": ${{{{ github.event.pull_request.number }}}}, "head_sha": "${{{{ github.event.pull_request.head.sha }}}}", "ensure_indexed": true, "run_recommended": true, "post_feedback": true, "create_commit_status": true}}'
"""
    elif request.template == "runner-subset-tests":
        yaml = _render_runner_subset_workflow(name, branches, retention)
    elif request.template == "nightly-regression":
        yaml = f"""name: {name}

on:
  schedule:
    - cron: '0 2 * * *'
  workflow_dispatch:

permissions:
  contents: read

jobs:
  quorvex-nightly-regression:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
      - run: npm ci
      - run: npx playwright install --with-deps
      - name: Run Quorvex generated tests
        env:
          APP_BASE_URL: ${{{{ secrets.{request.target_url_secret} }}}}
        run: npx playwright test tests/generated
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: playwright-report
          path: playwright-report/
          retention-days: {retention}
"""
    elif request.template == "release-gate":
        yaml = f"""name: {name}

on:
  workflow_dispatch:
    inputs:
      environment:
        description: Target environment
        required: true
        default: staging

permissions:
  contents: read
  deployments: write

jobs:
  quorvex-release-gate:
    runs-on: ubuntu-latest
    environment: ${{{{ inputs.environment }}}}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - run: npm ci
      - run: npx playwright install --with-deps
      - name: Run release gate suite
        env:
          APP_BASE_URL: ${{{{ secrets.{request.target_url_secret} }}}}
        run: npx playwright test --grep @release
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: release-gate-evidence
          path: |
            playwright-report/
            test-results/
          retention-days: {retention}
"""
    else:
        browsers = ", ".join(_browsers(request.browsers))
        yaml = f"""name: {name}

on:
  pull_request:
    branches: [{branches}]
  workflow_dispatch:

permissions:
  contents: read

jobs:
  quorvex-smoke:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        browser: [{browsers}]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
      - run: npm ci
      - run: npx playwright install --with-deps ${{{{ matrix.browser }}}}
      - name: Run smoke tests
        env:
          APP_BASE_URL: ${{{{ secrets.{request.target_url_secret} }}}}
        run: npx playwright test --project=${{{{ matrix.browser }}}} --grep @smoke
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: smoke-${{{{ matrix.browser }}}}
          path: |
            playwright-report/
            test-results/
          retention-days: {retention}
"""
    return path, yaml


def _validate_workflow_yaml(yaml: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    parsed: Any | None = None
    try:
        parsed = yaml_module_safe_load(yaml)
    except Exception as exc:
        errors.append(f"Generated workflow YAML is invalid: {exc}")
    deny_patterns = {
        "pull_request_target": "pull_request_target can expose secrets to untrusted code.",
        "curl | sh": "Pipe-to-shell install commands are not allowed in generated workflows.",
        "ACTIONS_STEP_DEBUG": "Debug tracing can leak sensitive data.",
    }
    for pattern, message in deny_patterns.items():
        if pattern in yaml:
            errors.append(message)
    if re.search(r"curl\s+.+\|\s*(bash|sh)", yaml):
        errors.append("Pipe-to-shell install commands are not allowed in generated workflows.")
    if "permissions:" not in yaml:
        errors.append("Generated workflow must declare minimal permissions.")
    if "actions/checkout@" in yaml and "actions/checkout@v4" not in yaml:
        warnings.append("Prefer current pinned major version for checkout.")
    if "upload-artifact" in yaml and "retention-days:" not in yaml:
        warnings.append("Artifact uploads should declare retention-days.")
    if "${{ secrets." in yaml and "echo ${{ secrets." in yaml:
        errors.append("Generated workflow must not echo secrets.")
    if parsed is not None:
        if not isinstance(parsed, dict):
            errors.append("Generated workflow must be a YAML mapping.")
        else:
            jobs = parsed.get("jobs")
            if not isinstance(jobs, dict) or not jobs:
                errors.append("Generated workflow must define at least one job.")
            permissions = parsed.get("permissions")
            if not isinstance(permissions, dict):
                errors.append("Generated workflow permissions must be an explicit mapping.")
            elif any(value == "write-all" for value in permissions.values()):
                errors.append("Generated workflow must not request write-all permissions.")
    return errors, warnings


def yaml_module_safe_load(content: str) -> Any:
    return yaml.safe_load(content)


@router.post("/workflow-change-requests")
async def create_workflow_change_request(
    project_id: str,
    request: WorkflowGenerateRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_edit(project_id, current_user, session)
    _require_project(project_id, session)
    if request.provider != "github":
        raise HTTPException(status_code=400, detail="Workflow generation currently supports GitHub Actions only")
    path, yaml = _render_github_workflow(request)
    errors, warnings = _validate_workflow_yaml(yaml)
    errors = _validate_workflow_request(request) + errors
    actor_id, _actor_email = _actor(current_user)
    change = CiWorkflowChangeRequest(
        project_id=project_id,
        provider=request.provider,
        workflow_name=request.workflow_name,
        workflow_path=path,
        ref=request.ref,
        generated_yaml=yaml,
        prompt=request.prompt,
        validation_errors=errors,
        validation_warnings=warnings,
        created_by=actor_id,
    )
    session.add(change)
    _audit(
        session,
        project_id=project_id,
        provider=request.provider,
        action="generate_workflow",
        target_type="workflow_change_request",
        target_id=change.id,
        status="blocked" if errors else "ok",
        user=current_user,
        metadata={"template": request.template, "workflow_path": path},
    )
    session.commit()
    session.refresh(change)
    project = _require_project(project_id, session)
    return _serialize_workflow_change(change, _get_github_config(project))


@router.post("/workflow-change-requests/{change_id}/pull-request")
async def open_workflow_pull_request(
    project_id: str,
    change_id: str,
    request: WorkflowPullRequestRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_edit(project_id, current_user, session)
    project = _require_project(project_id, session)
    change = session.get(CiWorkflowChangeRequest, change_id)
    if not change or change.project_id != project_id:
        raise HTTPException(status_code=404, detail="Workflow change request not found")
    if change.provider != "github":
        raise HTTPException(status_code=400, detail="Workflow PR creation currently supports GitHub Actions only")
    if change.status == "opened":
        return {
            **_serialize_workflow_change(change, _get_github_config(project)),
            "change_request_id": change.id,
        }
    if change.validation_errors:
        raise HTTPException(status_code=400, detail="Fix workflow validation errors before opening a pull request")

    config = _get_github_config(project)
    if not config:
        raise HTTPException(status_code=400, detail="GitHub is not configured")
    owner, repo = _github_repo(config)
    base_ref = (request.base_ref or change.ref or config.get("default_ref") or "main").strip()
    if not base_ref:
        base_ref = "main"
    branch_name = change.pull_request_branch or request.branch_name or f"quorvex/ci-workflow-{_safe_branch_segment(change.workflow_name)}-{change.id[:8]}"
    branch_name = _safe_branch_segment(branch_name)
    title = request.title or f"Add {change.workflow_name}"
    commit_message = request.commit_message or f"Add {change.workflow_name} workflow"
    body = request.body or _workflow_pr_body(change)

    change.status = "proposed"
    change.pull_request_branch = branch_name
    change.pull_request_base_ref = base_ref
    change.last_error = None
    change.updated_at = datetime.utcnow()
    session.add(change)
    session.commit()

    client = await _build_github_client(project)
    try:
        base = await client.get_ref(owner, repo, f"heads/{base_ref}")
        base_sha = ((base.get("object") or {}).get("sha") or "").strip()
        if not base_sha:
            raise HTTPException(status_code=502, detail="GitHub base branch did not return a commit SHA")
        try:
            await client.create_ref(owner, repo, f"heads/{branch_name}", base_sha)
        except GithubError as exc:
            if exc.status_code != 422:
                raise

        existing_prs = await client.list_pull_requests(owner, repo, head=f"{owner}:{branch_name}", base=base_ref)
        if existing_prs:
            pr = existing_prs[0]
            update = {"commit": {"sha": change.commit_sha}}
        else:
            existing = await client.get_content_metadata(owner, repo, change.workflow_path, ref=branch_name)
            update = await client.create_or_update_file(
                owner,
                repo,
                change.workflow_path,
                content=change.generated_yaml,
                message=commit_message,
                branch=branch_name,
                sha=(existing or {}).get("sha"),
            )
            change.commit_sha = ((update.get("commit") or {}).get("sha") if isinstance(update, dict) else None)
            change.updated_at = datetime.utcnow()
            session.add(change)
            session.commit()

            try:
                pr = await client.create_pull_request(
                    owner,
                    repo,
                    title=title,
                    head=branch_name,
                    base=base_ref,
                    body=body,
                    draft=request.draft,
                )
            except GithubError as exc:
                if exc.status_code != 422:
                    raise
                existing_prs = await client.list_pull_requests(owner, repo, head=f"{owner}:{branch_name}", base=base_ref)
                if not existing_prs:
                    raise
                pr = existing_prs[0]
    except GithubError as exc:
        detail = str(exc)
        if exc.status_code == 403:
            detail = "GitHub rejected the request. Check that the token can write repository contents and pull requests."
        elif exc.status_code == 404:
            detail = "GitHub repository, branch, or workflow path was not found."
        elif exc.status_code == 422:
            detail = f"GitHub could not create the workflow pull request: {exc}"
        change.last_error = detail
        change.updated_at = datetime.utcnow()
        session.add(change)
        session.commit()
        raise HTTPException(status_code=502, detail=detail) from exc
    finally:
        await client.close()

    change.status = "opened"
    change.pull_request_url = pr.get("html_url")
    change.pull_request_number = pr.get("number")
    change.pull_request_branch = branch_name
    change.pull_request_base_ref = base_ref
    change.commit_sha = ((update.get("commit") or {}).get("sha") if isinstance(update, dict) else change.commit_sha)
    change.last_error = None
    change.updated_at = datetime.utcnow()
    session.add(change)
    _audit(
        session,
        project_id=project_id,
        provider="github",
        action="open_workflow_pr",
        target_type="workflow_change_request",
        target_id=change.id,
        user=current_user,
        metadata={
            "branch": branch_name,
            "base_ref": base_ref,
            "workflow_path": change.workflow_path,
            "pull_request_number": pr.get("number"),
            "pull_request_url": pr.get("html_url"),
        },
    )
    session.commit()
    session.refresh(change)
    return {
        **_serialize_workflow_change(change, config),
        "change_request_id": change.id,
        "branch": branch_name,
        "workflow_path": change.workflow_path,
        "pull_request_number": pr.get("number"),
        "pull_request_url": pr.get("html_url"),
        "commit_sha": ((update.get("commit") or {}).get("sha") if isinstance(update, dict) else None),
    }


@router.get("/audit-events")
async def list_audit_events(
    project_id: str,
    limit: int = 50,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_view(project_id, current_user, session)
    limit = max(1, min(limit, 100))
    stmt = (
        select(CiAuditEvent)
        .where(CiAuditEvent.project_id == project_id)
        .order_by(CiAuditEvent.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": event.id,
            "provider": event.provider,
            "action": event.action,
            "target_type": event.target_type,
            "target_id": event.target_id,
            "status": event.status,
            "actor_email": event.actor_email,
            "metadata": event.event_metadata,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        }
        for event in session.exec(stmt).all()
    ]
