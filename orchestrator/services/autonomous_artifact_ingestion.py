"""Structured artifact ingestion for autonomous work items."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from typing import Any
from urllib.parse import urlparse

from sqlmodel import Session, col, select

from orchestrator.api.models_db import (
    ApplicationMap,
    AutonomousAgentWorkItem,
    AutonomousFinding,
    AutonomousMission,
    AutonomousMissionRun,
    AutonomousTestProposal,
    Requirement,
    RtmEntry,
    RtmSnapshot,
)
from orchestrator.services import autonomous_activities as facade
from orchestrator.services import autonomous_shared as shared


def _create_findings_from_completed_work_items(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
) -> int:
    created = 0
    items = session.exec(
        select(AutonomousAgentWorkItem).where(
            AutonomousAgentWorkItem.mission_id == mission.id,
            AutonomousAgentWorkItem.status == "completed",
        )
    ).all()
    for item in items:
        if facade._work_item_review_decision(item) in {"rejected", "needs_revision"}:
            continue
        result = item.result or {}
        output = str(result.get("output") or "").strip()
        if not output:
            continue
        structured, validation_errors, saw_structured_output = facade._extract_structured_agent_contract(output)
        if saw_structured_output and validation_errors:
            (
                repaired_structured,
                repair_errors,
                repair_attempts,
                repair_session_id,
                used_native_output_format,
            ) = facade._repair_structured_work_item_contract(
                session,
                mission,
                item,
                invalid_output=output,
                validation_errors=validation_errors,
            )
            if repaired_structured:
                structured = repaired_structured
                validation_errors = []
                output = str((item.result or {}).get("output") or output).strip()
            else:
                facade._persist_structured_guardrail_telemetry(
                    session,
                    item,
                    attempts=repair_attempts,
                    validation_errors=repair_errors,
                    used_native_output_format=used_native_output_format,
                    repair_session_id=repair_session_id,
                    fallback_revision_created=True,
                )
                validation_errors = repair_errors
                facade._create_contract_revision_work_item(session, mission, run, item, validation_errors)
                continue
        if structured:
            merge_summary = facade._merge_structured_work_item_artifacts(session, mission, run, item, structured)
            item.result = {**item.result, "structured_merge": merge_summary}
            session.add(item)
            session.commit()
            created += int(merge_summary.get("findings_created", 0) or 0)
            if any(
                int(merge_summary.get(key, 0) or 0)
                for key in (
                    "requirements_created",
                    "requirements_reused",
                    "rtm_entries_created",
                    "rtm_entries_reused",
                    "test_proposals_created",
                    "findings_reused",
                    "app_map_updates",
                )
            ):
                continue
        dedupe_key = hashlib.sha256(f"{mission.project_id}|work_item|{item.id}|finding".encode()).hexdigest()[:32]
        existing = session.exec(
            select(AutonomousFinding).where(
                AutonomousFinding.project_id == mission.project_id,
                AutonomousFinding.dedupe_key == dedupe_key,
            )
        ).first()
        if existing:
            continue
        title = f"{facade._title_case(item.role)} agent report"
        evidence = {
            "work_item_id": item.id,
            "role": item.role,
            "assigned_surface": item.assigned_surface,
            **facade._work_item_revision_metadata(item),
        }
        finding = AutonomousFinding(
            id=f"amfind-{uuid.uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            project_id=mission.project_id,
            finding_type="exploration" if item.role in {"surface_mapper", "explorer"} else "coverage_gap",
            severity="medium",
            title=title,
            description=output[:8000],
            status="open",
            confidence=0.75,
            dedupe_key=dedupe_key,
            source_type="autonomous_work_item",
            source_id=item.id,
            approval_required=True,
        )
        finding.evidence = evidence
        session.add(finding)
        created += 1
    if created:
        mission.total_findings += created
        session.add(mission)
        session.commit()
    return created


def _create_contract_revision_work_item(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
    item: AutonomousAgentWorkItem,
    validation_errors: list[str],
) -> AutonomousAgentWorkItem | None:
    existing = session.exec(
        select(AutonomousAgentWorkItem).where(
            AutonomousAgentWorkItem.mission_id == mission.id,
            col(AutonomousAgentWorkItem.status).in_(("queued", "running", "completed")),
        )
    ).all()
    for candidate in existing:
        progress = candidate.progress
        if (
            progress.get("revision_of_work_item_id") == item.id
            and progress.get("review_reason") == "structured_contract_validation"
        ):
            item.result = {
                **item.result,
                "review_decision": "needs_revision",
                "revision_work_item_id": candidate.id,
                "validation_errors": validation_errors,
            }
            session.add(item)
            session.commit()
            return candidate

    attempt = int((item.progress or {}).get("revision_attempt") or 0) + 1
    revision = AutonomousAgentWorkItem(
        id=f"amwork-{uuid.uuid4().hex[:12]}",
        mission_id=mission.id,
        run_id=run.id,
        project_id=mission.project_id,
        role=item.role,
        objective=(
            f"Revise the structured JSON output for work item {item.id}. "
            "Return only contract-valid JSON and preserve any valid discoveries."
        ),
        assigned_surface_json=item.assigned_surface_json,
        status="queued",
        priority=max(1, int(item.priority or 50) - 5),
    )
    revision.progress = {
        "phase": "created",
        "message": "Queued because the previous agent output did not match the structured contract.",
        "revision_of_work_item_id": item.id,
        "reviewer_work_item_id": item.id,
        "review_reason": "structured_contract_validation",
        "validation_errors": validation_errors[:20],
        "revision_attempt": attempt,
    }
    item.result = {
        **item.result,
        "review_decision": "needs_revision",
        "revision_work_item_id": revision.id,
        "validation_errors": validation_errors,
    }
    session.add(item)
    session.add(revision)
    session.commit()
    return revision


def _merge_structured_work_item_artifacts(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
    item: AutonomousAgentWorkItem,
    contract: dict[str, Any],
) -> dict[str, int]:
    summary = {
        "requirements_created": 0,
        "requirements_reused": 0,
        "rtm_entries_created": 0,
        "rtm_entries_reused": 0,
        "test_proposals_created": 0,
        "findings_created": 0,
        "findings_reused": 0,
        "app_map_updates": 0,
        "rtm_snapshots_created": 0,
    }

    for row in facade._dict_rows(contract.get("app_map_updates")):
        if facade._merge_app_map_update(session, mission, row):
            summary["app_map_updates"] += 1

    requirement_id_by_fingerprint: dict[str, int] = {}
    for row in facade._dict_rows(contract.get("requirements")):
        if not facade._row_has_required_evidence("requirement", row):
            facade.logger.info(
                "Quarantined low-evidence autonomous requirement from work item %s: %s", item.id, row.get("title")
            )
            continue
        requirement, created, fingerprint = facade._merge_requirement_artifact(session, mission, item, row)
        if not requirement or requirement.id is None:
            continue
        requirement_id_by_fingerprint[fingerprint] = requirement.id
        if created:
            summary["requirements_created"] += 1
        else:
            summary["requirements_reused"] += 1

    for row in facade._dict_rows(contract.get("rtm_candidates")):
        if (
            not facade._resolve_requirement_ids(session, mission.project_id, row)
            and len(requirement_id_by_fingerprint) == 1
        ):
            row = {**row, "requirement_id": next(iter(requirement_id_by_fingerprint.values()))}
        created = facade._merge_rtm_candidate(session, mission, row)
        if created is True:
            summary["rtm_entries_created"] += 1
        elif created is False:
            summary["rtm_entries_reused"] += 1

    for row in facade._dict_rows(contract.get("test_proposals")):
        requirement_ids = facade._resolve_requirement_ids(session, mission.project_id, row)
        if not requirement_ids and row.get("requirement_fingerprint"):
            req_id = requirement_id_by_fingerprint.get(str(row["requirement_fingerprint"]))
            if req_id:
                requirement_ids = [req_id]
        if not requirement_ids and len(requirement_id_by_fingerprint) == 1:
            requirement_ids = [next(iter(requirement_id_by_fingerprint.values()))]
        proposal = facade._merge_test_proposal_artifact(
            session, mission, run, item, row, requirement_ids=requirement_ids
        )
        if proposal:
            summary["test_proposals_created"] += 1

    for row in facade._dict_rows(contract.get("bugs")) + facade._dict_rows(contract.get("findings")):
        finding, created = facade._merge_bug_or_finding_artifact(session, mission, run, item, row)
        if not finding:
            continue
        if created:
            summary["findings_created"] += 1
        else:
            summary["findings_reused"] += 1

    if summary["rtm_entries_created"]:
        facade._create_rtm_snapshot(session, mission, source_work_item_id=item.id)
        summary["rtm_snapshots_created"] = 1

    session.commit()
    return summary


def _dict_rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in facade._as_list(value) if isinstance(row, dict)]


def _autonomous_require_evidence() -> bool:
    return os.environ.get("AUTONOMOUS_REQUIRE_EVIDENCE", "1").lower() not in {"0", "false", "no"}


def _row_has_required_evidence(kind: str, row: dict[str, Any]) -> bool:
    if not facade._autonomous_require_evidence():
        return True
    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    evidence_refs = facade._as_text_list(row.get("evidence_refs") or row.get("evidenceRefs"))
    direct_fields = [
        row.get("target_url"),
        row.get("url"),
        row.get("route"),
        row.get("selector"),
        row.get("source"),
        row.get("snapshot_ref"),
        row.get("screenshot"),
        row.get("observed_failure"),
        row.get("action"),
    ]
    nested_fields = []
    if evidence:
        nested_fields = [
            evidence.get("url"),
            evidence.get("target_url"),
            evidence.get("route"),
            evidence.get("selector"),
            evidence.get("text"),
            evidence.get("source"),
            evidence.get("snapshot_ref"),
            evidence.get("screenshot"),
            evidence.get("artifact"),
        ]
    has_observation = any(str(value or "").strip() for value in [*direct_fields, *nested_fields]) or bool(evidence_refs)
    if kind == "bug":
        return has_observation and bool(str(row.get("observed_failure") or row.get("description") or "").strip())
    if kind == "test_proposal":
        return has_observation or bool(facade._as_list(row.get("requirement_ids") or row.get("requirements")))
    if kind == "requirement":
        return has_observation or facade._as_float(row.get("confidence"), 0.0) >= 0.9
    return has_observation


def _merge_app_map_update(session: Session, mission: AutonomousMission, row: dict[str, Any]) -> bool:
    url = str(row.get("url") or row.get("target_url") or "").strip()
    if not url:
        return False
    surface_key = shared._stable_dedupe_hash(
        "surface", mission.project_id or "default", shared._route_from_url(url) or url
    )
    existing = session.exec(
        select(ApplicationMap).where(
            ApplicationMap.project_id == mission.project_id,
            ApplicationMap.app_surface_key == surface_key,
        )
    ).first()
    if not existing:
        existing = session.exec(
            select(ApplicationMap).where(
                ApplicationMap.project_id == mission.project_id,
                ApplicationMap.url == url,
            )
        ).first()
    now = shared._utcnow()
    if existing:
        existing.project_id = existing.project_id or mission.project_id
        existing.app_surface_key = existing.app_surface_key or surface_key
        existing.page_title = str(row.get("page_title") or row.get("title") or existing.page_title or "") or None
        existing.linked_urls = facade._as_text_list(row.get("linked_urls")) or existing.linked_urls
        if isinstance(row.get("elements"), dict):
            existing.elements = row["elements"]
        forms = row.get("forms")
        if isinstance(forms, list):
            existing.forms = [form for form in forms if isinstance(form, dict)]
        endpoints = row.get("api_endpoints")
        if isinstance(endpoints, list):
            existing.api_endpoints = [endpoint for endpoint in endpoints if isinstance(endpoint, dict)]
        existing.last_crawled = now
        session.add(existing)
        return True
    app_map = ApplicationMap(
        project_id=mission.project_id,
        app_surface_key=surface_key,
        url=url,
        page_title=str(row.get("page_title") or row.get("title") or "") or None,
        linked_urls=facade._as_text_list(row.get("linked_urls")) or None,
        elements=row.get("elements") if isinstance(row.get("elements"), dict) else None,
        forms=[form for form in facade._as_list(row.get("forms")) if isinstance(form, dict)] or None,
        api_endpoints=[endpoint for endpoint in facade._as_list(row.get("api_endpoints")) if isinstance(endpoint, dict)]
        or None,
        last_crawled=now,
    )
    session.add(app_map)
    return True


def _merge_requirement_artifact(
    session: Session,
    mission: AutonomousMission,
    item: AutonomousAgentWorkItem,
    row: dict[str, Any],
) -> tuple[Requirement | None, bool, str]:
    title = str(row.get("title") or "").strip()
    if not title:
        return None, False, ""
    category = str(row.get("category") or "other").strip() or "other"
    criteria = facade._as_text_list(row.get("acceptance_criteria") or row.get("criteria"))
    fingerprint = shared._requirement_fingerprint(
        {"title": title, "category": category, "acceptance_criteria": criteria}
    )
    existing_by_key = session.exec(
        select(Requirement).where(
            Requirement.project_id == mission.project_id, Requirement.canonical_key == fingerprint
        )
    ).first()
    candidates = (
        [existing_by_key]
        if existing_by_key
        else session.exec(select(Requirement).where(Requirement.project_id == mission.project_id)).all()
    )
    for requirement in candidates:
        if not requirement:
            continue
        existing_fingerprint = shared._requirement_fingerprint(
            {
                "title": requirement.title,
                "category": requirement.category,
                "acceptance_criteria": requirement.acceptance_criteria,
            }
        )
        if existing_fingerprint != fingerprint:
            continue
        existing_criteria = requirement.acceptance_criteria
        merged_criteria = sorted({*existing_criteria, *criteria})
        if merged_criteria != existing_criteria:
            requirement.acceptance_criteria = merged_criteria
        if row.get("description") and not requirement.description:
            requirement.description = str(row.get("description"))
        requirement.canonical_key = requirement.canonical_key or fingerprint
        requirement.confidence = max(float(requirement.confidence or 0), facade._as_float(row.get("confidence"), 0.7))
        requirement.updated_at = shared._utcnow()
        session.add(requirement)
        return requirement, False, fingerprint

    truth_state = str(row.get("truth_state") or "candidate_requirement")
    if truth_state not in {"candidate_requirement", "confirmed_requirement", "manual_requirement", "observed_behavior"}:
        truth_state = "candidate_requirement"
    now = shared._utcnow()
    requirement = Requirement(
        project_id=mission.project_id,
        req_code=facade._next_requirement_code(session, mission.project_id),
        title=title,
        description=str(row.get("description") or "") or None,
        category=category,
        priority=facade._normalize_risk(str(row.get("priority") or "medium")),
        status="confirmed" if truth_state == "confirmed_requirement" else "draft",
        canonical_key=fingerprint,
        truth_state=truth_state,
        source_type="autonomous_agent",
        confidence=facade._as_float(row.get("confidence"), 0.7),
        uncertainty_reason=str(
            row.get("uncertainty_reason") or "Generated from autonomous agent evidence and awaiting human review."
        ),
        acceptance_criteria_json=json.dumps(criteria),
        created_at=now,
        updated_at=now,
    )
    session.add(requirement)
    session.flush()
    return requirement, True, fingerprint


def _merge_rtm_candidate(
    session: Session,
    mission: AutonomousMission,
    row: dict[str, Any],
) -> bool | None:
    requirement_ids = facade._resolve_requirement_ids(session, mission.project_id, row)
    if not requirement_ids:
        return None
    test_spec_name = str(
        row.get("test_spec_name") or row.get("spec_name") or row.get("suggested_file_path") or ""
    ).strip()
    if not test_spec_name:
        return None
    created_any = False
    reused_any = False
    for requirement_id in requirement_ids:
        requirement = session.get(Requirement, requirement_id)
        if not requirement or requirement.project_id != mission.project_id:
            continue
        allow_candidate = bool(row.get("allow_candidate") or row.get("accepted_candidate"))
        if facade._requirement_truth_state(requirement) != "confirmed_requirement" and not allow_candidate:
            continue
        dedupe_key = shared._stable_dedupe_hash(
            mission.project_id or "default",
            "rtm",
            requirement_id,
            test_spec_name,
            row.get("test_spec_path") or row.get("spec_path"),
        )
        existing = session.exec(
            select(RtmEntry).where(
                RtmEntry.project_id == mission.project_id,
                RtmEntry.dedupe_key == dedupe_key,
            )
        ).first()
        if not existing:
            existing = session.exec(
                select(RtmEntry).where(
                    RtmEntry.project_id == mission.project_id,
                    RtmEntry.requirement_id == requirement_id,
                    RtmEntry.test_spec_name == test_spec_name,
                )
            ).first()
        now = shared._utcnow()
        if existing:
            existing.dedupe_key = existing.dedupe_key or dedupe_key
            existing.mapping_type = str(row.get("mapping_type") or existing.mapping_type or "suggested")
            existing.test_spec_path = (
                str(row.get("test_spec_path") or row.get("spec_path") or existing.test_spec_path or "") or None
            )
            existing.confidence = max(float(existing.confidence or 0), facade._as_float(row.get("confidence"), 0.7))
            existing.coverage_notes = str(row.get("coverage_notes") or existing.coverage_notes or "") or None
            existing.gap_notes = str(row.get("gap_notes") or existing.gap_notes or "") or None
            existing.updated_at = now
            session.add(existing)
            reused_any = True
            continue
        entry = RtmEntry(
            project_id=mission.project_id,
            requirement_id=requirement_id,
            test_spec_name=test_spec_name,
            test_spec_path=str(row.get("test_spec_path") or row.get("spec_path") or "") or None,
            mapping_type=str(row.get("mapping_type") or "suggested"),
            dedupe_key=dedupe_key,
            confidence=facade._as_float(row.get("confidence"), 0.7),
            coverage_notes=str(row.get("coverage_notes") or "") or None,
            gap_notes=str(row.get("gap_notes") or "") or None,
            created_at=now,
            updated_at=now,
        )
        session.add(entry)
        created_any = True
    if created_any:
        return True
    if reused_any:
        return False
    return None


def _merge_test_proposal_artifact(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
    item: AutonomousAgentWorkItem,
    row: dict[str, Any],
    *,
    requirement_ids: list[int],
) -> AutonomousTestProposal | None:
    title = str(row.get("title") or row.get("scenario") or "").strip()
    rationale = str(row.get("rationale") or row.get("description") or title).strip()
    if not title or not rationale:
        return None
    quarantined = not facade._row_has_required_evidence("test_proposal", row)
    target_url = str(row.get("target_url") or row.get("url") or "").strip() or facade._default_target_url(mission)
    if row.get("route") and not row.get("target_url"):
        target_url = facade._url_for_route(facade._default_target_url(mission), str(row["route"]))
    fingerprint = shared._spec_fingerprint(row, requirement_ids=requirement_ids)
    metadata = facade._artifact_source_metadata(
        item,
        artifact_type="test_proposal",
        fingerprint=fingerprint,
        extra={
            "requirement_ids": requirement_ids,
            "route": row.get("route") or shared._route_from_url(target_url),
            "agent_rationale": rationale,
            "evidence": row.get("evidence") if isinstance(row.get("evidence"), dict) else {},
        },
    )
    if quarantined:
        metadata["quarantined"] = True
        metadata["quarantine_reason"] = "autonomous_output_missing_required_evidence"
    if requirement_ids:
        metadata["requirement_id"] = requirement_ids[0]
    return facade._create_test_proposal(
        session,
        mission,
        run,
        source_type="autonomous_structured_spec",
        source_id=fingerprint,
        title=title,
        rationale=rationale,
        target_url=target_url,
        risk_level=str(row.get("risk_level") or row.get("severity") or "medium"),
        source_metadata=metadata,
        approval_status="rejected" if quarantined else "pending",
    )


def _merge_bug_or_finding_artifact(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
    item: AutonomousAgentWorkItem,
    row: dict[str, Any],
) -> tuple[AutonomousFinding | None, bool]:
    title = str(row.get("title") or "").strip()
    description = str(row.get("description") or row.get("observed_failure") or "").strip()
    if not title or not description:
        return None, False
    quarantined = not facade._row_has_required_evidence("bug", row)
    kind = (
        "bug"
        if row.get("observed_failure") or row.get("expected_behavior")
        else str(row.get("finding_type") or "coverage_gap")
    )
    fingerprint = (
        shared._bug_fingerprint(row)
        if kind == "bug"
        else shared._stable_dedupe_hash(
            "finding",
            kind,
            row.get("route") or row.get("target_url") or row.get("url"),
            title,
            description,
        )
    )
    dedupe_key = shared._stable_dedupe_hash(mission.project_id or "default", kind, fingerprint)
    existing = session.exec(
        select(AutonomousFinding).where(
            AutonomousFinding.project_id == mission.project_id,
            AutonomousFinding.dedupe_key == dedupe_key,
        )
    ).first()
    if existing:
        return existing, False
    now = shared._utcnow()
    evidence = facade._artifact_source_metadata(
        item,
        artifact_type=kind,
        fingerprint=fingerprint,
        extra={
            "target_url": row.get("target_url") or row.get("url"),
            "route": row.get("route") or shared._route_from_url(row.get("target_url") or row.get("url")),
            "action": row.get("action"),
            "observed_failure": row.get("observed_failure"),
            "expected_behavior": row.get("expected_behavior"),
            "evidence": row.get("evidence") if isinstance(row.get("evidence"), dict) else {},
        },
    )
    finding = AutonomousFinding(
        id=f"amfind-{uuid.uuid4().hex[:12]}",
        mission_id=mission.id,
        run_id=run.id,
        project_id=mission.project_id,
        finding_type=kind,
        severity=facade._normalize_risk(str(row.get("severity") or row.get("risk_level") or "medium")),
        title=title,
        description=description,
        status="rejected" if quarantined else "awaiting_approval" if kind == "bug" else "open",
        confidence=facade._as_float(row.get("confidence"), 0.75),
        dedupe_key=dedupe_key,
        evidence_json=json.dumps(evidence),
        source_type="autonomous_work_item",
        source_id=item.id,
        approval_required=True,
        created_at=now,
        updated_at=now,
    )
    session.add(finding)
    return finding, True


def _create_rtm_snapshot(session: Session, mission: AutonomousMission, *, source_work_item_id: str) -> None:
    requirements = session.exec(select(Requirement).where(Requirement.project_id == mission.project_id)).all()
    entries = session.exec(select(RtmEntry).where(RtmEntry.project_id == mission.project_id)).all()
    entries_by_requirement: dict[int, list[RtmEntry]] = {}
    for entry in entries:
        entries_by_requirement.setdefault(entry.requirement_id, []).append(entry)
    covered = 0
    partial = 0
    uncovered = 0
    rows = []
    for requirement in requirements:
        req_entries = entries_by_requirement.get(requirement.id or -1, [])
        if any(entry.mapping_type == "full" for entry in req_entries):
            covered += 1
            status = "covered"
        elif req_entries:
            partial += 1
            status = "partial"
        else:
            uncovered += 1
            status = "uncovered"
        rows.append(
            {
                "requirement_id": requirement.id,
                "req_code": requirement.req_code,
                "title": requirement.title,
                "status": status,
                "entries": [entry.test_spec_name for entry in req_entries],
            }
        )
    total = len(requirements)
    snapshot = RtmSnapshot(
        project_id=mission.project_id,
        snapshot_name=f"autonomous-{mission.id}-{source_work_item_id}",
        total_requirements=total,
        covered_requirements=covered,
        partial_requirements=partial,
        uncovered_requirements=uncovered,
        coverage_percentage=round((covered / total) * 100, 2) if total else 0.0,
        snapshot_data_json=json.dumps({"source_work_item_id": source_work_item_id, "rows": rows[:500]}),
        created_at=shared._utcnow(),
    )
    session.add(snapshot)


def _url_for_route(base_url: str, route: str) -> str:
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        return route
    path = route if route.startswith("/") else f"/{route}"
    return f"{parsed.scheme}://{parsed.netloc}{path}"
