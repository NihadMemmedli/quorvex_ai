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
