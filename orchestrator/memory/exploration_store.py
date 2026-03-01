"""
Exploration Store Module

Handles storage and retrieval of exploration data including:
- Exploration sessions
- Discovered transitions
- User flows
- API endpoints
- Requirements and RTM entries

Integrates with the database models and provides a clean API for
the exploration workflow.
"""

import json
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlmodel import col, select

from orchestrator.api.db import get_session

# Import models - these need to be imported after models_db is loaded
from orchestrator.api.models_db import (
    DiscoveredApiEndpoint,
    DiscoveredFlow,
    DiscoveredIssue,
    DiscoveredTransition,
    ExplorationSession,
    FlowStep,
    Requirement,
    RequirementSource,
    RtmEntry,
    RtmSnapshot,
)


class ExplorationStore:
    """
    Store for exploration data.

    Provides methods for storing and querying exploration sessions,
    transitions, flows, and related data.
    """

    def __init__(self, project_id: str = "default"):
        self.project_id = project_id

    def _get_session(self):
        """Get a database session."""
        return next(get_session())

    # ========== Exploration Session Methods ==========

    def create_session(
        self, session_id: str, entry_url: str, strategy: str = "goal_directed", config: dict[str, Any] | None = None
    ) -> ExplorationSession:
        """
        Create a new exploration session.

        Args:
            session_id: Unique session identifier
            entry_url: Starting URL for exploration
            strategy: Exploration strategy
            config: Additional configuration

        Returns:
            Created ExplorationSession
        """
        with self._get_session() as db:
            session = ExplorationSession(
                id=session_id,
                project_id=self.project_id,
                entry_url=entry_url,
                status="pending",
                strategy=strategy,
                config_json=json.dumps(config or {}),
                created_at=datetime.utcnow(),
            )
            db.add(session)
            db.commit()
            db.refresh(session)
            return session

    def update_session_status(
        self, session_id: str, status: str, error_message: str | None = None
    ) -> ExplorationSession | None:
        """Update session status."""
        with self._get_session() as db:
            session = db.get(ExplorationSession, session_id)
            if session:
                session.status = status
                if error_message:
                    session.error_message = error_message
                if status == "running" and not session.started_at:
                    session.started_at = datetime.utcnow()
                if status in ("completed", "failed", "stopped"):
                    session.completed_at = datetime.utcnow()
                db.commit()
                db.refresh(session)
            return session

    def update_session_counts(
        self,
        session_id: str,
        pages: int = 0,
        flows: int = 0,
        elements: int = 0,
        api_endpoints: int = 0,
        issues: int = 0,
    ) -> ExplorationSession | None:
        """Update session discovery counts."""
        with self._get_session() as db:
            session = db.get(ExplorationSession, session_id)
            if session:
                if pages:
                    session.pages_discovered = pages
                if flows:
                    session.flows_discovered = flows
                if elements:
                    session.elements_discovered = elements
                if api_endpoints:
                    session.api_endpoints_discovered = api_endpoints
                if issues:
                    session.issues_discovered = issues
                db.commit()
                db.refresh(session)
            return session

    def update_session_progress(self, session_id: str, progress_data: dict) -> None:
        """Update session live progress data (written during execution)."""
        with self._get_session() as db:
            session = db.get(ExplorationSession, session_id)
            if session:
                import json as _json

                session.progress_data = _json.dumps(progress_data)
                db.commit()

    def clear_session_progress(self, session_id: str) -> None:
        """Clear progress data when exploration finishes."""
        with self._get_session() as db:
            session = db.get(ExplorationSession, session_id)
            if session:
                session.progress_data = None
                db.commit()

    def get_session(self, session_id: str) -> ExplorationSession | None:
        """Get a session by ID."""
        with self._get_session() as db:
            return db.get(ExplorationSession, session_id)

    def list_sessions(self, status: str | None = None, limit: int = 50) -> list[ExplorationSession]:
        """List exploration sessions."""
        with self._get_session() as db:
            query = select(ExplorationSession).where(ExplorationSession.project_id == self.project_id)
            if status:
                query = query.where(ExplorationSession.status == status)
            query = query.order_by(col(ExplorationSession.created_at).desc()).limit(limit)
            return list(db.exec(query).all())

    # ========== Transition Methods ==========

    def store_transition(
        self,
        session_id: str,
        sequence_number: int,
        action_type: str,
        action_target: dict[str, Any],
        action_value: str | None,
        before_url: str,
        after_url: str,
        transition_type: str,
        before_page_type: str | None = None,
        after_page_type: str | None = None,
        before_snapshot_ref: str | None = None,
        after_snapshot_ref: str | None = None,
        api_calls: list[dict[str, Any]] | None = None,
        changes_description: str | None = None,
    ) -> DiscoveredTransition:
        """
        Store a discovered transition.

        Args:
            session_id: Parent session ID
            sequence_number: Order in exploration
            action_type: Type of action (click, fill, etc.)
            action_target: Element details
            action_value: Value if fill/select
            before_url: URL before action
            after_url: URL after action
            transition_type: Type of transition
            before_page_type: Page type before action
            after_page_type: Page type after action
            before_snapshot_ref: Reference to before snapshot
            after_snapshot_ref: Reference to after snapshot
            api_calls: API calls made during transition
            changes_description: Human-readable changes description

        Returns:
            Created DiscoveredTransition
        """
        with self._get_session() as db:
            transition = DiscoveredTransition(
                session_id=session_id,
                sequence_number=sequence_number,
                action_type=action_type,
                action_target_json=json.dumps(action_target),
                action_value=action_value,
                before_url=before_url,
                after_url=after_url,
                transition_type=transition_type,
                before_page_type=before_page_type,
                after_page_type=after_page_type,
                before_snapshot_ref=before_snapshot_ref,
                after_snapshot_ref=after_snapshot_ref,
                api_calls_json=json.dumps(api_calls or []),
                changes_description=changes_description,
                created_at=datetime.utcnow(),
            )
            db.add(transition)
            db.commit()
            db.refresh(transition)
            return transition

    def get_session_transitions(self, session_id: str) -> list[DiscoveredTransition]:
        """Get all transitions for a session."""
        with self._get_session() as db:
            query = (
                select(DiscoveredTransition)
                .where(DiscoveredTransition.session_id == session_id)
                .order_by(DiscoveredTransition.sequence_number)
            )
            return list(db.exec(query).all())

    # ========== Flow Methods ==========

    def store_flow(
        self,
        session_id: str,
        flow_name: str,
        flow_category: str,
        start_url: str,
        end_url: str,
        step_count: int,
        is_success_path: bool = True,
        description: str | None = None,
        preconditions: list[str] | None = None,
        postconditions: list[str] | None = None,
        steps: list[dict[str, Any]] | None = None,
    ) -> DiscoveredFlow:
        """
        Store a discovered flow.

        Args:
            session_id: Parent session ID
            flow_name: Name of the flow
            flow_category: Category (authentication, crud, etc.)
            start_url: Starting URL
            end_url: Ending URL
            step_count: Number of steps
            is_success_path: Whether this is a happy path
            description: Flow description
            preconditions: Required preconditions
            postconditions: Expected postconditions
            steps: Flow step details

        Returns:
            Created DiscoveredFlow
        """
        with self._get_session() as db:
            flow = DiscoveredFlow(
                session_id=session_id,
                project_id=self.project_id,
                flow_name=flow_name,
                flow_category=flow_category,
                description=description,
                start_url=start_url,
                end_url=end_url,
                step_count=step_count,
                is_success_path=is_success_path,
                preconditions_json=json.dumps(preconditions or []),
                postconditions_json=json.dumps(postconditions or []),
                created_at=datetime.utcnow(),
            )
            db.add(flow)
            # Flush to get the flow ID without committing the transaction
            db.flush()

            # Store flow steps if provided (same transaction)
            if steps:
                for i, step in enumerate(steps):
                    flow_step = FlowStep(
                        flow_id=flow.id,
                        step_number=i + 1,
                        action_type=step.get("action", "unknown"),
                        action_description=step.get("element", ""),
                        element_ref=step.get("ref"),
                        element_role=step.get("role"),
                        element_name=step.get("element"),
                        value=str(step.get("value")) if step.get("value") is not None else None,
                    )
                    db.add(flow_step)

            # Single commit for flow + all steps
            db.commit()
            db.refresh(flow)

            return flow

    def get_session_flows(self, session_id: str) -> list[DiscoveredFlow]:
        """Get all flows for a session."""
        with self._get_session() as db:
            query = (
                select(DiscoveredFlow)
                .where(DiscoveredFlow.session_id == session_id)
                .order_by(DiscoveredFlow.created_at)
            )
            return list(db.exec(query).all())

    def get_project_flows(self, category: str | None = None) -> list[DiscoveredFlow]:
        """Get all flows for the project."""
        with self._get_session() as db:
            query = select(DiscoveredFlow).where(DiscoveredFlow.project_id == self.project_id)
            if category:
                query = query.where(DiscoveredFlow.flow_category == category)
            query = query.order_by(col(DiscoveredFlow.created_at).desc())
            return list(db.exec(query).all())

    def get_flow_steps(self, flow_id: int) -> list[FlowStep]:
        """Get steps for a flow."""
        with self._get_session() as db:
            query = select(FlowStep).where(FlowStep.flow_id == flow_id).order_by(FlowStep.step_number)
            return list(db.exec(query).all())

    # ========== API Endpoint Methods ==========

    def store_api_endpoint(
        self,
        session_id: str,
        method: str,
        url: str,
        request_headers: dict[str, Any] | None = None,
        request_body_sample: str | None = None,
        response_status: int | None = None,
        response_body_sample: str | None = None,
        triggered_by_action: str | None = None,
    ) -> DiscoveredApiEndpoint:
        """
        Store a discovered API endpoint.

        Args:
            session_id: Parent session ID
            method: HTTP method
            url: Endpoint URL
            request_headers: Request headers
            request_body_sample: Sample request body
            response_status: Response status code
            response_body_sample: Sample response body
            triggered_by_action: UI action that triggered this

        Returns:
            Created or updated DiscoveredApiEndpoint
        """
        with self._get_session() as db:
            # Check if endpoint already exists
            query = select(DiscoveredApiEndpoint).where(
                DiscoveredApiEndpoint.session_id == session_id,
                DiscoveredApiEndpoint.method == method,
                DiscoveredApiEndpoint.url == url,
            )
            existing = db.exec(query).first()

            if existing:
                # Use atomic SQL increment to avoid race conditions
                from sqlalchemy import text

                db.execute(
                    text("UPDATE discovered_api_endpoints SET call_count = call_count + 1 WHERE id = :id"),
                    {"id": existing.id},
                )

                # Merge rich data if new data provided and existing fields are empty
                if request_headers and (
                    not existing.request_headers_json or existing.request_headers_json in ("{}", "", "null")
                ):
                    existing.request_headers_json = json.dumps(request_headers)
                if request_body_sample and not existing.request_body_sample:
                    existing.request_body_sample = request_body_sample
                if response_body_sample and not existing.response_body_sample:
                    existing.response_body_sample = response_body_sample

                db.commit()
                db.refresh(existing)
                return existing

            endpoint = DiscoveredApiEndpoint(
                session_id=session_id,
                project_id=self.project_id,
                method=method,
                url=url,
                request_headers_json=json.dumps(request_headers or {}),
                request_body_sample=request_body_sample,
                response_status=int(response_status) if response_status is not None else None,
                response_body_sample=response_body_sample,
                triggered_by_action=triggered_by_action,
                first_seen=datetime.utcnow(),
                call_count=1,
            )
            db.add(endpoint)
            db.commit()
            db.refresh(endpoint)
            return endpoint

    def get_session_api_endpoints(self, session_id: str) -> list[DiscoveredApiEndpoint]:
        """Get all API endpoints for a session."""
        with self._get_session() as db:
            query = (
                select(DiscoveredApiEndpoint)
                .where(DiscoveredApiEndpoint.session_id == session_id)
                .order_by(DiscoveredApiEndpoint.first_seen)
            )
            return list(db.exec(query).all())

    # ========== Issue Methods ==========

    def store_issue(
        self,
        session_id: str,
        issue_type: str,
        severity: str = "medium",
        url: str = "",
        description: str = "",
        element: str | None = None,
        evidence: str | None = None,
    ) -> DiscoveredIssue:
        """Store a discovered issue."""
        with self._get_session() as db:
            issue = DiscoveredIssue(
                session_id=session_id,
                issue_type=issue_type,
                severity=severity,
                url=url,
                description=description,
                element=element,
                evidence=evidence,
            )
            db.add(issue)
            db.commit()
            db.refresh(issue)
            return issue

    def get_session_issues(self, session_id: str) -> list[DiscoveredIssue]:
        """Get all issues for a session."""
        with self._get_session() as db:
            query = (
                select(DiscoveredIssue)
                .where(DiscoveredIssue.session_id == session_id)
                .order_by(DiscoveredIssue.created_at)
            )
            return list(db.exec(query).all())

    def update_flow(self, flow_id: int, session_id: str, **kwargs) -> DiscoveredFlow | None:
        """Update a discovered flow's metadata.

        Args:
            flow_id: Flow ID to update
            session_id: Session ID for ownership verification
            **kwargs: Fields to update

        Returns:
            Updated DiscoveredFlow or None if not found/mismatched
        """
        with self._get_session() as db:
            flow = db.get(DiscoveredFlow, flow_id)
            if not flow or flow.session_id != session_id:
                return None

            for key, value in kwargs.items():
                if key == "preconditions":
                    flow.preconditions_json = json.dumps(value)
                elif key == "postconditions":
                    flow.postconditions_json = json.dumps(value)
                elif hasattr(flow, key):
                    setattr(flow, key, value)

            db.commit()
            db.refresh(flow)
            return flow

    def delete_flow(self, flow_id: int, session_id: str) -> bool:
        """Delete a discovered flow and its steps.

        Args:
            flow_id: Flow ID to delete
            session_id: Session ID for ownership verification

        Returns:
            True if deleted, False if not found/mismatched
        """
        with self._get_session() as db:
            flow = db.get(DiscoveredFlow, flow_id)
            if not flow or flow.session_id != session_id:
                return False

            # Delete child FlowStep records first
            steps = db.exec(select(FlowStep).where(FlowStep.flow_id == flow_id)).all()
            for step in steps:
                db.delete(step)

            db.delete(flow)
            db.commit()
            return True

    def update_api_endpoint(self, endpoint_id: int, session_id: str, **kwargs) -> DiscoveredApiEndpoint | None:
        """Update a discovered API endpoint.

        Args:
            endpoint_id: Endpoint ID to update
            session_id: Session ID for ownership verification
            **kwargs: Fields to update

        Returns:
            Updated DiscoveredApiEndpoint or None if not found/mismatched
        """
        with self._get_session() as db:
            endpoint = db.get(DiscoveredApiEndpoint, endpoint_id)
            if not endpoint or endpoint.session_id != session_id:
                return None

            for key, value in kwargs.items():
                if key == "request_headers":
                    endpoint.request_headers_json = json.dumps(value)
                elif hasattr(endpoint, key):
                    setattr(endpoint, key, value)

            db.commit()
            db.refresh(endpoint)
            return endpoint

    def delete_api_endpoint(self, endpoint_id: int, session_id: str) -> bool:
        """Delete a discovered API endpoint.

        Args:
            endpoint_id: Endpoint ID to delete
            session_id: Session ID for ownership verification

        Returns:
            True if deleted, False if not found/mismatched
        """
        with self._get_session() as db:
            endpoint = db.get(DiscoveredApiEndpoint, endpoint_id)
            if not endpoint or endpoint.session_id != session_id:
                return False

            db.delete(endpoint)
            db.commit()
            return True

    def get_project_api_endpoints(self) -> list[DiscoveredApiEndpoint]:
        """Get all API endpoints for the project."""
        with self._get_session() as db:
            query = (
                select(DiscoveredApiEndpoint)
                .where(DiscoveredApiEndpoint.project_id == self.project_id)
                .order_by(col(DiscoveredApiEndpoint.call_count).desc())
            )
            return list(db.exec(query).all())

    # ========== Requirement Methods ==========

    def store_requirement(
        self,
        req_code: str,
        title: str,
        category: str,
        description: str | None = None,
        priority: str = "medium",
        status: str = "draft",
        acceptance_criteria: list[str] | None = None,
        source_session_id: str | None = None,
    ) -> Requirement:
        """
        Store a requirement.

        Args:
            req_code: Requirement code (e.g., REQ-001)
            title: Requirement title
            category: Category (authentication, crud, etc.)
            description: Detailed description
            priority: Priority level
            status: Requirement status
            acceptance_criteria: List of acceptance criteria
            source_session_id: Exploration session that discovered this

        Returns:
            Created Requirement
        """
        with self._get_session() as db:
            requirement = Requirement(
                project_id=self.project_id,
                req_code=req_code,
                title=title,
                description=description,
                category=category,
                priority=priority,
                status=status,
                acceptance_criteria_json=json.dumps(acceptance_criteria or []),
                source_session_id=source_session_id,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(requirement)
            db.commit()
            db.refresh(requirement)
            return requirement

    def get_requirements(self, category: str | None = None, status: str | None = None) -> list[Requirement]:
        """Get requirements for the project."""
        with self._get_session() as db:
            query = select(Requirement).where(Requirement.project_id == self.project_id)
            if category:
                query = query.where(Requirement.category == category)
            if status:
                query = query.where(Requirement.status == status)
            query = query.order_by(Requirement.req_code)
            return list(db.exec(query).all())

    def get_requirements_paginated(
        self,
        category: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Requirement], int]:
        """
        Get paginated requirements for the project.

        Args:
            category: Filter by category
            status: Filter by status
            priority: Filter by priority
            search: Search term for title (case-insensitive)
            limit: Maximum number of items to return
            offset: Number of items to skip

        Returns:
            Tuple of (list of requirements, total count)
        """
        with self._get_session() as db:
            # Build base query with filters
            query = select(Requirement).where(Requirement.project_id == self.project_id)

            if category:
                query = query.where(Requirement.category == category)
            if status:
                query = query.where(Requirement.status == status)
            if priority:
                query = query.where(Requirement.priority == priority)
            if search:
                query = query.where(Requirement.title.ilike(f"%{search}%"))

            # Get total count using a count query
            count_query = select(func.count()).select_from(query.subquery())
            total = db.exec(count_query).one()

            # Apply pagination and ordering
            query = query.order_by(Requirement.req_code).offset(offset).limit(limit)
            items = list(db.exec(query).all())

            return items, total

    def get_requirement(self, req_id: int) -> Requirement | None:
        """Get a requirement by ID."""
        with self._get_session() as db:
            return db.get(Requirement, req_id)

    def update_requirement(self, req_id: int, **kwargs) -> Requirement | None:
        """Update a requirement."""
        with self._get_session() as db:
            requirement = db.get(Requirement, req_id)
            if requirement:
                for key, value in kwargs.items():
                    if hasattr(requirement, key):
                        if key == "acceptance_criteria":
                            requirement.acceptance_criteria_json = json.dumps(value)
                        else:
                            setattr(requirement, key, value)
                requirement.updated_at = datetime.utcnow()
                db.commit()
                db.refresh(requirement)
            return requirement

    def link_requirement_source(
        self, requirement_id: int, source_type: str, source_id: int, confidence: float = 1.0
    ) -> RequirementSource:
        """Link a requirement to its source."""
        with self._get_session() as db:
            source = RequirementSource(
                requirement_id=requirement_id, source_type=source_type, source_id=source_id, confidence=confidence
            )
            db.add(source)
            db.commit()
            db.refresh(source)
            return source

    def get_next_requirement_code(self) -> str:
        """Get the next requirement code."""
        with self._get_session() as db:
            query = (
                select(Requirement)
                .where(Requirement.project_id == self.project_id)
                .order_by(col(Requirement.req_code).desc())
            )
            last = db.exec(query).first()
            if last:
                # Extract number from REQ-XXX format
                try:
                    num = int(last.req_code.split("-")[1])
                    return f"REQ-{num + 1:03d}"
                except (IndexError, ValueError):
                    pass
            return "REQ-001"

    # ========== RTM Methods ==========

    def clear_rtm_for_project(self, project_id: str | None = None) -> int:
        """Delete all RTM entries for the project.

        Args:
            project_id: Project ID to clear (defaults to self.project_id)

        Returns:
            Number of entries deleted
        """
        pid = project_id or self.project_id
        with self._get_session() as db:
            entries = db.exec(select(RtmEntry).where(RtmEntry.project_id == pid)).all()
            count = len(entries)
            for entry in entries:
                db.delete(entry)
            db.commit()
            return count

    def store_rtm_entry(
        self,
        requirement_id: int,
        test_spec_name: str,
        mapping_type: str,
        test_spec_path: str | None = None,
        confidence: float = 1.0,
        coverage_notes: str | None = None,
        gap_notes: str | None = None,
    ) -> RtmEntry:
        """
        Store an RTM entry (upsert on project_id + requirement_id + test_spec_name).

        Args:
            requirement_id: Linked requirement ID
            test_spec_name: Test spec name
            mapping_type: Type of mapping (full, partial, suggested)
            test_spec_path: Full path to spec file
            confidence: Confidence of mapping
            coverage_notes: What's covered
            gap_notes: What's missing

        Returns:
            Created or updated RtmEntry
        """
        with self._get_session() as db:
            # Upsert: check for existing entry with same composite key
            existing = db.exec(
                select(RtmEntry).where(
                    RtmEntry.project_id == self.project_id,
                    RtmEntry.requirement_id == requirement_id,
                    RtmEntry.test_spec_name == test_spec_name,
                )
            ).first()

            if existing:
                existing.mapping_type = mapping_type
                existing.test_spec_path = test_spec_path
                existing.confidence = confidence
                existing.coverage_notes = coverage_notes
                existing.gap_notes = gap_notes
                existing.updated_at = datetime.utcnow()
                db.commit()
                db.refresh(existing)
                return existing

            entry = RtmEntry(
                project_id=self.project_id,
                requirement_id=requirement_id,
                test_spec_name=test_spec_name,
                test_spec_path=test_spec_path,
                mapping_type=mapping_type,
                confidence=confidence,
                coverage_notes=coverage_notes,
                gap_notes=gap_notes,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(entry)
            db.commit()
            db.refresh(entry)
            return entry

    def get_rtm_entries(self, requirement_id: int | None = None) -> list[RtmEntry]:
        """Get RTM entries for the project."""
        with self._get_session() as db:
            query = select(RtmEntry).where(RtmEntry.project_id == self.project_id)
            if requirement_id:
                query = query.where(RtmEntry.requirement_id == requirement_id)
            return list(db.exec(query).all())

    def get_full_rtm(self) -> list[dict[str, Any]]:
        """Get full RTM with requirements and linked tests.

        Uses a single JOIN query instead of N+1 queries for scalability.
        """

        with self._get_session() as db:
            # Single query with LEFT JOIN to get all requirements with their RTM entries
            # This replaces N+1 queries (1 for requirements + N for each requirement's entries)
            query = (
                select(Requirement, RtmEntry)
                .where(Requirement.project_id == self.project_id)
                .outerjoin(
                    RtmEntry, (Requirement.id == RtmEntry.requirement_id) & (RtmEntry.project_id == self.project_id)
                )
                .order_by(Requirement.req_code)
            )

            results = db.exec(query).all()

            # Group RTM entries by requirement
            req_entries_map: dict[int, list[RtmEntry]] = {}
            req_map: dict[int, Requirement] = {}

            for req, entry in results:
                req_map[req.id] = req
                if req.id not in req_entries_map:
                    req_entries_map[req.id] = []
                if entry is not None:
                    req_entries_map[req.id].append(entry)

            # Build RTM response
            rtm = []
            for req_id, req in req_map.items():
                entries = req_entries_map.get(req_id, [])
                rtm.append(
                    {
                        "requirement": {
                            "id": req.id,
                            "code": req.req_code,
                            "title": req.title,
                            "description": req.description,
                            "category": req.category,
                            "priority": req.priority,
                            "status": req.status,
                            "acceptance_criteria": req.acceptance_criteria,
                        },
                        "tests": [
                            {
                                "entry_id": e.id,
                                "spec_name": e.test_spec_name,
                                "spec_path": e.test_spec_path,
                                "mapping_type": e.mapping_type,
                                "confidence": e.confidence,
                                "coverage_notes": e.coverage_notes,
                                "gap_notes": e.gap_notes,
                            }
                            for e in entries
                        ],
                        "coverage_status": self._calculate_coverage_status(entries),
                    }
                )

            return rtm

    def _calculate_coverage_status(self, entries: list[RtmEntry]) -> str:
        """Calculate coverage status from RTM entries."""
        if not entries:
            return "uncovered"

        mapping_types = [e.mapping_type for e in entries]
        if "full" in mapping_types:
            return "covered"
        if "partial" in mapping_types:
            return "partial"
        if "suggested" in mapping_types:
            return "suggested"
        return "uncovered"

    def create_rtm_snapshot(self, snapshot_name: str | None = None) -> RtmSnapshot:
        """Create a snapshot of the current RTM."""
        rtm = self.get_full_rtm()

        # Calculate statistics
        total = len(rtm)
        covered = sum(1 for r in rtm if r["coverage_status"] == "covered")
        partial = sum(1 for r in rtm if r["coverage_status"] == "partial")
        uncovered = sum(1 for r in rtm if r["coverage_status"] == "uncovered")

        coverage_pct = (covered / total * 100) if total > 0 else 0.0

        with self._get_session() as db:
            snapshot = RtmSnapshot(
                project_id=self.project_id,
                snapshot_name=snapshot_name or f"Snapshot {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                total_requirements=total,
                covered_requirements=covered,
                partial_requirements=partial,
                uncovered_requirements=uncovered,
                coverage_percentage=coverage_pct,
                snapshot_data_json=json.dumps(rtm),
                created_at=datetime.utcnow(),
            )
            db.add(snapshot)
            db.commit()
            db.refresh(snapshot)
            return snapshot

    def get_rtm_coverage_stats(self) -> dict[str, Any]:
        """Get RTM coverage statistics."""
        rtm = self.get_full_rtm()
        total = len(rtm)

        if total == 0:
            return {"total_requirements": 0, "covered": 0, "partial": 0, "uncovered": 0, "coverage_percentage": 0.0}

        covered = sum(1 for r in rtm if r["coverage_status"] == "covered")
        partial = sum(1 for r in rtm if r["coverage_status"] == "partial")
        uncovered = sum(1 for r in rtm if r["coverage_status"] == "uncovered")

        return {
            "total_requirements": total,
            "covered": covered,
            "partial": partial,
            "uncovered": uncovered,
            "coverage_percentage": round((covered / total) * 100, 1),
        }

    def get_rtm_paginated(
        self,
        limit: int = 50,
        offset: int = 0,
        search: str | None = None,
        coverage_status: str | None = None,
        category: str | None = None,
        priority: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Get paginated RTM with server-side filtering.

        Applies search/category/priority filters in SQL, then groups and
        filters by coverage_status in Python before paginating.

        Args:
            limit: Maximum items to return
            offset: Number of items to skip
            search: Search term for title or req_code (case-insensitive)
            coverage_status: Filter by coverage status (covered, partial, uncovered, suggested)
            category: Filter by requirement category
            priority: Filter by requirement priority

        Returns:
            Tuple of (paginated items, total count after all filters)
        """
        with self._get_session() as db:
            # Build base query with SQL-level filters
            query = (
                select(Requirement, RtmEntry)
                .where(Requirement.project_id == self.project_id)
                .outerjoin(
                    RtmEntry, (Requirement.id == RtmEntry.requirement_id) & (RtmEntry.project_id == self.project_id)
                )
            )

            if search:
                query = query.where(
                    (Requirement.title.ilike(f"%{search}%")) | (Requirement.req_code.ilike(f"%{search}%"))
                )
            if category:
                query = query.where(Requirement.category == category)
            if priority:
                query = query.where(Requirement.priority == priority)

            query = query.order_by(Requirement.req_code)
            results = db.exec(query).all()

            # Group by requirement (same logic as get_full_rtm)
            req_entries_map: dict[int, list] = {}
            req_map: dict[int, Any] = {}
            req_order: list[int] = []

            for req, entry in results:
                if req.id not in req_map:
                    req_map[req.id] = req
                    req_entries_map[req.id] = []
                    req_order.append(req.id)
                if entry is not None:
                    req_entries_map[req.id].append(entry)

            # Build RTM items with optional coverage_status filter
            all_items = []
            for req_id in req_order:
                req = req_map[req_id]
                entries = req_entries_map.get(req_id, [])
                item_coverage = self._calculate_coverage_status(entries)

                if coverage_status and coverage_status != "all" and item_coverage != coverage_status:
                    continue

                all_items.append(
                    {
                        "requirement": {
                            "id": req.id,
                            "code": req.req_code,
                            "title": req.title,
                            "description": req.description,
                            "category": req.category,
                            "priority": req.priority,
                            "status": req.status,
                            "acceptance_criteria": req.acceptance_criteria,
                        },
                        "tests": [
                            {
                                "entry_id": e.id,
                                "spec_name": e.test_spec_name,
                                "spec_path": e.test_spec_path,
                                "mapping_type": e.mapping_type,
                                "confidence": e.confidence,
                                "coverage_notes": e.coverage_notes,
                                "gap_notes": e.gap_notes,
                            }
                            for e in entries
                        ],
                        "coverage_status": item_coverage,
                    }
                )

            total = len(all_items)
            paginated = all_items[offset : offset + limit]
            return paginated, total

    def get_rtm_coverage_stats_fast(self) -> dict[str, Any]:
        """Get RTM coverage statistics using efficient SQL queries.

        Uses SQL COUNT and CASE expressions instead of loading all RTM data.
        """
        from sqlalchemy import case

        with self._get_session() as db:
            # Count total requirements
            total_query = select(func.count()).where(Requirement.project_id == self.project_id).select_from(Requirement)
            total = db.exec(total_query).one()

            if total == 0:
                return {"total_requirements": 0, "covered": 0, "partial": 0, "uncovered": 0, "coverage_percentage": 0.0}

            # Subquery: for each requirement, get the best mapping_type
            # full(3) > partial(2) > suggested(1) > none(0)
            coverage_sub = (
                select(
                    RtmEntry.requirement_id,
                    func.max(
                        case(
                            (RtmEntry.mapping_type == "full", 3),
                            (RtmEntry.mapping_type == "partial", 2),
                            (RtmEntry.mapping_type == "suggested", 1),
                            else_=0,
                        )
                    ).label("coverage_score"),
                )
                .where(RtmEntry.project_id == self.project_id)
                .group_by(RtmEntry.requirement_id)
                .subquery()
            )

            # Use a wrapping subquery to make GROUP BY on derived column portable
            inner = (
                select(
                    Requirement.id,
                    case(
                        (coverage_sub.c.coverage_score == 3, "covered"),
                        (coverage_sub.c.coverage_score == 2, "partial"),
                        (coverage_sub.c.coverage_score == 1, "suggested"),
                        else_="uncovered",
                    ).label("cov_status"),
                )
                .select_from(Requirement)
                .outerjoin(coverage_sub, Requirement.id == coverage_sub.c.requirement_id)
                .where(Requirement.project_id == self.project_id)
                .subquery()
            )

            stats_query = select(func.count().label("cnt"), inner.c.cov_status).group_by(inner.c.cov_status)

            results = db.exec(stats_query).all()

            stats = {"covered": 0, "partial": 0, "uncovered": 0}
            for count, status in results:
                if status == "covered":
                    stats["covered"] = count
                elif status == "partial":
                    stats["partial"] = count
                elif status == "suggested":
                    stats["uncovered"] += count
                else:
                    stats["uncovered"] += count

            return {
                "total_requirements": total,
                "covered": stats["covered"],
                "partial": stats["partial"],
                "uncovered": stats["uncovered"],
                "coverage_percentage": round((stats["covered"] / total) * 100, 1),
            }


# Global exploration store instance
_exploration_store: ExplorationStore | None = None


def get_exploration_store(project_id: str = "default", force_refresh: bool = False) -> ExplorationStore:
    """Get the exploration store instance."""
    global _exploration_store
    if _exploration_store is None or force_refresh or _exploration_store.project_id != project_id:
        _exploration_store = ExplorationStore(project_id=project_id)
    return _exploration_store
