"""Browser handoff, lease, and observation helpers for autonomous work items."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from orchestrator.api.models_db import AutonomousAgentWorkItem, AutonomousMission
from orchestrator.services import autonomous_activities as facade
from orchestrator.services import autonomous_shared as shared
from orchestrator.services.browser_auth_sessions import BrowserAuthSessionError, resolve_browser_auth_for_run


def _safe_model_attr(model: Any, attr: str, default: Any = None) -> Any:
    data = getattr(model, "__dict__", {}) or {}
    if attr in data:
        return data[attr]
    try:
        return getattr(model, attr)
    except Exception:
        pass
    try:
        from sqlalchemy import inspect as sqlalchemy_inspect

        inspected = sqlalchemy_inspect(model)
        key_names = [column.key for column in inspected.mapper.primary_key]
        if attr in key_names and inspected.identity:
            return inspected.identity[key_names.index(attr)]
    except Exception:
        return default
    return default


def _browser_owner_metadata(
    mission: AutonomousMission,
    item: AutonomousAgentWorkItem,
    *,
    handoff_id: str | None = None,
    child_agent_id: str | None = None,
) -> dict[str, Any]:
    item_id = facade._safe_model_attr(item, "id")
    return {
        "mission_id": facade._safe_model_attr(mission, "id"),
        "run_id": facade._safe_model_attr(item, "run_id"),
        "work_item_id": item_id,
        "child_agent_id": child_agent_id,
        "handoff_id": handoff_id or item_id,
        "role": facade._safe_model_attr(item, "role"),
        "recorded_at": shared._utcnow().isoformat(),
    }


def _tool_call_browser_action(tool_call: Any) -> dict[str, Any] | None:
    name = facade._short_tool_name(getattr(tool_call, "name", None))
    if not name.startswith("browser_"):
        return None
    raw_input = getattr(tool_call, "input", None)
    tool_input = raw_input if isinstance(raw_input, dict) else {}
    action_type = name.removeprefix("browser_")
    target = (
        tool_input.get("url")
        or tool_input.get("target")
        or tool_input.get("element")
        or tool_input.get("text")
        or tool_input.get("key")
        or tool_input.get("function")
    )
    action = {
        "action": "navigate" if name == "browser_navigate" else action_type,
        "target": str(target or name),
        "outcome": "ok" if getattr(tool_call, "success", True) else "failed",
    }
    if getattr(tool_call, "duration_ms", None) is not None:
        action["duration_ms"] = tool_call.duration_ms
    return action


def _snapshot_lines_from_app_map(update: dict[str, Any]) -> str:
    lines: list[str] = []
    elements = update.get("elements") or {}
    if isinstance(elements, dict):
        for role, values in elements.items():
            for value in facade._as_list(values)[:20]:
                if isinstance(value, dict):
                    name = value.get("name") or value.get("text") or value.get("label") or role
                else:
                    name = value
                if str(name or "").strip():
                    lines.append(f'- {str(role).lower()} "{str(name).strip()[:120]}"')
    forms = update.get("forms") or []
    for form in facade._as_list(forms)[:10]:
        if isinstance(form, dict):
            name = form.get("name") or form.get("action") or form.get("label") or "form"
            lines.append(f'- form "{str(name).strip()[:120]}"')
    return "\n".join(lines)


def _attach_browser_owner_metadata(
    *,
    project_id: str | None,
    session_id: str,
    owner_metadata: dict[str, Any],
) -> None:
    if not project_id:
        return
    try:
        from orchestrator.api.models_db import BrowserElement, BrowserPageState

        with Session(facade.engine) as db:
            states = db.exec(
                select(BrowserPageState).where(
                    BrowserPageState.project_id == project_id,
                    BrowserPageState.session_id == session_id,
                )
            ).all()
            for state in states:
                canonical = dict(state.canonical_json or {})
                canonical["owner_metadata"] = owner_metadata
                state.canonical_json = canonical
                db.add(state)
                elements = db.exec(
                    select(BrowserElement).where(
                        BrowserElement.project_id == project_id,
                        BrowserElement.state_id == state.id,
                    )
                ).all()
                for element in elements:
                    attrs = dict(element.attributes_json or {})
                    attrs["owner_metadata"] = owner_metadata
                    element.attributes_json = attrs
                    db.add(element)
            if states:
                db.commit()
    except Exception:
        facade.logger.debug("Unable to attach browser owner metadata.", exc_info=True)


def _record_browser_observations_for_work_item(
    *,
    mission: AutonomousMission,
    item: AutonomousAgentWorkItem,
    result: Any,
    browser_handoff: dict[str, Any] | None,
) -> dict[str, Any]:
    project_id = facade._safe_model_attr(mission, "project_id") or facade._safe_model_attr(item, "project_id")
    mission_id = facade._safe_model_attr(mission, "id") or facade._safe_model_attr(item, "mission_id")
    item_id = facade._safe_model_attr(item, "id")
    if not project_id and mission_id:
        try:
            with Session(facade.engine) as db:
                db_mission = db.get(AutonomousMission, mission_id)
                project_id = db_mission.project_id if db_mission else None
        except Exception:
            facade.logger.debug("Unable to rehydrate autonomous mission project.", exc_info=True)
    if not project_id:
        return {"states": 0, "transitions": 0, "app_map_states": 0}
    session_id = f"autonomous:{mission_id}:{item_id}"
    owner_metadata = facade._browser_owner_metadata(
        mission,
        item,
        handoff_id=(browser_handoff or {}).get("mcp_config_path") or item_id,
    )
    summary = {"states": 0, "transitions": 0, "app_map_states": 0, "session_id": session_id}
    try:
        from orchestrator.memory.browser_memory import get_exploration_memory_service

        memory = get_exploration_memory_service(project_id=project_id)
        action_trace = [
            action
            for action in (
                facade._tool_call_browser_action(tool_call) for tool_call in (getattr(result, "tool_calls", []) or [])
            )
            if action
        ]
        if action_trace:
            try:
                seeded = memory.seed_from_action_trace(
                    session_id=session_id,
                    entry_url=str((browser_handoff or {}).get("start_url") or facade._default_target_url(mission)),
                    action_trace=action_trace,
                )
                summary["states"] += int(seeded.get("states", 0) or 0)
                summary["transitions"] += int(seeded.get("transitions", 0) or 0)
            except Exception:
                facade.logger.debug("Unable to seed autonomous browser action trace.", exc_info=True)

        structured = facade._extract_structured_agent_output(getattr(result, "output", "") or "") or {}
        for update in structured.get("app_map_updates") or []:
            if not isinstance(update, dict) or not update.get("url"):
                continue
            memory.upsert_page_state(
                session_id=session_id,
                url=str(update.get("url")),
                title=str(update.get("page_title") or update.get("url")),
                snapshot_text=facade._snapshot_lines_from_app_map(update),
                snapshot_ref=f"autonomous:{item.id}",
                source_fidelity="autonomous_agent_observation",
            )
            summary["states"] += 1
            summary["app_map_states"] += 1

        if summary["states"] or summary["app_map_states"]:
            facade._attach_browser_owner_metadata(
                project_id=project_id,
                session_id=session_id,
                owner_metadata=owner_metadata,
            )
    except Exception:
        facade.logger.debug("Unable to record autonomous browser observations.", exc_info=True)
    return summary


def _allowed_tools_for_work_item(
    item: AutonomousAgentWorkItem,
    *,
    mcp_config_dir: Path | str | None = None,
) -> list[str]:
    try:
        from orchestrator.utils.agent_tool_allowlists import get_agent_allowed_tools

        allowed = get_agent_allowed_tools(item.role, mcp_config_dir=mcp_config_dir)
        if allowed:
            return allowed
    except Exception:
        facade.logger.debug("Could not resolve autonomous role tool profile for %s", item.role, exc_info=True)
    return ["Glob", "Grep", "Read", "LS"]


def _short_tool_name(tool_name: str | None) -> str:
    if not tool_name:
        return "tool"
    text = str(tool_name)
    if "__" in text:
        return text.split("__")[-1]
    return text


def _is_browser_tool(tool_name: str | None) -> bool:
    short_name = facade._short_tool_name(tool_name)
    text = str(tool_name or "")
    return short_name.startswith("browser_") or "__browser_" in text


def _browser_action_names(allowed_tools: list[str]) -> list[str]:
    actions: list[str] = []
    for tool in allowed_tools:
        short_name = facade._short_tool_name(tool)
        if short_name.startswith("browser_") and short_name not in actions:
            actions.append(short_name)
    return actions or list(shared.DEFAULT_BROWSER_ACTIONS)


def _state_hash_from_browser_contract(contract: dict[str, Any] | None) -> str | None:
    if not contract:
        return None
    basis = {
        "url": contract.get("last_known_url") or contract.get("start_url"),
        "title": contract.get("last_known_title"),
        "snapshot_summary": contract.get("snapshot_summary"),
        "browser_memory_state_ids": contract.get("browser_memory_state_ids") or [],
        "frontier_item_ids": contract.get("frontier_item_ids") or [],
    }
    if not any(basis.values()):
        return None
    return hashlib.sha256(json.dumps(basis, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:24]


def _browser_lease_for_handoff(
    *,
    owner_id: str,
    mode: str,
    timeout_seconds: int,
    contract: dict[str, Any],
    owner_type: str = "autonomous_work_item",
) -> dict[str, Any]:
    safe_mode = mode if mode in shared.BROWSER_LEASE_MODES else "isolated"
    now = shared._utcnow()
    last_snapshot_at = contract.get("last_snapshot_at") or contract.get("live_snapshot_at")
    return {
        "owner_type": owner_type,
        "owner_id": owner_id,
        "mode": safe_mode,
        "lease_timeout_seconds": max(30, int(timeout_seconds or 0)),
        "lease_until": (now + timedelta(seconds=max(30, int(timeout_seconds or 0)))).isoformat(),
        "heartbeat_at": now.isoformat(),
        "current_url": contract.get("last_known_url") or contract.get("start_url"),
        "page_state_hash": facade._state_hash_from_browser_contract(contract),
        "last_snapshot_at": last_snapshot_at,
    }


def _browser_contract_memory_context(mission: AutonomousMission, item: AutonomousAgentWorkItem) -> dict[str, Any]:
    context: dict[str, Any] = {
        "states": [],
        "frontier": [],
        "snapshot_summary": None,
        "last_known_url": None,
        "last_known_title": None,
        "omitted": {"states": 0, "frontier": 0},
    }
    if not mission.project_id:
        return context
    try:
        from orchestrator.memory.browser_memory import get_exploration_memory_service

        service = get_exploration_memory_service(project_id=mission.project_id)
        bundle = service.get_memory_bundle(query=item.objective, limit=5)
        states = bundle.get("states") or []
        frontier = bundle.get("frontier") or []
        context["states"] = states[:3]
        context["frontier"] = frontier[:5]
        context["omitted"] = {
            "states": max(0, len(states) - len(context["states"])),
            "frontier": max(0, len(frontier) - len(context["frontier"])),
        }
        if context["states"]:
            latest = context["states"][0]
            context["last_known_url"] = latest.get("url")
            context["last_known_title"] = latest.get("title")
            context["snapshot_summary"] = (
                f"Latest durable browser memory state {latest.get('id')} at "
                f"{latest.get('url') or 'unknown URL'} last seen {latest.get('last_seen_at') or 'unknown time'}."
            )
    except Exception:
        facade.logger.debug("Unable to build browser handoff memory context.", exc_info=True)
    return context


def _browser_context_handoff(
    *,
    mission: AutonomousMission,
    item: AutonomousAgentWorkItem,
    run_dir: Path,
    runtime: dict[str, Any],
    allowed_tools: list[str],
    mode: str = "isolated",
    storage_state_path: Path | str | None = None,
    auth_session_id: str | None = None,
    auth_session_name: str | None = None,
) -> dict[str, Any]:
    memory_context = facade._browser_contract_memory_context(mission, item)
    start_url = (item.assigned_surface or mission.target_urls or [facade._default_target_url(mission)])[0]
    expected_url_pattern = str((mission.config or {}).get("expected_url_pattern") or start_url or ".*")
    contract = {
        "contract_type": "BrowserContextHandoff",
        "run_dir": str(run_dir),
        "mcp_config_path": str(runtime.get("mcp_config_path") or run_dir / ".mcp.json"),
        "storage_state_attached": bool(storage_state_path),
        "auth_session_id": auth_session_id,
        "auth_session_name": auth_session_name,
        "start_url": start_url,
        "expected_url_pattern": expected_url_pattern,
        "last_known_url": memory_context.get("last_known_url") or start_url,
        "last_known_title": memory_context.get("last_known_title"),
        "snapshot_summary": memory_context.get("snapshot_summary")
        or "No live snapshot has been captured for this handoff yet.",
        "browser_memory_state_ids": [
            str(state.get("id")) for state in (memory_context.get("states") or []) if state.get("id")
        ],
        "frontier_item_ids": [
            str(frontier.get("id")) for frontier in (memory_context.get("frontier") or []) if frontier.get("id")
        ],
        "risk_level": str((mission.config or {}).get("browser_risk_level") or "medium"),
        "allowed_browser_actions": facade._browser_action_names(allowed_tools),
        "handoff_mode": mode if mode in shared.BROWSER_LEASE_MODES else "isolated",
        "omitted_browser_memory": memory_context.get("omitted") or {"states": 0, "frontier": 0},
    }
    contract["browser_lease"] = facade._browser_lease_for_handoff(
        owner_id=item.id,
        mode=contract["handoff_mode"],
        timeout_seconds=max(300, min(mission.max_runtime_minutes * 60, 7200)),
        contract=contract,
    )
    return contract


def _assert_browser_lease_available(
    session: Session,
    *,
    mission_id: str,
    requested_owner_id: str,
    mode: str,
) -> None:
    if mode == "isolated":
        return
    now = shared._utcnow()
    running_items = session.exec(
        select(AutonomousAgentWorkItem).where(
            AutonomousAgentWorkItem.mission_id == mission_id,
            AutonomousAgentWorkItem.status == "running",
        )
    ).all()
    for running in running_items:
        if running.id == requested_owner_id:
            continue
        lease = (running.progress or {}).get("browser_context_handoff", {}).get("browser_lease", {})
        if not isinstance(lease, dict) or lease.get("mode") in {None, "isolated", "read_only_snapshot"}:
            continue
        try:
            lease_until = datetime.fromisoformat(str(lease.get("lease_until")))
        except (TypeError, ValueError):
            lease_until = running.lease_until
        if lease_until and lease_until > now:
            raise RuntimeError(
                f"Browser lease conflict: work item {running.id} already owns a {lease.get('mode')} browser lease."
            )


def _validate_browser_handoff_mode(
    item: AutonomousAgentWorkItem,
    *,
    mode: str,
    max_snapshot_age_seconds: int = 300,
) -> None:
    if mode != "sequential_handoff":
        return
    existing = (item.progress or {}).get("browser_context_handoff", {})
    if not isinstance(existing, dict):
        existing = {}
    lease = existing.get("browser_lease") if isinstance(existing.get("browser_lease"), dict) else {}
    snapshot_at = lease.get("last_snapshot_at") or existing.get("last_snapshot_at")
    if not snapshot_at:
        raise RuntimeError("Sequential browser handoff requires a recent browser_snapshot in work-item progress.")
    try:
        snapshot_dt = datetime.fromisoformat(str(snapshot_at))
    except ValueError as exc:
        raise RuntimeError("Sequential browser handoff has an invalid browser_snapshot timestamp.") from exc
    if shared._utcnow() - snapshot_dt.replace(tzinfo=None) > timedelta(seconds=max_snapshot_age_seconds):
        raise RuntimeError("Sequential browser handoff requires a browser_snapshot captured within the last 5 minutes.")


def _child_browser_run_dir(mission: AutonomousMission, item: AutonomousAgentWorkItem, child_id: str) -> Path:
    return facade._autonomous_work_item_run_dir(mission, item) / "children" / child_id


def _prepare_child_browser_handoffs(
    *,
    mission: AutonomousMission,
    item: AutonomousAgentWorkItem,
    allowed_tools: list[str],
    parent_auth_session_id: str | None,
    parent_auth_session_name: str | None,
    max_children: int,
) -> list[dict[str, Any]]:
    if max_children <= 0:
        return []
    handoffs: list[dict[str, Any]] = []
    try:
        from orchestrator.utils.playwright_mcp import write_playwright_mcp_config
    except Exception:
        facade.logger.debug("Could not import Playwright MCP helper for child browser handoffs.", exc_info=True)
        return handoffs

    for index in range(max_children):
        child_id = f"child-{index + 1}"
        child_run_dir = facade._child_browser_run_dir(mission, item, child_id)
        child_run_dir.mkdir(parents=True, exist_ok=True)
        storage_state_path = None
        if parent_auth_session_id or (mission.config or {}).get("use_project_default_browser_auth"):
            try:
                with Session(facade.engine) as db_session:
                    resolved = resolve_browser_auth_for_run(
                        db_session,
                        mission.project_id,
                        run_dir=child_run_dir,
                        browser_auth_session_id=parent_auth_session_id,
                        use_default=bool((mission.config or {}).get("use_project_default_browser_auth")),
                    )
                storage_state_path = resolved.storage_state_path if resolved else None
            except BrowserAuthSessionError:
                facade.logger.debug("Could not attach browser auth storage state for child handoff.", exc_info=True)
        runtime = write_playwright_mcp_config(
            run_dir=child_run_dir,
            server_name="playwright",
            project_root=facade.REPOSITORY_ROOT,
            storage_state_path=storage_state_path,
        )
        child_allowed_tools = facade._allowed_tools_for_work_item(item, mcp_config_dir=child_run_dir)
        contract = facade._browser_context_handoff(
            mission=mission,
            item=item,
            run_dir=child_run_dir,
            runtime=runtime,
            allowed_tools=child_allowed_tools,
            mode="isolated",
            storage_state_path=storage_state_path,
            auth_session_id=parent_auth_session_id,
            auth_session_name=parent_auth_session_name,
        )
        contract.update(
            {
                "child_agent_id": child_id,
                "parent_work_item_id": item.id,
                "allowed_tools": child_allowed_tools,
                "strict_mcp_config": True,
                "required_first_browser_action": (
                    f"Call browser_navigate to {contract['start_url']}, then call browser_snapshot before interaction."
                ),
            }
        )
        facade._validate_child_browser_handoff_contract(contract)
        handoffs.append(contract)
    return handoffs


def _validate_child_browser_handoff_contract(contract: dict[str, Any]) -> None:
    if contract.get("handoff_mode") != "isolated":
        raise RuntimeError("Child browser handoff must use isolated mode.")
    mcp_config_path = Path(str(contract.get("mcp_config_path") or ""))
    if not mcp_config_path.exists():
        raise RuntimeError("Child browser handoff requires an isolated MCP config.")
    allowed = {facade._short_tool_name(tool) for tool in facade._as_text_list(contract.get("allowed_tools"))}
    missing = sorted({"browser_navigate", "browser_snapshot"} - allowed)
    if missing:
        raise RuntimeError(f"Child browser handoff missing required browser tools: {', '.join(missing)}")
    first_action = str(contract.get("required_first_browser_action") or "")
    if "browser_navigate" not in first_action or "browser_snapshot" not in first_action:
        raise RuntimeError("Child browser handoff must require navigate and snapshot evidence first.")


def _autonomous_work_item_run_dir(mission: AutonomousMission, item: AutonomousAgentWorkItem) -> Path:
    return facade.RUNS_DIR / "autonomous" / mission.id / item.id


def _prepare_autonomous_work_item_runtime(
    mission: AutonomousMission, item: AutonomousAgentWorkItem
) -> tuple[Path, dict[str, Any]]:
    run_dir = facade._autonomous_work_item_run_dir(mission, item)
    run_dir.mkdir(parents=True, exist_ok=True)
    runtime: dict[str, Any] = {}
    try:
        from orchestrator.utils.playwright_mcp import browser_runtime_status, write_playwright_mcp_config

        mission_config = mission.config
        storage_state_path = None
        auth_session_id = None
        auth_session_name = None
        if mission_config.get("browser_auth_session_id") or mission_config.get("use_project_default_browser_auth"):
            try:
                with Session(facade.engine) as db_session:
                    resolved = resolve_browser_auth_for_run(
                        db_session,
                        mission.project_id,
                        run_dir=run_dir,
                        browser_auth_session_id=mission_config.get("browser_auth_session_id"),
                        use_default=bool(mission_config.get("use_project_default_browser_auth")),
                    )
                storage_state_path = resolved.storage_state_path if resolved else None
                auth_session_id = resolved.session_id if resolved else None
                auth_session_name = resolved.session_name if resolved else None
            except BrowserAuthSessionError as exc:
                raise RuntimeError(f"{exc}. Refresh browser auth session.") from exc
        runtime = write_playwright_mcp_config(
            run_dir=run_dir,
            server_name="playwright",
            project_root=facade.REPOSITORY_ROOT,
            storage_state_path=storage_state_path,
        )
        runtime = {
            **runtime,
            **browser_runtime_status(),
            "storage_state_attached": bool(storage_state_path),
            "storage_state_path": str(storage_state_path) if storage_state_path else None,
            "auth_session_id": auth_session_id,
            "auth_session_name": auth_session_name,
        }
    except RuntimeError:
        raise
    except Exception:
        facade.logger.debug("Could not prepare autonomous work item browser runtime", exc_info=True)
    return run_dir, runtime
