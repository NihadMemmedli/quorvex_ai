from typing import Any

from fastapi import APIRouter

router = APIRouter()
_REGISTERED = False


def register_agent_routes(runtime: Any) -> None:
    """Register agent API routes against handlers kept in main.py."""
    global _REGISTERED
    if _REGISTERED:
        return

    routes = [
        ("POST", "/api/agents/runs", runtime.run_agent),
        ("GET", "/api/agents/runs", runtime.list_agent_runs),
        ("GET", "/api/agents/runs/{id}", runtime.get_agent_run),
        ("GET", "/api/agents/runs/{id}/coding/diff", runtime.get_coding_agent_diff),
        ("POST", "/api/agents/runs/{id}/coding/reject", runtime.reject_coding_agent_diff),
        ("POST", "/api/agents/runs/{id}/coding/apply", runtime.apply_coding_agent_diff),
        ("GET", "/api/agents/runs/{id}/events", runtime.list_agent_run_events_api),
        ("GET", "/api/agents/runs/{id}/events/stream", runtime.stream_agent_run_events_api),
        ("GET", "/api/agents/runs/{id}/trace", runtime.get_agent_run_trace_api),
        ("GET", "/api/agents/runs/{id}/trace/spans", runtime.list_agent_run_trace_spans_api),
        ("GET", "/api/agents/runs/{id}/trace/export", runtime.export_agent_run_trace_api),
        ("GET", "/api/agents/temporal/health", runtime.get_agent_temporal_health),
        ("POST", "/api/agents/runs/{id}/pause", runtime.pause_agent_run),
        ("POST", "/api/agents/runs/{id}/resume", runtime.resume_agent_run),
        ("POST", "/api/agents/runs/{id}/cancel", runtime.cancel_agent_run),
        ("POST", "/api/agents/runs/{id}/retry", runtime.retry_agent_run),
        ("GET", "/api/agents/runs/{id}/report", runtime.get_agent_run_report),
        ("PATCH", "/api/agents/runs/{run_id}/report", runtime.update_agent_run_report_overview),
        ("PATCH", "/api/agents/runs/{run_id}/report-items/{item_id}", runtime.update_agent_run_report_item),
        ("GET", "/api/agents/reports/search", runtime.search_agent_reports),
        ("POST", "/api/agents/runs/{run_id}/report-requirements/import", runtime.import_agent_report_requirements),
        ("POST", "/api/agents/exploratory", runtime.run_exploratory_agent),
        ("POST", "/api/agents/exploratory/{run_id}/synthesize", runtime.synthesize_specs),
        ("GET", "/api/agents/exploratory/{run_id}/specs", runtime.get_exploration_specs),
        ("GET", "/api/agents/exploratory/{run_id}/flows/{flow_id}", runtime.get_flow_details),
        ("PUT", "/api/agents/exploratory/{run_id}/flows/{flow_id}", runtime.update_flow),
        ("DELETE", "/api/agents/exploratory/{run_id}/flows/{flow_id}", runtime.delete_flow),
        ("POST", "/api/agents/exploratory/{run_id}/analyze-prerequisites", runtime.analyze_prerequisites),
        ("POST", "/api/agents/exploratory/{run_id}/flows/{flow_id}/spec", runtime.generate_flow_spec),
        ("GET", "/api/agents/exploratory/flow-spec-jobs/{job_id}", runtime.get_flow_spec_job_status),
        (
            "POST",
            "/api/agents/runs/{run_id}/report-items/{item_id}/generate-spec",
            runtime.generate_report_item_spec,
        ),
        ("POST", "/api/agents/exploratory/{run_id}/flows/{flow_id}/generate", runtime.generate_flow_test),
    ]
    for method, path, endpoint in routes:
        router.add_api_route(path, endpoint, methods=[method])

    _REGISTERED = True
