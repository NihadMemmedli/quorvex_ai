"""
LLM Testing Router

Provides endpoints for managing LLM providers, running test suites,
tracking background jobs, comparing models, and generating test suites with AI.
"""

import asyncio
import csv
import hashlib
import io
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from .credentials import decrypt_credential, encrypt_credential
from .db import engine
from .models_db import (
    LlmComparisonRun,
    LlmDataset,
    LlmDatasetCase,
    LlmDatasetVersion,
    LlmPromptIteration,
    LlmProvider,
    LlmSchedule,
    LlmScheduleExecution,
    LlmSpecVersion,
    LlmTestResult,
    LlmTestRun,
)

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SPECS_DIR = BASE_DIR / "specs"

router = APIRouter(prefix="/llm-testing", tags=["llm-testing"])

# ========== In-Memory Job Tracking ==========
_llm_jobs: dict[str, dict] = {}
MAX_TRACKED_JOBS = 200


def _cleanup_old_jobs():
    """Remove completed/failed jobs older than 1 hour."""
    try:
        now = time.time()
        to_remove = []
        for job_id, job in _llm_jobs.items():
            if job["status"] in ("completed", "failed", "cancelled"):
                completed_at = job.get("completed_at", 0)
                if now - completed_at > 3600:
                    to_remove.append(job_id)
        for job_id in to_remove:
            del _llm_jobs[job_id]
        if len(_llm_jobs) > MAX_TRACKED_JOBS:
            sorted_jobs = sorted(_llm_jobs.items(), key=lambda x: x[1].get("started_at", 0))
            for job_id, _ in sorted_jobs[: len(_llm_jobs) - MAX_TRACKED_JOBS]:
                del _llm_jobs[job_id]
    except Exception as e:
        logger.warning(f"Job cleanup error: {e}")


# ========== Pydantic Models ==========


class CreateProviderRequest(BaseModel):
    name: str
    base_url: str
    api_key: str
    model_id: str
    default_params: dict | None = None
    custom_pricing: list[float] | None = None  # [input_per_1m, output_per_1m]
    project_id: str | None = "default"


class UpdateProviderRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model_id: str | None = None
    default_params: dict | None = None
    custom_pricing: list[float] | None = None
    is_active: bool | None = None


class CreateSpecRequest(BaseModel):
    name: str
    content: str
    project_id: str | None = "default"


class UpdateSpecRequest(BaseModel):
    content: str


class RunRequest(BaseModel):
    spec_name: str
    provider_id: str
    project_id: str | None = "default"


class CompareRequest(BaseModel):
    spec_name: str
    provider_ids: list[str]
    name: str | None = None
    project_id: str | None = "default"


class GenerateSuiteRequest(BaseModel):
    system_prompt: str
    app_description: str | None = ""
    focus_areas: list[str] | None = None
    num_cases: int = 10
    project_id: str | None = "default"


# ========== Helper Functions ==========


def _get_specs_dir(project_id: str = "default") -> Path:
    """Get LLM specs directory, optionally scoped by project."""
    if project_id and project_id != "default":
        d = SPECS_DIR / project_id / "llm"
    else:
        d = SPECS_DIR / "llm"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _scan_llm_specs(project_id: str = "default") -> list[dict]:
    """Scan for LLM test spec markdown files."""
    specs = []
    if project_id and project_id != "default":
        d = SPECS_DIR / project_id / "llm"
    else:
        d = SPECS_DIR / "llm"

    if not d.exists():
        return specs
    for f in sorted(d.glob("*.md")):
        content = f.read_text(encoding="utf-8", errors="replace")
        lines = content.split("\n")
        title = f.stem
        for line in lines:
            if line.startswith("# "):
                title = line[2:].strip()
                break
        specs.append(
            {
                "name": f.stem,
                "title": title,
                "path": str(f),
                "size": f.stat().st_size,
                "modified": f.stat().st_mtime,
            }
        )
    return specs


def _compute_system_prompt_hash(content: str) -> str:
    """Compute SHA256 hash of the system prompt section from spec content."""
    # Extract the system prompt section (between ## System Prompt and next ##)
    lines = content.split("\n")
    in_system = False
    system_lines = []
    for line in lines:
        if line.strip().lower().startswith("## system prompt"):
            in_system = True
            continue
        if in_system and line.strip().startswith("## "):
            break
        if in_system:
            system_lines.append(line)
    text = "\n".join(system_lines).strip() if system_lines else content
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_provider_client(provider: LlmProvider):
    """Build an LlmProviderClient from a database provider record."""
    from services.llm_provider import LlmProviderClient, ProviderConfig

    api_key = decrypt_credential(provider.api_key_encrypted) if provider.api_key_encrypted else ""
    params = provider.default_params

    config = ProviderConfig(
        base_url=provider.base_url,
        api_key=api_key,
        model_id=provider.model_id,
        default_temperature=params.get("temperature", 0.7),
        default_max_tokens=params.get("max_tokens", 4096),
        custom_pricing=provider.custom_pricing,
    )
    return LlmProviderClient(config=config, provider_id=provider.id)


# ========== Provider Endpoints ==========


@router.post("/providers")
async def create_provider(req: CreateProviderRequest):
    """Create a new LLM provider with encrypted API key."""
    provider_id = f"llm-{uuid.uuid4().hex[:8]}"

    provider = LlmProvider(
        id=provider_id,
        project_id=req.project_id if req.project_id != "default" else None,
        name=req.name,
        base_url=req.base_url.rstrip("/"),
        api_key_encrypted=encrypt_credential(req.api_key),
        model_id=req.model_id,
        default_params_json=json.dumps(req.default_params or {}),
        custom_pricing_json=json.dumps(req.custom_pricing) if req.custom_pricing else None,
    )

    with Session(engine) as session:
        session.add(provider)
        session.commit()

    return {"id": provider_id, "message": "Provider created"}


@router.get("/providers")
async def list_providers(
    project_id: str = Query("default"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """List all providers (API keys masked)."""
    with Session(engine) as session:
        stmt = select(LlmProvider)
        if project_id and project_id != "default":
            stmt = stmt.where(LlmProvider.project_id == project_id)
        else:
            stmt = stmt.where(LlmProvider.project_id == None)
        providers = session.exec(stmt.offset(offset).limit(limit)).all()

    return [
        {
            "id": p.id,
            "name": p.name,
            "base_url": p.base_url,
            "model_id": p.model_id,
            "default_params": p.default_params,
            "custom_pricing": p.custom_pricing,
            "is_active": p.is_active,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in providers
    ]


@router.put("/providers/{provider_id}")
async def update_provider(provider_id: str, req: UpdateProviderRequest):
    """Update a provider."""
    with Session(engine) as session:
        provider = session.get(LlmProvider, provider_id)
        if not provider:
            raise HTTPException(404, "Provider not found")

        if req.name is not None:
            provider.name = req.name
        if req.base_url is not None:
            provider.base_url = req.base_url.rstrip("/")
        if req.api_key is not None:
            provider.api_key_encrypted = encrypt_credential(req.api_key)
        if req.model_id is not None:
            provider.model_id = req.model_id
        if req.default_params is not None:
            provider.default_params_json = json.dumps(req.default_params)
        if req.custom_pricing is not None:
            provider.custom_pricing_json = json.dumps(req.custom_pricing)
        if req.is_active is not None:
            provider.is_active = req.is_active
        provider.updated_at = datetime.utcnow()

        session.add(provider)
        session.commit()

    return {"message": "Provider updated"}


@router.delete("/providers/{provider_id}")
async def delete_provider(provider_id: str):
    """Delete a provider."""
    with Session(engine) as session:
        provider = session.get(LlmProvider, provider_id)
        if not provider:
            raise HTTPException(404, "Provider not found")
        session.delete(provider)
        session.commit()

    return {"message": "Provider deleted"}


@router.post("/providers/{provider_id}/health-check")
async def health_check_provider(provider_id: str):
    """Test provider connectivity."""
    with Session(engine) as session:
        provider = session.get(LlmProvider, provider_id)
        if not provider:
            raise HTTPException(404, "Provider not found")

    client = _build_provider_client(provider)
    try:
        result = await client.health_check()
        return result
    finally:
        await client.close()


# ========== Spec Endpoints ==========


@router.get("/specs")
async def list_specs(project_id: str = Query("default")):
    """List all LLM test specs."""
    return _scan_llm_specs(project_id)


@router.post("/specs")
async def create_spec(req: CreateSpecRequest):
    """Create a new LLM test spec."""
    specs_dir = _get_specs_dir(req.project_id)
    safe_name = req.name.replace("/", "-").replace("\\", "-")
    if not safe_name.endswith(".md"):
        safe_name += ".md"
    path = specs_dir / safe_name
    if path.exists():
        raise HTTPException(409, f"Spec '{safe_name}' already exists")
    path.write_text(req.content, encoding="utf-8")
    return {"name": path.stem, "path": str(path), "message": "Spec created"}


@router.get("/specs/{name}")
async def get_spec(name: str, project_id: str = Query("default")):
    """Get spec content."""
    specs_dir = _get_specs_dir(project_id)
    path = specs_dir / f"{name}.md"
    if not path.exists():
        # Fallback to global
        path = SPECS_DIR / "llm" / f"{name}.md"
    if not path.exists():
        raise HTTPException(404, "Spec not found")
    return {"name": name, "content": path.read_text(encoding="utf-8", errors="replace")}


@router.put("/specs/{name}")
async def update_spec(name: str, req: UpdateSpecRequest, project_id: str = Query("default")):
    """Update spec content with auto-versioning."""
    specs_dir = _get_specs_dir(project_id)
    path = specs_dir / f"{name}.md"
    if not path.exists():
        path = SPECS_DIR / "llm" / f"{name}.md"
    if not path.exists():
        raise HTTPException(404, "Spec not found")
    path.write_text(req.content, encoding="utf-8")

    # Auto-version: compute system_prompt_hash and check if changed
    new_hash = _compute_system_prompt_hash(req.content)
    db_project_id = project_id if project_id != "default" else None
    with Session(engine) as session:
        latest = session.exec(
            select(LlmSpecVersion)
            .where(LlmSpecVersion.spec_name == name, LlmSpecVersion.project_id == db_project_id)
            .order_by(LlmSpecVersion.version.desc())
        ).first()
        if not latest or latest.system_prompt_hash != new_hash:
            next_version = (latest.version + 1) if latest else 1
            version = LlmSpecVersion(
                project_id=db_project_id,
                spec_name=name,
                version=next_version,
                content=req.content,
                change_summary="Auto-saved on edit",
                system_prompt_hash=new_hash,
            )
            session.add(version)
            session.commit()

    return {"message": "Spec updated"}


@router.delete("/specs/{name}")
async def delete_spec(name: str, project_id: str = Query("default")):
    """Delete a spec."""
    specs_dir = _get_specs_dir(project_id)
    path = specs_dir / f"{name}.md"
    if not path.exists():
        path = SPECS_DIR / "llm" / f"{name}.md"
    if not path.exists():
        raise HTTPException(404, "Spec not found")
    path.unlink()
    return {"message": "Spec deleted"}


# ========== Run Endpoints ==========


@router.post("/run")
async def run_suite(req: RunRequest):
    """Run an LLM test suite against a provider (background job)."""
    _cleanup_old_jobs()

    # Validate provider exists
    with Session(engine) as session:
        provider = session.get(LlmProvider, req.provider_id)
        if not provider:
            raise HTTPException(404, "Provider not found")

    # Validate spec exists
    specs_dir = _get_specs_dir(req.project_id)
    spec_path = specs_dir / f"{req.spec_name}.md"
    if not spec_path.exists():
        spec_path = SPECS_DIR / "llm" / f"{req.spec_name}.md"
    if not spec_path.exists():
        raise HTTPException(404, f"Spec '{req.spec_name}' not found")

    job_id = f"llmj-{uuid.uuid4().hex[:8]}"
    run_id = f"llmr-{uuid.uuid4().hex[:8]}"

    _llm_jobs[job_id] = {
        "job_id": job_id,
        "run_id": run_id,
        "type": "run",
        "status": "running",
        "started_at": time.time(),
        "progress_current": 0,
        "progress_total": 0,
        "passed": 0,
        "failed": 0,
    }

    asyncio.create_task(_execute_run(job_id, run_id, req, str(spec_path)))
    return {"job_id": job_id, "run_id": run_id}


def _dataset_to_suite(dataset: LlmDataset, cases: list[LlmDatasetCase]):
    """Convert dataset cases into an in-memory LlmTestSuite — no file I/O."""
    from services.llm_spec_parser import LlmTestCase, LlmTestSuite

    suite = LlmTestSuite(name=dataset.name, description=dataset.description or "")
    for i, c in enumerate(cases):
        suite.test_cases.append(
            LlmTestCase(
                id=f"case-{i + 1}",
                name=f"Case {i + 1}",
                input_prompt=c.input_prompt,
                expected_output=c.expected_output or "",
                context=c.context if c.context else [],
                assertions=c.assertions if c.assertions else [],
            )
        )
    return suite


async def _execute_run(
    job_id: str,
    run_id: str,
    req: RunRequest,
    spec_path: str = None,
    comparison_id: str | None = None,
    suite=None,
    dataset_id: str | None = None,
    dataset_name: str | None = None,
    dataset_version: int | None = None,
):
    """Execute a test suite run in the background."""
    try:
        from services.llm_spec_parser import parse_llm_spec
        from workflows.llm_evaluator import evaluate_test_case

        # Read and parse spec (skip if suite already provided, e.g. from dataset)
        if suite is None:
            content = Path(spec_path).read_text(encoding="utf-8")
            suite = parse_llm_spec(content)

        # Get provider
        with Session(engine) as session:
            provider = session.get(LlmProvider, req.provider_id)
            if not provider:
                raise RuntimeError("Provider not found")

        client = _build_provider_client(provider)

        # Create DB run record
        db_run = LlmTestRun(
            id=run_id,
            project_id=req.project_id if req.project_id != "default" else None,
            provider_id=req.provider_id,
            comparison_id=comparison_id,
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            dataset_version=dataset_version,
            spec_name=req.spec_name,
            status="running",
            total_cases=len(suite.test_cases),
            progress_total=len(suite.test_cases),
            started_at=datetime.utcnow(),
        )
        with Session(engine) as session:
            session.add(db_run)
            session.commit()

        _llm_jobs[job_id]["progress_total"] = len(suite.test_cases)

        # Build system messages
        messages_prefix = []
        if suite.system_prompt:
            messages_prefix.append({"role": "system", "content": suite.system_prompt})

        # Run each test case
        all_scores: dict[str, list[float]] = {}
        all_latencies: list[int] = []
        total_tokens_in = 0
        total_tokens_out = 0
        total_cost = 0.0
        passed = 0
        failed = 0
        error_count = 0

        for i, tc in enumerate(suite.test_cases):
            try:
                # Call the LLM
                messages = messages_prefix + [{"role": "user", "content": tc.input_prompt}]
                temp = suite.defaults.get("temperature")
                max_tok = suite.defaults.get("max_tokens")
                llm_resp = await client.call(messages, temperature=temp, max_tokens=max_tok)

                if llm_resp.error:
                    error_count += 1
                    # Save error result
                    result_record = LlmTestResult(
                        run_id=run_id,
                        test_case_id=tc.id,
                        test_case_name=tc.name,
                        input_prompt=tc.input_prompt,
                        expected_output=tc.expected_output,
                        actual_output=f"ERROR: {llm_resp.error}",
                        model_id=llm_resp.model_id,
                        latency_ms=llm_resp.latency_ms,
                        overall_passed=False,
                        assertions_json=json.dumps(
                            [
                                {
                                    "name": "provider_error",
                                    "category": "error",
                                    "passed": False,
                                    "explanation": llm_resp.error,
                                }
                            ]
                        ),
                    )
                    with Session(engine) as session:
                        session.add(result_record)
                        session.commit()
                else:
                    # Evaluate
                    eval_result = await evaluate_test_case(
                        test_case_id=tc.id,
                        test_case_name=tc.name,
                        input_prompt=tc.input_prompt,
                        output=llm_resp.output,
                        expected_output=tc.expected_output,
                        system_prompt=suite.system_prompt,
                        context=tc.context if tc.context else None,
                        assertions=tc.assertions if tc.assertions else None,
                        metrics_config=tc.metrics if tc.metrics else None,
                        judge_config=tc.judge,
                        latency_ms=llm_resp.latency_ms,
                        tokens_out=llm_resp.tokens_out,
                        cost_usd=llm_resp.estimated_cost_usd,
                    )

                    if eval_result.overall_passed:
                        passed += 1
                    else:
                        failed += 1

                    # Track scores
                    for score_name, score_val in eval_result.scores.items():
                        all_scores.setdefault(score_name, []).append(score_val)

                    # Track metrics
                    all_latencies.append(llm_resp.latency_ms)
                    total_tokens_in += llm_resp.tokens_in
                    total_tokens_out += llm_resp.tokens_out
                    total_cost += llm_resp.estimated_cost_usd

                    # Save result
                    result_record = LlmTestResult(
                        run_id=run_id,
                        test_case_id=tc.id,
                        test_case_name=tc.name,
                        input_prompt=tc.input_prompt,
                        expected_output=tc.expected_output,
                        actual_output=llm_resp.output,
                        model_id=llm_resp.model_id,
                        latency_ms=llm_resp.latency_ms,
                        tokens_in=llm_resp.tokens_in,
                        tokens_out=llm_resp.tokens_out,
                        estimated_cost_usd=llm_resp.estimated_cost_usd,
                        overall_passed=eval_result.overall_passed,
                        assertions_json=json.dumps(
                            [a.__dict__ if hasattr(a, "__dict__") else a for a in eval_result.assertions]
                            if eval_result.assertions
                            else []
                        ),
                        scores_json=json.dumps(eval_result.scores),
                    )
                    with Session(engine) as session:
                        session.add(result_record)
                        session.commit()

            except Exception as e:
                logger.error(f"Test case {tc.id} error: {e}")
                error_count += 1

            # Update progress
            _llm_jobs[job_id]["progress_current"] = i + 1
            _llm_jobs[job_id]["passed"] = passed
            _llm_jobs[job_id]["failed"] = failed

        # Compute aggregated metrics
        avg_latency = sum(all_latencies) / len(all_latencies) if all_latencies else None
        p95_latency = (
            sorted(all_latencies)[int(len(all_latencies) * 0.95)]
            if len(all_latencies) > 1
            else (all_latencies[0] if all_latencies else None)
        )
        avg_scores = {k: round(sum(v) / len(v), 4) for k, v in all_scores.items()} if all_scores else {}

        # Update DB run
        with Session(engine) as session:
            db_run = session.get(LlmTestRun, run_id)
            if db_run:
                db_run.status = "completed"
                db_run.passed_cases = passed
                db_run.failed_cases = failed
                db_run.error_cases = error_count
                db_run.avg_latency_ms = avg_latency
                db_run.p95_latency_ms = p95_latency
                db_run.total_tokens_in = total_tokens_in
                db_run.total_tokens_out = total_tokens_out
                db_run.total_cost_usd = round(total_cost, 6)
                db_run.avg_scores_json = json.dumps(avg_scores)
                db_run.progress_current = len(suite.test_cases)
                db_run.completed_at = datetime.utcnow()
                session.add(db_run)
                session.commit()

        await client.close()

        _llm_jobs[job_id]["status"] = "completed"
        _llm_jobs[job_id]["completed_at"] = time.time()
        logger.info(f"LLM test run {run_id} completed: {passed} passed, {failed} failed, {error_count} errors")

    except Exception as e:
        logger.error(f"LLM test run {run_id} failed: {e}", exc_info=True)
        _llm_jobs[job_id]["status"] = "failed"
        _llm_jobs[job_id]["error"] = str(e)
        _llm_jobs[job_id]["completed_at"] = time.time()

        with Session(engine) as session:
            db_run = session.get(LlmTestRun, run_id)
            if db_run:
                db_run.status = "failed"
                db_run.error_message = str(e)[:500]
                db_run.completed_at = datetime.utcnow()
                session.add(db_run)
                session.commit()


# ========== Compare Endpoints ==========


@router.post("/compare")
async def compare_providers(req: CompareRequest):
    """Run a test suite against multiple providers in parallel (background job)."""
    _cleanup_old_jobs()

    if len(req.provider_ids) < 2:
        raise HTTPException(400, "At least 2 providers required for comparison")

    # Validate providers
    with Session(engine) as session:
        for pid in req.provider_ids:
            if not session.get(LlmProvider, pid):
                raise HTTPException(404, f"Provider '{pid}' not found")

    # Validate spec
    specs_dir = _get_specs_dir(req.project_id)
    spec_path = specs_dir / f"{req.spec_name}.md"
    if not spec_path.exists():
        spec_path = SPECS_DIR / "llm" / f"{req.spec_name}.md"
    if not spec_path.exists():
        raise HTTPException(404, f"Spec '{req.spec_name}' not found")

    comparison_id = f"llmc-{uuid.uuid4().hex[:8]}"
    job_id = f"llmj-{uuid.uuid4().hex[:8]}"

    # Create comparison record
    comparison = LlmComparisonRun(
        id=comparison_id,
        project_id=req.project_id if req.project_id != "default" else None,
        name=req.name or f"Compare {len(req.provider_ids)} providers",
        spec_name=req.spec_name,
        provider_ids_json=json.dumps(req.provider_ids),
        status="running",
    )
    with Session(engine) as session:
        session.add(comparison)
        session.commit()

    _llm_jobs[job_id] = {
        "job_id": job_id,
        "comparison_id": comparison_id,
        "type": "compare",
        "status": "running",
        "started_at": time.time(),
        "provider_count": len(req.provider_ids),
    }

    asyncio.create_task(_execute_comparison(job_id, comparison_id, req, str(spec_path)))
    return {"job_id": job_id, "comparison_id": comparison_id}


async def _execute_comparison(
    job_id: str,
    comparison_id: str,
    req: CompareRequest,
    spec_path: str = None,
    suite=None,
    dataset_id: str | None = None,
    dataset_name: str | None = None,
    dataset_version: int | None = None,
):
    """Execute a multi-provider comparison run."""
    try:
        # Create individual runs for each provider in parallel
        run_tasks = []
        run_ids = []
        for pid in req.provider_ids:
            run_id = f"llmr-{uuid.uuid4().hex[:8]}"
            run_ids.append(run_id)
            inner_req = RunRequest(
                spec_name=req.spec_name,
                provider_id=pid,
                project_id=req.project_id,
            )
            # Create a sub-job for tracking (not exposed to API)
            sub_job_id = f"llmj-sub-{uuid.uuid4().hex[:8]}"
            _llm_jobs[sub_job_id] = {
                "job_id": sub_job_id,
                "run_id": run_id,
                "type": "run",
                "status": "running",
                "started_at": time.time(),
                "progress_current": 0,
                "progress_total": 0,
                "passed": 0,
                "failed": 0,
            }

            run_tasks.append(
                _execute_run(
                    sub_job_id,
                    run_id,
                    inner_req,
                    spec_path,
                    comparison_id=comparison_id,
                    suite=suite,
                    dataset_id=dataset_id,
                    dataset_name=dataset_name,
                    dataset_version=dataset_version,
                )
            )

        # Run all providers in parallel
        results = await asyncio.gather(*run_tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Comparison sub-run {run_ids[i]} for provider {req.provider_ids[i]} failed: {result}")

        # Compute comparison summary
        summary = {}
        with Session(engine) as session:
            for i, pid in enumerate(req.provider_ids):
                run = session.get(LlmTestRun, run_ids[i])
                if run:
                    summary[pid] = {
                        "run_id": run_ids[i],
                        "pass_rate": run.pass_rate,
                        "avg_latency_ms": run.avg_latency_ms,
                        "total_cost_usd": run.total_cost_usd,
                        "passed": run.passed_cases,
                        "failed": run.failed_cases,
                        "scores": run.avg_scores,
                    }

        # Determine winner (highest pass rate, then lowest latency)
        winner = None
        if summary:
            sorted_providers = sorted(
                summary.items(),
                key=lambda x: (-x[1].get("pass_rate", 0), x[1].get("avg_latency_ms", float("inf"))),
            )
            winner = sorted_providers[0][0]

        # Compute per-case win rates
        with Session(engine) as session:
            # Get all test case IDs from first run
            first_results = session.exec(select(LlmTestResult).where(LlmTestResult.run_id == run_ids[0])).all()

            wins = {pid: 0 for pid in req.provider_ids}
            for tc_result in first_results:
                tc_id = tc_result.test_case_id
                best_pid = None
                best_score = -1

                for j, pid in enumerate(req.provider_ids):
                    result = session.exec(
                        select(LlmTestResult).where(
                            LlmTestResult.run_id == run_ids[j],
                            LlmTestResult.test_case_id == tc_id,
                        )
                    ).first()
                    if result:
                        score = 1 if result.overall_passed else 0
                        if score > best_score:
                            best_score = score
                            best_pid = pid
                if best_pid:
                    wins[best_pid] += 1

            for pid in req.provider_ids:
                if pid in summary:
                    summary[pid]["wins"] = wins.get(pid, 0)

        # Update comparison record
        with Session(engine) as session:
            comp = session.get(LlmComparisonRun, comparison_id)
            if comp:
                comp.status = "completed"
                comp.winner_provider_id = winner
                comp.comparison_summary_json = json.dumps(summary)
                comp.completed_at = datetime.utcnow()
                session.add(comp)
                session.commit()

        _llm_jobs[job_id]["status"] = "completed"
        _llm_jobs[job_id]["completed_at"] = time.time()
        logger.info(f"Comparison {comparison_id} completed. Winner: {winner}")

    except Exception as e:
        logger.error(f"Comparison {comparison_id} failed: {e}", exc_info=True)
        _llm_jobs[job_id]["status"] = "failed"
        _llm_jobs[job_id]["error"] = str(e)
        _llm_jobs[job_id]["completed_at"] = time.time()

        with Session(engine) as session:
            comp = session.get(LlmComparisonRun, comparison_id)
            if comp:
                comp.status = "failed"
                comp.error_message = str(e)[:500]
                comp.completed_at = datetime.utcnow()
                session.add(comp)
                session.commit()


# ========== Job Status ==========


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Poll job status with progress."""
    job = _llm_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


# ========== Run History ==========


@router.get("/runs")
async def list_runs(
    project_id: str = Query("default"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """List LLM test run history."""
    with Session(engine) as session:
        stmt = select(LlmTestRun).order_by(LlmTestRun.created_at.desc())
        if project_id and project_id != "default":
            stmt = stmt.where(LlmTestRun.project_id == project_id)
        else:
            stmt = stmt.where(LlmTestRun.project_id == None)
        stmt = stmt.offset(offset).limit(limit)
        runs = session.exec(stmt).all()

    return [
        {
            "id": r.id,
            "provider_id": r.provider_id,
            "comparison_id": r.comparison_id,
            "dataset_id": r.dataset_id,
            "dataset_name": r.dataset_name,
            "spec_name": r.spec_name,
            "status": r.status,
            "total_cases": r.total_cases,
            "passed_cases": r.passed_cases,
            "failed_cases": r.failed_cases,
            "error_cases": r.error_cases,
            "pass_rate": r.pass_rate,
            "avg_latency_ms": r.avg_latency_ms,
            "total_cost_usd": r.total_cost_usd,
            "progress_current": r.progress_current,
            "progress_total": r.progress_total,
            "error_message": r.error_message,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "duration_seconds": r.duration_seconds,
        }
        for r in runs
    ]


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    """Get run details with aggregated metrics."""
    with Session(engine) as session:
        run = session.get(LlmTestRun, run_id)
        if not run:
            raise HTTPException(404, "Run not found")

        return {
            "id": run.id,
            "provider_id": run.provider_id,
            "comparison_id": run.comparison_id,
            "dataset_id": run.dataset_id,
            "dataset_name": run.dataset_name,
            "spec_name": run.spec_name,
            "status": run.status,
            "total_cases": run.total_cases,
            "passed_cases": run.passed_cases,
            "failed_cases": run.failed_cases,
            "error_cases": run.error_cases,
            "pass_rate": run.pass_rate,
            "avg_latency_ms": run.avg_latency_ms,
            "p95_latency_ms": run.p95_latency_ms,
            "total_tokens_in": run.total_tokens_in,
            "total_tokens_out": run.total_tokens_out,
            "total_cost_usd": run.total_cost_usd,
            "avg_scores": run.avg_scores,
            "progress_current": run.progress_current,
            "progress_total": run.progress_total,
            "error_message": run.error_message,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "duration_seconds": run.duration_seconds,
        }


@router.get("/runs/{run_id}/results")
async def get_run_results(
    run_id: str,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """Get per-test-case results for a run."""
    with Session(engine) as session:
        results = session.exec(
            select(LlmTestResult).where(LlmTestResult.run_id == run_id).offset(offset).limit(limit)
        ).all()

    return [
        {
            "id": r.id,
            "test_case_id": r.test_case_id,
            "test_case_name": r.test_case_name,
            "input_prompt": r.input_prompt,
            "expected_output": r.expected_output,
            "actual_output": r.actual_output,
            "model_id": r.model_id,
            "latency_ms": r.latency_ms,
            "tokens_in": r.tokens_in,
            "tokens_out": r.tokens_out,
            "estimated_cost_usd": r.estimated_cost_usd,
            "overall_passed": r.overall_passed,
            "assertions": r.assertions,
            "scores": r.scores,
        }
        for r in results
    ]


# ========== Comparison History ==========


@router.get("/comparisons")
async def list_comparisons(
    project_id: str = Query("default"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """List comparison runs."""
    with Session(engine) as session:
        stmt = select(LlmComparisonRun).order_by(LlmComparisonRun.created_at.desc())
        if project_id and project_id != "default":
            stmt = stmt.where(LlmComparisonRun.project_id == project_id)
        else:
            stmt = stmt.where(LlmComparisonRun.project_id == None)
        stmt = stmt.offset(offset).limit(limit)
        comps = session.exec(stmt).all()

    return [
        {
            "id": c.id,
            "name": c.name,
            "spec_name": c.spec_name,
            "provider_ids": c.provider_ids,
            "status": c.status,
            "winner_provider_id": c.winner_provider_id,
            "comparison_summary": c.comparison_summary,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "completed_at": c.completed_at.isoformat() if c.completed_at else None,
        }
        for c in comps
    ]


@router.get("/comparisons/{comparison_id}")
async def get_comparison(comparison_id: str):
    """Get comparison details with per-provider breakdown."""
    with Session(engine) as session:
        comp = session.get(LlmComparisonRun, comparison_id)
        if not comp:
            raise HTTPException(404, "Comparison not found")

        # Get associated runs
        runs = session.exec(select(LlmTestRun).where(LlmTestRun.comparison_id == comparison_id)).all()

        return {
            "id": comp.id,
            "name": comp.name,
            "spec_name": comp.spec_name,
            "provider_ids": comp.provider_ids,
            "status": comp.status,
            "winner_provider_id": comp.winner_provider_id,
            "comparison_summary": comp.comparison_summary,
            "error_message": comp.error_message,
            "created_at": comp.created_at.isoformat() if comp.created_at else None,
            "completed_at": comp.completed_at.isoformat() if comp.completed_at else None,
            "runs": [
                {
                    "id": r.id,
                    "provider_id": r.provider_id,
                    "status": r.status,
                    "pass_rate": r.pass_rate,
                    "avg_latency_ms": r.avg_latency_ms,
                    "total_cost_usd": r.total_cost_usd,
                    "avg_scores": r.avg_scores,
                }
                for r in runs
            ],
        }


@router.get("/comparisons/{comparison_id}/matrix")
async def get_comparison_matrix(comparison_id: str):
    """Get case-by-case comparison matrix for a comparison run."""
    with Session(engine) as session:
        comp = session.get(LlmComparisonRun, comparison_id)
        if not comp:
            raise HTTPException(404, "Comparison not found")

        runs = session.exec(select(LlmTestRun).where(LlmTestRun.comparison_id == comparison_id)).all()

        matrix = []
        if runs:
            # Get test cases from first run as reference
            first_results = session.exec(select(LlmTestResult).where(LlmTestResult.run_id == runs[0].id)).all()

            for tc in first_results:
                row = {
                    "test_case_id": tc.test_case_id,
                    "test_case_name": tc.test_case_name,
                    "input_prompt": tc.input_prompt,
                    "providers": {},
                }
                for run in runs:
                    result = session.exec(
                        select(LlmTestResult).where(
                            LlmTestResult.run_id == run.id,
                            LlmTestResult.test_case_id == tc.test_case_id,
                        )
                    ).first()
                    if result:
                        row["providers"][run.provider_id] = {
                            "passed": result.overall_passed,
                            "output": result.actual_output[:500],
                            "latency_ms": result.latency_ms,
                            "cost_usd": result.estimated_cost_usd,
                            "scores": result.scores,
                        }
                matrix.append(row)

        return {"comparison_id": comparison_id, "matrix": matrix}


# ========== AI Test Suite Generation ==========


@router.post("/generate-suite")
async def generate_suite(req: GenerateSuiteRequest):
    """AI generates a test suite from a system prompt (background job)."""
    _cleanup_old_jobs()

    job_id = f"llmj-{uuid.uuid4().hex[:8]}"
    _llm_jobs[job_id] = {
        "job_id": job_id,
        "type": "generate",
        "status": "running",
        "started_at": time.time(),
    }

    asyncio.create_task(_execute_generate(job_id, req))
    return {"job_id": job_id}


async def _execute_generate(job_id: str, req: GenerateSuiteRequest):
    """Execute AI test suite generation."""
    try:
        from workflows.llm_test_generator import generate_llm_test_suite

        content = await generate_llm_test_suite(
            system_prompt=req.system_prompt,
            app_description=req.app_description or "",
            focus_areas=req.focus_areas,
            num_cases=req.num_cases,
        )

        # Auto-save the generated spec
        specs_dir = _get_specs_dir(req.project_id)
        # Generate a name from the first line
        first_line = content.split("\n")[0] if content else "generated-test"
        name = first_line.replace("# LLM Test Suite:", "").replace("# ", "").strip()
        safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in name).strip().replace(" ", "-").lower()
        if not safe_name:
            safe_name = f"generated-{uuid.uuid4().hex[:6]}"

        path = specs_dir / f"{safe_name}.md"
        counter = 1
        while path.exists():
            path = specs_dir / f"{safe_name}-{counter}.md"
            counter += 1

        path.write_text(content, encoding="utf-8")

        _llm_jobs[job_id]["status"] = "completed"
        _llm_jobs[job_id]["completed_at"] = time.time()
        _llm_jobs[job_id]["result"] = {
            "spec_name": path.stem,
            "path": str(path),
            "content": content,
        }
        logger.info(f"Generated LLM test suite: {path}")

    except Exception as e:
        logger.error(f"Suite generation failed: {e}", exc_info=True)
        _llm_jobs[job_id]["status"] = "failed"
        _llm_jobs[job_id]["error"] = str(e)
        _llm_jobs[job_id]["completed_at"] = time.time()


# ========== Dataset Endpoints ==========


class CreateDatasetRequest(BaseModel):
    name: str
    description: str = ""
    tags: list[str] = []
    project_id: str | None = "default"


class UpdateDatasetRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None


class CreateDatasetCaseRequest(BaseModel):
    input_prompt: str
    expected_output: str = ""
    context: list[str] = []
    assertions: list[dict] = []
    tags: list[str] = []


class UpdateDatasetCaseRequest(BaseModel):
    input_prompt: str | None = None
    expected_output: str | None = None
    context: list[str] | None = None
    assertions: list[dict] | None = None
    tags: list[str] | None = None


class DatasetRunRequest(BaseModel):
    provider_id: str
    project_id: str | None = "default"


class DatasetCompareRequest(BaseModel):
    provider_ids: list[str]
    name: str | None = None
    project_id: str | None = "default"


class AugmentRequest(BaseModel):
    focus: str = "edge_cases"  # edge_cases, adversarial, boundary, rephrase
    num_cases: int = 5


class BulkRunRequest(BaseModel):
    dataset_ids: list[str]
    provider_id: str
    project_id: str | None = "default"


class BulkCompareRequest(BaseModel):
    dataset_id: str
    project_id: str | None = "default"


class CreateScheduleRequest(BaseModel):
    name: str
    dataset_id: str
    provider_ids: list[str]
    cron_expression: str
    timezone: str = "UTC"
    notify_on_regression: bool = True
    regression_threshold: float = 20.0
    project_id: str | None = "default"


class UpdateScheduleRequest(BaseModel):
    name: str | None = None
    provider_ids: list[str] | None = None
    cron_expression: str | None = None
    timezone: str | None = None
    enabled: bool | None = None
    notify_on_regression: bool | None = None
    regression_threshold: float | None = None


@router.post("/datasets")
async def create_dataset(req: CreateDatasetRequest):
    """Create a new dataset."""
    dataset_id = f"llmd-{uuid.uuid4().hex[:8]}"
    dataset = LlmDataset(
        id=dataset_id,
        project_id=req.project_id if req.project_id != "default" else None,
        name=req.name,
        description=req.description,
        tags_json=json.dumps(req.tags),
    )
    with Session(engine) as session:
        session.add(dataset)
        session.commit()
    return {"id": dataset_id, "message": "Dataset created"}


@router.get("/datasets")
async def list_datasets(
    project_id: str = Query("default"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """List datasets filtered by project."""
    with Session(engine) as session:
        stmt = select(LlmDataset).order_by(LlmDataset.created_at.desc())
        if project_id and project_id != "default":
            stmt = stmt.where(LlmDataset.project_id == project_id)
        else:
            stmt = stmt.where(LlmDataset.project_id == None)
        datasets = session.exec(stmt.offset(offset).limit(limit)).all()

    return [
        {
            "id": d.id,
            "name": d.name,
            "description": d.description,
            "version": d.version,
            "tags": d.tags,
            "total_cases": d.total_cases,
            "is_golden": d.is_golden,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        }
        for d in datasets
    ]


@router.get("/datasets/{dataset_id}")
async def get_dataset(dataset_id: str):
    """Get a dataset with its cases."""
    with Session(engine) as session:
        dataset = session.get(LlmDataset, dataset_id)
        if not dataset:
            raise HTTPException(404, "Dataset not found")

        cases = session.exec(
            select(LlmDatasetCase).where(LlmDatasetCase.dataset_id == dataset_id).order_by(LlmDatasetCase.case_index)
        ).all()

        return {
            "id": dataset.id,
            "name": dataset.name,
            "description": dataset.description,
            "version": dataset.version,
            "tags": dataset.tags,
            "total_cases": dataset.total_cases,
            "is_golden": dataset.is_golden,
            "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
            "updated_at": dataset.updated_at.isoformat() if dataset.updated_at else None,
            "cases": [
                {
                    "id": c.id,
                    "dataset_id": c.dataset_id,
                    "case_index": c.case_index,
                    "input_prompt": c.input_prompt,
                    "expected_output": c.expected_output,
                    "context": c.context,
                    "assertions": c.assertions,
                    "tags": c.tags,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
                for c in cases
            ],
        }


@router.put("/datasets/{dataset_id}")
async def update_dataset(dataset_id: str, req: UpdateDatasetRequest):
    """Update dataset metadata."""
    with Session(engine) as session:
        dataset = session.get(LlmDataset, dataset_id)
        if not dataset:
            raise HTTPException(404, "Dataset not found")
        if req.name is not None:
            dataset.name = req.name
        if req.description is not None:
            dataset.description = req.description
        if req.tags is not None:
            dataset.tags_json = json.dumps(req.tags)
        dataset.updated_at = datetime.utcnow()
        session.add(dataset)
        session.commit()
    return {"message": "Dataset updated"}


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(dataset_id: str):
    """Delete dataset and all its cases."""
    with Session(engine) as session:
        dataset = session.get(LlmDataset, dataset_id)
        if not dataset:
            raise HTTPException(404, "Dataset not found")
        # Delete all cases first
        cases = session.exec(select(LlmDatasetCase).where(LlmDatasetCase.dataset_id == dataset_id)).all()
        for c in cases:
            session.delete(c)
        session.delete(dataset)
        session.commit()
    return {"message": "Dataset deleted"}


@router.post("/datasets/{dataset_id}/cases")
async def add_dataset_cases(dataset_id: str, cases: list[CreateDatasetCaseRequest]):
    """Add one or more cases to a dataset."""
    with Session(engine) as session:
        dataset = session.get(LlmDataset, dataset_id)
        if not dataset:
            raise HTTPException(404, "Dataset not found")

        # Get current max index
        existing = session.exec(
            select(LlmDatasetCase)
            .where(LlmDatasetCase.dataset_id == dataset_id)
            .order_by(LlmDatasetCase.case_index.desc())
        ).first()
        next_index = (existing.case_index + 1) if existing else 0

        added_ids = []
        for case_req in cases:
            case = LlmDatasetCase(
                dataset_id=dataset_id,
                case_index=next_index,
                input_prompt=case_req.input_prompt,
                expected_output=case_req.expected_output,
                context_json=json.dumps(case_req.context),
                assertions_json=json.dumps(case_req.assertions),
                tags_json=json.dumps(case_req.tags),
            )
            session.add(case)
            session.flush()
            added_ids.append(case.id)
            next_index += 1

        dataset.total_cases = dataset.total_cases + len(cases)
        dataset.updated_at = datetime.utcnow()
        session.add(dataset)

        _create_dataset_version_snapshot(session, dataset_id, "cases_added", f"Added {len(cases)} case(s)")
        session.commit()

    return {"added": len(cases), "ids": added_ids}


@router.put("/datasets/{dataset_id}/cases/{case_id}")
async def update_dataset_case(dataset_id: str, case_id: int, req: UpdateDatasetCaseRequest):
    """Update a single case."""
    with Session(engine) as session:
        case = session.get(LlmDatasetCase, case_id)
        if not case or case.dataset_id != dataset_id:
            raise HTTPException(404, "Case not found")
        if req.input_prompt is not None:
            case.input_prompt = req.input_prompt
        if req.expected_output is not None:
            case.expected_output = req.expected_output
        if req.context is not None:
            case.context_json = json.dumps(req.context)
        if req.assertions is not None:
            case.assertions_json = json.dumps(req.assertions)
        if req.tags is not None:
            case.tags_json = json.dumps(req.tags)
        session.add(case)

        _create_dataset_version_snapshot(session, dataset_id, "cases_modified", f"Modified case #{case_id}")
        session.commit()
    return {"message": "Case updated"}


@router.delete("/datasets/{dataset_id}/cases/{case_id}")
async def delete_dataset_case(dataset_id: str, case_id: int):
    """Delete a case and update total."""
    with Session(engine) as session:
        case = session.get(LlmDatasetCase, case_id)
        if not case or case.dataset_id != dataset_id:
            raise HTTPException(404, "Case not found")
        session.delete(case)

        dataset = session.get(LlmDataset, dataset_id)
        if dataset:
            dataset.total_cases = max(0, dataset.total_cases - 1)
            dataset.updated_at = datetime.utcnow()
            session.add(dataset)

            _create_dataset_version_snapshot(session, dataset_id, "cases_removed", f"Removed case #{case_id}")
        session.commit()
    return {"message": "Case deleted"}


@router.post("/datasets/import-csv")
async def import_csv_dataset(
    file: UploadFile = File(...),
    name: str = Query("Imported Dataset"),
    project_id: str = Query("default"),
):
    """Import a CSV file as a new dataset. Columns: input,expected_output,assertions,tags"""
    content = await file.read()
    text = content.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    dataset_id = f"llmd-{uuid.uuid4().hex[:8]}"
    dataset = LlmDataset(
        id=dataset_id,
        project_id=project_id if project_id != "default" else None,
        name=name,
        description=f"Imported from {file.filename}",
    )

    parsed_cases = []
    for idx, row in enumerate(reader):
        # Parse assertions: semicolon-separated like "contains:hello;not-contains:error"
        assertions = []
        raw_assertions = row.get("assertions", "").strip()
        if raw_assertions:
            for part in raw_assertions.split(";"):
                part = part.strip()
                if ":" in part:
                    atype, aval = part.split(":", 1)
                    assertions.append({"type": atype.strip(), "value": aval.strip()})

        # Parse tags: comma-separated
        tags = []
        raw_tags = row.get("tags", "").strip()
        if raw_tags:
            tags = [t.strip() for t in raw_tags.split(",") if t.strip()]

        case = LlmDatasetCase(
            dataset_id=dataset_id,
            case_index=idx,
            input_prompt=row.get("input", "").strip(),
            expected_output=row.get("expected_output", "").strip(),
            assertions_json=json.dumps(assertions),
            tags_json=json.dumps(tags),
        )
        parsed_cases.append(case)

    dataset.total_cases = len(parsed_cases)

    with Session(engine) as session:
        session.add(dataset)
        for c in parsed_cases:
            session.add(c)
        session.commit()

    return {"id": dataset_id, "name": name, "total_cases": len(parsed_cases)}


@router.get("/datasets/{dataset_id}/export")
async def export_dataset(dataset_id: str, format: str = Query("csv")):
    """Export dataset cases as CSV or JSON."""
    with Session(engine) as session:
        dataset = session.get(LlmDataset, dataset_id)
        if not dataset:
            raise HTTPException(404, "Dataset not found")

        cases = session.exec(
            select(LlmDatasetCase).where(LlmDatasetCase.dataset_id == dataset_id).order_by(LlmDatasetCase.case_index)
        ).all()

        cases_data = [
            {
                "input": c.input_prompt,
                "expected_output": c.expected_output,
                "assertions": ";".join(f"{a.get('type', '')}:{a.get('value', '')}" for a in c.assertions),
                "tags": ",".join(c.tags),
            }
            for c in cases
        ]

    if format == "json":
        return cases_data

    # CSV export
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["input", "expected_output", "assertions", "tags"])
    writer.writeheader()
    writer.writerows(cases_data)
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={dataset_id}.csv"},
    )


@router.post("/datasets/{dataset_id}/to-spec")
async def dataset_to_spec(dataset_id: str, project_id: str = Query("default")):
    """Generate a markdown spec from a dataset."""
    with Session(engine) as session:
        dataset = session.get(LlmDataset, dataset_id)
        if not dataset:
            raise HTTPException(404, "Dataset not found")

        cases = session.exec(
            select(LlmDatasetCase).where(LlmDatasetCase.dataset_id == dataset_id).order_by(LlmDatasetCase.case_index)
        ).all()

    # Build markdown spec
    lines = [
        f"# LLM Test Suite: {dataset.name}",
        "",
        "## Description",
        dataset.description or "Auto-generated from dataset.",
        "",
        "## Defaults",
        "- temperature: 0.7",
        "- max_tokens: 4096",
        "",
    ]

    for i, c in enumerate(cases):
        lines.append(f"## Test Case: case-{i + 1}")
        lines.append("**Input:**")
        lines.append(c.input_prompt)
        lines.append("")
        if c.expected_output:
            lines.append("**Expected Output:**")
            lines.append(c.expected_output)
            lines.append("")
        if c.assertions:
            lines.append("**Assertions:**")
            for a in c.assertions:
                lines.append(f"- {a.get('type', 'contains')}: {a.get('value', '')}")
            lines.append("")

    content = "\n".join(lines)
    specs_dir = _get_specs_dir(project_id)
    safe_name = (
        "".join(ch if ch.isalnum() or ch in "-_ " else "" for ch in dataset.name).strip().replace(" ", "-").lower()
    )
    if not safe_name:
        safe_name = f"dataset-{dataset_id}"
    path = specs_dir / f"{safe_name}.md"
    counter = 1
    while path.exists():
        path = specs_dir / f"{safe_name}-{counter}.md"
        counter += 1
    path.write_text(content, encoding="utf-8")

    return {"spec_name": path.stem, "path": str(path)}


@router.post("/datasets/from-spec/{spec_name}")
async def dataset_from_spec(spec_name: str, project_id: str = Query("default")):
    """Import spec test cases into a new dataset."""
    specs_dir = _get_specs_dir(project_id)
    spec_path = specs_dir / f"{spec_name}.md"
    if not spec_path.exists():
        spec_path = SPECS_DIR / "llm" / f"{spec_name}.md"
    if not spec_path.exists():
        raise HTTPException(404, f"Spec '{spec_name}' not found")

    from services.llm_spec_parser import parse_llm_spec

    spec_content = spec_path.read_text(encoding="utf-8", errors="replace")
    suite = parse_llm_spec(spec_content)

    dataset_id = f"llmd-{uuid.uuid4().hex[:8]}"
    dataset = LlmDataset(
        id=dataset_id,
        project_id=project_id if project_id != "default" else None,
        name=f"From spec: {spec_name}",
        description=f"Imported from spec {spec_name}",
    )

    parsed_cases = []
    for idx, tc in enumerate(suite.test_cases):
        assertions_list = []
        if tc.assertions:
            for a in tc.assertions:
                if isinstance(a, dict):
                    assertions_list.append(a)
                else:
                    assertions_list.append({"type": "custom", "value": str(a)})

        case = LlmDatasetCase(
            dataset_id=dataset_id,
            case_index=idx,
            input_prompt=tc.input_prompt,
            expected_output=tc.expected_output or "",
            context_json=json.dumps(tc.context if tc.context else []),
            assertions_json=json.dumps(assertions_list),
        )
        parsed_cases.append(case)

    dataset.total_cases = len(parsed_cases)

    with Session(engine) as session:
        session.add(dataset)
        for c in parsed_cases:
            session.add(c)
        session.commit()

    return {"id": dataset_id, "name": dataset.name, "total_cases": len(parsed_cases)}


@router.post("/datasets/{dataset_id}/duplicate")
async def duplicate_dataset(dataset_id: str):
    """Clone a dataset with all its cases."""
    with Session(engine) as session:
        original = session.get(LlmDataset, dataset_id)
        if not original:
            raise HTTPException(404, "Dataset not found")

        new_id = f"llmd-{uuid.uuid4().hex[:8]}"
        clone = LlmDataset(
            id=new_id,
            project_id=original.project_id,
            name=f"{original.name} (copy)",
            description=original.description,
            version=1,
            tags_json=original.tags_json,
        )

        cases = session.exec(
            select(LlmDatasetCase).where(LlmDatasetCase.dataset_id == dataset_id).order_by(LlmDatasetCase.case_index)
        ).all()

        new_cases = []
        for c in cases:
            new_case = LlmDatasetCase(
                dataset_id=new_id,
                case_index=c.case_index,
                input_prompt=c.input_prompt,
                expected_output=c.expected_output,
                context_json=c.context_json,
                assertions_json=c.assertions_json,
                tags_json=c.tags_json,
            )
            new_cases.append(new_case)

        clone.total_cases = len(new_cases)
        session.add(clone)
        for nc in new_cases:
            session.add(nc)
        session.commit()

    return {"id": new_id, "name": clone.name, "total_cases": clone.total_cases}


# ========== Dataset Execution Endpoints ==========


@router.post("/datasets/{dataset_id}/run")
async def run_dataset(dataset_id: str, req: DatasetRunRequest):
    """Run a dataset directly against a provider (no spec file needed)."""
    _cleanup_old_jobs()

    with Session(engine) as session:
        dataset = session.get(LlmDataset, dataset_id)
        if not dataset:
            raise HTTPException(404, "Dataset not found")
        provider = session.get(LlmProvider, req.provider_id)
        if not provider:
            raise HTTPException(404, "Provider not found")
        cases = session.exec(
            select(LlmDatasetCase).where(LlmDatasetCase.dataset_id == dataset_id).order_by(LlmDatasetCase.case_index)
        ).all()
        if not cases:
            raise HTTPException(400, "Dataset has no cases")

        suite = _dataset_to_suite(dataset, cases)
        ds_name = dataset.name
        ds_version = dataset.version

    job_id = f"llmj-{uuid.uuid4().hex[:8]}"
    run_id = f"llmr-{uuid.uuid4().hex[:8]}"

    inner_req = RunRequest(
        spec_name=f"dataset:{ds_name}",
        provider_id=req.provider_id,
        project_id=req.project_id,
    )

    _llm_jobs[job_id] = {
        "job_id": job_id,
        "run_id": run_id,
        "type": "run",
        "status": "running",
        "started_at": time.time(),
        "progress_current": 0,
        "progress_total": 0,
        "passed": 0,
        "failed": 0,
    }

    asyncio.create_task(
        _execute_run(
            job_id,
            run_id,
            inner_req,
            suite=suite,
            dataset_id=dataset_id,
            dataset_name=ds_name,
            dataset_version=ds_version,
        )
    )
    return {"job_id": job_id, "run_id": run_id}


@router.post("/datasets/{dataset_id}/compare")
async def compare_dataset(dataset_id: str, req: DatasetCompareRequest):
    """Compare a dataset across multiple providers."""
    _cleanup_old_jobs()

    if len(req.provider_ids) < 2:
        raise HTTPException(400, "At least 2 providers required for comparison")

    with Session(engine) as session:
        dataset = session.get(LlmDataset, dataset_id)
        if not dataset:
            raise HTTPException(404, "Dataset not found")
        for pid in req.provider_ids:
            if not session.get(LlmProvider, pid):
                raise HTTPException(404, f"Provider '{pid}' not found")
        cases = session.exec(
            select(LlmDatasetCase).where(LlmDatasetCase.dataset_id == dataset_id).order_by(LlmDatasetCase.case_index)
        ).all()
        if not cases:
            raise HTTPException(400, "Dataset has no cases")

        suite = _dataset_to_suite(dataset, cases)
        ds_name = dataset.name
        ds_version = dataset.version

    comparison_id = f"llmc-{uuid.uuid4().hex[:8]}"
    job_id = f"llmj-{uuid.uuid4().hex[:8]}"

    comparison = LlmComparisonRun(
        id=comparison_id,
        project_id=req.project_id if req.project_id != "default" else None,
        name=req.name or f"Dataset compare: {ds_name}",
        spec_name=f"dataset:{ds_name}",
        provider_ids_json=json.dumps(req.provider_ids),
        status="running",
    )
    with Session(engine) as session:
        session.add(comparison)
        session.commit()

    inner_compare_req = CompareRequest(
        spec_name=f"dataset:{ds_name}",
        provider_ids=req.provider_ids,
        name=req.name or f"Dataset compare: {ds_name}",
        project_id=req.project_id,
    )

    _llm_jobs[job_id] = {
        "job_id": job_id,
        "comparison_id": comparison_id,
        "type": "compare",
        "status": "running",
        "started_at": time.time(),
        "provider_count": len(req.provider_ids),
    }

    asyncio.create_task(
        _execute_comparison(
            job_id,
            comparison_id,
            inner_compare_req,
            suite=suite,
            dataset_id=dataset_id,
            dataset_name=ds_name,
            dataset_version=ds_version,
        )
    )
    return {"job_id": job_id, "comparison_id": comparison_id}


# ========== Golden Set Endpoints ==========


@router.post("/datasets/{dataset_id}/golden")
async def toggle_golden(dataset_id: str, is_golden: bool = Query(True)):
    """Toggle the golden flag on a dataset."""
    with Session(engine) as session:
        dataset = session.get(LlmDataset, dataset_id)
        if not dataset:
            raise HTTPException(404, "Dataset not found")
        dataset.is_golden = is_golden
        dataset.updated_at = datetime.utcnow()
        session.add(dataset)
        session.commit()
    return {"id": dataset_id, "is_golden": is_golden}


# ========== Dataset Versioning ==========


def _create_dataset_version_snapshot(session: Session, dataset_id: str, change_type: str, change_summary: str):
    """Create a version snapshot for a dataset after mutation."""
    import hashlib as _hl

    dataset = session.get(LlmDataset, dataset_id)
    if not dataset:
        return

    cases = session.exec(
        select(LlmDatasetCase).where(LlmDatasetCase.dataset_id == dataset_id).order_by(LlmDatasetCase.case_index)
    ).all()

    snapshot = []
    for c in cases:
        raw = f"{c.input_prompt}|{c.expected_output}|{c.assertions_json}"
        case_hash = _hl.sha256(raw.encode()).hexdigest()[:12]
        snapshot.append(
            {
                "case_id": c.id,
                "hash": case_hash,
                "input_preview": c.input_prompt[:80],
            }
        )

    dataset.version += 1
    dataset.updated_at = datetime.utcnow()
    session.add(dataset)

    version = LlmDatasetVersion(
        dataset_id=dataset_id,
        version=dataset.version,
        change_type=change_type,
        change_summary=change_summary,
        cases_snapshot_json=json.dumps(snapshot),
        total_cases=len(cases),
    )
    session.add(version)


@router.get("/datasets/{dataset_id}/versions")
async def list_dataset_versions(
    dataset_id: str,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """List version history for a dataset."""
    with Session(engine) as session:
        dataset = session.get(LlmDataset, dataset_id)
        if not dataset:
            raise HTTPException(404, "Dataset not found")

        versions = session.exec(
            select(LlmDatasetVersion)
            .where(LlmDatasetVersion.dataset_id == dataset_id)
            .order_by(LlmDatasetVersion.version.desc())
            .offset(offset)
            .limit(limit)
        ).all()

    return [
        {
            "id": v.id,
            "dataset_id": v.dataset_id,
            "version": v.version,
            "change_type": v.change_type,
            "change_summary": v.change_summary,
            "total_cases": v.total_cases,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in versions
    ]


@router.get("/datasets/{dataset_id}/diff")
async def diff_dataset_versions(dataset_id: str, v1: int = Query(...), v2: int = Query(...)):
    """Compare two dataset version snapshots."""
    with Session(engine) as session:
        ver1 = session.exec(
            select(LlmDatasetVersion).where(LlmDatasetVersion.dataset_id == dataset_id, LlmDatasetVersion.version == v1)
        ).first()
        ver2 = session.exec(
            select(LlmDatasetVersion).where(LlmDatasetVersion.dataset_id == dataset_id, LlmDatasetVersion.version == v2)
        ).first()

    if not ver1 or not ver2:
        raise HTTPException(404, "Version not found")

    snap1 = {item["hash"]: item for item in json.loads(ver1.cases_snapshot_json)}
    snap2 = {item["hash"]: item for item in json.loads(ver2.cases_snapshot_json)}

    hashes1 = set(snap1.keys())
    hashes2 = set(snap2.keys())

    added = [snap2[h] for h in hashes2 - hashes1]
    removed = [snap1[h] for h in hashes1 - hashes2]
    unchanged = [snap1[h] for h in hashes1 & hashes2]

    return {
        "v1": v1,
        "v2": v2,
        "added": added,
        "removed": removed,
        "unchanged_count": len(unchanged),
        "total_v1": ver1.total_cases,
        "total_v2": ver2.total_cases,
    }


# ========== AI Augmentation Endpoints ==========


@router.post("/datasets/{dataset_id}/augment")
async def augment_dataset_endpoint(dataset_id: str, req: AugmentRequest):
    """Generate new cases via AI augmentation (background job)."""
    _cleanup_old_jobs()

    with Session(engine) as session:
        dataset = session.get(LlmDataset, dataset_id)
        if not dataset:
            raise HTTPException(404, "Dataset not found")
        cases = session.exec(
            select(LlmDatasetCase).where(LlmDatasetCase.dataset_id == dataset_id).order_by(LlmDatasetCase.case_index)
        ).all()
        if not cases:
            raise HTTPException(400, "Dataset has no cases to augment from")

        cases_dicts = [
            {
                "input_prompt": c.input_prompt,
                "expected_output": c.expected_output,
                "context": c.context,
                "assertions": c.assertions,
            }
            for c in cases
        ]
        ds_name = dataset.name
        ds_desc = dataset.description

    job_id = f"llmj-aug-{uuid.uuid4().hex[:8]}"
    _llm_jobs[job_id] = {
        "job_id": job_id,
        "type": "augment",
        "status": "running",
        "started_at": time.time(),
        "dataset_id": dataset_id,
        "result": None,
    }

    async def _run_augmentation():
        try:
            from workflows.dataset_augmentor import augment_dataset as _augment

            generated = await _augment(
                cases=cases_dicts,
                focus=req.focus,
                num_cases=req.num_cases,
                dataset_name=ds_name,
                dataset_description=ds_desc,
            )
            _llm_jobs[job_id]["result"] = generated
            _llm_jobs[job_id]["status"] = "completed"
            _llm_jobs[job_id]["completed_at"] = time.time()
        except Exception as e:
            logger.error(f"Augmentation job {job_id} failed: {e}")
            _llm_jobs[job_id]["status"] = "failed"
            _llm_jobs[job_id]["error"] = str(e)
            _llm_jobs[job_id]["completed_at"] = time.time()

    asyncio.create_task(_run_augmentation())
    return {"job_id": job_id}


@router.post("/datasets/{dataset_id}/augment/{job_id}/accept")
async def accept_augmented_cases(
    dataset_id: str,
    job_id: str,
    selected_indices: list[int] = None,
):
    """Accept selected generated cases from an augmentation job."""
    if selected_indices is None:
        selected_indices = []
    job = _llm_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.get("status") != "completed":
        raise HTTPException(400, "Job not completed yet")

    generated = job.get("result", [])
    if not generated:
        raise HTTPException(400, "No generated cases to accept")

    # If no indices specified, accept all
    if not selected_indices:
        selected_indices = list(range(len(generated)))

    selected = [generated[i] for i in selected_indices if i < len(generated)]
    if not selected:
        raise HTTPException(400, "No valid cases selected")

    with Session(engine) as session:
        dataset = session.get(LlmDataset, dataset_id)
        if not dataset:
            raise HTTPException(404, "Dataset not found")

        existing = session.exec(
            select(LlmDatasetCase)
            .where(LlmDatasetCase.dataset_id == dataset_id)
            .order_by(LlmDatasetCase.case_index.desc())
        ).first()
        next_index = (existing.case_index + 1) if existing else 0

        for case_data in selected:
            case = LlmDatasetCase(
                dataset_id=dataset_id,
                case_index=next_index,
                input_prompt=case_data.get("input_prompt", ""),
                expected_output=case_data.get("expected_output", ""),
                context_json=json.dumps(case_data.get("context", [])),
                assertions_json=json.dumps(case_data.get("assertions", [])),
                tags_json=json.dumps(case_data.get("tags", [])),
            )
            session.add(case)
            next_index += 1

        dataset.total_cases += len(selected)
        session.add(dataset)

        _create_dataset_version_snapshot(session, dataset_id, "cases_added", f"AI augmented: +{len(selected)} cases")
        session.commit()

    return {"added": len(selected)}


# ========== Bulk Execution Endpoints ==========


@router.post("/bulk-run")
async def bulk_run_datasets(req: BulkRunRequest):
    """Run multiple datasets against one provider."""
    _cleanup_old_jobs()

    with Session(engine) as session:
        provider = session.get(LlmProvider, req.provider_id)
        if not provider:
            raise HTTPException(404, "Provider not found")

    job_id = f"llmj-bulk-{uuid.uuid4().hex[:8]}"
    _llm_jobs[job_id] = {
        "job_id": job_id,
        "type": "bulk_run",
        "status": "running",
        "started_at": time.time(),
        "sub_runs": {},
    }

    async def _run_bulk():
        sem = asyncio.Semaphore(3)
        tasks = []

        for ds_id in req.dataset_ids:

            async def _run_single(dataset_id=ds_id):
                async with sem:
                    with Session(engine) as session:
                        dataset = session.get(LlmDataset, dataset_id)
                        if not dataset:
                            return
                        cases = session.exec(
                            select(LlmDatasetCase)
                            .where(LlmDatasetCase.dataset_id == dataset_id)
                            .order_by(LlmDatasetCase.case_index)
                        ).all()
                        if not cases:
                            return
                        suite = _dataset_to_suite(dataset, cases)
                        ds_name = dataset.name
                        ds_version = dataset.version

                    sub_run_id = f"llmr-{uuid.uuid4().hex[:8]}"
                    sub_job_id = f"llmj-sub-{uuid.uuid4().hex[:8]}"
                    _llm_jobs[sub_job_id] = {
                        "job_id": sub_job_id,
                        "run_id": sub_run_id,
                        "type": "run",
                        "status": "running",
                        "started_at": time.time(),
                        "progress_current": 0,
                        "progress_total": 0,
                        "passed": 0,
                        "failed": 0,
                    }
                    _llm_jobs[job_id]["sub_runs"][dataset_id] = {
                        "run_id": sub_run_id,
                        "job_id": sub_job_id,
                        "dataset_name": ds_name,
                    }

                    inner_req = RunRequest(
                        spec_name=f"dataset:{ds_name}",
                        provider_id=req.provider_id,
                        project_id=req.project_id,
                    )
                    await _execute_run(
                        sub_job_id,
                        sub_run_id,
                        inner_req,
                        suite=suite,
                        dataset_id=dataset_id,
                        dataset_name=ds_name,
                        dataset_version=ds_version,
                    )

            tasks.append(_run_single())

        await asyncio.gather(*tasks, return_exceptions=True)
        _llm_jobs[job_id]["status"] = "completed"
        _llm_jobs[job_id]["completed_at"] = time.time()

    asyncio.create_task(_run_bulk())
    return {"job_id": job_id}


@router.post("/bulk-compare")
async def bulk_compare_dataset(req: BulkCompareRequest):
    """Run one dataset against all active providers."""
    _cleanup_old_jobs()

    with Session(engine) as session:
        dataset = session.get(LlmDataset, req.dataset_id)
        if not dataset:
            raise HTTPException(404, "Dataset not found")

        db_project_id = req.project_id if req.project_id != "default" else None
        providers = session.exec(
            select(LlmProvider).where(LlmProvider.is_active == True, LlmProvider.project_id == db_project_id)
        ).all()
        if len(providers) < 2:
            raise HTTPException(400, "Need at least 2 active providers")

    provider_ids = [p.id for p in providers]
    compare_req = DatasetCompareRequest(
        provider_ids=provider_ids,
        name=f"All providers vs {dataset.name}",
        project_id=req.project_id,
    )
    return await compare_dataset(req.dataset_id, compare_req)


# ========== Schedule Endpoints ==========


@router.post("/schedules")
async def create_schedule(req: CreateScheduleRequest):
    """Create a new recurring dataset test schedule."""
    with Session(engine) as session:
        dataset = session.get(LlmDataset, req.dataset_id)
        if not dataset:
            raise HTTPException(404, "Dataset not found")
        for pid in req.provider_ids:
            if not session.get(LlmProvider, pid):
                raise HTTPException(404, f"Provider '{pid}' not found")

    schedule_id = f"llms-{uuid.uuid4().hex[:8]}"
    schedule = LlmSchedule(
        id=schedule_id,
        project_id=req.project_id if req.project_id != "default" else None,
        name=req.name,
        dataset_id=req.dataset_id,
        provider_ids_json=json.dumps(req.provider_ids),
        cron_expression=req.cron_expression,
        timezone=req.timezone,
        notify_on_regression=req.notify_on_regression,
        regression_threshold=req.regression_threshold,
    )
    with Session(engine) as session:
        session.add(schedule)
        session.commit()

    # Register with APScheduler
    try:
        from services.scheduler import add_llm_schedule_job

        add_llm_schedule_job(schedule_id, req.cron_expression, req.timezone)
    except Exception as e:
        logger.warning(f"Failed to register schedule with APScheduler: {e}")

    return {"id": schedule_id, "message": "Schedule created"}


@router.get("/schedules")
async def list_schedules(
    project_id: str = Query("default"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """List all LLM dataset schedules."""
    with Session(engine) as session:
        stmt = select(LlmSchedule).order_by(LlmSchedule.created_at.desc())
        if project_id and project_id != "default":
            stmt = stmt.where(LlmSchedule.project_id == project_id)
        else:
            stmt = stmt.where(LlmSchedule.project_id == None)
        schedules = session.exec(stmt.offset(offset).limit(limit)).all()

        # Fetch dataset names
        ds_names = {}
        for s in schedules:
            if s.dataset_id not in ds_names:
                ds = session.get(LlmDataset, s.dataset_id)
                ds_names[s.dataset_id] = ds.name if ds else "Unknown"

    from services.scheduler import get_next_run_time

    return [
        {
            "id": s.id,
            "name": s.name,
            "dataset_id": s.dataset_id,
            "dataset_name": ds_names.get(s.dataset_id, "Unknown"),
            "provider_ids": s.provider_ids,
            "cron_expression": s.cron_expression,
            "timezone": s.timezone,
            "enabled": s.enabled,
            "notify_on_regression": s.notify_on_regression,
            "regression_threshold": s.regression_threshold,
            "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
            "next_run_at": (
                get_next_run_time(s.id, s.cron_expression, s.timezone).isoformat()
                if s.enabled and get_next_run_time(s.id, s.cron_expression, s.timezone)
                else None
            ),
            "total_executions": s.total_executions,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in schedules
    ]


@router.get("/schedules/{schedule_id}")
async def get_schedule(schedule_id: str):
    """Get schedule details with execution history."""
    with Session(engine) as session:
        schedule = session.get(LlmSchedule, schedule_id)
        if not schedule:
            raise HTTPException(404, "Schedule not found")

        dataset = session.get(LlmDataset, schedule.dataset_id)
        executions = session.exec(
            select(LlmScheduleExecution)
            .where(LlmScheduleExecution.schedule_id == schedule_id)
            .order_by(LlmScheduleExecution.created_at.desc())
            .limit(20)
        ).all()

    from services.scheduler import get_next_run_time

    return {
        "id": schedule.id,
        "name": schedule.name,
        "dataset_id": schedule.dataset_id,
        "dataset_name": dataset.name if dataset else "Unknown",
        "provider_ids": schedule.provider_ids,
        "cron_expression": schedule.cron_expression,
        "timezone": schedule.timezone,
        "enabled": schedule.enabled,
        "notify_on_regression": schedule.notify_on_regression,
        "regression_threshold": schedule.regression_threshold,
        "last_run_at": schedule.last_run_at.isoformat() if schedule.last_run_at else None,
        "next_run_at": (
            get_next_run_time(schedule.id, schedule.cron_expression, schedule.timezone).isoformat()
            if schedule.enabled and get_next_run_time(schedule.id, schedule.cron_expression, schedule.timezone)
            else None
        ),
        "total_executions": schedule.total_executions,
        "created_at": schedule.created_at.isoformat() if schedule.created_at else None,
        "executions": [
            {
                "id": ex.id,
                "status": ex.status,
                "run_ids": ex.run_ids,
                "dataset_version": ex.dataset_version,
                "error_message": ex.error_message,
                "started_at": ex.started_at.isoformat() if ex.started_at else None,
                "completed_at": ex.completed_at.isoformat() if ex.completed_at else None,
                "created_at": ex.created_at.isoformat() if ex.created_at else None,
            }
            for ex in executions
        ],
    }


@router.put("/schedules/{schedule_id}")
async def update_schedule(schedule_id: str, req: UpdateScheduleRequest):
    """Update a schedule."""
    with Session(engine) as session:
        schedule = session.get(LlmSchedule, schedule_id)
        if not schedule:
            raise HTTPException(404, "Schedule not found")

        if req.name is not None:
            schedule.name = req.name
        if req.provider_ids is not None:
            schedule.provider_ids_json = json.dumps(req.provider_ids)
        if req.cron_expression is not None:
            schedule.cron_expression = req.cron_expression
        if req.timezone is not None:
            schedule.timezone = req.timezone
        if req.enabled is not None:
            schedule.enabled = req.enabled
        if req.notify_on_regression is not None:
            schedule.notify_on_regression = req.notify_on_regression
        if req.regression_threshold is not None:
            schedule.regression_threshold = req.regression_threshold

        schedule.updated_at = datetime.utcnow()
        session.add(schedule)
        session.commit()

        cron = schedule.cron_expression
        tz = schedule.timezone
        enabled = schedule.enabled

    # Update APScheduler
    try:
        from services.scheduler import add_llm_schedule_job, pause_schedule_job

        if enabled:
            add_llm_schedule_job(schedule_id, cron, tz)
        else:
            pause_schedule_job(schedule_id)
    except Exception as e:
        logger.warning(f"Failed to update APScheduler job: {e}")

    return {"message": "Schedule updated"}


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str):
    """Delete a schedule."""
    with Session(engine) as session:
        schedule = session.get(LlmSchedule, schedule_id)
        if not schedule:
            raise HTTPException(404, "Schedule not found")
        # Delete execution records
        execs = session.exec(select(LlmScheduleExecution).where(LlmScheduleExecution.schedule_id == schedule_id)).all()
        for ex in execs:
            session.delete(ex)
        session.delete(schedule)
        session.commit()

    try:
        from services.scheduler import remove_schedule_job

        remove_schedule_job(schedule_id)
    except Exception as e:
        logger.debug(f"Failed to remove APScheduler job: {e}")

    return {"message": "Schedule deleted"}


@router.post("/schedules/{schedule_id}/run-now")
async def run_schedule_now(schedule_id: str):
    """Manually trigger a schedule execution."""
    with Session(engine) as session:
        schedule = session.get(LlmSchedule, schedule_id)
        if not schedule:
            raise HTTPException(404, "Schedule not found")

        dataset = session.get(LlmDataset, schedule.dataset_id)
        if not dataset:
            raise HTTPException(404, "Dataset not found")

        cases = session.exec(
            select(LlmDatasetCase)
            .where(LlmDatasetCase.dataset_id == schedule.dataset_id)
            .order_by(LlmDatasetCase.case_index)
        ).all()
        if not cases:
            raise HTTPException(400, "Dataset has no cases")

        suite = _dataset_to_suite(dataset, cases)
        ds_name = dataset.name
        ds_version = dataset.version
        provider_ids = schedule.provider_ids

    # Create execution record
    execution = LlmScheduleExecution(
        schedule_id=schedule_id,
        status="running",
        dataset_version=ds_version,
        started_at=datetime.utcnow(),
    )
    with Session(engine) as session:
        session.add(execution)
        session.commit()
        session.refresh(execution)
        exec_id = execution.id

    job_id = f"llmj-sched-{uuid.uuid4().hex[:8]}"
    _llm_jobs[job_id] = {
        "job_id": job_id,
        "type": "schedule_run",
        "status": "running",
        "started_at": time.time(),
        "schedule_id": schedule_id,
        "execution_id": exec_id,
    }

    async def _run_scheduled():
        run_ids = []
        try:
            sem = asyncio.Semaphore(3)
            tasks = []
            for pid in provider_ids:

                async def _run_for_provider(provider_id=pid):
                    async with sem:
                        sub_run_id = f"llmr-{uuid.uuid4().hex[:8]}"
                        sub_job_id = f"llmj-sub-{uuid.uuid4().hex[:8]}"
                        _llm_jobs[sub_job_id] = {
                            "job_id": sub_job_id,
                            "run_id": sub_run_id,
                            "type": "run",
                            "status": "running",
                            "started_at": time.time(),
                            "progress_current": 0,
                            "progress_total": 0,
                            "passed": 0,
                            "failed": 0,
                        }
                        inner_req = RunRequest(
                            spec_name=f"dataset:{ds_name}",
                            provider_id=provider_id,
                            project_id="default",
                        )
                        await _execute_run(
                            sub_job_id,
                            sub_run_id,
                            inner_req,
                            suite=suite,
                            dataset_id=schedule.dataset_id,
                            dataset_name=ds_name,
                            dataset_version=ds_version,
                        )
                        return sub_run_id

                tasks.append(_run_for_provider())

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, str):
                    run_ids.append(r)

            with Session(engine) as session:
                ex = session.get(LlmScheduleExecution, exec_id)
                if ex:
                    ex.status = "completed"
                    ex.run_ids_json = json.dumps(run_ids)
                    ex.completed_at = datetime.utcnow()
                    session.add(ex)

                sched = session.get(LlmSchedule, schedule_id)
                if sched:
                    sched.last_run_at = datetime.utcnow()
                    sched.total_executions += 1
                    session.add(sched)
                session.commit()

            _llm_jobs[job_id]["status"] = "completed"
            _llm_jobs[job_id]["completed_at"] = time.time()
            _llm_jobs[job_id]["run_ids"] = run_ids

        except Exception as e:
            logger.error(f"Scheduled run failed: {e}")
            with Session(engine) as session:
                ex = session.get(LlmScheduleExecution, exec_id)
                if ex:
                    ex.status = "failed"
                    ex.error_message = str(e)[:500]
                    ex.completed_at = datetime.utcnow()
                    session.add(ex)
                    session.commit()
            _llm_jobs[job_id]["status"] = "failed"
            _llm_jobs[job_id]["error"] = str(e)

    asyncio.create_task(_run_scheduled())
    return {"job_id": job_id, "execution_id": exec_id}


# ========== Analytics Endpoints ==========

_PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90}


def _project_filter(stmt, model, project_id: str):
    """Apply project_id filter consistently."""
    if project_id and project_id != "default":
        return stmt.where(model.project_id == project_id)
    return stmt.where(model.project_id == None)


@router.get("/analytics/overview")
async def analytics_overview(
    project_id: str = Query("default"),
    period: str = Query("30d"),
):
    """Aggregated overview: total runs, cost, avg pass rate, avg latency, top provider, regression flag."""
    cutoff = datetime.utcnow() - timedelta(days=_PERIOD_DAYS.get(period, 30))

    with Session(engine) as session:
        base = select(LlmTestRun).where(
            LlmTestRun.status == "completed",
            LlmTestRun.created_at >= cutoff,
        )
        base = _project_filter(base, LlmTestRun, project_id)
        runs = session.exec(base).all()

        if not runs:
            return {
                "total_runs": 0,
                "total_cost": 0.0,
                "avg_pass_rate": 0.0,
                "avg_latency": None,
                "top_provider": None,
                "recent_regression": False,
            }

        total_runs = len(runs)
        total_cost = sum(r.total_cost_usd for r in runs)
        avg_pass_rate = sum(r.pass_rate for r in runs) / total_runs
        latencies = [r.avg_latency_ms for r in runs if r.avg_latency_ms is not None]
        avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else None

        # Top provider by run count
        provider_counts: dict[str, int] = {}
        for r in runs:
            if r.provider_id:
                provider_counts[r.provider_id] = provider_counts.get(r.provider_id, 0) + 1
        top_provider = max(provider_counts, key=provider_counts.get) if provider_counts else None

        # Recent regression: check if any spec/provider pair's latest run dropped >20% from previous
        recent_regression = False
        spec_provider_runs: dict[str, list[LlmTestRun]] = {}
        for r in runs:
            key = f"{r.spec_name}||{r.provider_id}"
            spec_provider_runs.setdefault(key, []).append(r)

        for _key, group in spec_provider_runs.items():
            sorted_group = sorted(group, key=lambda x: x.created_at, reverse=True)
            if len(sorted_group) >= 2:
                current = sorted_group[0].pass_rate
                previous = sorted_group[1].pass_rate
                if previous > 0 and (previous - current) > 20:
                    recent_regression = True
                    break

    return {
        "total_runs": total_runs,
        "total_cost": round(total_cost, 4),
        "avg_pass_rate": round(avg_pass_rate, 1),
        "avg_latency": avg_latency,
        "top_provider": top_provider,
        "recent_regression": recent_regression,
    }


@router.get("/analytics/trends")
async def analytics_trends(
    project_id: str = Query("default"),
    period: str = Query("30d"),
    provider_id: str | None = Query(None),
    spec_name: str | None = Query(None),
):
    """Daily trend data: pass rate, run count, avg latency, cost."""
    cutoff = datetime.utcnow() - timedelta(days=_PERIOD_DAYS.get(period, 30))

    with Session(engine) as session:
        base = select(LlmTestRun).where(
            LlmTestRun.status == "completed",
            LlmTestRun.created_at >= cutoff,
        )
        base = _project_filter(base, LlmTestRun, project_id)
        if provider_id:
            base = base.where(LlmTestRun.provider_id == provider_id)
        if spec_name:
            base = base.where(LlmTestRun.spec_name == spec_name)
        base = base.order_by(LlmTestRun.created_at)
        runs = session.exec(base).all()

    # Group by date
    daily: dict[str, dict] = {}
    for r in runs:
        date_key = r.created_at.strftime("%Y-%m-%d") if r.created_at else "unknown"
        if date_key not in daily:
            daily[date_key] = {"pass_rates": [], "latencies": [], "cost": 0.0, "count": 0}
        daily[date_key]["pass_rates"].append(r.pass_rate)
        if r.avg_latency_ms is not None:
            daily[date_key]["latencies"].append(r.avg_latency_ms)
        daily[date_key]["cost"] += r.total_cost_usd
        daily[date_key]["count"] += 1

    data_points = []
    for date_key in sorted(daily.keys()):
        d = daily[date_key]
        avg_pr = sum(d["pass_rates"]) / len(d["pass_rates"]) if d["pass_rates"] else 0
        avg_lat = round(sum(d["latencies"]) / len(d["latencies"]), 1) if d["latencies"] else None
        data_points.append(
            {
                "date": date_key,
                "pass_rate": round(avg_pr, 1),
                "runs": d["count"],
                "avg_latency": avg_lat,
                "cost": round(d["cost"], 4),
            }
        )

    return {"data_points": data_points}


@router.get("/analytics/latency-distribution")
async def analytics_latency_distribution(
    project_id: str = Query("default"),
    period: str = Query("30d"),
    provider_id: str | None = Query(None),
):
    """Latency histogram and percentiles per provider."""
    cutoff = datetime.utcnow() - timedelta(days=_PERIOD_DAYS.get(period, 30))

    with Session(engine) as session:
        # Get runs in period
        run_stmt = select(LlmTestRun.id, LlmTestRun.provider_id).where(
            LlmTestRun.status == "completed",
            LlmTestRun.created_at >= cutoff,
        )
        run_stmt = _project_filter(run_stmt, LlmTestRun, project_id)
        if provider_id:
            run_stmt = run_stmt.where(LlmTestRun.provider_id == provider_id)
        run_rows = session.exec(run_stmt).all()

        if not run_rows:
            return {"providers": []}

        run_id_to_provider: dict[str, str] = {}
        for row in run_rows:
            run_id_to_provider[row[0]] = row[1] or "unknown"

        run_ids = list(run_id_to_provider.keys())

        # Fetch results
        results = session.exec(
            select(LlmTestResult.run_id, LlmTestResult.latency_ms).where(LlmTestResult.run_id.in_(run_ids))
        ).all()

        # Get provider names
        provider_ids_set = set(run_id_to_provider.values())
        provider_names: dict[str, str] = {}
        if provider_ids_set:
            providers_db = session.exec(
                select(LlmProvider.id, LlmProvider.name).where(LlmProvider.id.in_(list(provider_ids_set)))
            ).all()
            for p in providers_db:
                provider_names[p[0]] = p[1]

    # Group latencies by provider
    provider_latencies: dict[str, list[int]] = {}
    for row in results:
        pid = run_id_to_provider.get(row[0], "unknown")
        provider_latencies.setdefault(pid, []).append(row[1])

    # Histogram buckets
    bucket_ranges = [
        ("0-100", 0, 100),
        ("100-200", 100, 200),
        ("200-500", 200, 500),
        ("500-1000", 500, 1000),
        ("1000-2000", 1000, 2000),
        ("2000-5000", 2000, 5000),
        ("5000+", 5000, float("inf")),
    ]

    providers_result = []
    for pid, latencies in provider_latencies.items():
        if not latencies:
            continue

        # Build histogram
        histogram = []
        for label, low, high in bucket_ranges:
            count = sum(1 for lat in latencies if low <= lat < high)
            histogram.append({"bucket": label, "count": count})

        # Percentiles
        sorted_lat = sorted(latencies)
        n = len(sorted_lat)

        def _percentile(p: float, data=sorted_lat, length=n) -> int:
            idx = int(length * p / 100)
            return data[min(idx, length - 1)]

        providers_result.append(
            {
                "provider_id": pid,
                "provider_name": provider_names.get(pid, pid),
                "histogram": histogram,
                "percentiles": {
                    "p50": _percentile(50),
                    "p75": _percentile(75),
                    "p90": _percentile(90),
                    "p95": _percentile(95),
                    "p99": _percentile(99),
                },
            }
        )

    return {"providers": providers_result}


@router.get("/analytics/cost-tracking")
async def analytics_cost_tracking(
    project_id: str = Query("default"),
    period: str = Query("30d"),
):
    """Daily cost breakdown by provider."""
    cutoff = datetime.utcnow() - timedelta(days=_PERIOD_DAYS.get(period, 30))

    with Session(engine) as session:
        base = select(LlmTestRun).where(
            LlmTestRun.status == "completed",
            LlmTestRun.created_at >= cutoff,
        )
        base = _project_filter(base, LlmTestRun, project_id)
        runs = session.exec(base).all()

    # Group by date
    daily: dict[str, dict[str, float]] = {}
    totals: dict[str, float] = {}
    total_tokens_in = 0
    total_tokens_out = 0
    total_cost = 0.0

    for r in runs:
        date_key = r.created_at.strftime("%Y-%m-%d") if r.created_at else "unknown"
        pid = r.provider_id or "unknown"
        daily.setdefault(date_key, {})
        daily[date_key][pid] = daily[date_key].get(pid, 0) + r.total_cost_usd
        totals[pid] = totals.get(pid, 0) + r.total_cost_usd
        total_tokens_in += r.total_tokens_in
        total_tokens_out += r.total_tokens_out
        total_cost += r.total_cost_usd

    daily_costs = []
    for date_key in sorted(daily.keys()):
        by_provider = daily[date_key]
        daily_costs.append(
            {
                "date": date_key,
                "total_cost": round(sum(by_provider.values()), 4),
                "by_provider": {k: round(v, 4) for k, v in by_provider.items()},
            }
        )

    return {
        "daily_costs": daily_costs,
        "totals": {
            "total_cost": round(total_cost, 4),
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
            "by_provider": {k: round(v, 4) for k, v in totals.items()},
        },
    }


@router.get("/analytics/regressions")
async def analytics_regressions(
    project_id: str = Query("default"),
    threshold: float = Query(20),
):
    """Detect spec/provider pairs where pass rate dropped more than threshold%."""
    with Session(engine) as session:
        base = select(LlmTestRun).where(LlmTestRun.status == "completed")
        base = _project_filter(base, LlmTestRun, project_id)
        base = base.order_by(LlmTestRun.created_at.desc())
        runs = session.exec(base).all()

    # Group by spec+provider, keep last 2
    pairs: dict[str, list] = {}
    for r in runs:
        key = f"{r.spec_name}||{r.provider_id}"
        if key not in pairs:
            pairs[key] = []
        if len(pairs[key]) < 2:
            pairs[key].append(r)

    regressions = []
    for _key, group in pairs.items():
        if len(group) < 2:
            continue
        current = group[0]  # most recent
        previous = group[1]
        drop = previous.pass_rate - current.pass_rate
        if drop > threshold:
            regressions.append(
                {
                    "spec_name": current.spec_name,
                    "provider_id": current.provider_id,
                    "previous_pass_rate": previous.pass_rate,
                    "current_pass_rate": current.pass_rate,
                    "drop_percentage": round(drop, 1),
                    "run_id": current.id,
                }
            )

    # Flag golden dataset regressions
    for reg in regressions:
        spec = reg["spec_name"]
        reg["is_golden"] = False
        if spec.startswith("dataset:"):
            ds_name = spec[len("dataset:") :]
            with Session(engine) as session:
                ds = session.exec(
                    select(LlmDataset).where(LlmDataset.name == ds_name, LlmDataset.is_golden == True)
                ).first()
                if ds:
                    reg["is_golden"] = True

    # Sort golden regressions to top
    regressions.sort(key=lambda x: (not x.get("is_golden", False), -x["drop_percentage"]))
    return {"regressions": regressions}


# ========== Dataset Analytics Endpoints ==========


@router.get("/analytics/dataset-performance")
async def analytics_dataset_performance(project_id: str = Query("default")):
    """Per-dataset aggregates: pass rate, latency, cost, best provider."""
    with Session(engine) as session:
        stmt = select(LlmTestRun).where(
            LlmTestRun.status == "completed",
            LlmTestRun.dataset_id != None,
        )
        stmt = _project_filter(stmt, LlmTestRun, project_id)
        runs = session.exec(stmt).all()

        # Group by dataset_id
        ds_runs: dict[str, list] = {}
        for r in runs:
            ds_runs.setdefault(r.dataset_id, []).append(r)

        # Get dataset info
        ds_map = {}
        for ds_id in ds_runs:
            ds = session.get(LlmDataset, ds_id)
            if ds:
                ds_map[ds_id] = ds

    results = []
    for ds_id, ds_run_list in ds_runs.items():
        ds = ds_map.get(ds_id)
        if not ds:
            continue

        total_runs = len(ds_run_list)
        avg_pass = sum(r.pass_rate for r in ds_run_list) / total_runs if total_runs else 0
        latencies = [r.avg_latency_ms for r in ds_run_list if r.avg_latency_ms]
        avg_lat = sum(latencies) / len(latencies) if latencies else None
        total_cost = sum(r.total_cost_usd for r in ds_run_list)

        # Find best provider (highest pass rate)
        provider_scores: dict[str, list[float]] = {}
        for r in ds_run_list:
            if r.provider_id:
                provider_scores.setdefault(r.provider_id, []).append(r.pass_rate)
        best_pid = None
        if provider_scores:
            best_pid = max(provider_scores, key=lambda k: sum(provider_scores[k]) / len(provider_scores[k]))

        results.append(
            {
                "dataset_id": ds_id,
                "dataset_name": ds.name,
                "is_golden": ds.is_golden,
                "total_runs": total_runs,
                "avg_pass_rate": round(avg_pass, 1),
                "avg_latency_ms": round(avg_lat, 1) if avg_lat else None,
                "total_cost": round(total_cost, 4),
                "best_provider_id": best_pid,
            }
        )

    results.sort(key=lambda x: x["total_runs"], reverse=True)
    return results


@router.get("/analytics/dataset-trends")
async def analytics_dataset_trends(
    dataset_id: str = Query(...),
    project_id: str = Query("default"),
    period: str = Query("30d"),
):
    """Daily trend for a specific dataset."""
    days = _PERIOD_DAYS.get(period, 30)
    cutoff = datetime.utcnow() - timedelta(days=days)

    with Session(engine) as session:
        stmt = select(LlmTestRun).where(
            LlmTestRun.status == "completed",
            LlmTestRun.dataset_id == dataset_id,
            LlmTestRun.created_at >= cutoff,
        )
        stmt = _project_filter(stmt, LlmTestRun, project_id)
        stmt = stmt.order_by(LlmTestRun.created_at)
        runs = session.exec(stmt).all()

    # Group by date
    daily: dict[str, list] = {}
    for r in runs:
        day = r.created_at.strftime("%Y-%m-%d") if r.created_at else "unknown"
        daily.setdefault(day, []).append(r)

    trend = []
    for day, day_runs in sorted(daily.items()):
        avg_pass = sum(r.pass_rate for r in day_runs) / len(day_runs)
        latencies = [r.avg_latency_ms for r in day_runs if r.avg_latency_ms]
        avg_lat = sum(latencies) / len(latencies) if latencies else None
        cost = sum(r.total_cost_usd for r in day_runs)
        trend.append(
            {
                "date": day,
                "pass_rate": round(avg_pass, 1),
                "runs": len(day_runs),
                "avg_latency": round(avg_lat, 1) if avg_lat else None,
                "cost": round(cost, 4),
            }
        )

    return trend


@router.get("/analytics/golden-dashboard")
async def analytics_golden_dashboard(project_id: str = Query("default")):
    """Summary of all golden datasets with latest run status and trend."""
    with Session(engine) as session:
        stmt = select(LlmDataset).where(LlmDataset.is_golden == True)
        if project_id and project_id != "default":
            stmt = stmt.where(LlmDataset.project_id == project_id)
        else:
            stmt = stmt.where(LlmDataset.project_id == None)
        golden_datasets = session.exec(stmt).all()

    results = []
    for ds in golden_datasets:
        with Session(engine) as session:
            recent_runs = session.exec(
                select(LlmTestRun)
                .where(
                    LlmTestRun.dataset_id == ds.id,
                    LlmTestRun.status == "completed",
                )
                .order_by(LlmTestRun.created_at.desc())
                .limit(5)
            ).all()

        if not recent_runs:
            results.append(
                {
                    "dataset_id": ds.id,
                    "dataset_name": ds.name,
                    "latest_pass_rate": 0,
                    "trend": "stable",
                    "last_run_at": None,
                    "total_runs": 0,
                }
            )
            continue

        latest = recent_runs[0]
        total = len(recent_runs)

        # Determine trend from last few runs
        if total >= 2:
            rates = [r.pass_rate for r in recent_runs]
            if rates[0] > rates[-1] + 5:
                trend = "improving"
            elif rates[0] < rates[-1] - 5:
                trend = "degrading"
            else:
                trend = "stable"
        else:
            trend = "stable"

        results.append(
            {
                "dataset_id": ds.id,
                "dataset_name": ds.name,
                "latest_pass_rate": latest.pass_rate,
                "trend": trend,
                "last_run_at": latest.created_at.isoformat() if latest.created_at else None,
                "total_runs": total,
            }
        )

    return results


# ========== Prompt Engineering Endpoints ==========


class SaveVersionRequest(BaseModel):
    change_summary: str = ""
    project_id: str | None = "default"


class CreateIterationRequest(BaseModel):
    spec_name: str
    name: str = ""
    version_a: int
    version_b: int
    provider_id: str
    project_id: str | None = "default"


class SuggestImprovementsRequest(BaseModel):
    run_id: str | None = None
    project_id: str | None = "default"


@router.post("/specs/{name}/versions")
async def save_version(name: str, req: SaveVersionRequest):
    """Save current spec content as a new version."""
    specs_dir = _get_specs_dir(req.project_id)
    path = specs_dir / f"{name}.md"
    if not path.exists():
        path = SPECS_DIR / "llm" / f"{name}.md"
    if not path.exists():
        raise HTTPException(404, "Spec not found")

    content = path.read_text(encoding="utf-8")
    system_prompt_hash = _compute_system_prompt_hash(content)
    db_project_id = req.project_id if req.project_id != "default" else None

    with Session(engine) as session:
        latest = session.exec(
            select(LlmSpecVersion)
            .where(LlmSpecVersion.spec_name == name, LlmSpecVersion.project_id == db_project_id)
            .order_by(LlmSpecVersion.version.desc())
        ).first()
        next_version = (latest.version + 1) if latest else 1

        version = LlmSpecVersion(
            project_id=db_project_id,
            spec_name=name,
            version=next_version,
            content=content,
            change_summary=req.change_summary or f"Version {next_version}",
            system_prompt_hash=system_prompt_hash,
        )
        session.add(version)
        session.commit()
        session.refresh(version)

    return {"version": next_version, "id": version.id, "message": "Version saved"}


@router.get("/specs/{name}/versions")
async def list_versions(
    name: str,
    project_id: str = Query("default"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """List all versions for a spec, sorted by version DESC."""
    db_project_id = project_id if project_id != "default" else None
    with Session(engine) as session:
        versions = session.exec(
            select(LlmSpecVersion)
            .where(LlmSpecVersion.spec_name == name, LlmSpecVersion.project_id == db_project_id)
            .order_by(LlmSpecVersion.version.desc())
            .offset(offset)
            .limit(limit)
        ).all()

    return [
        {
            "id": v.id,
            "version": v.version,
            "change_summary": v.change_summary,
            "system_prompt_hash": v.system_prompt_hash,
            "run_ids": v.run_ids,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in versions
    ]


@router.get("/specs/{name}/versions/{version}")
async def get_version(name: str, version: int, project_id: str = Query("default")):
    """Get specific version content."""
    db_project_id = project_id if project_id != "default" else None
    with Session(engine) as session:
        v = session.exec(
            select(LlmSpecVersion).where(
                LlmSpecVersion.spec_name == name,
                LlmSpecVersion.version == version,
                LlmSpecVersion.project_id == db_project_id,
            )
        ).first()
        if not v:
            raise HTTPException(404, "Version not found")

    return {
        "id": v.id,
        "version": v.version,
        "content": v.content,
        "change_summary": v.change_summary,
        "system_prompt_hash": v.system_prompt_hash,
        "run_ids": v.run_ids,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


@router.post("/specs/{name}/versions/{version}/restore")
async def restore_version(name: str, version: int, project_id: str = Query("default")):
    """Restore an old version as current spec content."""
    db_project_id = project_id if project_id != "default" else None

    with Session(engine) as session:
        v = session.exec(
            select(LlmSpecVersion).where(
                LlmSpecVersion.spec_name == name,
                LlmSpecVersion.version == version,
                LlmSpecVersion.project_id == db_project_id,
            )
        ).first()
        if not v:
            raise HTTPException(404, "Version not found")
        restored_content = v.content

    # Write to spec file
    specs_dir = _get_specs_dir(project_id)
    path = specs_dir / f"{name}.md"
    if not path.exists():
        path = SPECS_DIR / "llm" / f"{name}.md"
    if not path.exists():
        raise HTTPException(404, "Spec file not found")
    path.write_text(restored_content, encoding="utf-8")

    # Auto-save a new version
    system_prompt_hash = _compute_system_prompt_hash(restored_content)
    with Session(engine) as session:
        latest = session.exec(
            select(LlmSpecVersion)
            .where(LlmSpecVersion.spec_name == name, LlmSpecVersion.project_id == db_project_id)
            .order_by(LlmSpecVersion.version.desc())
        ).first()
        next_version = (latest.version + 1) if latest else 1

        new_v = LlmSpecVersion(
            project_id=db_project_id,
            spec_name=name,
            version=next_version,
            content=restored_content,
            change_summary=f"Restored from version {version}",
            system_prompt_hash=system_prompt_hash,
        )
        session.add(new_v)
        session.commit()

    return {"message": f"Restored version {version}", "new_version": next_version}


@router.post("/prompt-iterations")
async def create_prompt_iteration(req: CreateIterationRequest):
    """Create and start an A/B comparison between two spec versions."""
    db_project_id = req.project_id if req.project_id != "default" else None

    # Validate versions exist
    with Session(engine) as session:
        va = session.exec(
            select(LlmSpecVersion).where(
                LlmSpecVersion.spec_name == req.spec_name,
                LlmSpecVersion.version == req.version_a,
                LlmSpecVersion.project_id == db_project_id,
            )
        ).first()
        vb = session.exec(
            select(LlmSpecVersion).where(
                LlmSpecVersion.spec_name == req.spec_name,
                LlmSpecVersion.version == req.version_b,
                LlmSpecVersion.project_id == db_project_id,
            )
        ).first()
        if not va:
            raise HTTPException(404, f"Version {req.version_a} not found")
        if not vb:
            raise HTTPException(404, f"Version {req.version_b} not found")

        provider = session.get(LlmProvider, req.provider_id)
        if not provider:
            raise HTTPException(404, "Provider not found")

    iteration_id = f"llmi-{uuid.uuid4().hex[:8]}"
    iteration = LlmPromptIteration(
        id=iteration_id,
        project_id=db_project_id,
        spec_name=req.spec_name,
        name=req.name or f"v{req.version_a} vs v{req.version_b}",
        version_a=req.version_a,
        version_b=req.version_b,
        provider_id=req.provider_id,
        status="running",
    )
    with Session(engine) as session:
        session.add(iteration)
        session.commit()

    job_id = f"llmj-{uuid.uuid4().hex[:8]}"
    _llm_jobs[job_id] = {
        "job_id": job_id,
        "iteration_id": iteration_id,
        "type": "prompt_iteration",
        "status": "running",
        "started_at": time.time(),
    }

    asyncio.create_task(_execute_prompt_iteration(job_id, iteration_id, req))
    return {"job_id": job_id, "iteration_id": iteration_id}


async def _execute_prompt_iteration(job_id: str, iteration_id: str, req: CreateIterationRequest):
    """Execute A/B test between two spec versions."""
    try:
        db_project_id = req.project_id if req.project_id != "default" else None

        with Session(engine) as session:
            va = session.exec(
                select(LlmSpecVersion).where(
                    LlmSpecVersion.spec_name == req.spec_name,
                    LlmSpecVersion.version == req.version_a,
                    LlmSpecVersion.project_id == db_project_id,
                )
            ).first()
            vb = session.exec(
                select(LlmSpecVersion).where(
                    LlmSpecVersion.spec_name == req.spec_name,
                    LlmSpecVersion.version == req.version_b,
                    LlmSpecVersion.project_id == db_project_id,
                )
            ).first()
            content_a = va.content
            content_b = vb.content

        run_id_a = f"llmr-{uuid.uuid4().hex[:8]}"
        run_id_b = f"llmr-{uuid.uuid4().hex[:8]}"
        specs_dir = _get_specs_dir(req.project_id)

        temp_a = specs_dir / f"_iter_{iteration_id}_a.md"
        temp_a.write_text(content_a, encoding="utf-8")
        temp_b = specs_dir / f"_iter_{iteration_id}_b.md"
        temp_b.write_text(content_b, encoding="utf-8")

        try:
            sub_job_a = f"llmj-sub-{uuid.uuid4().hex[:8]}"
            _llm_jobs[sub_job_a] = {
                "job_id": sub_job_a,
                "run_id": run_id_a,
                "type": "run",
                "status": "running",
                "started_at": time.time(),
                "progress_current": 0,
                "progress_total": 0,
                "passed": 0,
                "failed": 0,
            }
            req_a = RunRequest(spec_name=temp_a.stem, provider_id=req.provider_id, project_id=req.project_id)
            await _execute_run(sub_job_a, run_id_a, req_a, str(temp_a), comparison_id=None)

            sub_job_b = f"llmj-sub-{uuid.uuid4().hex[:8]}"
            _llm_jobs[sub_job_b] = {
                "job_id": sub_job_b,
                "run_id": run_id_b,
                "type": "run",
                "status": "running",
                "started_at": time.time(),
                "progress_current": 0,
                "progress_total": 0,
                "passed": 0,
                "failed": 0,
            }
            req_b = RunRequest(spec_name=temp_b.stem, provider_id=req.provider_id, project_id=req.project_id)
            await _execute_run(sub_job_b, run_id_b, req_b, str(temp_b), comparison_id=None)

            with Session(engine) as session:
                run_a = session.get(LlmTestRun, run_id_a)
                run_b = session.get(LlmTestRun, run_id_b)

                summary = {}
                winner = "tie"
                if run_a and run_b:
                    summary = {
                        "version_a": {
                            "pass_rate": run_a.pass_rate,
                            "avg_latency_ms": run_a.avg_latency_ms,
                            "total_cost_usd": run_a.total_cost_usd,
                            "passed": run_a.passed_cases,
                            "failed": run_a.failed_cases,
                        },
                        "version_b": {
                            "pass_rate": run_b.pass_rate,
                            "avg_latency_ms": run_b.avg_latency_ms,
                            "total_cost_usd": run_b.total_cost_usd,
                            "passed": run_b.passed_cases,
                            "failed": run_b.failed_cases,
                        },
                    }
                    if run_a.pass_rate > run_b.pass_rate:
                        winner = "a"
                    elif run_b.pass_rate > run_a.pass_rate:
                        winner = "b"
                    elif (run_a.avg_latency_ms or 0) < (run_b.avg_latency_ms or float("inf")):
                        winner = "a"
                    elif (run_b.avg_latency_ms or 0) < (run_a.avg_latency_ms or float("inf")):
                        winner = "b"

                iteration = session.get(LlmPromptIteration, iteration_id)
                if iteration:
                    iteration.run_id_a = run_id_a
                    iteration.run_id_b = run_id_b
                    iteration.status = "completed"
                    iteration.winner = winner
                    iteration.summary_json = json.dumps(summary)
                    iteration.completed_at = datetime.utcnow()
                    session.add(iteration)
                    session.commit()

        finally:
            if temp_a.exists():
                temp_a.unlink()
            if temp_b.exists():
                temp_b.unlink()

        _llm_jobs[job_id]["status"] = "completed"
        _llm_jobs[job_id]["completed_at"] = time.time()
        logger.info(f"Prompt iteration {iteration_id} completed. Winner: {winner}")

    except Exception as e:
        logger.error(f"Prompt iteration {iteration_id} failed: {e}", exc_info=True)
        _llm_jobs[job_id]["status"] = "failed"
        _llm_jobs[job_id]["error"] = str(e)
        _llm_jobs[job_id]["completed_at"] = time.time()

        with Session(engine) as session:
            iteration = session.get(LlmPromptIteration, iteration_id)
            if iteration:
                iteration.status = "failed"
                iteration.completed_at = datetime.utcnow()
                session.add(iteration)
                session.commit()


@router.get("/prompt-iterations")
async def list_prompt_iterations(
    project_id: str = Query("default"),
    spec_name: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """List prompt iterations filtered by project and optionally spec_name."""
    db_project_id = project_id if project_id != "default" else None
    with Session(engine) as session:
        stmt = select(LlmPromptIteration).where(LlmPromptIteration.project_id == db_project_id)
        if spec_name:
            stmt = stmt.where(LlmPromptIteration.spec_name == spec_name)
        stmt = stmt.order_by(LlmPromptIteration.created_at.desc())
        iterations = session.exec(stmt.offset(offset).limit(limit)).all()

    return [
        {
            "id": it.id,
            "spec_name": it.spec_name,
            "name": it.name,
            "version_a": it.version_a,
            "version_b": it.version_b,
            "provider_id": it.provider_id,
            "run_id_a": it.run_id_a,
            "run_id_b": it.run_id_b,
            "status": it.status,
            "winner": it.winner,
            "summary": it.summary,
            "ai_suggestions": it.ai_suggestions,
            "created_at": it.created_at.isoformat() if it.created_at else None,
            "completed_at": it.completed_at.isoformat() if it.completed_at else None,
        }
        for it in iterations
    ]


@router.get("/prompt-iterations/{iteration_id}")
async def get_prompt_iteration(iteration_id: str):
    """Get iteration details with side-by-side run results."""
    with Session(engine) as session:
        iteration = session.get(LlmPromptIteration, iteration_id)
        if not iteration:
            raise HTTPException(404, "Iteration not found")

        run_a_data = None
        run_b_data = None
        if iteration.run_id_a:
            run_a = session.get(LlmTestRun, iteration.run_id_a)
            if run_a:
                run_a_data = {
                    "id": run_a.id,
                    "status": run_a.status,
                    "pass_rate": run_a.pass_rate,
                    "avg_latency_ms": run_a.avg_latency_ms,
                    "total_cost_usd": run_a.total_cost_usd,
                    "passed_cases": run_a.passed_cases,
                    "failed_cases": run_a.failed_cases,
                    "avg_scores": run_a.avg_scores,
                }
        if iteration.run_id_b:
            run_b = session.get(LlmTestRun, iteration.run_id_b)
            if run_b:
                run_b_data = {
                    "id": run_b.id,
                    "status": run_b.status,
                    "pass_rate": run_b.pass_rate,
                    "avg_latency_ms": run_b.avg_latency_ms,
                    "total_cost_usd": run_b.total_cost_usd,
                    "passed_cases": run_b.passed_cases,
                    "failed_cases": run_b.failed_cases,
                    "avg_scores": run_b.avg_scores,
                }

        return {
            "id": iteration.id,
            "spec_name": iteration.spec_name,
            "name": iteration.name,
            "version_a": iteration.version_a,
            "version_b": iteration.version_b,
            "provider_id": iteration.provider_id,
            "run_id_a": iteration.run_id_a,
            "run_id_b": iteration.run_id_b,
            "status": iteration.status,
            "winner": iteration.winner,
            "summary": iteration.summary,
            "ai_suggestions": iteration.ai_suggestions,
            "created_at": iteration.created_at.isoformat() if iteration.created_at else None,
            "completed_at": iteration.completed_at.isoformat() if iteration.completed_at else None,
            "run_a": run_a_data,
            "run_b": run_b_data,
        }


@router.post("/specs/{name}/suggest-improvements")
async def suggest_improvements(name: str, req: SuggestImprovementsRequest):
    """AI analyzes failed run results and suggests prompt improvements."""
    specs_dir = _get_specs_dir(req.project_id)
    path = specs_dir / f"{name}.md"
    if not path.exists():
        path = SPECS_DIR / "llm" / f"{name}.md"
    if not path.exists():
        raise HTTPException(404, "Spec not found")

    spec_content = path.read_text(encoding="utf-8")

    failed_results = []
    if req.run_id:
        with Session(engine) as session:
            results = session.exec(
                select(LlmTestResult).where(LlmTestResult.run_id == req.run_id, LlmTestResult.overall_passed == False)
            ).all()
            failed_results = [
                {
                    "case": r.test_case_name,
                    "input": r.input_prompt[:200],
                    "expected": r.expected_output[:200],
                    "actual": r.actual_output[:200],
                    "assertions": r.assertions,
                }
                for r in results
            ]

    return {
        "suggestions": f"Analysis of {len(failed_results)} failed test cases for spec '{name}'.\n\nTo get AI-powered suggestions, configure the AgentRunner integration.",
        "modified_spec": spec_content,
        "failed_count": len(failed_results),
    }
