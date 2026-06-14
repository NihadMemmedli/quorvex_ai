"""Project-scoped test data API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from orchestrator.services.test_data_resolver import (
    normalize_test_data_format,
    normalize_test_data_key,
    normalize_test_data_status,
    prepare_test_data_item_storage,
    resolve_test_data_refs,
    resolve_testdata_in_markdown,
)

from .db import get_session
from .middleware.auth import get_current_user_optional
from .middleware.permissions import EDIT_ROLES, VIEW_ROLES, check_project_access
from .models_auth import User
from .models_db import Project, TestDataItem, TestDataSet

router = APIRouter(prefix="/test-data", tags=["test-data"])


class TestDataSetRequest(BaseModel):
    project_id: str
    key: str
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    status: str = "active"
    format: str = "json"


class TestDataSetUpdateRequest(BaseModel):
    key: str | None = None
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    status: str | None = None
    format: str | None = None


class TestDataItemRequest(BaseModel):
    key: str
    name: str = ""
    description: str = ""
    status: str = "active"
    format: str = "json"
    data: Any = None
    text: str | None = None
    sensitive_fields: list[str] = Field(default_factory=list)


class TestDataItemUpdateRequest(BaseModel):
    key: str | None = None
    name: str | None = None
    description: str | None = None
    status: str | None = None
    format: str | None = None
    data: Any = None
    text: str | None = None
    sensitive_fields: list[str] | None = None
    replace_content: bool = True


class TestDataResolveRequest(BaseModel):
    project_id: str
    refs: list[str] = Field(default_factory=list)
    render_as: str = "json"
    include_archived: bool = False


class TestDataSpecResolveRequest(BaseModel):
    project_id: str
    content: str


def _dataset_to_dict(dataset: TestDataSet, item_count: int | None = None) -> dict[str, Any]:
    payload = {
        "id": dataset.id,
        "project_id": dataset.project_id,
        "key": dataset.key,
        "name": dataset.name,
        "description": dataset.description,
        "tags": dataset.tags,
        "status": dataset.status,
        "format": dataset.format,
        "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
        "updated_at": dataset.updated_at.isoformat() if dataset.updated_at else None,
    }
    if item_count is not None:
        payload["item_count"] = item_count
    return payload


def _item_to_dict(dataset: TestDataSet, item: TestDataItem, session: Session) -> dict[str, Any]:
    ref = f"{dataset.key}.{item.key}"
    resolved = resolve_test_data_refs(
        session,
        project_id=dataset.project_id,
        refs=[ref],
        render_as="json",
        include_archived=True,
        decrypt_sensitive=False,
    )
    payload = (resolved.get("items") or {}).get(ref, {})
    return {
        "id": item.id,
        "dataset_id": item.dataset_id,
        "dataset_key": dataset.key,
        "ref": ref,
        "key": item.key,
        "name": item.name,
        "description": item.description,
        "status": item.status,
        "format": item.format,
        "data": payload.get("data"),
        "text": payload.get("text"),
        "sensitive_fields": item.sensitive_fields,
        "placeholders": payload.get("placeholders") or {},
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


async def _ensure_project_access(
    project_id: str,
    user: User | None,
    roles: list[str],
    session: Session,
) -> None:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await check_project_access(project_id, user, roles, session)


def _project_matches(row_project_id: str | None, project_id: str) -> bool:
    if project_id == "default":
        return row_project_id in (None, "default")
    return row_project_id == project_id


def _get_dataset_or_404(dataset_id: str, project_id: str, session: Session) -> TestDataSet:
    dataset = session.get(TestDataSet, dataset_id)
    if not dataset or not _project_matches(dataset.project_id, project_id):
        raise HTTPException(status_code=404, detail="Test data dataset not found")
    return dataset


def _get_item_or_404(item_id: str, dataset_id: str, session: Session) -> TestDataItem:
    item = session.get(TestDataItem, item_id)
    if not item or item.dataset_id != dataset_id:
        raise HTTPException(status_code=404, detail="Test data item not found")
    return item


def _commit_or_unique_error(session: Session, detail: str) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=detail) from exc


def _normalize_key(value: str, *, label: str = "key") -> str:
    try:
        return normalize_test_data_key(value, label=label)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _normalize_status(value: str | None) -> str:
    try:
        return normalize_test_data_status(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _normalize_format(value: str | None) -> str:
    try:
        return normalize_test_data_format(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/datasets")
async def list_datasets(
    project_id: str = Query(...),
    tags: list[str] | None = Query(default=None),
    status: str | None = Query(default=None),
    format: str | None = Query(default=None),
    user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    await _ensure_project_access(project_id, user, VIEW_ROLES, session)
    stmt = select(TestDataSet).where(TestDataSet.project_id == project_id).order_by(TestDataSet.updated_at.desc())
    if status:
        stmt = stmt.where(TestDataSet.status == _normalize_status(status))
    if format:
        stmt = stmt.where(TestDataSet.format == _normalize_format(format))
    datasets = session.exec(stmt).all()
    if tags:
        wanted = {tag.strip() for tag in tags if tag.strip()}
        datasets = [dataset for dataset in datasets if wanted.issubset(set(dataset.tags))]
    return {
        "datasets": [
            _dataset_to_dict(
                dataset,
                item_count=len(session.exec(select(TestDataItem).where(TestDataItem.dataset_id == dataset.id)).all()),
            )
            for dataset in datasets
        ],
        "total": len(datasets),
    }


@router.post("/datasets", status_code=201)
async def create_dataset(
    request: TestDataSetRequest,
    user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    await _ensure_project_access(request.project_id, user, EDIT_ROLES, session)
    key = _normalize_key(request.key)
    dataset = TestDataSet(
        project_id=request.project_id,
        key=key,
        name=request.name.strip() or key,
        description=request.description.strip(),
        status=_normalize_status(request.status),
        format=_normalize_format(request.format),
    )
    dataset.tags = request.tags
    session.add(dataset)
    _commit_or_unique_error(session, "A test data dataset with this key already exists in the project")
    session.refresh(dataset)
    return _dataset_to_dict(dataset, item_count=0)


@router.get("/datasets/{dataset_id}")
async def get_dataset(
    dataset_id: str,
    project_id: str = Query(...),
    user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    dataset = _get_dataset_or_404(dataset_id, project_id, session)
    await _ensure_project_access(dataset.project_id, user, VIEW_ROLES, session)
    items = session.exec(select(TestDataItem).where(TestDataItem.dataset_id == dataset.id).order_by(TestDataItem.key)).all()
    return {**_dataset_to_dict(dataset, item_count=len(items)), "items": [_item_to_dict(dataset, item, session) for item in items]}


@router.put("/datasets/{dataset_id}")
async def update_dataset(
    dataset_id: str,
    request: TestDataSetUpdateRequest,
    project_id: str = Query(...),
    user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    dataset = _get_dataset_or_404(dataset_id, project_id, session)
    await _ensure_project_access(dataset.project_id, user, EDIT_ROLES, session)
    if request.key is not None:
        dataset.key = _normalize_key(request.key)
    if request.name is not None:
        dataset.name = request.name.strip() or dataset.key
    if request.description is not None:
        dataset.description = request.description.strip()
    if request.tags is not None:
        dataset.tags = request.tags
    if request.status is not None:
        dataset.status = _normalize_status(request.status)
    if request.format is not None:
        dataset.format = _normalize_format(request.format)
    dataset.updated_at = datetime.utcnow()
    session.add(dataset)
    _commit_or_unique_error(session, "A test data dataset with this key already exists in the project")
    session.refresh(dataset)
    return _dataset_to_dict(dataset)


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(
    dataset_id: str,
    project_id: str = Query(...),
    user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    dataset = _get_dataset_or_404(dataset_id, project_id, session)
    await _ensure_project_access(dataset.project_id, user, EDIT_ROLES, session)
    for item in session.exec(select(TestDataItem).where(TestDataItem.dataset_id == dataset.id)).all():
        session.delete(item)
    session.delete(dataset)
    session.commit()
    return {"status": "deleted", "id": dataset_id}


@router.get("/datasets/{dataset_id}/items")
async def list_items(
    dataset_id: str,
    project_id: str = Query(...),
    status: str | None = Query(default=None),
    user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    dataset = _get_dataset_or_404(dataset_id, project_id, session)
    await _ensure_project_access(dataset.project_id, user, VIEW_ROLES, session)
    stmt = select(TestDataItem).where(TestDataItem.dataset_id == dataset.id).order_by(TestDataItem.key)
    if status:
        stmt = stmt.where(TestDataItem.status == _normalize_status(status))
    items = session.exec(stmt).all()
    return {"items": [_item_to_dict(dataset, item, session) for item in items], "total": len(items)}


@router.post("/datasets/{dataset_id}/items", status_code=201)
async def create_item(
    dataset_id: str,
    request: TestDataItemRequest,
    project_id: str = Query(...),
    user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    dataset = _get_dataset_or_404(dataset_id, project_id, session)
    await _ensure_project_access(dataset.project_id, user, EDIT_ROLES, session)
    storage = prepare_test_data_item_storage(
        data=request.data,
        text=request.text,
        sensitive_fields=request.sensitive_fields,
    )
    item = TestDataItem(
        dataset_id=dataset.id,
        key=_normalize_key(request.key),
        name=request.name.strip(),
        description=request.description.strip(),
        status=_normalize_status(request.status),
        format=_normalize_format(request.format),
        data_text=storage["text"],
    )
    item.data = storage["data"]
    item.sensitive_fields = storage["sensitive_fields"]
    item.encrypted_values = storage["encrypted_values"]
    session.add(item)
    _commit_or_unique_error(session, "A test data item with this key already exists in the dataset")
    session.refresh(item)
    return _item_to_dict(dataset, item, session)


@router.put("/datasets/{dataset_id}/items/{item_id}")
async def update_item(
    dataset_id: str,
    item_id: str,
    request: TestDataItemUpdateRequest,
    project_id: str = Query(...),
    user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    dataset = _get_dataset_or_404(dataset_id, project_id, session)
    await _ensure_project_access(dataset.project_id, user, EDIT_ROLES, session)
    item = _get_item_or_404(item_id, dataset.id, session)
    if request.key is not None:
        item.key = _normalize_key(request.key)
    if request.name is not None:
        item.name = request.name.strip()
    if request.description is not None:
        item.description = request.description.strip()
    if request.status is not None:
        item.status = _normalize_status(request.status)
    if request.format is not None:
        item.format = _normalize_format(request.format)
    if request.replace_content:
        storage = prepare_test_data_item_storage(
            data=request.data,
            text=request.text,
            sensitive_fields=request.sensitive_fields or [],
        )
        item.data = storage["data"]
        item.data_text = storage["text"]
        item.sensitive_fields = storage["sensitive_fields"]
        item.encrypted_values = storage["encrypted_values"]
    item.updated_at = datetime.utcnow()
    session.add(item)
    _commit_or_unique_error(session, "A test data item with this key already exists in the dataset")
    session.refresh(item)
    return _item_to_dict(dataset, item, session)


@router.delete("/datasets/{dataset_id}/items/{item_id}")
async def delete_item(
    dataset_id: str,
    item_id: str,
    project_id: str = Query(...),
    user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    dataset = _get_dataset_or_404(dataset_id, project_id, session)
    await _ensure_project_access(dataset.project_id, user, EDIT_ROLES, session)
    item = _get_item_or_404(item_id, dataset.id, session)
    session.delete(item)
    session.commit()
    return {"status": "deleted", "id": item_id}


@router.post("/resolve")
async def resolve_refs(
    request: TestDataResolveRequest,
    user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    await _ensure_project_access(request.project_id, user, VIEW_ROLES, session)
    render_as = request.render_as if request.render_as in {"json", "markdown", "env", "masked_ui"} else "json"
    resolved = resolve_test_data_refs(
        session,
        project_id=request.project_id,
        refs=request.refs,
        render_as="json" if render_as == "masked_ui" else render_as,
        include_archived=request.include_archived,
        decrypt_sensitive=False,
    )
    if render_as == "masked_ui":
        resolved["masked_ui"] = resolved.get("json") or {}
    return resolved


@router.post("/resolve/spec")
async def resolve_spec_markdown(
    request: TestDataSpecResolveRequest,
    user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    await _ensure_project_access(request.project_id, user, VIEW_ROLES, session)
    return {
        "project_id": request.project_id,
        "content": resolve_testdata_in_markdown(
            request.content,
            session=session,
            project_id=request.project_id,
        ),
    }
