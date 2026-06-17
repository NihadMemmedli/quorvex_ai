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
    ]
    for method, path, endpoint in routes:
        router.add_api_route(path, endpoint, methods=[method])

    _REGISTERED = True
