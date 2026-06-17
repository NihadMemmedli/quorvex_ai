"""Exploratory agent and legacy spec-generation endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from orchestrator.services.agent_runtimes import normalize_agent_runtime as default_normalize_agent_runtime
from utils.agent_tool_allowlists import get_agent_allowed_tools as default_get_agent_allowed_tools

from . import agent_flow_spec_support
from .db import get_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent-exploratory"])


class ExploratoryRunRequest(BaseModel):
    """Enhanced exploratory testing request."""

    url: str
    time_limit_minutes: int = 15
    instructions: str = ""
    auth: dict[str, Any] | None = None
    test_data: dict[str, Any] | None = None
    test_data_refs: list[str] | None = None
    focus_areas: list[str] | None = None
    excluded_patterns: list[str] | None = None
    project_id: str | None = None
    runtime: str | None = None
    model_tier: str | None = "tool_deep"
    browser_auth_session_id: str | None = None
    use_project_default_browser_auth: bool = False
    advanced_tools: bool = False
    record_video: bool = False


class GenerateReportItemSpecRequest(BaseModel):
    browser_auth_session_id: str | None = None
    use_project_default_browser_auth: bool = False
    skip_browser_auth: bool = False
    inherit_browser_auth: bool = False


class GenerateFlowTestRequest(BaseModel):
    browser_auth_session_id: str | None = None
    use_project_default_browser_auth: bool = False
    skip_browser_auth: bool = False
    inherit_browser_auth: bool = True


class FlowUpdateRequest(BaseModel):
    """Partial update request for a discovered flow."""

    title: str | None = None
    pages: list[str] | None = None
    happy_path: str | None = None
    edge_cases: list[str] | None = None
    test_ideas: list[str] | None = None
    entry_point: str | None = None
    exit_point: str | None = None
    complexity: str | None = None


@dataclass(frozen=True)
class AgentExploratoryDependencies:
    agent_run_model: type[Any]
    db_session_factory: Callable[[Any], Any]
    db_engine: Any
    runs_dir: Path
    project_root: Path
    flow_spec_jobs: dict[str, dict]
    max_flow_spec_jobs: int
    agent_partial_status: str
    agent_browser_auth_resolution_error: type[Exception]
    browser_runtime_status: Callable[[], dict[str, Any]]
    record_agent_run_event: Callable[..., None]
    start_agent_run_temporal_or_fail: Callable[..., Awaitable[None]]
    get_agent_report_run: Callable[[Session, str, str], Any]
    serialize_agent_run: Callable[[Any, Session | None], dict[str, Any]]
    build_spec_generation_source_config: Callable[..., dict[str, Any]]
    apply_report_spec_browser_auth_request: Callable[..., tuple[dict[str, Any], bool]]
    spec_generation_auth_metadata: Callable[..., dict[str, Any]]
    resolve_agent_browser_auth_storage_path: Callable[..., Path | None]
    prepare_spec_generation_mcp_config: Callable[[Path, Path | str | None], dict[str, Any]]
    update_agent_run_progress: Callable[[str, dict[str, Any]], None]
    get_spec_metadata: Callable[[Any, str, str | None], Any]
    spec_metadata_model: type[Any]
    short_tool_name: Callable[[str | None], str]
    run_flow_spec_generation: Callable[..., Awaitable[None]]
    normalize_agent_runtime: Callable[[str | None], str] = default_normalize_agent_runtime
    get_agent_allowed_tools: Callable[..., list[str]] = default_get_agent_allowed_tools
    logger_override: logging.Logger | None = None


_dependencies_provider: Callable[[], AgentExploratoryDependencies] | None = None


def configure_dependencies_provider(provider: Callable[[], AgentExploratoryDependencies]) -> None:
    global _dependencies_provider
    _dependencies_provider = provider


def _deps(deps: AgentExploratoryDependencies | None = None) -> AgentExploratoryDependencies:
    if deps is not None:
        return deps
    if _dependencies_provider is None:
        raise RuntimeError("Agent exploratory dependencies have not been configured")
    return _dependencies_provider()


def _log(deps: AgentExploratoryDependencies) -> logging.Logger:
    return deps.logger_override or logger


def _verify_exploration_run_project(
    run_id: str,
    project_id: str | None,
    session: Session,
    deps: AgentExploratoryDependencies,
) -> Any:
    """Verify an exploration run exists and belongs to the specified project."""
    exploration_run = session.get(deps.agent_run_model, run_id)
    if not exploration_run:
        raise HTTPException(status_code=404, detail="Exploration run not found")

    if project_id and exploration_run.project_id:
        if project_id == "default":
            if exploration_run.project_id not in (None, "default"):
                raise HTTPException(status_code=404, detail="Exploration run not found")
        elif exploration_run.project_id != project_id:
            raise HTTPException(status_code=404, detail="Exploration run not found")

    return exploration_run


async def run_exploratory_agent_impl(
    request: ExploratoryRunRequest,
    *,
    session: Session,
    deps: AgentExploratoryDependencies | None = None,
) -> dict[str, Any]:
    """Run enhanced exploratory testing with autonomous exploration."""
    deps = _deps(deps)
    from agents.auth_handler import AuthHandler, get_auth_test_data

    config = request.dict()
    runtime = deps.normalize_agent_runtime(request.runtime or config.get("runtime"))
    config["runtime"] = runtime
    config["agent_tool_profile"] = (
        "app-explorer-advanced"
        if bool(config.get("advanced_tools") or config.get("record_video"))
        else "app-explorer-basic"
    )

    auth_result = {"success": True, "type": "none"}
    if request.auth:
        auth_handler = AuthHandler()
        auth_result = await auth_handler.authenticate(None, request.auth, request.url)

        if auth_result.get("success") and auth_result.get("instructions"):
            config["auth_instructions"] = auth_result["instructions"]

        if config.get("test_data") is None:
            config["test_data"] = {}
        config["test_data"].update(get_auth_test_data(request.auth or {}))

    run_id = str(uuid.uuid4())
    run = deps.agent_run_model(
        id=run_id,
        agent_type="exploratory",
        runtime=runtime,
        config_json=json.dumps(config),
        status="queued",
        project_id=request.project_id,
    )
    browser_metadata = deps.browser_runtime_status()
    run.progress = {
        **browser_metadata,
        "phase": "queued",
        "status": "queued",
        "runtime": runtime,
        "message": "Exploratory agent run is queued for Temporal.",
        "updated_at": datetime.utcnow().isoformat(),
    }
    session.add(run)
    session.commit()

    deps.record_agent_run_event(
        run_id,
        event_type="created",
        message="Exploratory agent run created with status queued.",
        payload={"agent_type": "exploratory", "runtime": runtime, "status": "queued"},
        session=session,
    )

    await deps.start_agent_run_temporal_or_fail(run, session)
    session.refresh(run)

    return {
        "run_id": run_id,
        "status": run.status,
        "auth": auth_result.get("type", "none"),
        "project_id": request.project_id,
        "temporal_workflow_id": run.temporal_workflow_id,
        "temporal_run_id": run.temporal_run_id,
        "agent_runtime": runtime,
        "browser_runtime": browser_metadata.get("browser_runtime"),
        "live_view_available": bool(browser_metadata.get("live_view_available")),
        "vnc_url": browser_metadata.get("vnc_url"),
    }


async def synthesize_specs_impl(
    run_id: str,
    *,
    session: Session,
    deps: AgentExploratoryDependencies | None = None,
) -> dict[str, Any]:
    """Generate .md test specs from exploration results."""
    deps = _deps(deps)
    exploration_run = session.get(deps.agent_run_model, run_id)
    if not exploration_run:
        raise HTTPException(status_code=404, detail="Exploration run not found")

    exploration_result = exploration_run.result
    if not exploration_result:
        raise HTTPException(status_code=400, detail="No exploration results found")
    flow_summaries = (
        exploration_result.get("discovered_flow_summaries")
        if isinstance(exploration_result, dict) and isinstance(exploration_result.get("discovered_flow_summaries"), list)
        else []
    )
    if exploration_run.status not in {"completed", deps.agent_partial_status}:
        raise HTTPException(status_code=400, detail="Exploration must be completed before synthesis")
    if exploration_run.status == deps.agent_partial_status and not flow_summaries:
        raise HTTPException(status_code=400, detail="Recovered exploration has no evidence-backed flows to synthesize")

    output_dir = str(deps.project_root / "specs" / "generated")
    synthesis_run_id = str(uuid.uuid4())

    exploration_project_id = exploration_run.project_id
    if not exploration_project_id:
        exploration_project_id = exploration_result.get("config", {}).get("project_id")
    if not exploration_project_id and exploration_run.config_json:
        run_config = json.loads(exploration_run.config_json)
        exploration_project_id = run_config.get("project_id")

    synthesis_config = {
        "exploration_results": exploration_result,
        "url": exploration_result.get("config", {}).get("url", ""),
        "output_dir": output_dir,
        "run_id": run_id,
        "project_id": exploration_project_id,
        "runtime": getattr(exploration_run, "runtime", "claude_sdk")
        or exploration_run.config.get("runtime")
        or "claude_sdk",
    }
    synthesis_runtime = deps.normalize_agent_runtime(synthesis_config.get("runtime"))

    synthesis_run = deps.agent_run_model(
        id=synthesis_run_id,
        agent_type="spec-synthesis",
        runtime=synthesis_runtime,
        config_json=json.dumps(synthesis_config),
        status="queued",
        project_id=exploration_project_id,
    )
    session.add(synthesis_run)
    session.commit()

    deps.record_agent_run_event(
        synthesis_run_id,
        event_type="created",
        message="Spec synthesis agent run created with status queued.",
        payload={
            "agent_type": "spec-synthesis",
            "runtime": synthesis_runtime,
            "status": "queued",
            "exploration_run_id": run_id,
        },
        session=session,
    )

    await deps.start_agent_run_temporal_or_fail(synthesis_run, session)
    session.refresh(synthesis_run)

    return {
        "synthesis_run_id": synthesis_run_id,
        "exploration_run_id": run_id,
        "status": synthesis_run.status,
        "temporal_workflow_id": synthesis_run.temporal_workflow_id,
        "temporal_run_id": synthesis_run.temporal_run_id,
    }


async def get_exploration_specs_impl(
    run_id: str,
    *,
    project_id: str | None,
    session: Session,
    deps: AgentExploratoryDependencies | None = None,
) -> dict[str, Any]:
    """Get generated specs from an exploration run."""
    deps = _deps(deps)
    _verify_exploration_run_project(run_id, project_id, session, deps)

    statement = select(deps.agent_run_model).where(deps.agent_run_model.config_json.contains(run_id)).order_by(
        deps.agent_run_model.created_at.desc()
    )
    synthesis_runs = session.exec(statement).all()

    if not synthesis_runs:
        return {"specs": {}, "message": "No specs generated yet. Run /synthesize first."}

    for run in synthesis_runs:
        if run.status == "completed" and run.result:
            return {
                "specs": run.result.get("specs", {}),
                "summary": run.result.get("summary", ""),
                "total_specs": run.result.get("total_specs", 0),
                "flows_covered": run.result.get("flows_covered", []),
                "generated_at": run.result.get("generated_at"),
            }

    raise HTTPException(status_code=404, detail="No completed spec synthesis found")


def _flow_by_id(flows: list[dict[str, Any]], flow_id: str) -> tuple[dict[str, Any] | None, int | None]:
    flow = next((fl for fl in flows if fl.get("id") == flow_id), None)
    if flow:
        return flow, flows.index(flow)
    if flow_id.startswith("flow_"):
        try:
            index = int(flow_id.split("_")[1]) - 1
            if 0 <= index < len(flows):
                return flows[index], index
        except (ValueError, IndexError):
            pass
    return None, None


async def _read_flows_file(flows_file: Path, run_id: str) -> dict[str, Any]:
    if not await asyncio.to_thread(flows_file.exists):
        raise HTTPException(
            status_code=404,
            detail=f"Flows file not found for run {run_id}. The exploration may not have completed yet.",
        )
    raw = await asyncio.to_thread(flows_file.read_text)
    return json.loads(raw)


async def get_flow_details_impl(
    run_id: str,
    flow_id: str,
    *,
    project_id: str | None,
    session: Session,
    deps: AgentExploratoryDependencies | None = None,
) -> dict[str, Any]:
    """Get full details for a specific discovered flow."""
    deps = _deps(deps)
    _verify_exploration_run_project(run_id, project_id, session, deps)
    flows_file = deps.project_root / "runs" / run_id / "flows.json"

    try:
        data = await _read_flows_file(flows_file, run_id)
        flows = data.get("flows", [])
        flow, _ = _flow_by_id(flows, flow_id)
        if not flow:
            raise HTTPException(
                status_code=404,
                detail=f"Flow {flow_id} not found in run {run_id}. Available flows: {[f.get('id') for f in flows]}",
            )
        return {"flow": flow}
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Failed to parse flows.json file")
    except HTTPException:
        raise
    except Exception as e:
        _log(deps).error(f"Error reading flow details: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


async def update_flow_impl(
    run_id: str,
    flow_id: str,
    request: FlowUpdateRequest,
    *,
    project_id: str | None,
    session: Session,
    deps: AgentExploratoryDependencies | None = None,
) -> dict[str, Any]:
    """Update a specific discovered flow with partial data."""
    deps = _deps(deps)
    _verify_exploration_run_project(run_id, project_id, session, deps)
    flows_file = deps.project_root / "runs" / run_id / "flows.json"

    try:
        data = await _read_flows_file(flows_file, run_id)
        flows = data.get("flows", [])
        flow, flow_index = _flow_by_id(flows, flow_id)
        if flow is None or flow_index is None:
            raise HTTPException(
                status_code=404,
                detail=f"Flow {flow_id} not found in run {run_id}. Available flows: {[fl.get('id') for fl in flows]}",
            )

        flow.update(request.model_dump(exclude_none=True))
        flows[flow_index] = flow
        data["flows"] = flows
        await asyncio.to_thread(flows_file.write_text, json.dumps(data, indent=2))
        return {"flow": flow}
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Failed to parse flows.json file")
    except HTTPException:
        raise
    except Exception as e:
        _log(deps).error(f"Error updating flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


async def delete_flow_impl(
    run_id: str,
    flow_id: str,
    *,
    project_id: str | None,
    session: Session,
    deps: AgentExploratoryDependencies | None = None,
) -> dict[str, Any]:
    """Delete a specific discovered flow."""
    deps = _deps(deps)
    _verify_exploration_run_project(run_id, project_id, session, deps)
    flows_file = deps.project_root / "runs" / run_id / "flows.json"

    try:
        data = await _read_flows_file(flows_file, run_id)
        flows = data.get("flows", [])
        flow, flow_index = _flow_by_id(flows, flow_id)
        if flow is None or flow_index is None:
            raise HTTPException(
                status_code=404,
                detail=f"Flow {flow_id} not found in run {run_id}. Available flows: {[fl.get('id') for fl in flows]}",
            )

        flows.pop(flow_index)
        data["flows"] = flows
        await asyncio.to_thread(flows_file.write_text, json.dumps(data, indent=2))
        return {"deleted": True, "flow_id": flow_id, "remaining_flows": len(flows)}
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Failed to parse flows.json file")
    except HTTPException:
        raise
    except Exception as e:
        _log(deps).error(f"Error deleting flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


async def analyze_prerequisites_impl(
    run_id: str,
    *,
    force_reanalyze: bool = False,
    project_id: str | None,
    session: Session,
    deps: AgentExploratoryDependencies | None = None,
) -> dict[str, Any]:
    """Analyze discovered flows and enrich them with prerequisite information."""
    deps = _deps(deps)
    from agents.prerequisites_agent import PrerequisitesAgent
    from load_env import setup_claude_env

    _verify_exploration_run_project(run_id, project_id, session, deps)
    flows_file = deps.project_root / "runs" / run_id / "flows.json"
    result_file = deps.project_root / "runs" / run_id / "result.json"

    if not await asyncio.to_thread(flows_file.exists):
        raise HTTPException(status_code=404, detail=f"Flows file not found for run {run_id}")

    setup_claude_env()

    try:
        raw = await asyncio.to_thread(flows_file.read_text)
        data = json.loads(raw)
        flows = data.get("flows", [])

        if not force_reanalyze and flows and flows[0].get("prerequisites"):
            return {
                "enriched_flows": flows,
                "flow_graph": data.get("flow_graph", {}),
                "summary": "Loaded previously analyzed prerequisites",
                "cached": True,
            }

        exploration_results = {}
        auth_config = {}
        test_data = {}
        exploration_url = ""

        if await asyncio.to_thread(result_file.exists):
            result_raw = await asyncio.to_thread(result_file.read_text)
            exploration_results = json.loads(result_raw)
            auth_config = exploration_results.get("config", {}).get("auth", {})
            test_data = exploration_results.get("config", {}).get("test_data", {})
            exploration_url = exploration_results.get("exploration_url", "")

        agent = PrerequisitesAgent()
        result = await agent.run(
            {
                "flows": flows,
                "action_trace": exploration_results.get("action_trace", []),
                "exploration_url": exploration_url,
                "auth_config": auth_config,
                "test_data": test_data,
            }
        )

        enriched_flows = result.get("enriched_flows", flows)
        updated_json = json.dumps(
            {
                "flows": enriched_flows,
                "flow_graph": result.get("flow_graph", {}),
                "entities_discovered": result.get("entities_discovered", []),
                "prerequisites_analyzed_at": result.get("analyzed_at"),
            },
            indent=2,
        )
        await asyncio.to_thread(flows_file.write_text, updated_json)

        return {
            "enriched_flows": enriched_flows,
            "flow_graph": result.get("flow_graph", {}),
            "entities_discovered": result.get("entities_discovered", []),
            "summary": result.get("summary", "Analysis complete"),
            "cached": False,
        }
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Failed to parse flows.json file")
    except Exception as e:
        _log(deps).error(f"Error analyzing prerequisites: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


async def generate_flow_spec_impl(
    run_id: str,
    flow_id: str,
    *,
    force_regenerate: bool = False,
    project_id: str | None,
    session: Session,
    deps: AgentExploratoryDependencies | None = None,
) -> dict[str, Any]:
    """Generate a test spec for a single discovered flow."""
    deps = _deps(deps)
    from agents.spec_synthesis_agent import SpecSynthesisAgent
    from load_env import setup_claude_env
    from utils.json_utils import extract_json_from_markdown

    _verify_exploration_run_project(run_id, project_id, session, deps)
    flows_file = deps.project_root / "runs" / run_id / "flows.json"
    result_file = deps.project_root / "runs" / run_id / "result.json"

    if not await asyncio.to_thread(flows_file.exists):
        raise HTTPException(status_code=404, detail=f"Flows file not found for run {run_id}")

    setup_claude_env()

    try:
        raw = await asyncio.to_thread(flows_file.read_text)
        data = json.loads(raw)
        flows = data.get("flows", [])
        flow, _ = _flow_by_id(flows, flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail=f"Flow {flow_id} not found")

        if not force_regenerate and "generated_spec" in flow:
            existing_spec = flow["generated_spec"]
            return {
                "spec_content": existing_spec["spec_content"],
                "filename": existing_spec.get("filename", f"{flow.get('title', 'spec').lower().replace(' ', '_')}.md"),
                "flow_title": flow.get("title", "Unnamed Flow"),
                "summary": "Loaded previously generated spec",
                "generated_at": existing_spec.get("generated_at", datetime.now().isoformat()),
                "cached": True,
            }

        exploration_results = {}
        if await asyncio.to_thread(result_file.exists):
            result_raw = await asyncio.to_thread(result_file.read_text)
            exploration_results = json.loads(result_raw)

        base_url = exploration_results.get("exploration_url", "")
        if not base_url:
            pages = flow.get("pages", [])
            if pages:
                from urllib.parse import urlparse

                parsed = urlparse(pages[0])
                base_url = f"{parsed.scheme}://{parsed.netloc}"

        agent = SpecSynthesisAgent()
        result = await agent._query_agent(_build_single_flow_prompt(flow, base_url))
        spec_data = extract_json_from_markdown(result)

        spec_content = None
        filename = None
        if "specs" in spec_data and spec_data["specs"]:
            for category in ["happy_path", "negative", "edge_case", "edge_cases", "accessibility", "regression"]:
                if category in spec_data["specs"] and spec_data["specs"][category]:
                    for fname, content in spec_data["specs"][category].items():
                        spec_content = content
                        filename = fname
                        break
                if spec_content:
                    break
            if not spec_content:
                for _category, files in spec_data["specs"].items():
                    for fname, content in files.items():
                        spec_content = content
                        filename = fname
                        break
                    if spec_content:
                        break
        else:
            spec_content, filename = _generate_fallback_spec(flow, base_url)

        flow_title = flow.get("title", "Unnamed Flow")
        spec_result = {
            "spec_content": spec_content,
            "filename": filename or f"{flow_title.lower().replace(' ', '_')}.md",
            "flow_title": flow_title,
            "summary": spec_data.get("summary", f"Generated test spec for {flow_title}"),
            "generated_at": datetime.now().isoformat(),
            "cached": False,
        }

        flow["generated_spec"] = {
            "spec_content": spec_result["spec_content"],
            "filename": spec_result["filename"],
            "generated_at": spec_result["generated_at"],
        }

        for i, candidate in enumerate(flows):
            if candidate.get("id") == flow.get("id"):
                flows[i] = flow
                break

        await asyncio.to_thread(flows_file.write_text, json.dumps({"flows": flows}, indent=2))
        return spec_result
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Failed to parse flows.json file")
    except Exception as e:
        _log(deps).error(f"Error generating spec: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


def _build_single_flow_prompt(flow: dict[str, Any], base_url: str) -> str:
    """Build a synthesis prompt for generating a spec from a single flow."""
    flow_title = flow.get("title", "Unnamed Flow")
    happy_path = flow.get("happy_path", "")
    pages = flow.get("pages", [])
    edge_cases = flow.get("edge_cases", [])
    test_ideas = flow.get("test_ideas", [])
    entry = flow.get("entry_point", "")
    exit_point = flow.get("exit_point", "")
    prerequisites = flow.get("prerequisites", {})
    produces = flow.get("produces", {})
    dependency_reason = flow.get("dependency_reason", "")

    flow_desc = f"\nFLOW: {flow_title}\n"
    flow_desc += f"Description: {happy_path}\n"
    if pages:
        flow_desc += f"Pages visited: {' → '.join(pages)}\n"
    if entry:
        flow_desc += f"Entry point: {entry}\n"
    if exit_point:
        flow_desc += f"Exit point: {exit_point}\n"
    if edge_cases:
        flow_desc += f"Edge cases: {', '.join(edge_cases[:5])}\n"
    if test_ideas:
        flow_desc += f"Test ideas: {', '.join(test_ideas[:3])}\n"

    prereq_section = ""
    if prerequisites:
        prereq_section = "\n## PREREQUISITES (CRITICAL - Include in spec)\n"
        auth = prerequisites.get("authentication", {})
        if auth.get("required"):
            prereq_section += "\n### Authentication Required:\n"
            prereq_section += f"- User type: {auth.get('user_type', 'standard user')}\n"
            prereq_section += f"- Login URL: {auth.get('login_url', '/login')}\n"
            if auth.get("permissions"):
                prereq_section += f"- Permissions: {', '.join(auth.get('permissions', []))}\n"

        data_reqs = prerequisites.get("data_requirements", [])
        if data_reqs:
            prereq_section += "\n### Data Requirements:\n"
            for req in data_reqs:
                entity = req.get("entity", "unknown")
                state = req.get("state", "exists")
                desc = req.get("description", f"{entity} must {state}")
                prereq_section += f"- {desc}\n"

        prior_flows = prerequisites.get("prior_flows", [])
        if prior_flows:
            prereq_section += "\n### Prior Flows Required:\n"
            prereq_section += f"- Must complete: {', '.join(prior_flows)}\n"
            if dependency_reason:
                prereq_section += f"- Reason: {dependency_reason}\n"

        app_state = prerequisites.get("application_state", {})
        if app_state.get("starting_page"):
            prereq_section += "\n### Application State:\n"
            prereq_section += f"- Starting page: {app_state.get('starting_page')}\n"
            if app_state.get("required_state"):
                prereq_section += f"- Required state: {app_state.get('required_state')}\n"

        setup_steps = prerequisites.get("setup_steps", [])
        if setup_steps:
            prereq_section += "\n### Setup Steps (include these BEFORE main test steps):\n"
            for i, step in enumerate(setup_steps, 1):
                prereq_section += f"{i}. {step}\n"

    produces_section = ""
    if produces:
        entities = produces.get("entities", [])
        enables = produces.get("enables_flows", [])
        if entities or enables:
            produces_section = "\n## WHAT THIS FLOW PRODUCES:\n"
            if entities:
                produces_section += f"- Creates: {', '.join(entities)}\n"
            if enables:
                produces_section += f"- Enables flows: {', '.join(enables)}\n"

    return f"""You are a Test Specification Generator.

Generate COMPREHENSIVE individual .md E2E scenario specs for the following discovered user flow.

{flow_desc}
{prereq_section}
{produces_section}

REQUIREMENTS:
1. Return one runnable spec per scenario. Use balanced E2E coverage where evidence supports it:
   - happy path
   - navigation/state transition
   - negative/error
   - edge case
   - accessibility
   - responsive/mobile or critical console-error regression

2. Follow this EXACT spec format for each file:
   ```markdown
   # Test: [Feature Name] - [Scenario Name]

   ## Description
   [Brief description of what this tests]

   ## Prerequisites
   [List all prerequisites - authentication, data, prior flows, etc.]
   - Authentication: [Required/Not required, user type]
   - Data: [What data must exist before running]
   - Prior flows: [What flows must complete first]

   ## Steps
   1. [Setup step - e.g., Login as user type]
   2. [Setup step - e.g., Navigate to starting page]
   3. [Main test step]
   4. [Continue with actual test actions]
   ...
   N. Assert [expected outcome]

   ## Expected Outcome
   - [Expected result 1]
   - [Expected result 2]

   ## Test Data
   - [Any test data requirements]
   ```

3. CRITICAL RULES:
   - **ALWAYS include Prerequisites section** - even if minimal
   - **Setup steps come FIRST** in the Steps section
   - Parse the happy_path description into specific, actionable steps
   - Don't use placeholders like "Complete step X" - use actual actions
   - Include specific URLs and element descriptions based on the flow
   - Use placeholders `{{{{VAR_NAME}}}}` for secrets/passwords
   - If authentication is required, include login steps at the beginning
   - If data requirements exist, mention them in Prerequisites
   - Do not invent unsupported business behavior; if evidence is thin, use conservative page/journey checks

OUTPUT FORMAT (return ONLY JSON):
```json
{{
  "specs": {{
    "happy_path": {{
      "tc-001-{flow_title.lower().replace(" ", "_").replace("/", "_")}-happy-path.md": "# Test: {flow_title} - Happy Path\\n\\n## Description\\n...\\n\\n## Prerequisites\\n...\\n\\n## Steps\\n..."
    }},
    "edge_case": {{
      "tc-002-{flow_title.lower().replace(" ", "_").replace("/", "_")}-edge-case.md": "# Test: {flow_title} - Edge Case\\n\\n## Description\\n..."
    }}
  }},
  "summary": "Generated individual E2E scenario specs for {flow_title}"
}}
```

Now generate the test spec."""


def _generate_fallback_spec(flow: dict[str, Any], base_url: str) -> tuple[str, str]:
    """Generate a basic spec as fallback when agent fails."""
    from orchestrator.workflows.spec_scenario_builder import render_scenario_markdown, scenario_from_requirement

    flow_title = flow.get("title", "Unnamed Flow")
    happy_path = flow.get("happy_path", "")
    pages = flow.get("pages", [])
    entry = flow.get("entry_point", "")
    exit_point = flow.get("exit_point", "")
    prerequisites = flow.get("prerequisites", {})

    preconditions = []
    if prerequisites:
        auth = prerequisites.get("authentication", {})
        if auth.get("required"):
            preconditions.append(f"Authentication required ({auth.get('user_type', 'standard user')})")
        else:
            preconditions.append("Authentication not required")

        for req in prerequisites.get("data_requirements", []):
            preconditions.append(f"Data: {req.get('description', req.get('entity', 'unknown'))}")

        prior_flows = prerequisites.get("prior_flows", [])
        if prior_flows:
            preconditions.append(f"Prior flows: {', '.join(prior_flows)}")

    steps = [str(setup_step) for setup_step in prerequisites.get("setup_steps", [])]

    if not any("navigate" in step.lower() for step in steps):
        if entry:
            destination = entry if str(entry).startswith(("http://", "https://")) else f"{{{{BASE_URL}}}}{entry}"
            steps.append(f"Navigate to {destination}")
        elif pages:
            steps.append(f"Navigate to {pages[0]}")

    if happy_path:
        for action in re.split(r"[,.]", happy_path):
            action = action.strip()
            if action and len(action) > 5 and not action.startswith(
                ("Navigate", "Click", "Fill", "Verify", "Check", "Select", "Assert")
            ):
                steps.append(action)

    if exit_point:
        destination = (
            exit_point if str(exit_point).startswith(("http://", "https://")) else f"{{{{BASE_URL}}}}{exit_point}"
        )
        steps.append(f"Verify arrival at {destination}")
    else:
        steps.append("Verify successful completion")

    edge_cases = flow.get("edge_cases", [])
    expected = [
        f"User successfully completes the {flow_title}",
        "All pages load correctly",
        "No blocking errors are displayed",
    ]
    if edge_cases:
        expected.append("Known edge cases are handled safely or documented for separate coverage")

    scenario = scenario_from_requirement(
        title=flow_title,
        description=happy_path or f"Validate the {flow_title} flow.",
        target_url=entry or base_url,
        flow_steps=steps,
        acceptance_criteria=expected,
        category="happy_path",
        priority="medium",
        source_flows=[flow_title],
    )
    scenario.preconditions = preconditions or ["Fresh browser session"]
    scenario.test_data.append("Base URL: {{BASE_URL}}")
    if edge_cases:
        scenario.test_data.extend(f"Edge case to cover separately: {case}" for case in edge_cases[:5])
    spec_content = render_scenario_markdown(scenario)

    safe_name = re.sub(r"[^\w\s-]", "", flow_title)
    safe_name = re.sub(r"[-\s]+", "_", safe_name)
    safe_name = safe_name.lower().strip("_")
    return spec_content, f"{safe_name}.md"


def _cleanup_flow_spec_jobs(deps: AgentExploratoryDependencies | None = None) -> None:
    deps = _deps(deps)
    agent_flow_spec_support._cleanup_flow_spec_jobs(deps.flow_spec_jobs, deps.max_flow_spec_jobs)


async def _run_flow_spec_generation_impl(
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
    deps: AgentExploratoryDependencies | None = None,
) -> None:
    """Compatibility background runner backed by flow-spec support helpers."""
    deps = _deps(deps)
    await agent_flow_spec_support.run_flow_spec_generation(
        job_id=job_id,
        run_id=run_id,
        flow_id=flow_id,
        flow=flow,
        flows=flows,
        flows_file_path=flows_file_path,
        run_project_id=run_project_id,
        run_config=run_config,
        spec_agent_run_id=spec_agent_run_id,
        jobs=deps.flow_spec_jobs,
        runs_dir=deps.runs_dir,
        project_root=deps.project_root,
        db_engine=deps.db_engine,
        db_session_factory=deps.db_session_factory,
        agent_run_model=deps.agent_run_model,
        spec_metadata_model=deps.spec_metadata_model,
        get_spec_metadata=deps.get_spec_metadata,
        resolve_agent_browser_auth_storage_path=deps.resolve_agent_browser_auth_storage_path,
        prepare_spec_generation_mcp_config=deps.prepare_spec_generation_mcp_config,
        spec_generation_auth_metadata=deps.spec_generation_auth_metadata,
        update_agent_run_progress=deps.update_agent_run_progress,
        record_agent_run_event=deps.record_agent_run_event,
        browser_runtime_status_callback=deps.browser_runtime_status,
        short_tool_name=deps.short_tool_name,
        logger_override=deps.logger_override,
    )


async def get_flow_spec_job_status_impl(
    job_id: str,
    *,
    deps: AgentExploratoryDependencies | None = None,
) -> dict[str, Any]:
    """Get status of a flow spec generation job."""
    deps = _deps(deps)
    job = deps.flow_spec_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    response = {
        "job_id": job_id,
        "status": job["status"],
        "message": job.get("message"),
        "agent_run_id": job.get("agent_run_id"),
        "agent_task_id": job.get("agent_task_id"),
        "result": job.get("result"),
    }
    agent_run_id = job.get("agent_run_id")
    if agent_run_id:
        with deps.db_session_factory(deps.db_engine) as db_session:
            spec_run = db_session.get(deps.agent_run_model, agent_run_id)
            if spec_run:
                response["agent_run"] = deps.serialize_agent_run(spec_run, db_session)
    return response


async def generate_report_item_spec_impl(
    run_id: str,
    item_id: str,
    *,
    item_type: str | None,
    project_id: str,
    request_body: GenerateReportItemSpecRequest | None,
    background_tasks: BackgroundTasks,
    session: Session,
    deps: AgentExploratoryDependencies | None = None,
) -> dict[str, Any]:
    """Generate a browser-backed spec from a custom agent finding or test idea."""
    import time as _time

    deps = _deps(deps)
    source_run = deps.get_agent_report_run(session, run_id, project_id)

    result = source_run.result or {}
    report = result.get("structured_report") if isinstance(result, dict) else None
    if not isinstance(report, dict):
        raise HTTPException(status_code=400, detail="This run does not have a structured report")

    normalized_type = (item_type or "").strip().lower()
    candidates: list[tuple[str, dict[str, Any]]] = []
    if normalized_type in ("", "finding", "findings"):
        candidates.extend(("finding", item) for item in report.get("findings") or [] if isinstance(item, dict))
    if normalized_type in ("", "test_idea", "test_ideas", "test idea"):
        candidates.extend(("test_idea", item) for item in report.get("test_ideas") or [] if isinstance(item, dict))

    matched = next(((kind, item) for kind, item in candidates if str(item.get("id")) == item_id), None)
    if not matched:
        raise HTTPException(status_code=404, detail=f"Report item {item_id} not found")

    kind, item = matched
    base_url = str(source_run.config.get("url") or "").strip()
    target_url = str(item.get("page") or base_url or "").strip()
    if not target_url:
        raise HTTPException(status_code=400, detail="This report item has no page URL to explore")

    title = str(item.get("title") or item_id)
    steps = item.get("steps") if isinstance(item.get("steps"), list) else []
    happy_path = "\n".join(str(step) for step in steps) if steps else str(item.get("description") or title)
    evidence = str(item.get("evidence") or item.get("expected") or "").strip()

    flow = {
        "id": item_id,
        "title": title,
        "entry_point": target_url,
        "exit_point": target_url,
        "pages": [target_url],
        "happy_path": happy_path,
        "edge_cases": [evidence] if evidence and kind == "finding" else [],
        "test_ideas": [evidence] if evidence and kind == "test_idea" else [f"Create a regression spec for {item_id}"],
    }

    _cleanup_flow_spec_jobs(deps)
    job_id = f"reportspec-{run_id}-{item_id}-{uuid.uuid4().hex[:8]}"
    spec_agent_run_id = job_id
    spec_run_dir = deps.runs_dir / spec_agent_run_id
    await asyncio.to_thread(spec_run_dir.mkdir, parents=True, exist_ok=True)
    flows_file = spec_run_dir / "source-flow.json"

    source_config = source_run.config or {}
    run_project_id = source_run.project_id or project_id or source_config.get("project_id")
    inherited_run_config = deps.build_spec_generation_source_config(
        source_config,
        target_url=base_url or target_url,
        project_id=run_project_id,
    )
    inherited_run_config, browser_auth_inherited = deps.apply_report_spec_browser_auth_request(
        inherited_run_config,
        request_body,
    )
    auth_metadata = deps.spec_generation_auth_metadata(inherited_run_config, inherited=browser_auth_inherited)
    spec_agent_run = deps.agent_run_model(
        id=spec_agent_run_id,
        agent_type="spec_generation",
        runtime="claude_sdk",
        status="running",
        started_at=datetime.utcnow(),
        project_id=run_project_id,
    )
    spec_agent_run.config = {
        "source": "custom_agent_report",
        "source_run_id": run_id,
        "source_item_id": item_id,
        "source_item_type": kind,
        "flow_title": title,
        "project_id": run_project_id,
        "url": target_url,
        "source_url": inherited_run_config.get("url"),
        "allowed_tools": [],
        **{key: inherited_run_config[key] for key in ("auth", "browser_auth") if key in inherited_run_config},
        **auth_metadata,
    }
    spec_agent_run.progress = {
        "phase": "queued",
        "status": "running",
        "message": "Starting Native Planner spec generation...",
        "has_browser_tools": True,
        **auth_metadata,
        "updated_at": datetime.utcnow().isoformat(),
    }
    session.add(spec_agent_run)
    session.commit()
    deps.record_agent_run_event(
        spec_agent_run_id,
        event_type="started",
        message="Started Native Planner spec generation.",
        payload={"source_run_id": run_id, "source_item_id": item_id, "source_item_type": kind},
        session=session,
    )

    deps.flow_spec_jobs[job_id] = {
        "status": "running",
        "message": "Starting spec generation...",
        "started_at": _time.time(),
        "run_id": run_id,
        "flow_id": item_id,
        "agent_run_id": spec_agent_run_id,
    }

    try:
        storage_state_path = deps.resolve_agent_browser_auth_storage_path(
            run_id=spec_agent_run_id,
            project_id=run_project_id,
            config=inherited_run_config,
            run_dir=spec_run_dir,
        )
        mcp_runtime = await asyncio.to_thread(
            deps.prepare_spec_generation_mcp_config,
            spec_run_dir,
            storage_state_path,
        )
        session.refresh(spec_agent_run)
        spec_agent_run.config = {
            **(spec_agent_run.config or {}),
            "allowed_tools": deps.get_agent_allowed_tools("playwright-test-planner", mcp_config_dir=spec_run_dir),
        }
        spec_agent_run.progress = {
            **(spec_agent_run.progress or {}),
            "phase": "queued",
            "status": "running",
            "message": "Starting Native Planner spec generation...",
            "has_browser_tools": True,
            **auth_metadata,
            **mcp_runtime,
            "updated_at": datetime.utcnow().isoformat(),
        }
        session.add(spec_agent_run)
        session.commit()
    except RuntimeError as exc:
        message = str(exc)
        failure_metadata: dict[str, Any] = {}
        if isinstance(exc, deps.agent_browser_auth_resolution_error):
            action_message = (
                "Selected browser auth session is revoked or invalid. "
                "Choose an active session or generate without auth."
            )
            failure_metadata = {
                "browser_auth_failure": True,
                "browser_auth_error": message,
                "message": action_message,
            }
            if exc.browser_auth_session_id:
                failure_metadata["browser_auth_session_id"] = exc.browser_auth_session_id
            message = action_message
        session.refresh(spec_agent_run)
        spec_agent_run.status = "failed"
        spec_agent_run.completed_at = datetime.utcnow()
        spec_agent_run.result = {
            "error": message,
            "source_run_id": run_id,
            "source_item_id": item_id,
            **failure_metadata,
        }
        spec_agent_run.progress = {
            **(spec_agent_run.progress or {}),
            "phase": "failed",
            "status": "failed",
            "message": message,
            "has_browser_tools": True,
            **auth_metadata,
            **failure_metadata,
            "updated_at": datetime.utcnow().isoformat(),
        }
        session.add(spec_agent_run)
        session.commit()
        deps.flow_spec_jobs[job_id].update({"status": "failed", "message": message, "completed_at": _time.time()})
        deps.record_agent_run_event(
            spec_agent_run_id,
            event_type="failed",
            level="error",
            message=message,
            payload={"source_run_id": run_id, "source_item_id": item_id, "source_item_type": kind},
            session=session,
        )
        return {
            "status": "failed",
            "job_id": job_id,
            "agent_run_id": spec_agent_run_id,
            "message": message,
        }

    background_tasks.add_task(
        deps.run_flow_spec_generation,
        job_id=job_id,
        run_id=run_id,
        flow_id=item_id,
        flow=flow,
        flows=[flow],
        flows_file_path=str(flows_file),
        run_project_id=run_project_id,
        run_config=inherited_run_config,
        spec_agent_run_id=spec_agent_run_id,
    )

    return {
        "status": "running",
        "job_id": job_id,
        "agent_run_id": spec_agent_run_id,
        "message": "Spec generation started. Poll for status.",
    }


async def generate_flow_test_impl(
    run_id: str,
    flow_id: str,
    *,
    force_regenerate: bool = False,
    project_id: str | None,
    request_body: GenerateFlowTestRequest | None,
    background_tasks: BackgroundTasks,
    session: Session,
    deps: AgentExploratoryDependencies | None = None,
) -> dict[str, Any]:
    """Generate a validated test for a flow using Native Planner + Generator pipeline."""
    import time as _time

    deps = _deps(deps)
    _verify_exploration_run_project(run_id, project_id, session, deps)
    flows_file = deps.runs_dir / run_id / "flows.json"

    if not await asyncio.to_thread(flows_file.exists):
        raise HTTPException(status_code=404, detail=f"Flows file not found for run {run_id}")

    try:
        raw = await asyncio.to_thread(flows_file.read_text)
        data = json.loads(raw)
        flows = data.get("flows", [])

        exploration_run = session.get(deps.agent_run_model, run_id)
        run_config = json.loads(exploration_run.config_json) if exploration_run and exploration_run.config_json else {}
        run_project_id = exploration_run.project_id or project_id or run_config.get("project_id")

        flow, _ = _flow_by_id(flows, flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail=f"Flow {flow_id} not found")

        inherited_run_config = deps.build_spec_generation_source_config(
            run_config,
            target_url=flow.get("entry_point") or "",
            project_id=run_project_id,
        )
        inherited_run_config, _ = deps.apply_report_spec_browser_auth_request(inherited_run_config, request_body)

        if not force_regenerate and "generated_test" in flow:
            cached = flow["generated_test"]
            spec_file = cached.get("spec_file")
            if spec_file and Path(spec_file).exists():
                return {
                    "status": "success",
                    "cached": True,
                    "spec_file": spec_file,
                    "spec_content": cached.get("spec_content"),
                    "test_file": cached.get("test_file"),
                    "test_code": cached.get("test_code"),
                    "validated": cached.get("validated", False),
                    "flow_title": flow.get("title", "Unnamed Flow"),
                    "requires_auth": cached.get("requires_auth", False),
                    "pipeline": cached.get("pipeline", "native_planner_generator"),
                    "generated_at": cached.get("generated_at"),
                }

        _cleanup_flow_spec_jobs(deps)
        job_id = f"flowspec-{run_id}-{flow_id}-{uuid.uuid4().hex[:8]}"
        spec_agent_run_id = job_id
        spec_run_dir = deps.runs_dir / spec_agent_run_id
        await asyncio.to_thread(spec_run_dir.mkdir, parents=True, exist_ok=True)
        auth_metadata = deps.spec_generation_auth_metadata(inherited_run_config)
        spec_agent_run = deps.agent_run_model(
            id=spec_agent_run_id,
            agent_type="spec_generation",
            runtime="claude_sdk",
            status="running",
            started_at=datetime.utcnow(),
            project_id=run_project_id,
        )
        spec_agent_run.config = {
            "source": "exploratory_flow",
            "source_run_id": run_id,
            "source_flow_id": flow_id,
            "flow_title": flow.get("title", "Unnamed Flow"),
            "project_id": run_project_id,
            "url": flow.get("entry_point") or inherited_run_config.get("url"),
            "source_url": inherited_run_config.get("url"),
            "allowed_tools": [],
            **{key: inherited_run_config[key] for key in ("auth", "browser_auth") if key in inherited_run_config},
            **auth_metadata,
        }
        spec_agent_run.progress = {
            "phase": "queued",
            "status": "running",
            "message": "Starting Native Planner spec generation...",
            "has_browser_tools": True,
            **auth_metadata,
            "updated_at": datetime.utcnow().isoformat(),
        }
        session.add(spec_agent_run)
        session.commit()
        deps.record_agent_run_event(
            spec_agent_run_id,
            event_type="started",
            message="Started Native Planner spec generation.",
            payload={"source_run_id": run_id, "source_flow_id": flow_id, "flow_title": flow.get("title")},
            session=session,
        )

        deps.flow_spec_jobs[job_id] = {
            "status": "running",
            "message": "Starting spec generation...",
            "started_at": _time.time(),
            "run_id": run_id,
            "flow_id": flow_id,
            "agent_run_id": spec_agent_run_id,
        }

        try:
            storage_state_path = deps.resolve_agent_browser_auth_storage_path(
                run_id=spec_agent_run_id,
                project_id=run_project_id,
                config=inherited_run_config,
                run_dir=spec_run_dir,
            )
            mcp_runtime = await asyncio.to_thread(
                deps.prepare_spec_generation_mcp_config,
                spec_run_dir,
                storage_state_path,
            )
            session.refresh(spec_agent_run)
            spec_agent_run.config = {
                **(spec_agent_run.config or {}),
                "allowed_tools": deps.get_agent_allowed_tools("playwright-test-planner", mcp_config_dir=spec_run_dir),
            }
            spec_agent_run.progress = {
                **(spec_agent_run.progress or {}),
                "phase": "queued",
                "status": "running",
                "message": "Starting Native Planner spec generation...",
                "has_browser_tools": True,
                **auth_metadata,
                **mcp_runtime,
                "updated_at": datetime.utcnow().isoformat(),
            }
            session.add(spec_agent_run)
            session.commit()
        except RuntimeError as exc:
            message = str(exc)
            session.refresh(spec_agent_run)
            spec_agent_run.status = "failed"
            spec_agent_run.completed_at = datetime.utcnow()
            spec_agent_run.result = {"error": message, "source_run_id": run_id, "source_flow_id": flow_id}
            spec_agent_run.progress = {
                **(spec_agent_run.progress or {}),
                "phase": "failed",
                "status": "failed",
                "message": message,
                "has_browser_tools": True,
                **auth_metadata,
                "updated_at": datetime.utcnow().isoformat(),
            }
            session.add(spec_agent_run)
            session.commit()
            deps.flow_spec_jobs[job_id].update({"status": "failed", "message": message, "completed_at": _time.time()})
            deps.record_agent_run_event(
                spec_agent_run_id,
                event_type="failed",
                level="error",
                message=message,
                payload={"source_run_id": run_id, "source_flow_id": flow_id, "flow_title": flow.get("title")},
                session=session,
            )
            return {
                "status": "failed",
                "job_id": job_id,
                "agent_run_id": spec_agent_run_id,
                "message": message,
            }

        background_tasks.add_task(
            deps.run_flow_spec_generation,
            job_id=job_id,
            run_id=run_id,
            flow_id=flow_id,
            flow=flow,
            flows=flows,
            flows_file_path=str(flows_file),
            run_project_id=run_project_id,
            run_config=inherited_run_config,
            spec_agent_run_id=spec_agent_run_id,
        )

        return {
            "status": "running",
            "job_id": job_id,
            "agent_run_id": spec_agent_run_id,
            "message": "Spec generation started. Poll for status.",
        }
    except HTTPException:
        raise
    except Exception as e:
        _log(deps).error(f"Error generating test: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/api/agents/exploratory")
async def run_exploratory_agent(
    request: ExploratoryRunRequest,
    session: Session = Depends(get_session),
):
    return await run_exploratory_agent_impl(request, session=session, deps=_deps())


@router.post("/api/agents/exploratory/{run_id}/synthesize")
async def synthesize_specs(run_id: str, session: Session = Depends(get_session)):
    return await synthesize_specs_impl(run_id, session=session, deps=_deps())


@router.get("/api/agents/exploratory/{run_id}/specs")
async def get_exploration_specs(
    run_id: str,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    return await get_exploration_specs_impl(run_id, project_id=project_id, session=session, deps=_deps())


@router.get("/api/agents/exploratory/{run_id}/flows/{flow_id}")
async def get_flow_details(
    run_id: str,
    flow_id: str,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    return await get_flow_details_impl(run_id, flow_id, project_id=project_id, session=session, deps=_deps())


@router.put("/api/agents/exploratory/{run_id}/flows/{flow_id}")
async def update_flow(
    run_id: str,
    flow_id: str,
    request: FlowUpdateRequest,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    return await update_flow_impl(run_id, flow_id, request, project_id=project_id, session=session, deps=_deps())


@router.delete("/api/agents/exploratory/{run_id}/flows/{flow_id}")
async def delete_flow(
    run_id: str,
    flow_id: str,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    return await delete_flow_impl(run_id, flow_id, project_id=project_id, session=session, deps=_deps())


@router.post("/api/agents/exploratory/{run_id}/analyze-prerequisites")
async def analyze_prerequisites(
    run_id: str,
    force_reanalyze: bool = False,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    return await analyze_prerequisites_impl(
        run_id,
        force_reanalyze=force_reanalyze,
        project_id=project_id,
        session=session,
        deps=_deps(),
    )


@router.post("/api/agents/exploratory/{run_id}/flows/{flow_id}/spec")
async def generate_flow_spec(
    run_id: str,
    flow_id: str,
    force_regenerate: bool = False,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    return await generate_flow_spec_impl(
        run_id,
        flow_id,
        force_regenerate=force_regenerate,
        project_id=project_id,
        session=session,
        deps=_deps(),
    )


@router.get("/api/agents/exploratory/flow-spec-jobs/{job_id}")
async def get_flow_spec_job_status(job_id: str):
    return await get_flow_spec_job_status_impl(job_id, deps=_deps())


@router.post("/api/agents/runs/{run_id}/report-items/{item_id}/generate-spec")
async def generate_report_item_spec(
    run_id: str,
    item_id: str,
    item_type: str | None = Query(default=None, description="finding or test_idea"),
    project_id: str = Query(..., description="Project ID for verification"),
    request_body: GenerateReportItemSpecRequest | None = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: Session = Depends(get_session),
):
    return await generate_report_item_spec_impl(
        run_id,
        item_id,
        item_type=item_type,
        project_id=project_id,
        request_body=request_body,
        background_tasks=background_tasks,
        session=session,
        deps=_deps(),
    )


@router.post("/api/agents/exploratory/{run_id}/flows/{flow_id}/generate")
async def generate_flow_test(
    run_id: str,
    flow_id: str,
    force_regenerate: bool = False,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    request_body: GenerateFlowTestRequest | None = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: Session = Depends(get_session),
):
    return await generate_flow_test_impl(
        run_id,
        flow_id,
        force_regenerate=force_regenerate,
        project_id=project_id,
        request_body=request_body,
        background_tasks=background_tasks,
        session=session,
        deps=_deps(),
    )
