"""
Database Testing Router

Provides endpoints for managing PostgreSQL connection profiles, running schema analysis,
executing data quality checks, and tracking results with AI-powered suggestions.
"""

import asyncio
import json
import logging
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from .credentials import decrypt_credential, encrypt_credential
from .db import engine
from .models_db import DbConnection, DbTestCheck, DbTestRun

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SPECS_DIR = BASE_DIR / "specs"

router = APIRouter(prefix="/database-testing", tags=["database-testing"])

# ========== In-Memory Job Tracking ==========
_db_jobs: dict[str, dict] = {}
MAX_TRACKED_JOBS = 200


def _cleanup_old_jobs():
    """Remove completed/failed jobs older than 1 hour."""
    try:
        now = time.time()
        to_remove = []
        for job_id, job in _db_jobs.items():
            if job["status"] in ("completed", "failed", "cancelled"):
                completed_at = job.get("completed_at", 0)
                if now - completed_at > 3600:
                    to_remove.append(job_id)
        for job_id in to_remove:
            del _db_jobs[job_id]
        # Enforce hard cap
        if len(_db_jobs) > MAX_TRACKED_JOBS:
            sorted_jobs = sorted(_db_jobs.items(), key=lambda x: x[1].get("started_at", 0))
            for job_id, _ in sorted_jobs[: len(_db_jobs) - MAX_TRACKED_JOBS]:
                del _db_jobs[job_id]
    except Exception as e:
        logger.warning(f"Job cleanup error: {e}")


# ========== Pydantic Models ==========


class CreateConnectionRequest(BaseModel):
    name: str
    host: str
    port: int = 5432
    database: str
    username: str
    password: str
    ssl_mode: str = "prefer"
    schema_name: str = "public"
    is_read_only: bool = True
    project_id: str


class UpdateConnectionRequest(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    password: str | None = None
    ssl_mode: str | None = None
    schema_name: str | None = None
    is_read_only: bool | None = None


class CreateDbSpecRequest(BaseModel):
    name: str
    content: str
    project_id: str


class UpdateDbSpecRequest(BaseModel):
    content: str


class RunChecksRequest(BaseModel):
    spec_name: str
    project_id: str


class RunFullRequest(BaseModel):
    project_id: str


class SuggestRequest(BaseModel):
    project_id: str


class ApproveSuggestionsRequest(BaseModel):
    suggestions: list
    spec_name: str | None = None
    project_id: str


class GenerateSpecRequest(BaseModel):
    connection_id: str
    spec_name: str | None = None
    instructions: str | None = None
    focus_areas: list[str] | None = None
    auto_run: bool = False
    preview_only: bool = False
    project_id: str


class SaveGeneratedSpecRequest(BaseModel):
    checks: list
    spec_name: str | None = None
    project_id: str


class QueryDatabaseRequest(BaseModel):
    sql: str
    limit: int = 100


# ========== Helper Functions ==========


def _get_specs_dir(project_id: str = "default") -> Path:
    """Get database specs directory, optionally scoped by project."""
    if project_id and project_id != "default":
        d = SPECS_DIR / project_id / "database"
    else:
        d = SPECS_DIR / "database"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _scan_db_specs(project_id: str = "default") -> list[dict]:
    """Scan for database test spec markdown files, scoped to a single project."""
    specs = []
    d = _get_specs_dir(project_id)

    if not d.exists():
        return specs

    for md_file in sorted(d.rglob("*.md")):
        try:
            specs.append(
                {
                    "name": md_file.name,
                    "path": str(md_file.relative_to(BASE_DIR)),
                    "modified_at": datetime.fromtimestamp(md_file.stat().st_mtime).isoformat(),
                }
            )
        except Exception as e:
            logger.warning(f"Error scanning db spec {md_file}: {e}")

    return specs


def _generate_conn_id() -> str:
    return f"dbc-{uuid.uuid4().hex[:8]}"


def _generate_run_id() -> str:
    return f"dbt-{uuid.uuid4().hex[:8]}"


def _default_spec_name(seed: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", seed.lower()).strip("-")[:64] or "database-spec"
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M")
    return f"ai-generated-{slug}-{timestamp}.md"


def _normalize_spec_name(spec_name: str | None, seed: str) -> str:
    name = spec_name.strip() if spec_name else _default_spec_name(seed)
    return name if name.endswith(".md") else f"{name}.md"


def _checks_to_markdown(spec_name: str, checks: list) -> str:
    lines = [f"# Database Quality Checks: {spec_name.replace('.md', '')}", ""]
    for i, check in enumerate(checks, 1):
        if not isinstance(check, dict):
            continue
        lines.append(f"## Check {i}: {check.get('check_name', f'check_{i}')}")
        if check.get("description"):
            lines.append(f"**Description**: {check['description']}")
        lines.append(f"**Type**: {check.get('check_type', 'custom')}")
        lines.append(f"**Severity**: {check.get('severity', 'medium')}")
        if check.get("table_name"):
            lines.append(f"**Table**: {check['table_name']}")
        if check.get("column_name"):
            lines.append(f"**Column**: {check['column_name']}")
        lines.append(f"**Expect Empty**: {check.get('expect_empty', True)}")
        lines.append("")
        lines.append("```sql")
        lines.append(check.get("sql_query", "SELECT 1"))
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def _limit_read_query(sql: str, limit: int) -> str:
    clean_sql = sql.strip().rstrip(";").strip()
    if not clean_sql:
        raise HTTPException(status_code=400, detail="Query is empty")
    if ";" in clean_sql:
        raise HTTPException(status_code=400, detail="Only one read-only statement is allowed")

    bounded_limit = max(1, min(int(limit or 100), 500))
    upper = clean_sql.upper()
    if upper.startswith(("SELECT", "WITH")):
        return f"SELECT * FROM ({clean_sql}) AS qvx_query LIMIT {bounded_limit}"
    if upper.startswith("EXPLAIN"):
        return clean_sql
    return clean_sql


def _mask_connection(conn: DbConnection) -> dict:
    """Return connection dict with password masked."""
    return {
        "id": conn.id,
        "project_id": conn.project_id,
        "name": conn.name,
        "host": conn.host,
        "port": conn.port,
        "database": conn.database,
        "username": conn.username,
        "password": "********" if conn.password_encrypted else "",
        "ssl_mode": conn.ssl_mode,
        "schema_name": conn.schema_name,
        "is_read_only": conn.is_read_only,
        "last_tested_at": conn.last_tested_at.isoformat() if conn.last_tested_at else None,
        "last_test_success": conn.last_test_success,
        "last_test_error": conn.last_test_error,
        "created_at": conn.created_at.isoformat() if conn.created_at else None,
        "updated_at": conn.updated_at.isoformat() if conn.updated_at else None,
    }


def _get_connector(conn: DbConnection):
    """Create a DatabaseConnector from a DbConnection model."""
    from services.database.db_connector import DatabaseConnector

    password = decrypt_credential(conn.password_encrypted)
    return DatabaseConnector(
        host=conn.host,
        port=conn.port,
        database=conn.database,
        username=conn.username,
        password=password,
        ssl_mode=conn.ssl_mode,
        schema_name=conn.schema_name,
        is_read_only=conn.is_read_only,
    )


def _project_scope(model, project_id: str):
    if project_id == "default":
        return (model.project_id == "default") | (model.project_id == None)
    return model.project_id == project_id


def _get_connection_for_project(session: Session, conn_id: str, project_id: str) -> DbConnection | None:
    return session.exec(
        select(DbConnection).where(DbConnection.id == conn_id, _project_scope(DbConnection, project_id))
    ).first()


def _get_run_for_project(session: Session, run_id: str, project_id: str) -> DbTestRun | None:
    return session.exec(
        select(DbTestRun).where(DbTestRun.id == run_id, _project_scope(DbTestRun, project_id))
    ).first()


def _get_spec_path_for_project(spec_name: str, project_id: str) -> Path | None:
    specs_dir = _get_specs_dir(project_id)
    if specs_dir.exists():
        for md_file in specs_dir.rglob("*.md"):
            if md_file.name == spec_name:
                return md_file
    return None


# ========== Background Job Runners ==========


async def _run_schema_analysis_job(job_id: str, run_id: str, conn_id: str, project_id: str):
    """Background task for schema analysis."""
    _db_jobs[job_id]["status"] = "running"
    _db_jobs[job_id]["started_at"] = time.time()

    try:
        # Update DB status
        with Session(engine) as session:
            run = _get_run_for_project(session, run_id, project_id)
            if run:
                run.status = "running"
                run.started_at = datetime.utcnow()
                run.current_stage = "connecting"
                run.stage_message = "Connecting to database..."
                session.add(run)
                session.commit()

        # Get connection details
        with Session(engine) as session:
            conn = _get_connection_for_project(session, conn_id, project_id)
            if not conn:
                raise RuntimeError(f"Connection '{conn_id}' not found")
            connector = _get_connector(conn)

        # Connect and introspect
        with Session(engine) as session:
            run = _get_run_for_project(session, run_id, project_id)
            if run:
                run.current_stage = "introspecting"
                run.stage_message = "Introspecting database schema..."
                session.add(run)
                session.commit()

        await connector.connect()
        try:
            schema_data = await connector.introspect_schema()
        finally:
            await connector.close()

        # Save schema snapshot
        with Session(engine) as session:
            run = _get_run_for_project(session, run_id, project_id)
            if run:
                run.schema_snapshot_json = json.dumps(schema_data)
                run.current_stage = "analyzing"
                run.stage_message = f"AI analyzing {len(schema_data.get('tables', []))} tables..."
                session.add(run)
                session.commit()

        # AI analysis
        findings = None
        ai_error = None
        try:
            from workflows.db_schema_analyzer import analyze_schema

            findings = await analyze_schema(schema_data)

            with Session(engine) as session:
                run = _get_run_for_project(session, run_id, project_id)
                if run:
                    run.schema_findings_json = json.dumps(findings)
                    run.ai_summary = findings.get("summary", "") if isinstance(findings, dict) else ""
                    # Set severity counts from AI findings
                    if isinstance(findings, dict):
                        finding_list = findings.get("findings", [])
                        sev_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
                        for f in finding_list:
                            sev = f.get("severity", "info").lower()
                            if sev in sev_counts:
                                sev_counts[sev] += 1
                        run.critical_count = sev_counts["critical"]
                        run.high_count = sev_counts["high"]
                        run.medium_count = sev_counts["medium"]
                        run.low_count = sev_counts["low"]
                        run.info_count = sev_counts["info"]
                        run.total_checks = len(finding_list)
                    session.add(run)
                    session.commit()
        except ImportError:
            ai_error = "db_schema_analyzer module not available"
            logger.warning(ai_error)
        except Exception as e:
            ai_error = str(e)
            logger.error(f"AI schema analysis failed: {e}")

        # Mark completed
        tables_found = len(schema_data.get("tables", []))
        with Session(engine) as session:
            run = _get_run_for_project(session, run_id, project_id)
            if run:
                run.status = "completed"
                run.completed_at = datetime.utcnow()
                run.current_stage = "done"
                if ai_error:
                    run.stage_message = (
                        f"Schema introspected ({tables_found} tables) but AI analysis failed: {ai_error}"
                    )
                    run.error_message = f"AI analysis failed: {ai_error}"
                else:
                    run.stage_message = f"Schema analysis complete - {tables_found} tables found"
                session.add(run)
                session.commit()

        # Include findings in job result so frontend can display them
        job_result: dict = {"tables_found": tables_found}
        if findings and isinstance(findings, dict):
            job_result["findings"] = findings.get("findings", [])
            job_result["summary"] = findings.get("summary", "")
            job_result["health_score"] = findings.get("health_score", 50)
        if ai_error:
            job_result["ai_error"] = ai_error

        _db_jobs[job_id]["status"] = "completed"
        _db_jobs[job_id]["completed_at"] = time.time()
        _db_jobs[job_id]["result"] = job_result

    except Exception as e:
        logger.error(f"Schema analysis failed: {e}")
        with Session(engine) as session:
            run = _get_run_for_project(session, run_id, project_id)
            if run:
                run.status = "failed"
                run.error_message = str(e)
                run.completed_at = datetime.utcnow()
                session.add(run)
                session.commit()
        _db_jobs[job_id]["status"] = "failed"
        _db_jobs[job_id]["error"] = str(e)
        _db_jobs[job_id]["completed_at"] = time.time()


async def _run_data_quality_job(job_id: str, run_id: str, conn_id: str, spec_name: str, project_id: str):
    """Background task for data quality checks from a spec."""
    _db_jobs[job_id]["status"] = "running"
    _db_jobs[job_id]["started_at"] = time.time()

    try:
        # Update DB status
        with Session(engine) as session:
            run = _get_run_for_project(session, run_id, project_id)
            if run:
                run.status = "running"
                run.started_at = datetime.utcnow()
                run.current_stage = "parsing"
                run.stage_message = "Parsing spec file..."
                session.add(run)
                session.commit()

        # Parse spec to checks
        try:
            from workflows.db_spec_parser import parse_spec_to_checks
        except ImportError:
            raise RuntimeError("db_spec_parser workflow not available")

        specs_dir = _get_specs_dir(project_id)
        spec_path = specs_dir / spec_name
        if not spec_path.exists():
            raise RuntimeError(f"Spec '{spec_name}' not found")

        spec_content = spec_path.read_text(encoding="utf-8")
        checks = await parse_spec_to_checks(spec_content)

        if not checks:
            raise RuntimeError("No checks parsed from spec")

        # Get connection
        with Session(engine) as session:
            conn = _get_connection_for_project(session, conn_id, project_id)
            if not conn:
                raise RuntimeError(f"Connection '{conn_id}' not found")
            connector = _get_connector(conn)

        # Connect
        with Session(engine) as session:
            run = _get_run_for_project(session, run_id, project_id)
            if run:
                run.current_stage = "connecting"
                run.stage_message = "Connecting to database..."
                run.total_checks = len(checks)
                session.add(run)
                session.commit()

        await connector.connect()

        try:
            passed = 0
            failed = 0
            errors = 0
            severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}

            for i, check in enumerate(checks):
                with Session(engine) as session:
                    run = _get_run_for_project(session, run_id, project_id)
                    if run:
                        run.current_stage = "executing"
                        run.stage_message = f"Running check {i + 1}/{len(checks)}: {check.get('check_name', 'unknown')}"
                        session.add(run)
                        session.commit()

                check_record = DbTestCheck(
                    run_id=run_id,
                    project_id=project_id,
                    check_name=check.get("check_name", f"check_{i + 1}"),
                    check_type=check.get("check_type", "custom"),
                    table_name=check.get("table_name"),
                    column_name=check.get("column_name"),
                    description=check.get("description"),
                    sql_query=check.get("sql_query", ""),
                    severity=check.get("severity", "medium"),
                    expected_result=check.get("expected_result"),
                    status="pending",
                )

                try:
                    result = await connector.execute_check(check["sql_query"])
                    check_record.row_count = result["row_count"]
                    check_record.sample_data_json = json.dumps(result["sample_data"])
                    check_record.actual_result = (
                        json.dumps(result["sample_data"][:3]) if result["sample_data"] else "[]"
                    )
                    check_record.execution_time_ms = result["execution_time_ms"]

                    # Determine pass/fail: checks typically fail if they return rows
                    # (e.g., "find nulls in non-nullable column" returns rows = fail)
                    expect_empty = check.get("expect_empty", True)
                    if expect_empty:
                        check_record.status = "passed" if result["row_count"] == 0 else "failed"
                    else:
                        check_record.status = "passed" if result["row_count"] > 0 else "failed"

                    if check_record.status == "passed":
                        passed += 1
                    else:
                        failed += 1
                        severity_counts[check_record.severity] = severity_counts.get(check_record.severity, 0) + 1

                except Exception as e:
                    check_record.status = "error"
                    check_record.error_message = str(e)
                    errors += 1

                with Session(engine) as session:
                    session.add(check_record)
                    session.commit()

        finally:
            await connector.close()

        # Update run with results
        with Session(engine) as session:
            run = _get_run_for_project(session, run_id, project_id)
            if run:
                run.status = "completed"
                run.completed_at = datetime.utcnow()
                run.passed_checks = passed
                run.failed_checks = failed
                run.error_checks = errors
                run.critical_count = severity_counts["critical"]
                run.high_count = severity_counts["high"]
                run.medium_count = severity_counts["medium"]
                run.low_count = severity_counts["low"]
                run.info_count = severity_counts["info"]
                run.current_stage = "done"
                run.stage_message = f"Completed: {passed} passed, {failed} failed, {errors} errors"
                session.add(run)
                session.commit()

        _db_jobs[job_id]["status"] = "completed"
        _db_jobs[job_id]["completed_at"] = time.time()
        _db_jobs[job_id]["result"] = {"passed": passed, "failed": failed, "errors": errors}

    except Exception as e:
        logger.error(f"Data quality job failed: {e}")
        with Session(engine) as session:
            run = _get_run_for_project(session, run_id, project_id)
            if run:
                run.status = "failed"
                run.error_message = str(e)
                run.completed_at = datetime.utcnow()
                session.add(run)
                session.commit()
        _db_jobs[job_id]["status"] = "failed"
        _db_jobs[job_id]["error"] = str(e)
        _db_jobs[job_id]["completed_at"] = time.time()


async def _run_full_pipeline_job(job_id: str, run_id: str, conn_id: str, project_id: str):
    """Background task for full pipeline: schema analysis + suggest tests + execute."""
    _db_jobs[job_id]["status"] = "running"
    _db_jobs[job_id]["started_at"] = time.time()

    try:
        # Update DB status
        with Session(engine) as session:
            run = _get_run_for_project(session, run_id, project_id)
            if run:
                run.status = "running"
                run.started_at = datetime.utcnow()
                run.current_stage = "connecting"
                run.stage_message = "Connecting to database..."
                session.add(run)
                session.commit()

        # Get connection details
        with Session(engine) as session:
            conn = _get_connection_for_project(session, conn_id, project_id)
            if not conn:
                raise RuntimeError(f"Connection '{conn_id}' not found")
            connector = _get_connector(conn)

        # Phase 1: Connect and introspect
        with Session(engine) as session:
            run = _get_run_for_project(session, run_id, project_id)
            if run:
                run.current_stage = "introspecting"
                run.stage_message = "Introspecting database schema..."
                session.add(run)
                session.commit()

        await connector.connect()
        try:
            schema_data = await connector.introspect_schema()
        except Exception:
            await connector.close()
            raise

        with Session(engine) as session:
            run = _get_run_for_project(session, run_id, project_id)
            if run:
                run.schema_snapshot_json = json.dumps(schema_data)
                session.add(run)
                session.commit()

        # Phase 2: AI analysis
        with Session(engine) as session:
            run = _get_run_for_project(session, run_id, project_id)
            if run:
                run.current_stage = "analyzing"
                run.stage_message = f"AI analyzing {len(schema_data.get('tables', []))} tables..."
                session.add(run)
                session.commit()

        checks = []
        try:
            from workflows.db_schema_analyzer import analyze_schema

            findings = await analyze_schema(schema_data)
            with Session(engine) as session:
                run = _get_run_for_project(session, run_id, project_id)
                if run:
                    run.schema_findings_json = json.dumps(findings)
                    run.ai_summary = findings.get("summary", "") if isinstance(findings, dict) else ""
                    session.add(run)
                    session.commit()
        except ImportError:
            logger.warning("db_schema_analyzer not available, skipping AI analysis")
        except Exception as e:
            logger.warning(f"AI schema analysis failed: {e}")

        # Phase 3: Generate test suggestions
        with Session(engine) as session:
            run = _get_run_for_project(session, run_id, project_id)
            if run:
                run.current_stage = "generating"
                run.stage_message = "Generating data quality checks..."
                session.add(run)
                session.commit()

        try:
            from workflows.db_test_generator import generate_tests_from_schema

            # Pass findings from earlier schema analysis for context
            schema_findings = None
            with Session(engine) as session:
                run = _get_run_for_project(session, run_id, project_id)
                if run and run.schema_findings_json:
                    try:
                        parsed = json.loads(run.schema_findings_json)
                        schema_findings = parsed.get("findings") if isinstance(parsed, dict) else parsed
                    except json.JSONDecodeError:
                        pass
            checks = await generate_tests_from_schema(schema_data, findings=schema_findings)
            with Session(engine) as session:
                run = _get_run_for_project(session, run_id, project_id)
                if run:
                    run.ai_suggestions_json = json.dumps(checks)
                    run.total_checks = len(checks)
                    session.add(run)
                    session.commit()
        except ImportError:
            logger.warning("db_test_generator not available, skipping test generation")
        except Exception as e:
            logger.warning(f"Test generation failed: {e}")

        # Phase 4: Execute generated checks
        if checks:
            with Session(engine) as session:
                run = _get_run_for_project(session, run_id, project_id)
                if run:
                    run.current_stage = "executing"
                    run.stage_message = f"Executing {len(checks)} data quality checks..."
                    session.add(run)
                    session.commit()

            passed = 0
            failed = 0
            errors = 0
            severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}

            for i, check in enumerate(checks):
                check_record = DbTestCheck(
                    run_id=run_id,
                    project_id=project_id,
                    check_name=check.get("check_name", f"check_{i + 1}"),
                    check_type=check.get("check_type", "custom"),
                    table_name=check.get("table_name"),
                    column_name=check.get("column_name"),
                    description=check.get("description"),
                    sql_query=check.get("sql_query", ""),
                    severity=check.get("severity", "medium"),
                    expected_result=check.get("expected_result"),
                    status="pending",
                )

                try:
                    result = await connector.execute_check(check["sql_query"])
                    check_record.row_count = result["row_count"]
                    check_record.sample_data_json = json.dumps(result["sample_data"])
                    check_record.actual_result = (
                        json.dumps(result["sample_data"][:3]) if result["sample_data"] else "[]"
                    )
                    check_record.execution_time_ms = result["execution_time_ms"]

                    expect_empty = check.get("expect_empty", True)
                    if expect_empty:
                        check_record.status = "passed" if result["row_count"] == 0 else "failed"
                    else:
                        check_record.status = "passed" if result["row_count"] > 0 else "failed"

                    if check_record.status == "passed":
                        passed += 1
                    else:
                        failed += 1
                        severity_counts[check_record.severity] = severity_counts.get(check_record.severity, 0) + 1

                except Exception as e:
                    check_record.status = "error"
                    check_record.error_message = str(e)
                    errors += 1

                with Session(engine) as session:
                    session.add(check_record)
                    session.commit()

            with Session(engine) as session:
                run = _get_run_for_project(session, run_id, project_id)
                if run:
                    run.passed_checks = passed
                    run.failed_checks = failed
                    run.error_checks = errors
                    run.critical_count = severity_counts["critical"]
                    run.high_count = severity_counts["high"]
                    run.medium_count = severity_counts["medium"]
                    run.low_count = severity_counts["low"]
                    run.info_count = severity_counts["info"]
                    session.add(run)
                    session.commit()

        await connector.close()

        # Mark completed
        with Session(engine) as session:
            run = _get_run_for_project(session, run_id, project_id)
            if run:
                run.status = "completed"
                run.completed_at = datetime.utcnow()
                run.current_stage = "done"
                run.stage_message = "Full pipeline complete"
                session.add(run)
                session.commit()

        _db_jobs[job_id]["status"] = "completed"
        _db_jobs[job_id]["completed_at"] = time.time()
        _db_jobs[job_id]["result"] = {"checks_run": len(checks)}

    except Exception as e:
        logger.error(f"Full pipeline failed: {e}")
        with Session(engine) as session:
            run = _get_run_for_project(session, run_id, project_id)
            if run:
                run.status = "failed"
                run.error_message = str(e)
                run.completed_at = datetime.utcnow()
                session.add(run)
                session.commit()
        _db_jobs[job_id]["status"] = "failed"
        _db_jobs[job_id]["error"] = str(e)
        _db_jobs[job_id]["completed_at"] = time.time()


async def _run_suggestion_job(job_id: str, run_id: str, project_id: str):
    """Background task for generating AI suggestions from schema findings."""
    _db_jobs[job_id]["status"] = "running"
    _db_jobs[job_id]["started_at"] = time.time()

    try:
        with Session(engine) as session:
            run = _get_run_for_project(session, run_id, project_id)
            if not run:
                raise RuntimeError(f"Run '{run_id}' not found")
            if not run.schema_snapshot_json:
                raise RuntimeError("No schema snapshot available. Run schema analysis first.")
            schema_data = json.loads(run.schema_snapshot_json)

            run.current_stage = "generating"
            run.stage_message = "AI generating test suggestions..."
            session.add(run)
            session.commit()

        from workflows.db_test_generator import generate_tests_from_schema

        # Pass findings for context if available
        schema_findings = None
        with Session(engine) as session:
            run_obj = _get_run_for_project(session, run_id, project_id)
            if run_obj and run_obj.schema_findings_json:
                try:
                    parsed = json.loads(run_obj.schema_findings_json)
                    schema_findings = parsed.get("findings") if isinstance(parsed, dict) else parsed
                except json.JSONDecodeError:
                    pass
        suggestions = await generate_tests_from_schema(schema_data, findings=schema_findings)

        with Session(engine) as session:
            run = _get_run_for_project(session, run_id, project_id)
            if run:
                run.ai_suggestions_json = json.dumps(suggestions)
                run.current_stage = "done"
                run.stage_message = f"Generated {len(suggestions)} test suggestions"
                session.add(run)
                session.commit()

        _db_jobs[job_id]["status"] = "completed"
        _db_jobs[job_id]["completed_at"] = time.time()
        _db_jobs[job_id]["result"] = {"suggestions_count": len(suggestions), "suggestions": suggestions}

    except ImportError:
        logger.error("db_test_generator workflow not available")
        _db_jobs[job_id]["status"] = "failed"
        _db_jobs[job_id]["error"] = "db_test_generator workflow not implemented"
        _db_jobs[job_id]["completed_at"] = time.time()
    except Exception as e:
        logger.error(f"Suggestion generation failed for run {run_id}: {e}")
        _db_jobs[job_id]["status"] = "failed"
        _db_jobs[job_id]["error"] = str(e)
        _db_jobs[job_id]["completed_at"] = time.time()


async def _run_generate_spec_job(
    job_id: str,
    conn_id: str,
    spec_name: str,
    project_id: str,
    instructions: str | None = None,
    focus_areas: list[str] | None = None,
    auto_run: bool = False,
    preview_only: bool = False,
):
    """Background task: introspect schema -> AI analyze -> AI generate checks -> preview or save."""
    _db_jobs[job_id]["status"] = "running"
    _db_jobs[job_id]["started_at"] = time.time()

    try:
        # Stage 1: Connect
        _db_jobs[job_id]["stage_message"] = "Connecting to database..."
        with Session(engine) as session:
            conn = _get_connection_for_project(session, conn_id, project_id)
            if not conn:
                raise RuntimeError(f"Connection '{conn_id}' not found")
            connector = _get_connector(conn)

        await connector.connect()

        # Stage 2: Introspect
        _db_jobs[job_id]["stage_message"] = "Introspecting database schema..."
        try:
            schema_data = await connector.introspect_schema()
        finally:
            await connector.close()

        tables_count = len(schema_data.get("tables", []))
        _db_jobs[job_id]["stage_message"] = f"Schema introspected: {tables_count} tables found"

        # Stage 3: AI analysis (non-fatal)
        findings = None
        try:
            _db_jobs[job_id]["stage_message"] = f"AI analyzing {tables_count} tables..."
            from workflows.db_schema_analyzer import analyze_schema

            analysis_result = await analyze_schema(schema_data)
            if isinstance(analysis_result, dict):
                findings = analysis_result.get("findings", [])
            elif isinstance(analysis_result, list):
                findings = analysis_result
        except Exception as e:
            logger.warning(f"AI schema analysis failed (non-fatal): {e}")

        # Stage 4: Generate checks
        _db_jobs[job_id]["stage_message"] = "AI generating data quality checks..."
        from workflows.db_test_generator import generate_tests_from_schema

        checks = await generate_tests_from_schema(
            schema_data,
            findings=findings,
            focus_areas=focus_areas,
            instructions=instructions,
        )

        if not checks:
            raise RuntimeError("AI produced no valid checks")

        # Stage 5: Format as markdown spec
        _db_jobs[job_id]["stage_message"] = f"Formatting {len(checks)} checks as spec..."
        content = _checks_to_markdown(spec_name, checks)

        job_result: dict = {
            "spec_name": spec_name,
            "checks_count": len(checks),
            "tables_analyzed": tables_count,
            "checks": checks,
            "content": content,
            "preview_only": preview_only,
        }

        # Stage 6: Save spec file unless caller asked for a review preview first
        if not preview_only:
            _db_jobs[job_id]["stage_message"] = "Saving spec file..."
            specs_dir = _get_specs_dir(project_id)
            target = specs_dir / spec_name
            target.write_text(content, encoding="utf-8")
            logger.info(f"AI-generated spec saved: {target}")
            job_result["path"] = str(target.relative_to(BASE_DIR))

        # Stage 7 (optional): Auto-run
        if auto_run and not preview_only:
            _db_jobs[job_id]["stage_message"] = f"Executing {len(checks)} checks..."
            try:
                from workflows.db_spec_parser import parse_spec_to_checks

                parsed_checks = await parse_spec_to_checks(content)

                run_id = _generate_run_id()
                with Session(engine) as session:
                    run = DbTestRun(
                        id=run_id,
                        connection_id=conn_id,
                        project_id=project_id,
                        spec_name=spec_name,
                        run_type="data_quality",
                        status="running",
                        current_stage="executing",
                        stage_message=f"Executing {len(parsed_checks)} checks...",
                        total_checks=len(parsed_checks),
                        started_at=datetime.utcnow(),
                    )
                    session.add(run)
                    session.commit()

                # Re-connect for execution
                with Session(engine) as session:
                    conn = _get_connection_for_project(session, conn_id, project_id)
                    if not conn:
                        raise RuntimeError(f"Connection '{conn_id}' not found for auto-run")
                    exec_connector = _get_connector(conn)

                await exec_connector.connect()
                passed = 0
                failed = 0
                errors = 0
                try:
                    for i, check in enumerate(parsed_checks):
                        check_record = DbTestCheck(
                            run_id=run_id,
                            project_id=project_id,
                            check_name=check.get("check_name", f"check_{i + 1}"),
                            check_type=check.get("check_type", "custom"),
                            table_name=check.get("table_name"),
                            column_name=check.get("column_name"),
                            description=check.get("description"),
                            sql_query=check.get("sql_query", ""),
                            severity=check.get("severity", "medium"),
                            expected_result=check.get("expected_result"),
                            status="pending",
                        )
                        try:
                            result = await exec_connector.execute_check(check["sql_query"])
                            check_record.row_count = result["row_count"]
                            check_record.sample_data_json = json.dumps(result["sample_data"])
                            check_record.actual_result = (
                                json.dumps(result["sample_data"][:3]) if result["sample_data"] else "[]"
                            )
                            check_record.execution_time_ms = result["execution_time_ms"]
                            expect_empty = check.get("expect_empty", True)
                            if expect_empty:
                                check_record.status = "passed" if result["row_count"] == 0 else "failed"
                            else:
                                check_record.status = "passed" if result["row_count"] > 0 else "failed"
                            if check_record.status == "passed":
                                passed += 1
                            else:
                                failed += 1
                        except Exception as e:
                            check_record.status = "error"
                            check_record.error_message = str(e)
                            errors += 1

                        with Session(engine) as session:
                            session.add(check_record)
                            session.commit()
                finally:
                    await exec_connector.close()

                with Session(engine) as session:
                    run = _get_run_for_project(session, run_id, project_id)
                    if run:
                        run.status = "completed"
                        run.completed_at = datetime.utcnow()
                        run.passed_checks = passed
                        run.failed_checks = failed
                        run.error_checks = errors
                        run.current_stage = "done"
                        run.stage_message = f"Completed: {passed} passed, {failed} failed, {errors} errors"
                        session.add(run)
                        session.commit()

                job_result["execution_run_id"] = run_id
                job_result["passed"] = passed
                job_result["failed"] = failed
                job_result["errors"] = errors
            except Exception as e:
                logger.error(f"Auto-run failed (spec already saved): {e}")
                job_result["auto_run_error"] = str(e)

        _db_jobs[job_id]["status"] = "completed"
        _db_jobs[job_id]["completed_at"] = time.time()
        _db_jobs[job_id]["result"] = job_result
        _db_jobs[job_id]["stage_message"] = (
            "Spec preview generated successfully" if preview_only else "Spec generated successfully"
        )

    except Exception as e:
        logger.error(f"Generate spec job failed: {e}")
        _db_jobs[job_id]["status"] = "failed"
        _db_jobs[job_id]["error"] = str(e)
        _db_jobs[job_id]["completed_at"] = time.time()
        _db_jobs[job_id]["stage_message"] = f"Failed: {e}"


# ========== Connection CRUD Endpoints ==========


@router.post("/connections")
async def create_connection(req: CreateConnectionRequest):
    """Create a new database connection profile."""
    conn_id = _generate_conn_id()
    project_id = req.project_id

    conn = DbConnection(
        id=conn_id,
        project_id=project_id,
        name=req.name,
        host=req.host,
        port=req.port,
        database=req.database,
        username=req.username,
        password_encrypted=encrypt_credential(req.password),
        ssl_mode=req.ssl_mode,
        schema_name=req.schema_name,
        is_read_only=req.is_read_only,
    )

    with Session(engine) as session:
        session.add(conn)
        session.commit()
        session.refresh(conn)

    logger.info(f"Created database connection: {conn_id} ({req.name})")
    return _mask_connection(conn)


@router.get("/connections")
async def list_connections(
    project_id: str = Query(...),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """List all database connections for a project."""
    with Session(engine) as session:
        statement = select(DbConnection).where(DbConnection.project_id == project_id)
        statement = statement.order_by(DbConnection.created_at.desc())
        connections = session.exec(statement.offset(offset).limit(limit)).all()

    return [_mask_connection(c) for c in connections]


@router.get("/connections/{conn_id}")
async def get_connection(conn_id: str, project_id: str = Query(...)):
    """Get a single database connection profile."""
    with Session(engine) as session:
        conn = _get_connection_for_project(session, conn_id, project_id)
        if not conn:
            raise HTTPException(status_code=404, detail=f"Connection '{conn_id}' not found")
        return _mask_connection(conn)


@router.put("/connections/{conn_id}")
async def update_connection(conn_id: str, req: UpdateConnectionRequest, project_id: str = Query(...)):
    """Update a database connection profile."""
    with Session(engine) as session:
        conn = _get_connection_for_project(session, conn_id, project_id)
        if not conn:
            raise HTTPException(status_code=404, detail=f"Connection '{conn_id}' not found")

        if req.name is not None:
            conn.name = req.name
        if req.host is not None:
            conn.host = req.host
        if req.port is not None:
            conn.port = req.port
        if req.database is not None:
            conn.database = req.database
        if req.username is not None:
            conn.username = req.username
        if req.password is not None:
            conn.password_encrypted = encrypt_credential(req.password)
        if req.ssl_mode is not None:
            conn.ssl_mode = req.ssl_mode
        if req.schema_name is not None:
            conn.schema_name = req.schema_name
        if req.is_read_only is not None:
            conn.is_read_only = req.is_read_only

        conn.updated_at = datetime.utcnow()
        session.add(conn)
        session.commit()
        session.refresh(conn)

        return _mask_connection(conn)


@router.delete("/connections/{conn_id}")
async def delete_connection(conn_id: str, project_id: str = Query(...)):
    """Delete a database connection profile."""
    with Session(engine) as session:
        conn = _get_connection_for_project(session, conn_id, project_id)
        if not conn:
            raise HTTPException(status_code=404, detail=f"Connection '{conn_id}' not found")
        session.delete(conn)
        session.commit()

    return {"message": f"Connection '{conn_id}' deleted"}


@router.post("/connections/{conn_id}/test")
async def test_connection(conn_id: str, project_id: str = Query(...)):
    """Test a database connection."""
    with Session(engine) as session:
        conn = _get_connection_for_project(session, conn_id, project_id)
        if not conn:
            raise HTTPException(status_code=404, detail=f"Connection '{conn_id}' not found")
        connector = _get_connector(conn)

    try:
        server_info = await connector.connect()
        await connector.close()

        with Session(engine) as session:
            conn = _get_connection_for_project(session, conn_id, project_id)
            if conn:
                conn.last_tested_at = datetime.utcnow()
                conn.last_test_success = True
                conn.last_test_error = None
                session.add(conn)
                session.commit()

        return {"success": True, "server_info": server_info}

    except Exception as e:
        with Session(engine) as session:
            conn = _get_connection_for_project(session, conn_id, project_id)
            if conn:
                conn.last_tested_at = datetime.utcnow()
                conn.last_test_success = False
                conn.last_test_error = str(e)
                session.add(conn)
                session.commit()

        raise HTTPException(status_code=400, detail=f"Connection test failed: {e}")


# ========== Database Viewer Endpoints ==========


@router.get("/connections/{conn_id}/schema")
async def get_connection_schema(conn_id: str, project_id: str = Query(...)):
    """Introspect a connection and return its live schema without creating a run."""
    with Session(engine) as session:
        conn = _get_connection_for_project(session, conn_id, project_id)
        if not conn:
            raise HTTPException(status_code=404, detail=f"Connection '{conn_id}' not found")
        connector = _get_connector(conn)

    try:
        await connector.connect()
        try:
            schema_data = await connector.introspect_schema()
        finally:
            await connector.close()
        return {
            "connection_id": conn_id,
            "schema": schema_data,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Schema introspection failed: {e}")


@router.post("/connections/{conn_id}/query")
async def query_connection(conn_id: str, req: QueryDatabaseRequest, project_id: str = Query(...)):
    """Run a bounded read-only query for the DB viewer."""
    with Session(engine) as session:
        conn = _get_connection_for_project(session, conn_id, project_id)
        if not conn:
            raise HTTPException(status_code=404, detail=f"Connection '{conn_id}' not found")
        connector = _get_connector(conn)

    sql = _limit_read_query(req.sql, req.limit)
    try:
        await connector.connect()
        try:
            result = await connector.execute_read_query(sql, req.limit)
        finally:
            await connector.close()
        return {
            "connection_id": conn_id,
            "sql": sql,
            **result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Query failed: {e}")


# ========== Schema Analysis Endpoints ==========


@router.post("/analyze/{conn_id}")
async def start_schema_analysis(conn_id: str, project_id: str = Query(...)):
    """Start schema analysis as a background job."""
    _cleanup_old_jobs()

    with Session(engine) as session:
        conn = _get_connection_for_project(session, conn_id, project_id)
        if not conn:
            raise HTTPException(status_code=404, detail=f"Connection '{conn_id}' not found")

    run_id = _generate_run_id()
    job_id = f"job-{uuid.uuid4().hex[:8]}"

    with Session(engine) as session:
        run = DbTestRun(
            id=run_id,
            connection_id=conn_id,
            project_id=project_id,
            run_type="schema_analysis",
            status="pending",
            current_stage="pending",
            stage_message="Queued for schema analysis",
        )
        session.add(run)
        session.commit()

    _db_jobs[job_id] = {
        "job_id": job_id,
        "run_id": run_id,
        "run_type": "schema_analysis",
        "connection_id": conn_id,
        "status": "pending",
        "created_at": time.time(),
        "project_id": project_id,
    }

    asyncio.create_task(_run_schema_analysis_job(job_id, run_id, conn_id, project_id))

    return {"job_id": job_id, "run_id": run_id, "status": "pending"}


@router.get("/runs/{run_id}/schema")
async def get_schema_results(run_id: str, project_id: str = Query(...)):
    """Get schema snapshot and findings for a run."""
    with Session(engine) as session:
        run = _get_run_for_project(session, run_id, project_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

        return {
            "run_id": run.id,
            "status": run.status,
            "schema_snapshot": run.schema_snapshot,
            "schema_findings": run.schema_findings,
            "ai_summary": run.ai_summary,
            "current_stage": run.current_stage,
            "stage_message": run.stage_message,
        }


# ========== Spec CRUD Endpoints ==========


@router.get("/specs")
async def list_db_specs(project_id: str = Query(...)):
    """List all database test specifications."""
    return _scan_db_specs(project_id)


@router.get("/specs/{name:path}")
async def get_db_spec(name: str, project_id: str = Query(...)):
    """Get a single database spec content."""
    target = _get_spec_path_for_project(name, project_id)

    if not target or not target.exists():
        raise HTTPException(status_code=404, detail=f"Database spec '{name}' not found")

    content = target.read_text(encoding="utf-8")
    return {
        "name": target.name,
        "path": str(target.relative_to(BASE_DIR)),
        "content": content,
    }


@router.post("/specs")
async def create_db_spec(req: CreateDbSpecRequest):
    """Create a new database test spec file."""
    name = req.name if req.name.endswith(".md") else f"{req.name}.md"
    specs_dir = _get_specs_dir(req.project_id)
    target = specs_dir / name

    if target.exists():
        raise HTTPException(status_code=409, detail=f"Spec '{name}' already exists")

    target.write_text(req.content, encoding="utf-8")
    logger.info(f"Created database spec: {target}")
    return {
        "name": target.name,
        "path": str(target.relative_to(BASE_DIR)),
        "message": "Database spec created",
    }


@router.put("/specs/{name:path}")
async def update_db_spec(name: str, req: UpdateDbSpecRequest, project_id: str = Query(...)):
    """Update an existing database spec."""
    target = _get_spec_path_for_project(name, project_id)

    if not target or not target.exists():
        raise HTTPException(status_code=404, detail=f"Database spec '{name}' not found")

    target.write_text(req.content, encoding="utf-8")
    return {"name": target.name, "path": str(target.relative_to(BASE_DIR)), "message": "Spec updated"}


@router.delete("/specs/{name:path}")
async def delete_db_spec(name: str, project_id: str = Query(...)):
    """Delete a database spec."""
    target = _get_spec_path_for_project(name, project_id)

    if not target or not target.exists():
        raise HTTPException(status_code=404, detail=f"Database spec '{name}' not found")

    target.unlink()
    return {"message": f"Spec '{name}' deleted"}


# ========== Execution Endpoints ==========


@router.post("/run/{conn_id}")
async def start_data_quality_run(conn_id: str, req: RunChecksRequest):
    """Run data quality checks from a spec against a connection."""
    _cleanup_old_jobs()

    with Session(engine) as session:
        conn = _get_connection_for_project(session, conn_id, req.project_id)
        if not conn:
            raise HTTPException(status_code=404, detail=f"Connection '{conn_id}' not found")
    if not _get_spec_path_for_project(req.spec_name, req.project_id):
        raise HTTPException(status_code=404, detail=f"Spec '{req.spec_name}' not found")

    run_id = _generate_run_id()
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    project_id = req.project_id

    with Session(engine) as session:
        run = DbTestRun(
            id=run_id,
            connection_id=conn_id,
            project_id=project_id,
            spec_name=req.spec_name,
            run_type="data_quality",
            status="pending",
            current_stage="pending",
            stage_message="Queued for data quality checks",
        )
        session.add(run)
        session.commit()

    _db_jobs[job_id] = {
        "job_id": job_id,
        "run_id": run_id,
        "run_type": "data_quality",
        "connection_id": conn_id,
        "spec_name": req.spec_name,
        "status": "pending",
        "created_at": time.time(),
        "project_id": project_id,
    }

    asyncio.create_task(_run_data_quality_job(job_id, run_id, conn_id, req.spec_name, project_id))

    return {"job_id": job_id, "run_id": run_id, "status": "pending"}


@router.post("/run-full/{conn_id}")
async def start_full_pipeline(conn_id: str, req: RunFullRequest):
    """Run full pipeline: schema analysis + generate tests + execute."""
    _cleanup_old_jobs()

    with Session(engine) as session:
        conn = _get_connection_for_project(session, conn_id, req.project_id)
        if not conn:
            raise HTTPException(status_code=404, detail=f"Connection '{conn_id}' not found")

    run_id = _generate_run_id()
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    project_id = req.project_id

    with Session(engine) as session:
        run = DbTestRun(
            id=run_id,
            connection_id=conn_id,
            project_id=project_id,
            run_type="full",
            status="pending",
            current_stage="pending",
            stage_message="Queued for full database testing pipeline",
        )
        session.add(run)
        session.commit()

    _db_jobs[job_id] = {
        "job_id": job_id,
        "run_id": run_id,
        "run_type": "full",
        "connection_id": conn_id,
        "status": "pending",
        "created_at": time.time(),
        "project_id": project_id,
    }

    asyncio.create_task(_run_full_pipeline_job(job_id, run_id, conn_id, project_id))

    return {"job_id": job_id, "run_id": run_id, "status": "pending"}


# ========== AI Suggestion Endpoints ==========


@router.post("/suggest/{run_id}")
async def start_suggestions(run_id: str, req: SuggestRequest):
    """Generate test suggestions from schema findings."""
    _cleanup_old_jobs()

    with Session(engine) as session:
        run = _get_run_for_project(session, run_id, req.project_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
        if not run.schema_snapshot_json:
            raise HTTPException(status_code=400, detail="No schema snapshot available. Run schema analysis first.")

    job_id = f"job-{uuid.uuid4().hex[:8]}"
    project_id = req.project_id

    _db_jobs[job_id] = {
        "job_id": job_id,
        "run_id": run_id,
        "run_type": "suggestions",
        "status": "pending",
        "created_at": time.time(),
        "project_id": project_id,
    }

    asyncio.create_task(_run_suggestion_job(job_id, run_id, project_id))

    return {"job_id": job_id, "run_id": run_id, "status": "pending"}


@router.get("/runs/{run_id}/suggestions")
async def get_suggestions(run_id: str, project_id: str = Query(...)):
    """Get AI-generated test suggestions for a run."""
    with Session(engine) as session:
        run = _get_run_for_project(session, run_id, project_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

        return {
            "run_id": run.id,
            "suggestions": run.ai_suggestions or [],
            "current_stage": run.current_stage,
            "stage_message": run.stage_message,
        }


@router.post("/runs/{run_id}/approve-suggestions")
async def approve_suggestions(run_id: str, req: ApproveSuggestionsRequest):
    """Save approved suggestions as a spec file."""
    with Session(engine) as session:
        run = _get_run_for_project(session, run_id, req.project_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    project_id = req.project_id
    spec_name = _normalize_spec_name(req.spec_name, run.spec_name or run.connection_id or "suggestions")
    content = _checks_to_markdown(spec_name, req.suggestions)

    specs_dir = _get_specs_dir(project_id)
    target = specs_dir / spec_name
    if target.exists():
        raise HTTPException(status_code=409, detail=f"Spec '{spec_name}' already exists")
    target.write_text(content, encoding="utf-8")

    logger.info(f"Saved approved suggestions as spec: {target}")
    return {
        "name": spec_name,
        "path": str(target.relative_to(BASE_DIR)),
        "checks_count": len(req.suggestions),
        "message": "Suggestions saved as spec",
    }


# ========== AI Spec Generation Endpoint ==========


@router.post("/generate-spec")
async def generate_spec(req: GenerateSpecRequest):
    """Generate a database test spec using AI: introspect -> analyze -> generate checks -> save."""
    _cleanup_old_jobs()

    project_id = req.project_id

    # Validate connection exists
    with Session(engine) as session:
        conn = _get_connection_for_project(session, req.connection_id, project_id)
        if not conn:
            raise HTTPException(status_code=404, detail=f"Connection '{req.connection_id}' not found")
        conn_name = conn.name

    spec_name = _normalize_spec_name(req.spec_name, conn_name)

    # Check for duplicate spec name
    specs_dir = _get_specs_dir(project_id)
    if not req.preview_only and (specs_dir / spec_name).exists():
        raise HTTPException(status_code=409, detail=f"Spec '{spec_name}' already exists")

    job_id = f"job-{uuid.uuid4().hex[:8]}"

    _db_jobs[job_id] = {
        "job_id": job_id,
        "run_type": "generate_spec",
        "connection_id": req.connection_id,
        "spec_name": spec_name,
        "status": "pending",
        "stage_message": "Queued for AI spec generation",
        "created_at": time.time(),
        "project_id": project_id,
    }

    asyncio.create_task(
        _run_generate_spec_job(
            job_id=job_id,
            conn_id=req.connection_id,
            spec_name=spec_name,
            project_id=project_id,
            instructions=req.instructions,
            focus_areas=req.focus_areas,
            auto_run=req.auto_run,
            preview_only=req.preview_only,
        )
    )

    return {"job_id": job_id, "spec_name": spec_name, "status": "pending"}


@router.post("/generated-specs/save")
async def save_generated_spec(req: SaveGeneratedSpecRequest):
    """Save reviewed generated checks as a database spec markdown file."""
    project_id = req.project_id
    spec_name = _normalize_spec_name(req.spec_name, "database-spec")
    if not req.checks:
        raise HTTPException(status_code=400, detail="No checks provided")

    specs_dir = _get_specs_dir(project_id)
    target = specs_dir / spec_name
    if target.exists():
        raise HTTPException(status_code=409, detail=f"Spec '{spec_name}' already exists")

    content = _checks_to_markdown(spec_name, req.checks)
    target.write_text(content, encoding="utf-8")

    return {
        "name": spec_name,
        "path": str(target.relative_to(BASE_DIR)),
        "checks_count": len(req.checks),
        "message": "Generated spec saved",
    }


# ========== Job Tracking + History Endpoints ==========


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str, project_id: str = Query(...)):
    """Poll job status."""
    job = _db_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    if job.get("project_id") and job.get("project_id") != project_id:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job


@router.get("/runs")
async def list_runs(
    project_id: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List database test run history."""
    with Session(engine) as session:
        statement = select(DbTestRun).where(DbTestRun.project_id == project_id)
        statement = statement.order_by(DbTestRun.created_at.desc()).offset(offset).limit(limit)
        runs = session.exec(statement).all()

        # Count total
        count_stmt = select(func.count()).select_from(DbTestRun).where(DbTestRun.project_id == project_id)
        total = session.exec(count_stmt).one()

    return {
        "runs": [
            {
                "id": r.id,
                "connection_id": r.connection_id,
                "project_id": r.project_id,
                "spec_name": r.spec_name,
                "run_type": r.run_type,
                "status": r.status,
                "current_stage": r.current_stage,
                "stage_message": r.stage_message,
                "total_checks": r.total_checks,
                "passed_checks": r.passed_checks,
                "failed_checks": r.failed_checks,
                "error_checks": r.error_checks,
                "pass_rate": r.pass_rate,
                "critical_count": r.critical_count,
                "high_count": r.high_count,
                "medium_count": r.medium_count,
                "low_count": r.low_count,
                "info_count": r.info_count,
                "error_message": r.error_message,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "duration_seconds": r.duration_seconds,
            }
            for r in runs
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/runs/{run_id}")
async def get_run(run_id: str, project_id: str = Query(...)):
    """Get database test run details."""
    with Session(engine) as session:
        run = _get_run_for_project(session, run_id, project_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

        # Count checks
        check_stmt = select(func.count()).select_from(DbTestCheck).where(DbTestCheck.run_id == run_id)
        check_count = session.exec(check_stmt).one()

        return {
            "id": run.id,
            "connection_id": run.connection_id,
            "project_id": run.project_id,
            "spec_name": run.spec_name,
            "run_type": run.run_type,
            "status": run.status,
            "current_stage": run.current_stage,
            "stage_message": run.stage_message,
            "total_checks": run.total_checks,
            "passed_checks": run.passed_checks,
            "failed_checks": run.failed_checks,
            "error_checks": run.error_checks,
            "pass_rate": run.pass_rate,
            "critical_count": run.critical_count,
            "high_count": run.high_count,
            "medium_count": run.medium_count,
            "low_count": run.low_count,
            "info_count": run.info_count,
            "ai_summary": run.ai_summary,
            "error_message": run.error_message,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "duration_seconds": run.duration_seconds,
            "checks_count": check_count,
        }


@router.get("/runs/{run_id}/checks")
async def get_checks(
    run_id: str,
    project_id: str = Query(...),
    status: str | None = Query(None, description="Filter by status: passed,failed,error,skipped"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """Get individual check results for a run."""
    with Session(engine) as session:
        run = _get_run_for_project(session, run_id, project_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

        statement = select(DbTestCheck).where(DbTestCheck.run_id == run_id, _project_scope(DbTestCheck, project_id))
        if status:
            status_list = [s.strip().lower() for s in status.split(",")]
            statement = statement.where(DbTestCheck.status.in_(status_list))
        checks = session.exec(statement.offset(offset).limit(limit)).all()

        return [
            {
                "id": c.id,
                "run_id": c.run_id,
                "check_name": c.check_name,
                "check_type": c.check_type,
                "table_name": c.table_name,
                "column_name": c.column_name,
                "description": c.description,
                "sql_query": c.sql_query,
                "status": c.status,
                "severity": c.severity,
                "expected_result": c.expected_result,
                "actual_result": c.actual_result,
                "row_count": c.row_count,
                "sample_data": c.sample_data,
                "error_message": c.error_message,
                "execution_time_ms": c.execution_time_ms,
            }
            for c in checks
        ]


# ========== Summary Endpoint ==========


@router.get("/summary")
async def get_summary(project_id: str = Query(...)):
    """Get dashboard stats for database testing."""
    with Session(engine) as session:
        # Count connections
        conn_stmt = select(func.count()).select_from(DbConnection).where(DbConnection.project_id == project_id)
        total_connections = session.exec(conn_stmt).one()

        # Count runs
        run_stmt = select(func.count()).select_from(DbTestRun).where(DbTestRun.project_id == project_id)
        total_runs = session.exec(run_stmt).one()

        # Average pass rate from completed runs
        completed_stmt = select(DbTestRun).where(DbTestRun.status == "completed", DbTestRun.project_id == project_id)
        completed_runs = session.exec(completed_stmt).all()

        avg_pass_rate = 0.0
        if completed_runs:
            rates = [r.pass_rate for r in completed_runs if r.total_checks > 0]
            if rates:
                avg_pass_rate = round(sum(rates) / len(rates), 1)

        # Total checks
        total_passed = sum(r.passed_checks for r in completed_runs)
        total_failed = sum(r.failed_checks for r in completed_runs)
        total_errors = sum(r.error_checks for r in completed_runs)

    return {
        "total_connections": total_connections,
        "total_runs": total_runs,
        "avg_pass_rate": avg_pass_rate,
        "total_checks_passed": total_passed,
        "total_checks_failed": total_failed,
        "total_checks_errors": total_errors,
        "project_id": project_id,
    }
