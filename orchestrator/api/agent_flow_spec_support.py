"""Support helpers for browser-backed flow spec generation."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time as time_module
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

MAX_FLOW_SPEC_JOBS = 100
_flow_spec_jobs: dict[str, dict] = {}


def _requires_authentication(url: str) -> bool:
    """Check if URL pattern typically requires authentication."""
    auth_patterns = [
        "/user/",
        "/admin/",
        "/dashboard",
        "/account/",
        "/my_",
        "/settings",
        "/profile",
        "/billing",
        "/itinerary",
        "/trips",
        "/bookings",
    ]
    return any(pattern in url.lower() for pattern in auth_patterns)


def _detect_login_url(target_url: str) -> str:
    """Detect login URL based on target domain."""
    parsed = urlparse(target_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    # Map domains to login URLs.
    login_url_map = {
        "myapp.example.com": "/users/sign_in",
        "pre.myapp.example.com": "/users/sign_in",
    }

    for domain_pattern, login_path in login_url_map.items():
        if domain_pattern in parsed.netloc:
            return f"{base}{login_path}"

    # Default: assume /login.
    return f"{base}/login"


def _is_login_page(url: str) -> bool:
    """Check if URL is a login page itself."""
    login_patterns = ["/login", "/signin", "/sign_in", "/sign-in", "/auth"]
    return any(pattern in url.lower() for pattern in login_patterns)


def _extract_domain_name(url: str) -> str:
    """Extract a clean domain name from URL for folder naming."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        # Remove common prefixes.
        hostname = re.sub(r"^(www\.|pre\.|staging\.|dev\.|test\.)", "", hostname)
        # Get the main domain part before the TLD.
        parts = hostname.split(".")
        if len(parts) >= 2:
            return parts[0]
        return hostname or "unknown"
    except Exception as e:
        logger.debug(f"URL parse failed for hostname extraction: {e}")
        return "unknown"


def _slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    slug = text.lower()
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"[^\w\-]", "", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug[:50] if len(slug) > 50 else slug


def _cleanup_flow_spec_jobs(
    jobs: dict[str, dict] | None = None,
    max_jobs: int | None = None,
) -> None:
    """Remove completed/failed jobs older than 1 hour, enforce cap."""
    jobs = _flow_spec_jobs if jobs is None else jobs
    max_jobs = MAX_FLOW_SPEC_JOBS if max_jobs is None else max_jobs

    now = time_module.time()
    to_remove = []
    for job_id, job in jobs.items():
        if job["status"] in ("completed", "failed"):
            completed_at = job.get("completed_at", 0)
            if now - completed_at > 3600:
                to_remove.append(job_id)
    for job_id in to_remove:
        del jobs[job_id]
    if len(jobs) > max_jobs:
        evictable = sorted(
            [(jid, j) for jid, j in jobs.items() if j["status"] != "running"],
            key=lambda x: x[1].get("started_at", 0),
        )
        for job_id, _ in evictable[: len(jobs) - max_jobs]:
            del jobs[job_id]


async def run_flow_spec_generation(
    job_id: str,
    run_id: str,
    flow_id: str,
    flow: dict,
    flows: list,
    flows_file_path: str,
    run_project_id: str | None,
    run_config: dict,
    spec_agent_run_id: str | None = None,
    *,
    jobs: dict[str, dict],
    runs_dir: Path,
    project_root: Path,
    db_engine: Any,
    db_session_factory: Callable[[Any], Any],
    agent_run_model: type[Any],
    spec_metadata_model: type[Any],
    get_spec_metadata: Callable[[Any, str, str | None], Any],
    resolve_agent_browser_auth_storage_path: Callable[..., Path | None],
    prepare_spec_generation_mcp_config: Callable[[Path, Path | str | None], dict[str, Any]],
    spec_generation_auth_metadata: Callable[..., dict[str, Any]],
    update_agent_run_progress: Callable[[str, dict[str, Any]], None],
    record_agent_run_event: Callable[..., None],
    browser_runtime_status_callback: Callable[[], dict[str, Any]],
    short_tool_name: Callable[[str | None], str],
    logger_override: logging.Logger | None = None,
) -> None:
    """Background task: run Native Planner to generate spec for a flow."""
    log = logger_override or logger

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from load_env import setup_claude_env
    from workflows.native_planner import NativePlanner

    try:
        setup_claude_env()
        flows_file = Path(flows_file_path)
        spec_run_dir = runs_dir / spec_agent_run_id if spec_agent_run_id else None
        if spec_run_dir:
            await asyncio.to_thread(spec_run_dir.mkdir, parents=True, exist_ok=True)
            storage_state_path = resolve_agent_browser_auth_storage_path(
                run_id=spec_agent_run_id,
                project_id=run_project_id or run_config.get("project_id"),
                config=run_config,
                run_dir=spec_run_dir,
            )
            mcp_runtime = await asyncio.to_thread(
                prepare_spec_generation_mcp_config,
                spec_run_dir,
                storage_state_path,
            )
            if spec_agent_run_id:
                update_agent_run_progress(
                    spec_agent_run_id,
                    {
                        "phase": "browser_setup",
                        "message": "Prepared browser MCP runtime for spec generation.",
                        "has_browser_tools": True,
                        **spec_generation_auth_metadata(run_config),
                        **mcp_runtime,
                    },
                )

        jobs[job_id]["message"] = "Preparing flow context..."
        if spec_agent_run_id:
            update_agent_run_progress(
                spec_agent_run_id,
                {
                    "phase": "preparing",
                    "message": "Preparing flow context...",
                    "has_browser_tools": True,
                    **browser_runtime_status_callback(),
                },
            )

        flow_title = flow.get("title", "Unnamed Flow")
        entry_point = flow.get("entry_point") or (flow.get("pages", [""])[0] if flow.get("pages") else "")
        exit_point = flow.get("exit_point", "")
        happy_path = flow.get("happy_path", "")
        edge_cases = flow.get("edge_cases", [])
        test_ideas = flow.get("test_ideas", [])

        if not entry_point:
            raise ValueError("Flow must have an entry_point or at least one page")

        if entry_point.startswith("/"):
            base_url = run_config.get("url", "")
            if base_url:
                parsed = urlparse(base_url)
                base_origin = f"{parsed.scheme}://{parsed.netloc}"
                entry_point = f"{base_origin}{entry_point}"
                log.info(f"Resolved relative entry_point to: {entry_point}")

        requires_auth = _requires_authentication(entry_point)
        if _is_login_page(entry_point):
            requires_auth = False

        credentials = None
        login_url = None
        if requires_auth:
            credentials = {"username": os.getenv("LOGIN_USERNAME", ""), "password": os.getenv("LOGIN_PASSWORD", "")}
            login_url = _detect_login_url(entry_point)
            if not credentials.get("username") or not credentials.get("password"):
                log.warning("Auth required but credentials not set in environment")

        flow_context = f"""## Flow: {flow_title}

### Description
{happy_path if happy_path else f"Test the {flow_title} user flow."}

### Target URL
{entry_point}

### Expected End State
{exit_point if exit_point else "Flow completes successfully"}

### Edge Cases to Consider
{chr(10).join(f"- {ec}" for ec in edge_cases[:5]) if edge_cases else "- None specified"}

### Test Ideas
{chr(10).join(f"- {idea}" for idea in test_ideas[:5]) if test_ideas else "- Test the happy path"}
"""
        auth_metadata = spec_generation_auth_metadata(run_config)
        if auth_metadata.get("browser_auth_session_id") or auth_metadata.get("use_project_default_browser_auth"):
            session_name = (
                auth_metadata.get("browser_auth_session_name")
                or auth_metadata.get("browser_auth_session_id")
                or "selected session"
            )
            flow_context += (
                "\n## Browser Authentication Context\n"
                f"The browser starts authenticated with saved session `{session_name}`. "
                "Do not generate login steps unless the scenario explicitly tests login, logout, or authentication failure.\n"
            )

        jobs[job_id]["message"] = "Running Native Planner (browser exploration)..."
        log.info(f"Starting Native Planner for flow: {flow_title}")
        if spec_run_dir and not await asyncio.to_thread((spec_run_dir / ".mcp.json").exists):
            raise RuntimeError(f"Spec generation setup failed: missing browser MCP config at {spec_run_dir / '.mcp.json'}")

        domain_name = _extract_domain_name(entry_point)
        flow_slug = _slugify(flow_title)
        folder_name = f"explorer-{domain_name}-{flow_slug}"

        effective_project_id = run_project_id if run_project_id else folder_name

        def _on_planner_task_enqueued(agent_task_id: str) -> None:
            jobs[job_id]["agent_task_id"] = agent_task_id
            if spec_agent_run_id:
                update_agent_run_progress(spec_agent_run_id, {"agent_task_id": agent_task_id})

        def _on_planner_tool_use(tool_name: str, tool_input: dict[str, Any]) -> None:
            jobs[job_id]["message"] = f"Using {short_tool_name(tool_name)}..."
            if not spec_agent_run_id:
                return
            runtime = browser_runtime_status_callback()
            is_browser_action = str(tool_name).startswith("mcp__playwright")
            update_agent_run_progress(
                spec_agent_run_id,
                {
                    "phase": "tool_use",
                    "message": f"Using {short_tool_name(tool_name)}",
                    "last_tool": tool_name,
                    "last_tool_input": tool_input,
                    "has_browser_tools": True,
                    **runtime,
                },
            )
            record_agent_run_event(
                spec_agent_run_id,
                event_type="browser_action" if is_browser_action else "tool_call",
                message=f"Using {short_tool_name(tool_name)}.",
                payload={
                    "tool_name": tool_name,
                    "tool_label": short_tool_name(tool_name),
                    "tool_input": tool_input,
                    "source_run_id": run_id,
                    "source_flow_id": flow_id,
                },
            )

        def _on_planner_progress(progress: dict[str, Any]) -> None:
            if not spec_agent_run_id:
                return
            last_tool = progress.get("last_tool")
            update_agent_run_progress(
                spec_agent_run_id,
                {
                    **progress,
                    "phase": progress.get("phase") or "running",
                    "message": f"Using {short_tool_name(str(last_tool))}"
                    if last_tool
                    else "Native Planner is exploring the browser",
                    "has_browser_tools": True,
                    **browser_runtime_status_callback(),
                },
            )

        planner = NativePlanner(
            project_id=effective_project_id,
            on_tool_use=_on_planner_tool_use,
            on_progress=_on_planner_progress,
            on_task_enqueued=_on_planner_task_enqueued,
            owner_type="agent_run" if spec_agent_run_id else None,
            owner_id=spec_agent_run_id,
            owner_label=f"Spec generation {flow_title}" if spec_agent_run_id else None,
            session_dir=spec_run_dir,
            cwd=spec_run_dir,
        )
        output_dir = project_root / "specs" / folder_name

        spec_path = await planner.generate_spec_from_flow_context(
            flow_title=flow_title,
            flow_context=flow_context,
            target_url=entry_point,
            login_url=login_url,
            credentials=credentials,
            output_dir=output_dir,
        )

        spec_exists = await asyncio.to_thread(spec_path.exists)
        spec_content = await asyncio.to_thread(spec_path.read_text) if spec_exists else None

        if not spec_content:
            raise RuntimeError("Native Planner failed to generate spec")

        log.info(f"Native Planner created spec: {spec_path}")

        jobs[job_id]["message"] = "Registering spec..."
        if spec_agent_run_id:
            update_agent_run_progress(
                spec_agent_run_id,
                {
                    "phase": "registering",
                    "message": "Registering generated spec...",
                    "has_browser_tools": True,
                    **browser_runtime_status_callback(),
                },
            )
        try:
            with db_session_factory(db_engine) as db_session:
                spec_name = str(spec_path.relative_to(project_root / "specs"))
                existing_meta = get_spec_metadata(db_session, spec_name, effective_project_id)
                if not existing_meta:
                    meta = spec_metadata_model(spec_name=spec_name, project_id=effective_project_id, tags_json="[]")
                    db_session.add(meta)
                db_session.commit()
                log.info(f"Registered spec in DB: {spec_name} (project: {effective_project_id})")
        except Exception as e:
            log.warning(f"Failed to register spec in DB: {e}")

        log.info(f"Spec generation complete for: {flow_title}")

        generated_at = datetime.now().isoformat()
        flow["generated_test"] = {
            "spec_file": str(spec_path),
            "spec_content": spec_content,
            "test_file": None,
            "test_code": None,
            "generated_at": generated_at,
            "validated": False,
            "requires_auth": requires_auth,
            "pipeline": "native_planner_generator",
        }

        for i, f in enumerate(flows):
            if f.get("id") == flow.get("id"):
                flows[i] = flow
                break

        updated_json = json.dumps({"flows": flows}, indent=2)
        await asyncio.to_thread(flows_file.write_text, updated_json)

        jobs[job_id].update(
            {
                "status": "completed",
                "message": "Spec generation complete",
                "completed_at": time_module.time(),
                "result": {
                    "status": "success",
                    "spec_file": str(spec_path),
                    "spec_content": spec_content,
                    "test_file": None,
                    "test_code": None,
                    "validated": False,
                    "flow_title": flow_title,
                    "requires_auth": requires_auth,
                    "pipeline": "native_planner_generator",
                    "cached": False,
                    "generated_at": generated_at,
                },
            }
        )
        if spec_agent_run_id:
            with db_session_factory(db_engine) as db_session:
                spec_run = db_session.get(agent_run_model, spec_agent_run_id)
                if spec_run:
                    spec_run.status = "completed"
                    spec_run.completed_at = datetime.utcnow()
                    spec_run.result = {
                        "summary": f"Generated spec for {flow_title}",
                        "spec_file": str(spec_path),
                        "spec_content": spec_content,
                        "source_run_id": run_id,
                        "source_flow_id": flow_id,
                        "pipeline": "native_planner_generator",
                    }
                    spec_run.progress = {
                        **(spec_run.progress or {}),
                        "phase": "completed",
                        "status": "completed",
                        "message": "Spec generation complete",
                        "has_browser_tools": True,
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                    db_session.add(spec_run)
                    db_session.commit()
            record_agent_run_event(
                spec_agent_run_id,
                event_type="completed",
                message="Spec generation complete.",
                payload={"spec_file": str(spec_path), "source_run_id": run_id, "source_flow_id": flow_id},
            )

    except Exception as e:
        log.error(f"Flow spec generation failed: {e}", exc_info=True)
        jobs[job_id].update(
            {
                "status": "failed",
                "message": str(e),
                "completed_at": time_module.time(),
            }
        )
        if spec_agent_run_id:
            with db_session_factory(db_engine) as db_session:
                spec_run = db_session.get(agent_run_model, spec_agent_run_id)
                if spec_run:
                    spec_run.status = "failed"
                    spec_run.completed_at = datetime.utcnow()
                    spec_run.result = {"error": str(e), "source_run_id": run_id, "source_flow_id": flow_id}
                    spec_run.progress = {
                        **(spec_run.progress or {}),
                        "phase": "failed",
                        "status": "failed",
                        "message": str(e),
                        "has_browser_tools": True,
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                    db_session.add(spec_run)
                    db_session.commit()
            record_agent_run_event(
                spec_agent_run_id,
                event_type="failed",
                level="error",
                message=str(e),
                payload={"source_run_id": run_id, "source_flow_id": flow_id},
            )
