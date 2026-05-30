"""Recording Mode API backed by Playwright codegen."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import AnyHttpUrl, BaseModel, Field
from sqlmodel import Session, select

from services.recording_codegen import build_codegen_command, has_usable_codegen_output, read_codegen_failure
from services.recording_parser import import_recording_to_spec, slugify

from .db import engine, get_session
from .middleware.auth import get_current_user_optional
from .middleware.permissions import EDIT_ROLES, VIEW_ROLES, check_project_access
from .models_auth import User
from .models_db import Project, RecordingSession, SpecMetadata

router = APIRouter(prefix="/recordings", tags=["recordings"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
RUNS_DIR = BASE_DIR / "runs"
SPECS_DIR = BASE_DIR / "specs"
TESTS_RECORDINGS_DIR = BASE_DIR / "tests" / "recordings"

_ACTIVE_PROCESSES: dict[str, subprocess.Popen] = {}
_ACTIVE_LOCK = threading.Lock()


class RecordingStartRequest(BaseModel):
    target_url: AnyHttpUrl
    project_id: str | None = "default"
    name: str | None = Field(default=None, max_length=140)
    viewport_size: str | None = Field(default=None, pattern=r"^\d{2,5},\s?\d{2,5}$")
    device: str | None = None
    load_storage_path: str | None = None
    save_storage: bool = False
    save_har: bool = False


class RecordingImportRequest(BaseModel):
    name: str | None = Field(default=None, max_length=140)


class RecordingResponse(BaseModel):
    id: str
    project_id: str | None
    status: str
    target_url: str
    engine: str
    name: str | None
    output_spec_path: str | None
    output_code_path: str | None
    artifact_dir: str | None
    process_id: int | None
    browser_url: str | None = None
    error: str | None
    config: dict[str, Any]
    created_at: str
    started_at: str | None
    completed_at: str | None
    duration_seconds: int | None


class RecordingListResponse(BaseModel):
    items: list[RecordingResponse]
    total: int


class RecordingImportResponse(BaseModel):
    status: str
    session: RecordingResponse
    spec_path: str
    code_path: str
    parsed_steps: int
    unsupported_lines: int


@router.post("/start", response_model=RecordingResponse)
async def start_recording(
    request: RecordingStartRequest,
    current_user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    project_id = request.project_id or "default"
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    await check_project_access(project_id, current_user, EDIT_ROLES, session)
    _ensure_local_recorder_available()

    recording_id = f"recording_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    artifact_dir = RUNS_DIR / "recordings" / recording_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    code_path = artifact_dir / "recording.spec.ts"
    stdout_path = artifact_dir / "codegen.log"
    stderr_path = artifact_dir / "codegen.err.log"
    config = _build_config(request, artifact_dir)
    command = build_codegen_command(str(request.target_url), code_path, config)

    rec = RecordingSession(
        id=recording_id,
        project_id=project_id,
        status="starting",
        target_url=str(request.target_url),
        engine="playwright-codegen",
        name=request.name or _default_name(str(request.target_url)),
        output_code_path=_relative(code_path),
        artifact_dir=_relative(artifact_dir),
        config_json="{}",
        started_at=datetime.utcnow(),
    )
    rec.config = {**config, "command": command}
    session.add(rec)
    session.commit()
    session.refresh(rec)

    try:
        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
            process = subprocess.Popen(
                command,
                cwd=BASE_DIR,
                stdout=stdout,
                stderr=stderr,
                env=os.environ.copy(),
                start_new_session=True,
            )
    except Exception as exc:
        rec.status = "failed"
        rec.error = f"Failed to launch Playwright recorder: {exc}"
        rec.completed_at = datetime.utcnow()
        session.add(rec)
        session.commit()
        raise HTTPException(status_code=500, detail=rec.error) from exc

    rec.process_id = process.pid
    rec.status = "recording"
    session.add(rec)
    session.commit()
    session.refresh(rec)

    with _ACTIVE_LOCK:
        _ACTIVE_PROCESSES[recording_id] = process

    threading.Thread(target=_watch_recording_process, args=(recording_id, process, code_path), daemon=True).start()
    return _to_response(rec)


@router.get("", response_model=RecordingListResponse)
async def list_recordings(
    project_id: str | None = Query(default=None),
    current_user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    if project_id:
        await check_project_access(project_id, current_user, VIEW_ROLES, session)

    query = select(RecordingSession).order_by(RecordingSession.created_at.desc())
    if project_id:
        query = query.where(RecordingSession.project_id == project_id)
    items = session.exec(query.limit(50)).all()
    for rec in items:
        _refresh_status(rec, session)
    return RecordingListResponse(items=[_to_response(rec) for rec in items], total=len(items))


@router.get("/{recording_id}", response_model=RecordingResponse)
async def get_recording(
    recording_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    rec = _get_recording_or_404(recording_id, session)
    if rec.project_id:
        await check_project_access(rec.project_id, current_user, VIEW_ROLES, session)
    _refresh_status(rec, session)
    return _to_response(rec)


@router.post("/{recording_id}/stop", response_model=RecordingResponse)
async def stop_recording(
    recording_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    rec = _get_recording_or_404(recording_id, session)
    if rec.project_id:
        await check_project_access(rec.project_id, current_user, EDIT_ROLES, session)

    with _ACTIVE_LOCK:
        process = _ACTIVE_PROCESSES.get(recording_id)

    if process and process.poll() is None:
        _terminate_process(process)
    elif rec.process_id and _pid_exists(rec.process_id):
        _terminate_pid(rec.process_id)

    rec.status = "stopped"
    rec.completed_at = datetime.utcnow()
    session.add(rec)
    session.commit()
    session.refresh(rec)
    return _to_response(rec)


@router.get("/{recording_id}/code", response_class=PlainTextResponse)
async def get_recording_code(
    recording_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    rec = _get_recording_or_404(recording_id, session)
    if rec.project_id:
        await check_project_access(rec.project_id, current_user, VIEW_ROLES, session)
    if not rec.output_code_path:
        raise HTTPException(status_code=404, detail="Recording code not found")
    code_path = BASE_DIR / rec.output_code_path
    if not code_path.exists():
        raise HTTPException(status_code=404, detail="Recording code not found")
    return PlainTextResponse(code_path.read_text(encoding="utf-8"))


@router.post("/{recording_id}/import", response_model=RecordingImportResponse)
async def import_recording(
    recording_id: str,
    request: RecordingImportRequest | None = None,
    current_user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    rec = _get_recording_or_404(recording_id, session)
    if rec.project_id:
        await check_project_access(rec.project_id, current_user, EDIT_ROLES, session)
    _refresh_status(rec, session)

    if rec.status not in ("completed", "stopped"):
        raise HTTPException(status_code=400, detail="Recording must be completed or stopped before import")
    if not rec.output_code_path:
        raise HTTPException(status_code=400, detail="Recording has no generated Playwright code")

    artifact_code_path = BASE_DIR / rec.output_code_path
    if not artifact_code_path.exists() or artifact_code_path.stat().st_size == 0:
        raise HTTPException(status_code=400, detail="Generated Playwright code is missing or empty")

    title = (request.name if request else None) or rec.name or _default_name(rec.target_url)
    slug = _unique_slug(slugify(title), rec.project_id, session)
    spec_rel = Path("recordings") / f"{slug}.md"
    spec_path = SPECS_DIR / spec_rel
    code_rel = Path("tests") / "recordings" / f"{slug}.spec.ts"
    code_path = BASE_DIR / code_rel

    TESTS_RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    SPECS_DIR.joinpath("recordings").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(artifact_code_path, code_path)

    parsed, markdown = import_recording_to_spec(
        artifact_code_path,
        title=title,
        target_url=rec.target_url,
        source_code_path=str(code_rel),
    )
    spec_path.write_text(markdown, encoding="utf-8")

    rec.output_spec_path = str(spec_rel)
    rec.output_code_path = str(code_rel)
    session.add(rec)

    meta = session.get(SpecMetadata, str(spec_rel))
    if not meta:
        meta = SpecMetadata(spec_name=str(spec_rel), project_id=rec.project_id, tags_json='["recorded"]')
    else:
        meta.project_id = rec.project_id
        tags = set(meta.tags)
        tags.add("recorded")
        meta.tags = sorted(tags)
    meta.description = f"Imported from recording session {rec.id}"
    meta.last_modified = datetime.utcnow()
    session.add(meta)
    session.commit()
    session.refresh(rec)

    return RecordingImportResponse(
        status="imported",
        session=_to_response(rec),
        spec_path=str(spec_rel),
        code_path=str(code_rel),
        parsed_steps=len(parsed.steps),
        unsupported_lines=len(parsed.unsupported_lines),
    )


def _build_config(request: RecordingStartRequest, artifact_dir: Path) -> dict[str, Any]:
    config: dict[str, Any] = {}
    if request.viewport_size:
        config["viewport_size"] = request.viewport_size.replace(" ", "")
    if request.device:
        config["device"] = request.device
    if request.load_storage_path:
        storage = _resolve_project_path(request.load_storage_path)
        if not storage.exists():
            raise HTTPException(status_code=400, detail="Storage state file does not exist")
        config["load_storage_path"] = str(storage)
    if request.save_storage:
        config["save_storage_path"] = str(artifact_dir / "storage-state.json")
    if request.save_har:
        config["save_har_path"] = str(artifact_dir / "recording.har")
    return config


def _watch_recording_process(recording_id: str, process: subprocess.Popen, code_path: Path):
    process.wait()
    with _ACTIVE_LOCK:
        _ACTIVE_PROCESSES.pop(recording_id, None)

    with Session(engine) as session:
        rec = session.get(RecordingSession, recording_id)
        if not rec or rec.status == "stopped":
            return
        rec.completed_at = datetime.utcnow()
        if has_usable_codegen_output(code_path):
            rec.status = "completed"
            rec.error = None
        else:
            rec.status = "failed"
            rec.error = read_codegen_failure(code_path)
        session.add(rec)
        session.commit()


def _refresh_status(rec: RecordingSession, session: Session):
    if rec.status not in ("starting", "recording"):
        return

    with _ACTIVE_LOCK:
        process = _ACTIVE_PROCESSES.get(rec.id)
    if process and process.poll() is None:
        return
    if process and process.poll() is not None:
        code_path = BASE_DIR / rec.output_code_path if rec.output_code_path else None
        rec.completed_at = rec.completed_at or datetime.utcnow()
        rec.status = "completed" if code_path and has_usable_codegen_output(code_path) else "failed"
        rec.error = None if rec.status == "completed" else read_codegen_failure(code_path)
        session.add(rec)
        session.commit()
        session.refresh(rec)
        return

    if rec.process_id and _pid_exists(rec.process_id):
        return

    code_path = BASE_DIR / rec.output_code_path if rec.output_code_path else None
    rec.completed_at = rec.completed_at or datetime.utcnow()
    rec.status = "completed" if code_path and has_usable_codegen_output(code_path) else "failed"
    if rec.status == "failed":
        rec.error = read_codegen_failure(
            code_path, fallback="Recorder process is no longer running and no generated code was found"
        )
    session.add(rec)
    session.commit()
    session.refresh(rec)

def _ensure_local_recorder_available():
    if not shutil.which("npx"):
        raise HTTPException(status_code=500, detail="npx is required to launch Playwright codegen")
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        raise HTTPException(
            status_code=400,
            detail="Recording Mode v1 requires a local headed browser session. DISPLAY is not set.",
        )


def _terminate_process(process: subprocess.Popen):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except Exception:
        process.terminate()


def _terminate_pid(pid: int):
    try:
        os.killpg(pid, signal.SIGTERM)
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _get_recording_or_404(recording_id: str, session: Session) -> RecordingSession:
    rec = session.get(RecordingSession, recording_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")
    return rec


def _to_response(rec: RecordingSession) -> RecordingResponse:
    return RecordingResponse(
        id=rec.id,
        project_id=rec.project_id,
        status=rec.status,
        target_url=rec.target_url,
        engine=rec.engine,
        name=rec.name,
        output_spec_path=rec.output_spec_path,
        output_code_path=rec.output_code_path,
        artifact_dir=rec.artifact_dir,
        process_id=rec.process_id,
        browser_url=_recorder_browser_url(),
        error=rec.error,
        config=rec.config,
        created_at=rec.created_at.isoformat(),
        started_at=rec.started_at.isoformat() if rec.started_at else None,
        completed_at=rec.completed_at.isoformat() if rec.completed_at else None,
        duration_seconds=rec.duration_seconds,
    )


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(BASE_DIR.resolve()))


def _resolve_project_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path
    path = path.resolve()
    if not str(path).startswith(str(BASE_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Path must be inside the project workspace")
    return path


def _default_name(target_url: str) -> str:
    cleaned = target_url.replace("https://", "").replace("http://", "").strip("/")
    return f"Recorded flow for {cleaned or 'site'}"


def _recorder_browser_url() -> str | None:
    explicit = os.getenv("RECORDER_BROWSER_URL") or os.getenv("VNC_PUBLIC_URL")
    if explicit:
        return explicit
    if Path("/.dockerenv").exists() or os.getenv("VNC_ENABLED", "").lower() == "true":
        return "http://localhost:6080/vnc.html?autoconnect=true&resize=scale"
    return None


def _unique_slug(base_slug: str, project_id: str | None, session: Session) -> str:
    slug = base_slug
    counter = 2
    while (SPECS_DIR / "recordings" / f"{slug}.md").exists() or session.get(SpecMetadata, f"recordings/{slug}.md"):
        slug = f"{base_slug}-{counter}"
        counter += 1
    return slug
