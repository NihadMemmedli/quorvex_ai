"""Prompt and context builders for autonomous work items."""

from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session, col, select

from orchestrator.api.models_db import AutonomousAgentWorkItem, AutonomousMission, AutonomousTestProposal, Requirement
from orchestrator.services import autonomous_activities as facade


def _autonomous_test_data_execution_context(mission: AutonomousMission) -> dict[str, Any]:
    config = mission.config or {}
    refs = config.get("test_data_refs") if isinstance(config.get("test_data_refs"), list) else []
    markdown = "\n".join(
        [
            mission.name or "",
            json.dumps(config, default=str),
            "\n".join(mission.target_urls or []),
        ]
    )
    try:
        from orchestrator.services.test_data_resolver import resolve_test_data_execution_context

        with Session(facade.engine) as session:
            return resolve_test_data_execution_context(
                session,
                project_id=mission.project_id or "default",
                refs=[str(ref) for ref in refs],
                markdown=markdown,
            )
    except Exception:
        facade.logger.debug("Unable to resolve autonomous mission test data.", exc_info=True)
        return {}


def _agent_prompt_for_work_item(
    mission: AutonomousMission,
    item: AutonomousAgentWorkItem,
    test_data_context: dict[str, Any] | None = None,
    browser_handoff: dict[str, Any] | None = None,
    child_browser_handoffs: list[dict[str, Any]] | None = None,
) -> str:
    surfaces = item.assigned_surface or mission.target_urls
    revision_context = item.progress or {}
    context_bundle = facade._work_item_context_bundle(mission, item, omit_browser_memory=bool(browser_handoff))
    test_data_context = test_data_context or facade._autonomous_test_data_execution_context(mission)
    context_note = ""
    if context_bundle:
        context_note = f"""
Canonical context bundle:
{facade._compact_json(context_bundle, max_chars=7000)}
"""
    browser_note = ""
    if browser_handoff:
        child_contracts = child_browser_handoffs or []
        first_action = "None required."
        if browser_handoff.get("handoff_mode") != "sequential_handoff":
            first_action = (
                f"Call browser_navigate to {browser_handoff.get('start_url')}, "
                "then call browser_snapshot before interacting."
            )
        browser_note = f"""
Current Browser Contract:
{facade._compact_json(browser_handoff, max_chars=4500)}

Known Browser Memory:
- state ids: {", ".join(browser_handoff.get("browser_memory_state_ids") or []) or "none"}
- frontier item ids: {", ".join(browser_handoff.get("frontier_item_ids") or []) or "none"}
- omitted: {facade._compact_json(browser_handoff.get("omitted_browser_memory") or {{}}, max_chars=600)}

Required First Browser Action:
{first_action}

State Validation Rules:
- Call browser_snapshot before the first browser interaction.
- After navigation, dialog handling, form submission, or any state-changing click, call browser_snapshot again.
- If browser memory conflicts with the live snapshot, treat browser memory as stale and prefer the live snapshot.
- Close the browser when done if browser_close is available.
- Do not delegate browser work unless the child receives one of the BrowserContextHandoff packets below.
- Parallel browser subagents must use isolated mode with their own run_dir and mcp_config_path.

BrowserContextHandoff packets available for isolated child agents:
{facade._compact_json(child_contracts, max_chars=5000) if child_contracts else "[]"}
"""
    test_data_note = ""
    if test_data_context.get("prompt_markdown"):
        test_data_note = f"""
{test_data_context["prompt_markdown"]}

When delegating to subagents, copy the relevant test-data ref names and plaintext values needed for execution into each delegated prompt. Subagents do not automatically inherit this full parent context.
"""
    revision_note = ""
    if revision_context.get("revision_of_work_item_id"):
        revision_note = f"""
Revision request:
- revise work item: {revision_context.get("revision_of_work_item_id")}
- reviewer work item: {revision_context.get("reviewer_work_item_id") or "human/manual review"}
- reviewer reason: {revision_context.get("review_reason") or "No reason provided"}
- revision attempt: {revision_context.get("revision_attempt") or 1}
Address the reviewer feedback directly and explain what changed from the prior output.
"""
    return f"""You are the {item.role} agent in a Quorvex autonomous QA team.

Mission: {mission.name}
Objective: {item.objective}
Target surfaces: {", ".join(surfaces or ["project data and known app artifacts"])}
{context_note}
{browser_note}
{test_data_note}
{revision_note}

Work only by inspecting the app/project through available tools. Do not write repository files.
Return JSON only, preferably in a ```json fenced block, with this exact top-level shape:
{{
  "summary": "short factual summary",
  "requirements": [
    {{
      "title": "requirement title",
      "description": "what the product should do",
      "category": "authentication|navigation|crud|validation|checkout|other",
      "priority": "low|medium|high|critical",
      "acceptance_criteria": ["observable criterion"],
      "evidence": {{"url": "observed URL if any", "selector": "observed selector/text if any", "source": "browser_snapshot|test_run|memory|file"}},
      "evidence_refs": ["artifact, snapshot, URL, selector, or source IDs"],
      "truth_state": "candidate_requirement",
      "confidence": 0.0,
      "uncertainty_reason": "why this is candidate/uncertain"
    }}
  ],
  "rtm_candidates": [
    {{
      "requirement_id": 0,
      "requirement_code": "REQ-001",
      "test_spec_name": "existing-or-proposed spec name",
      "test_spec_path": "path if known",
      "mapping_type": "full|partial|suggested",
      "confidence": 0.0,
      "coverage_notes": "covered behavior",
      "gap_notes": "remaining gap",
      "allow_candidate": false
    }}
  ],
  "test_proposals": [
    {{
      "title": "test proposal title",
      "rationale": "why this test matters",
      "target_url": "absolute URL if known",
      "route": "/route if known",
      "test_type": "e2e|api|regression|security|accessibility|unit",
      "risk_level": "low|medium|high|critical",
      "requirement_ids": [],
      "evidence": {{"url": "observed URL if any", "selector": "observed selector/text if any", "source": "browser_snapshot|test_run|memory|file"}}
    }}
  ],
  "bugs": [
    {{
      "title": "bug title",
      "description": "observed problem",
      "severity": "low|medium|high|critical",
      "target_url": "absolute URL if known",
      "route": "/route if known",
      "action": "user action",
      "observed_failure": "what happened",
      "expected_behavior": "what should happen",
      "evidence": {{}}
    }}
  ],
  "app_map_updates": [
    {{
      "url": "absolute URL",
      "page_title": "page title",
      "linked_urls": [],
      "elements": {{}},
      "forms": [],
      "api_endpoints": []
    }}
  ],
  "blockers": []
}}

Every proposed file or repository change must be a proposal only. The human approval flow will materialize files later.
"""


def _work_item_context_bundle(
    mission: AutonomousMission,
    item: AutonomousAgentWorkItem,
    *,
    omit_browser_memory: bool = False,
) -> dict[str, Any]:
    bundle: dict[str, Any] = {}
    try:
        from orchestrator.memory.unified import get_unified_memory_service

        memory_bundle = get_unified_memory_service().build_bundle(
            query=item.objective,
            project_id=mission.project_id,
            agent_type=item.role,
            limit=8,
            include_review_required=True,
            include_usage=False,
        )
        if omit_browser_memory and isinstance(memory_bundle, dict):
            memory_bundle["browser_memory"] = {
                "states": [],
                "elements": [],
                "frontier": [],
                "omitted_reason": "current_browser_handoff_present",
            }
            diagnostics = memory_bundle.setdefault("diagnostics", {})
            if isinstance(diagnostics, dict):
                diagnostics.setdefault("warnings", []).append(
                    "Durable browser memory omitted because this work item has a current browser handoff."
                )
        bundle["memory"] = memory_bundle
    except BaseException as exc:
        if exc.__class__.__name__ != "PanicException":
            raise
        facade.logger.debug("Unable to build autonomous work item memory context.", exc_info=True)

    try:
        requirements = []
        with Session(facade.engine) as context_session:
            for requirement in context_session.exec(
                select(Requirement)
                .where(Requirement.project_id == mission.project_id)
                .order_by(col(Requirement.updated_at).desc())
                .limit(12)
            ).all():
                requirements.append(
                    {
                        "id": requirement.id,
                        "req_code": requirement.req_code,
                        "title": requirement.title,
                        "truth_state": facade._requirement_truth_state(requirement),
                        "priority": requirement.priority,
                    }
                )
            open_proposals = context_session.exec(
                select(AutonomousTestProposal)
                .where(
                    AutonomousTestProposal.project_id == mission.project_id,
                    col(AutonomousTestProposal.approval_status).in_(("pending", "approved", "materialized")),
                )
                .order_by(col(AutonomousTestProposal.updated_at).desc())
                .limit(12)
            ).all()
            bundle["canonical"] = {
                "requirements": requirements,
                "active_test_proposals": [
                    {
                        "id": proposal.id,
                        "title": proposal.title,
                        "status": proposal.approval_status,
                        "validation_status": proposal.validation_status,
                        "path": proposal.materialized_file_path or proposal.suggested_file_path,
                    }
                    for proposal in open_proposals
                ],
            }
    except Exception:
        facade.logger.debug("Unable to build autonomous canonical context.", exc_info=True)
    return bundle


def _compact_json(value: Any, *, max_chars: int) -> str:
    text = json.dumps(value, default=str, sort_keys=True)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."
