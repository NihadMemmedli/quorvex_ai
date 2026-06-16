import io
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session

from logging_config import get_logger
from utils.spec_parser import parse_spec_file

from . import import_utils, spec_files
from .db import get_session
from .export_utils import generate_testrail_csv, generate_testrail_xml
from .models_db import get_spec_metadata as get_db_spec_metadata

logger = get_logger(__name__)
router = APIRouter()

SPECS_DIR = spec_files.SPECS_DIR

# File upload security constants
MAX_UPLOAD_SIZE_BYTES = 5_000_000  # 5MB
ALLOWED_UPLOAD_TYPES = {"text/csv", "application/csv", "text/markdown", "text/plain"}


class ExportTestrailRequest(BaseModel):
    spec_names: list[str]
    format: str = "xml"  # "xml" or "csv"
    separated_steps: bool = True
    project_id: str | None = None


@router.post("/import/testrail")
async def import_testrail(file: UploadFile = File(...)):
    # Security: Validate file size
    # Read content first to check size (UploadFile.size may not be reliable)
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413, detail=f"File exceeds maximum size of {MAX_UPLOAD_SIZE_BYTES // 1_000_000}MB"
        )

    # Security: Validate content type
    if file.content_type and file.content_type not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{file.content_type}'. Allowed: {', '.join(ALLOWED_UPLOAD_TYPES)}",
        )

    try:
        specs = import_utils.parse_testrail_csv(content)

        saved_files = []
        for spec in specs:
            fname = spec["name"]
            # Ensure safe filename
            if not fname.endswith(".md"):
                fname += ".md"

            # Security: Remove path components to prevent path traversal
            fname = Path(fname).name

            fpath = SPECS_DIR / fname
            # Ensure specs dir exists
            SPECS_DIR.mkdir(parents=True, exist_ok=True)

            fpath.write_text(spec["content"])
            saved_files.append(fname)

            # Sync to DB if needed?
            # The system syncs on startup, but maybe we should add to DB here too?
            # existing sync_data_from_files() logic runs at startup.
            # But the user might want to see them immediately.
            # However, spec metadata is separately managed.
            # The list_specs() endpoint reads from file system directly, so it should be fine.

        return {"count": len(saved_files), "files": saved_files}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/export/testrail")
def export_testrail(request: ExportTestrailRequest, session: Session = Depends(get_session)):
    """Export selected specs as TestRail-compatible XML or CSV file."""
    if not request.spec_names:
        raise HTTPException(status_code=400, detail="No specs selected for export")

    if request.format not in ("xml", "csv"):
        raise HTTPException(status_code=400, detail="Format must be 'xml' or 'csv'")

    all_cases = []
    for spec_name in request.spec_names:
        spec_path = SPECS_DIR / spec_name
        if not spec_path.exists():
            continue

        # Load DB metadata for tags
        metadata = None
        meta = get_db_spec_metadata(session, spec_name, request.project_id)
        if meta:
            metadata = {"tags": meta.tags}

        try:
            cases = parse_spec_file(spec_path, metadata=metadata, specs_dir=SPECS_DIR)
            all_cases.extend(cases)
        except Exception as e:
            logger.warning(f"Failed to parse spec {spec_name}: {e}")
            continue

    if not all_cases:
        raise HTTPException(status_code=400, detail="No test cases could be parsed from the selected specs")

    project_name = "Exported Tests"
    if request.project_id:
        project_name = request.project_id

    if request.format == "xml":
        content = generate_testrail_xml(all_cases, project_name=project_name)
        media_type = "application/xml"
        filename = "testrail-export.xml"
    else:
        content = generate_testrail_csv(all_cases, separated_steps=request.separated_steps)
        media_type = "text/csv"
        filename = "testrail-export.csv"

    return StreamingResponse(
        io.StringIO(content),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
