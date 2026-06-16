from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["agent-sessions"])


@router.get("/api/agents/sessions")
async def list_sessions():
    """List saved authentication sessions."""
    from agents.auth_handler import AuthHandler

    auth_handler = AuthHandler()
    sessions = auth_handler.list_sessions()

    return {"sessions": sessions}


@router.post("/api/agents/sessions/{session_id}")
async def create_session(session_id: str, cookies: list[dict[str, Any]], storage: dict[str, Any]):
    """
    Save an authentication session for future use.

    This allows you to capture a logged-in session and reuse it
    for future explorations.
    """
    from agents.auth_handler import AuthHandler

    auth_handler = AuthHandler()
    result = await auth_handler.save_session(session_id, cookies, storage)

    if result.get("success"):
        return result
    else:
        raise HTTPException(status_code=400, detail=result.get("error"))


@router.delete("/api/agents/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a saved authentication session."""
    from agents.auth_handler import AuthHandler

    auth_handler = AuthHandler()
    if auth_handler.delete_session(session_id):
        return {"status": "deleted", "session_id": session_id}
    else:
        raise HTTPException(status_code=404, detail="Session not found")
