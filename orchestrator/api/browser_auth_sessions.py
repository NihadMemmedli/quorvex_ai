"""Project-scoped reusable browser login sessions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from orchestrator.services.browser_auth_sessions import (
    BrowserAuthSessionError,
    create_browser_auth_session,
    list_browser_auth_sessions,
    refresh_browser_auth_session,
    revoke_browser_auth_session,
    serialize_browser_auth_session,
    set_default_browser_auth_session,
    validate_browser_auth_session,
)

from .db import get_session
from .middleware.auth import get_current_user_optional
from .middleware.permissions import EDIT_ROLES, VIEW_ROLES, check_project_access
from .models_auth import User
from .models_db import Project

router = APIRouter(prefix="/projects/{project_id}/browser-auth-sessions", tags=["browser-auth-sessions"])


class BrowserAuthSessionCreateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    base_url: str = Field(min_length=1)
    login_url: str = Field(min_length=1)
    username_key: str = Field(min_length=1)
    password_key: str = Field(min_length=1)
    username_selector: str | None = Field(default=None, max_length=500)
    password_selector: str | None = Field(default=None, max_length=500)
    username_continue_selector: str | None = Field(default=None, max_length=500)
    submit_selector: str | None = Field(default=None, max_length=500)
    success_url_pattern: str | None = Field(default=None, max_length=500)
    expires_at: datetime | None = None
    make_default: bool = False
    storage_state: dict[str, Any] | None = None


class BrowserAuthSessionResponse(BaseModel):
    id: str
    project_id: str
    name: str
    base_url: str
    login_url: str
    username_key: str
    password_key: str
    username_selector: str | None = None
    password_selector: str | None = None
    username_continue_selector: str | None = None
    submit_selector: str | None = None
    success_url_pattern: str | None = None
    status: str
    is_default: bool
    created_at: str | None = None
    last_validated_at: str | None = None
    expires_at: str | None = None
    failure_reason: str | None = None
    capture_backend_version: str | None = None


class BrowserAuthSessionListResponse(BaseModel):
    sessions: list[BrowserAuthSessionResponse]
    project_id: str


def _project_or_404(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _response(row) -> BrowserAuthSessionResponse:
    return BrowserAuthSessionResponse(**serialize_browser_auth_session(row))


def _error(exc: BrowserAuthSessionError) -> HTTPException:
    message = str(exc)
    lower_message = message.lower()
    status_code = 404 if lower_message in {
        "browser auth session was not found",
        "project default browser auth session was not found",
    } else 400
    return HTTPException(status_code=status_code, detail=message)


@router.get("", response_model=BrowserAuthSessionListResponse)
async def list_project_browser_auth_sessions(
    project_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    _project_or_404(session, project_id)
    await check_project_access(project_id, current_user, VIEW_ROLES, session)
    rows = list_browser_auth_sessions(session, project_id)
    return BrowserAuthSessionListResponse(project_id=project_id, sessions=[_response(row) for row in rows])


@router.post("", response_model=BrowserAuthSessionResponse, status_code=201)
async def create_project_browser_auth_session(
    project_id: str,
    request: BrowserAuthSessionCreateRequest,
    current_user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    _project_or_404(session, project_id)
    await check_project_access(project_id, current_user, EDIT_ROLES, session)
    try:
        row = create_browser_auth_session(
            session,
            project_id=project_id,
            name=request.name,
            base_url=request.base_url,
            login_url=request.login_url,
            username_key=request.username_key,
            password_key=request.password_key,
            username_selector=request.username_selector,
            password_selector=request.password_selector,
            username_continue_selector=request.username_continue_selector,
            submit_selector=request.submit_selector,
            success_url_pattern=request.success_url_pattern,
            expires_at=request.expires_at,
            make_default=request.make_default,
            storage_state=request.storage_state,
        )
        return _response(row)
    except BrowserAuthSessionError as exc:
        raise _error(exc) from exc


@router.post("/{session_id}/validate", response_model=BrowserAuthSessionResponse)
async def validate_project_browser_auth_session(
    project_id: str,
    session_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    _project_or_404(session, project_id)
    await check_project_access(project_id, current_user, EDIT_ROLES, session)
    try:
        return _response(validate_browser_auth_session(session, project_id, session_id))
    except BrowserAuthSessionError as exc:
        raise _error(exc) from exc


@router.post("/{session_id}/refresh", response_model=BrowserAuthSessionResponse)
async def refresh_project_browser_auth_session(
    project_id: str,
    session_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    _project_or_404(session, project_id)
    await check_project_access(project_id, current_user, EDIT_ROLES, session)
    try:
        return _response(refresh_browser_auth_session(session, project_id, session_id))
    except BrowserAuthSessionError as exc:
        raise _error(exc) from exc


@router.delete("/{session_id}", response_model=BrowserAuthSessionResponse)
async def delete_project_browser_auth_session(
    project_id: str,
    session_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    _project_or_404(session, project_id)
    await check_project_access(project_id, current_user, EDIT_ROLES, session)
    try:
        return _response(revoke_browser_auth_session(session, project_id, session_id))
    except BrowserAuthSessionError as exc:
        raise _error(exc) from exc


@router.patch("/{session_id}/default", response_model=BrowserAuthSessionResponse)
async def set_project_default_browser_auth_session(
    project_id: str,
    session_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    _project_or_404(session, project_id)
    await check_project_access(project_id, current_user, EDIT_ROLES, session)
    try:
        return _response(set_default_browser_auth_session(session, project_id, session_id))
    except BrowserAuthSessionError as exc:
        raise _error(exc) from exc
