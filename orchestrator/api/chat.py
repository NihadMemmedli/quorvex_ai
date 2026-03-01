"""Chat conversation CRUD endpoints for the AI assistant."""

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, delete, func
from sqlmodel import Session, select

from .db import get_session
from .middleware.auth import get_current_user_optional
from .models_db import (
    ChatConversation,
    ChatMessage,
    ChatMessageFeedback,
    ExplorationSession,
    RegressionBatch,
    Requirement,
    RtmEntry,
    TestRun,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


# ---------- Request / Response schemas ----------


class CreateConversationRequest(BaseModel):
    title: str | None = "New Conversation"
    project_id: str | None = None


class UpdateConversationRequest(BaseModel):
    title: str


class SaveMessageRequest(BaseModel):
    role: str  # user, assistant, tool
    content: str = ""
    content_json: str | None = None  # Full UIMessage parts as JSON
    tool_name: str | None = None
    tool_args: dict | None = None
    tool_result: dict | None = None


class BulkSaveMessagesRequest(BaseModel):
    messages: list[SaveMessageRequest]


class UpdateContentJsonRequest(BaseModel):
    content_json: str


class SubmitFeedbackRequest(BaseModel):
    message_index: int
    rating: str  # "up" or "down"
    comment: str | None = None


# ---------- Conversations ----------


@router.get("/conversations")
async def list_conversations(
    project_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    """List conversations, optionally filtered by project."""
    query = select(ChatConversation).order_by(
        ChatConversation.is_starred.desc(),
        ChatConversation.updated_at.desc(),
    )

    if project_id:
        query = query.where(ChatConversation.project_id == project_id)
    if user:
        query = query.where(ChatConversation.user_id == user.id)

    total = session.exec(
        select(func.count())
        .select_from(ChatConversation)
        .where(
            *([ChatConversation.project_id == project_id] if project_id else []),
            *([ChatConversation.user_id == user.id] if user else []),
        )
    ).one()

    conversations = session.exec(query.offset(offset).limit(limit)).all()

    # Message counts per conversation
    conv_ids = [c.id for c in conversations]
    counts_map: dict[str, int] = {}
    if conv_ids:
        counts_rows = session.exec(
            select(ChatMessage.conversation_id, func.count())
            .where(ChatMessage.conversation_id.in_(conv_ids))
            .group_by(ChatMessage.conversation_id)
        ).all()
        counts_map = {row[0]: row[1] for row in counts_rows}

    return {
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
                "project_id": c.project_id,
                "is_starred": c.is_starred,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
                "message_count": counts_map.get(c.id, 0),
                "summary": c.summary,
            }
            for c in conversations
        ],
        "total": total,
    }


@router.get("/conversations/search")
async def search_conversations(
    q: str = Query(..., min_length=3),
    project_id: str | None = Query(None),
    limit: int = Query(20, ge=1, le=50),
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    """Search conversations by message content."""
    # First, find conversation IDs that match user/project filters
    conv_filter = select(ChatConversation.id)
    if user:
        conv_filter = conv_filter.where(ChatConversation.user_id == user.id)
    if project_id:
        conv_filter = conv_filter.where(ChatConversation.project_id == project_id)
    allowed_conv_ids = [row for row in session.exec(conv_filter).all()]

    if not allowed_conv_ids:
        return {"results": []}

    # Search messages within those conversations
    msg_query = (
        select(ChatMessage.conversation_id, ChatMessage.content)
        .where(
            ChatMessage.conversation_id.in_(allowed_conv_ids),
            ChatMessage.content.ilike(f"%{q}%"),
        )
        .limit(limit * 3)
    )
    results = session.exec(msg_query).all()

    # Group by conversation, get first matching snippet
    seen: dict[str, str] = {}
    for conv_id, content in results:
        if conv_id not in seen:
            idx = content.lower().find(q.lower())
            start = max(0, idx - 40)
            end = min(len(content), idx + len(q) + 40)
            snippet = ("..." if start > 0 else "") + content[start:end] + ("..." if end < len(content) else "")
            seen[conv_id] = snippet
        if len(seen) >= limit:
            break

    if not seen:
        return {"results": []}

    convs = session.exec(select(ChatConversation).where(ChatConversation.id.in_(list(seen.keys())))).all()

    return {
        "results": [
            {
                "id": c.id,
                "title": c.title,
                "snippet": seen.get(c.id, ""),
                "updated_at": c.updated_at.isoformat(),
            }
            for c in convs
        ]
    }


@router.post("/conversations")
async def create_conversation(
    req: CreateConversationRequest,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    """Create a new conversation."""
    conv = ChatConversation(
        title=req.title or "New Conversation",
        project_id=req.project_id,
        user_id=user.id if user else None,
    )
    session.add(conv)
    session.commit()
    session.refresh(conv)
    return {
        "id": conv.id,
        "title": conv.title,
        "project_id": conv.project_id,
        "is_starred": conv.is_starred,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
    }


@router.put("/conversations/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    req: UpdateConversationRequest,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    """Update conversation title."""
    conv = session.get(ChatConversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if user and conv.user_id and conv.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your conversation")

    conv.title = req.title
    conv.updated_at = datetime.utcnow()
    session.add(conv)
    session.commit()
    return {"ok": True}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    """Delete a conversation and all its messages and feedback."""
    conv = session.get(ChatConversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if user and conv.user_id and conv.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your conversation")

    try:
        # Bulk SQL DELETE in FK-safe order (bypasses ORM UoW ordering issues)
        session.execute(delete(ChatMessageFeedback).where(ChatMessageFeedback.conversation_id == conversation_id))
        session.execute(delete(ChatMessage).where(ChatMessage.conversation_id == conversation_id))
        session.execute(delete(ChatConversation).where(ChatConversation.id == conversation_id))
        session.commit()
        logger.info(f"Deleted conversation {conversation_id}")
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to delete conversation {conversation_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete conversation")

    return {"ok": True}


# ---------- Messages ----------


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: str,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    """Get all messages for a conversation."""
    conv = session.get(ChatConversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if user and conv.user_id and conv.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your conversation")

    messages = session.exec(
        select(ChatMessage).where(ChatMessage.conversation_id == conversation_id).order_by(ChatMessage.created_at)
    ).all()

    return {
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "content_json": m.content_json,
                "tool_name": m.tool_name,
                "tool_args": m.tool_args,
                "tool_result": m.tool_result,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ]
    }


@router.post("/conversations/{conversation_id}/messages")
async def save_message(
    conversation_id: str,
    req: SaveMessageRequest,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    """Save a message to a conversation."""
    conv = session.get(ChatConversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msg = ChatMessage(
        conversation_id=conversation_id,
        role=req.role,
        content=req.content,
        content_json=req.content_json,
    )
    if req.tool_name:
        msg.tool_name = req.tool_name
    if req.tool_args:
        msg.tool_args = req.tool_args
    if req.tool_result:
        msg.tool_result = req.tool_result

    session.add(msg)

    # Update conversation timestamp
    conv.updated_at = datetime.utcnow()
    session.add(conv)

    session.commit()
    session.refresh(msg)
    return {
        "id": msg.id,
        "role": msg.role,
        "content": msg.content,
        "created_at": msg.created_at.isoformat(),
    }


@router.post("/conversations/{conversation_id}/messages/bulk")
async def save_messages_bulk(
    conversation_id: str,
    req: BulkSaveMessagesRequest,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    """Save multiple messages in one request (user + assistant after each turn)."""
    conv = session.get(ChatConversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    saved = []
    for m in req.messages:
        msg = ChatMessage(
            conversation_id=conversation_id,
            role=m.role,
            content=m.content,
            content_json=m.content_json,
        )
        if m.tool_name:
            msg.tool_name = m.tool_name
        if m.tool_args:
            msg.tool_args = m.tool_args
        if m.tool_result:
            msg.tool_result = m.tool_result
        session.add(msg)
        saved.append(msg)

    conv.updated_at = datetime.utcnow()
    session.add(conv)
    session.commit()

    return {"saved": len(saved)}


@router.patch("/conversations/{conversation_id}/messages/{message_id}/content-json")
async def update_message_content_json(
    conversation_id: str,
    message_id: int,
    req: UpdateContentJsonRequest,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    """Update the content_json of an existing message (e.g. to persist tool results)."""
    conv = session.get(ChatConversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if user and conv.user_id and conv.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your conversation")

    msg = session.get(ChatMessage, message_id)
    if not msg or msg.conversation_id != conversation_id:
        raise HTTPException(status_code=404, detail="Message not found")

    msg.content_json = req.content_json
    session.add(msg)

    conv.updated_at = datetime.utcnow()
    session.add(conv)

    session.commit()
    return {"ok": True}


async def _generate_ai_title(user_message: str, assistant_message: str = "") -> str:
    """Generate a concise conversation title using AI."""
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    model = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-20250514")

    if not auth_token:
        raise ValueError("No ANTHROPIC_AUTH_TOKEN configured")

    user_part = user_message[:200].strip()
    assistant_part = assistant_message[:200].strip() if assistant_message else ""

    content = f"User: {user_part}"
    if assistant_part:
        content += f"\nAssistant: {assistant_part}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{base_url}/v1/messages",
            headers={
                "x-api-key": auth_token,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 30,
                "system": "Generate a concise 5-8 word title for this conversation. Return ONLY the title text, nothing else. No quotes, no punctuation at the end.",
                "messages": [{"role": "user", "content": content}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        title = data["content"][0]["text"].strip().strip("\"'")

        if len(title) < 3 or len(title) > 80:
            raise ValueError(f"Title length out of range: {len(title)}")

        return title


@router.post("/conversations/{conversation_id}/auto-title")
async def auto_title(
    conversation_id: str,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    """Generate a conversation title using AI, with truncation fallback."""
    conv = session.get(ChatConversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    first_user_msg = session.exec(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .where(ChatMessage.role == "user")
        .order_by(ChatMessage.created_at)
        .limit(1)
    ).first()

    if not first_user_msg or not first_user_msg.content:
        return {"title": conv.title}

    # Also fetch first assistant message for better context
    first_assistant_msg = session.exec(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .where(ChatMessage.role == "assistant")
        .order_by(ChatMessage.created_at)
        .limit(1)
    ).first()

    title = None
    try:
        title = await _generate_ai_title(
            first_user_msg.content,
            first_assistant_msg.content if first_assistant_msg else "",
        )
    except Exception as e:
        logger.warning(f"AI title generation failed, using fallback: {e}")

    # Fallback to truncation
    if not title:
        title = first_user_msg.content.strip()
        if len(title) > 60:
            title = title[:57] + "..."

    conv.title = title
    conv.updated_at = datetime.utcnow()
    session.add(conv)
    session.commit()

    return {"title": conv.title}


@router.post("/conversations/{conversation_id}/generate-summary")
async def generate_summary(
    conversation_id: str,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    """Generate a summary from first user message and last assistant message."""
    conv = session.get(ChatConversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if user and conv.user_id and conv.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your conversation")

    first_user_msg = session.exec(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .where(ChatMessage.role == "user")
        .order_by(ChatMessage.created_at)
        .limit(1)
    ).first()

    last_assistant_msg = session.exec(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .where(ChatMessage.role == "assistant")
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
    ).first()

    first_part = (first_user_msg.content or "")[:100] if first_user_msg else ""
    last_part = (last_assistant_msg.content or "")[:100] if last_assistant_msg else ""

    summary = f"{first_part} → {last_part}"
    if len(summary) > 150:
        summary = summary[:150]

    conv.summary = summary
    conv.updated_at = datetime.utcnow()
    session.add(conv)
    session.commit()

    return {"summary": conv.summary}


# ---------- Feedback & Starring ----------


@router.post("/conversations/{conversation_id}/feedback")
async def submit_feedback(
    conversation_id: str,
    req: SubmitFeedbackRequest,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    """Submit feedback (thumbs up/down) on an AI message."""
    conv = session.get(ChatConversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if user and conv.user_id and conv.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your conversation")

    if req.rating not in ("up", "down"):
        raise HTTPException(status_code=400, detail="Rating must be 'up' or 'down'")

    feedback = ChatMessageFeedback(
        conversation_id=conversation_id,
        message_index=req.message_index,
        rating=req.rating,
        comment=req.comment,
        user_id=user.id if user else None,
    )
    session.add(feedback)
    session.commit()
    session.refresh(feedback)

    return {
        "id": feedback.id,
        "conversation_id": feedback.conversation_id,
        "message_index": feedback.message_index,
        "rating": feedback.rating,
        "comment": feedback.comment,
        "created_at": feedback.created_at.isoformat(),
    }


@router.patch("/conversations/{conversation_id}/star")
async def toggle_star(
    conversation_id: str,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    """Toggle the starred status of a conversation."""
    conv = session.get(ChatConversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if user and conv.user_id and conv.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your conversation")

    conv.is_starred = not conv.is_starred
    conv.updated_at = datetime.utcnow()
    session.add(conv)
    session.commit()

    return {"is_starred": conv.is_starred}


# ---------- Recent Summaries ----------


@router.get("/conversations/recent-summaries")
async def get_recent_summaries(
    project_id: str | None = Query(None),
    limit: int = Query(5, ge=1, le=10),
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    """Get recent conversation titles + first/last messages for context."""
    query = select(ChatConversation).order_by(ChatConversation.updated_at.desc())
    if project_id:
        query = query.where(ChatConversation.project_id == project_id)
    if user:
        query = query.where(ChatConversation.user_id == user.id)

    conversations = session.exec(query.limit(limit)).all()
    summaries = []

    for conv in conversations:
        messages = session.exec(
            select(ChatMessage).where(ChatMessage.conversation_id == conv.id).order_by(ChatMessage.created_at)
        ).all()

        first_msg = ""
        last_msg = ""
        if messages:
            first_msg = messages[0].content[:200] if messages[0].content else ""
            if len(messages) > 1:
                last_msg = messages[-1].content[:200] if messages[-1].content else ""

        summaries.append(
            {
                "id": conv.id,
                "title": conv.title,
                "first_message": first_msg,
                "last_message": last_msg,
                "updated_at": conv.updated_at.isoformat(),
            }
        )

    return {"summaries": summaries}


# ---------- Project Context ----------


@router.get("/project-context")
async def get_project_context(
    project_id: str | None = Query(None),
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    """Get compact project stats for proactive AI prompts."""
    now = datetime.utcnow()
    seven_days_ago = now - timedelta(days=7)
    fourteen_days_ago = now - timedelta(days=14)
    thirty_days_ago = now - timedelta(days=30)

    result = {
        "recent_runs": 0,
        "recent_failures": 0,
        "total_requirements": 0,
        "recent_explorations": 0,
        "flaky_tests": [],
        "pass_rate_7d": 0.0,
        "pass_rate_prior_7d": 0.0,
        "stale_specs_count": 0,
        "uncovered_requirements_count": 0,
        "welcome_cards": [],
        "dynamic_suggestions": [],
    }

    try:
        # Recent test runs (last 7 days)
        runs_query = select(func.count()).select_from(TestRun).where(TestRun.created_at >= seven_days_ago)
        failures_query = (
            select(func.count())
            .select_from(TestRun)
            .where(
                TestRun.created_at >= seven_days_ago,
                TestRun.status == "failed",
            )
        )
        if project_id:
            runs_query = runs_query.where(TestRun.project_id == project_id)
            failures_query = failures_query.where(TestRun.project_id == project_id)

        result["recent_runs"] = session.exec(runs_query).one()
        result["recent_failures"] = session.exec(failures_query).one()

        # Total requirements
        req_query = select(func.count()).select_from(Requirement)
        if project_id:
            req_query = req_query.where(Requirement.project_id == project_id)
        result["total_requirements"] = session.exec(req_query).one()

        # Recent explorations (last 7 days)
        exp_query = (
            select(func.count()).select_from(ExplorationSession).where(ExplorationSession.created_at >= seven_days_ago)
        )
        if project_id:
            exp_query = exp_query.where(ExplorationSession.project_id == project_id)
        result["recent_explorations"] = session.exec(exp_query).one()

        # --- Extended stats ---

        # Pass rate for last 7 days
        passed_7d_query = (
            select(func.count())
            .select_from(TestRun)
            .where(
                TestRun.created_at >= seven_days_ago,
                TestRun.status == "passed",
            )
        )
        if project_id:
            passed_7d_query = passed_7d_query.where(TestRun.project_id == project_id)
        passed_7d = session.exec(passed_7d_query).one()
        total_7d = result["recent_runs"]
        result["pass_rate_7d"] = round((passed_7d / total_7d * 100) if total_7d > 0 else 0.0, 1)

        # Pass rate for prior 7 days (7-14 days ago)
        prior_runs_query = (
            select(func.count())
            .select_from(TestRun)
            .where(
                TestRun.created_at >= fourteen_days_ago,
                TestRun.created_at < seven_days_ago,
            )
        )
        prior_passed_query = (
            select(func.count())
            .select_from(TestRun)
            .where(
                TestRun.created_at >= fourteen_days_ago,
                TestRun.created_at < seven_days_ago,
                TestRun.status == "passed",
            )
        )
        if project_id:
            prior_runs_query = prior_runs_query.where(TestRun.project_id == project_id)
            prior_passed_query = prior_passed_query.where(TestRun.project_id == project_id)
        prior_total = session.exec(prior_runs_query).one()
        prior_passed = session.exec(prior_passed_query).one()
        result["pass_rate_prior_7d"] = round((prior_passed / prior_total * 100) if prior_total > 0 else 0.0, 1)

        # Flaky tests: specs with both passed and failed in last 14 days
        flaky_base = (
            select(
                TestRun.spec_name,
                func.count().label("total"),
                func.sum(case((TestRun.status == "passed", 1), else_=0)).label("pass_count"),
                func.sum(case((TestRun.status == "failed", 1), else_=0)).label("fail_count"),
            )
            .where(TestRun.created_at >= fourteen_days_ago)
            .group_by(TestRun.spec_name)
        )
        if project_id:
            flaky_base = flaky_base.where(TestRun.project_id == project_id)
        flaky_rows = session.exec(flaky_base).all()
        flaky_list = []
        for row in flaky_rows:
            spec_name, total, pass_count, fail_count = row
            if (pass_count or 0) > 0 and (fail_count or 0) > 0:
                flaky_list.append(
                    {
                        "spec_name": spec_name,
                        "pass_count": pass_count or 0,
                        "fail_count": fail_count or 0,
                    }
                )
        # Sort by most failures, take top 3
        flaky_list.sort(key=lambda x: x["fail_count"], reverse=True)
        result["flaky_tests"] = flaky_list[:3]

        # Stale specs: specs whose latest run is older than 30 days
        latest_run_per_spec = select(
            TestRun.spec_name,
            func.max(TestRun.created_at).label("last_run"),
        ).group_by(TestRun.spec_name)
        if project_id:
            latest_run_per_spec = latest_run_per_spec.where(TestRun.project_id == project_id)
        spec_rows = session.exec(latest_run_per_spec).all()
        stale_count = sum(1 for _, last_run in spec_rows if last_run < thirty_days_ago)
        result["stale_specs_count"] = stale_count

        # Uncovered requirements: requirements with no RTM entry
        uncovered_base = (
            select(func.count()).select_from(Requirement).where(~Requirement.id.in_(select(RtmEntry.requirement_id)))
        )
        if project_id:
            uncovered_base = uncovered_base.where(Requirement.project_id == project_id)
        result["uncovered_requirements_count"] = session.exec(uncovered_base).one()

        # --- Welcome cards ---
        welcome_cards = []

        # Card 1: Failures or Test Management
        if result["recent_failures"] > 0:
            welcome_cards.append(
                {
                    "icon": "AlertTriangle",
                    "label": "Failing Tests",
                    "desc": f"{result['recent_failures']} failures this week",
                    "suggestion": "Analyze recent test failures",
                    "color": "#ef4444",
                    "metric": str(result["recent_failures"]),
                }
            )
        else:
            welcome_cards.append(
                {
                    "icon": "FlaskConical",
                    "label": "Test Management",
                    "desc": "Run and manage tests",
                    "suggestion": "Show recent test results",
                    "color": "#3b82f6",
                    "metric": None,
                }
            )

        # Card 2: Pass Rate or Discovery
        if result["pass_rate_7d"] > 0:
            welcome_cards.append(
                {
                    "icon": "BarChart3",
                    "label": "Pass Rate",
                    "desc": f"{result['pass_rate_7d']}% this week",
                    "suggestion": "Show pass rate trends",
                    "color": "#10b981" if result["pass_rate_7d"] >= 80 else "#f59e0b",
                    "metric": f"{result['pass_rate_7d']}%",
                }
            )
        else:
            welcome_cards.append(
                {
                    "icon": "Search",
                    "label": "Discovery",
                    "desc": "Explore apps and generate requirements",
                    "suggestion": "Start new exploration",
                    "color": "#8b5cf6",
                    "metric": None,
                }
            )

        # Card 3: Flaky Tests or Security
        if len(result["flaky_tests"]) > 0:
            welcome_cards.append(
                {
                    "icon": "RefreshCw",
                    "label": "Flaky Tests",
                    "desc": f"{len(result['flaky_tests'])} flaky specs detected",
                    "suggestion": "Show flaky test analysis",
                    "color": "#f59e0b",
                    "metric": str(len(result["flaky_tests"])),
                }
            )
        else:
            welcome_cards.append(
                {
                    "icon": "Shield",
                    "label": "Security",
                    "desc": "Scan for vulnerabilities",
                    "suggestion": "Run a security scan",
                    "color": "#ef4444",
                    "metric": None,
                }
            )

        # Card 4: Coverage Gaps or Analytics
        if result["uncovered_requirements_count"] > 0:
            welcome_cards.append(
                {
                    "icon": "Clock",
                    "label": "Coverage Gaps",
                    "desc": f"{result['uncovered_requirements_count']} uncovered requirements",
                    "suggestion": "Check RTM coverage",
                    "color": "#8b5cf6",
                    "metric": str(result["uncovered_requirements_count"]),
                }
            )
        else:
            welcome_cards.append(
                {
                    "icon": "BarChart3",
                    "label": "Analytics",
                    "desc": "Track trends and performance",
                    "suggestion": "Show pass rate trends",
                    "color": "#10b981",
                    "metric": None,
                }
            )

        result["welcome_cards"] = welcome_cards

        # --- Dynamic suggestions ---
        dynamic_suggestions = [
            "What can you do?",
            "Show recent test results",
            "Dashboard stats",
            "Check coverage",
        ]
        if result["recent_failures"] > 0:
            dynamic_suggestions[0] = "Analyze recent failures"
        if len(result["flaky_tests"]) > 0:
            dynamic_suggestions[1] = "Show flaky test analysis"
        if result["uncovered_requirements_count"] > 0:
            dynamic_suggestions[3] = "Show uncovered requirements"

        result["dynamic_suggestions"] = dynamic_suggestions

    except Exception as e:
        logger.warning(f"Error fetching project context: {e}")

    return result


# ---------- Entity Search & Resolve ----------

SPECS_DIR = Path(__file__).resolve().parent.parent.parent / "specs"


@router.get("/search-entities")
async def search_entities(
    q: str = Query(..., min_length=1),
    project_id: str | None = Query(None),
    limit: int = Query(10, ge=1, le=30),
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    """Search across specs, runs, batches, explorations, and requirements."""
    entities: list[dict] = []
    q_lower = q.lower()
    per_type_limit = max(limit // 5, 2)

    # 1. Test specs (filesystem glob)
    try:
        if SPECS_DIR.exists():
            for spec_path in SPECS_DIR.rglob("*.md"):
                if spec_path.name.startswith("_"):
                    continue
                if q_lower in spec_path.name.lower():
                    rel = spec_path.relative_to(SPECS_DIR)
                    entities.append(
                        {
                            "type": "spec",
                            "id": str(rel),
                            "label": str(rel),
                            "description": "Test spec",
                        }
                    )
                    if len([e for e in entities if e["type"] == "spec"]) >= per_type_limit:
                        break
    except Exception as e:
        logger.warning(f"Error searching specs: {e}")

    # 2. Test runs
    try:
        runs_query = (
            select(TestRun)
            .where(TestRun.spec_name.ilike(f"%{q}%"))
            .order_by(TestRun.created_at.desc())
            .limit(per_type_limit)
        )
        if project_id:
            runs_query = runs_query.where(TestRun.project_id == project_id)
        runs = session.exec(runs_query).all()
        for r in runs:
            entities.append(
                {
                    "type": "run",
                    "id": r.id,
                    "label": f"Run {r.id[:12]}",
                    "description": f"{r.spec_name} — {r.status}",
                }
            )
    except Exception as e:
        logger.warning(f"Error searching runs: {e}")

    # 3. Regression batches
    try:
        batch_query = (
            select(RegressionBatch)
            .where((RegressionBatch.name.ilike(f"%{q}%")) | (RegressionBatch.id.ilike(f"%{q}%")))
            .order_by(RegressionBatch.created_at.desc())
            .limit(per_type_limit)
        )
        if project_id:
            batch_query = batch_query.where(RegressionBatch.project_id == project_id)
        batches = session.exec(batch_query).all()
        for b in batches:
            label = f"Batch: {b.name}" if b.name else b.id
            entities.append(
                {
                    "type": "batch",
                    "id": b.id,
                    "label": label,
                    "description": f"{b.total_tests} tests, {b.passed} passed",
                }
            )
    except Exception as e:
        logger.warning(f"Error searching batches: {e}")

    # 4. Exploration sessions
    try:
        exp_query = (
            select(ExplorationSession)
            .where((ExplorationSession.entry_url.ilike(f"%{q}%")) | (ExplorationSession.id.ilike(f"%{q}%")))
            .order_by(ExplorationSession.created_at.desc())
            .limit(per_type_limit)
        )
        if project_id:
            exp_query = exp_query.where(ExplorationSession.project_id == project_id)
        explorations = session.exec(exp_query).all()
        for e in explorations:
            entities.append(
                {
                    "type": "exploration",
                    "id": e.id,
                    "label": e.id,
                    "description": e.entry_url,
                }
            )
    except Exception as e:
        logger.warning(f"Error searching explorations: {e}")

    # 5. Requirements
    try:
        req_query = (
            select(Requirement)
            .where((Requirement.req_code.ilike(f"%{q}%")) | (Requirement.title.ilike(f"%{q}%")))
            .order_by(Requirement.created_at.desc())
            .limit(per_type_limit)
        )
        if project_id:
            req_query = req_query.where(Requirement.project_id == project_id)
        requirements = session.exec(req_query).all()
        for r in requirements:
            entities.append(
                {
                    "type": "requirement",
                    "id": str(r.id),
                    "label": r.req_code,
                    "description": r.title,
                }
            )
    except Exception as e:
        logger.warning(f"Error searching requirements: {e}")

    return {"entities": entities[:limit]}


@router.get("/resolve-entity")
async def resolve_entity(
    type: str = Query(..., regex="^(spec|run|batch|requirement|exploration)$"),
    id: str = Query(..., min_length=1),
    project_id: str | None = Query(None),
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    """Resolve an entity to its full content for AI context injection."""

    if type == "spec":
        # Search for the spec file in specs/
        spec_path = SPECS_DIR / id
        if not spec_path.exists():
            # Try globbing for a match
            matches = list(SPECS_DIR.rglob(id))
            if not matches:
                raise HTTPException(status_code=404, detail=f"Spec '{id}' not found")
            spec_path = matches[0]
        # Ensure the path is within SPECS_DIR (prevent path traversal)
        try:
            spec_path.resolve().relative_to(SPECS_DIR.resolve())
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid spec path")
        content = spec_path.read_text(encoding="utf-8")
        return {
            "type": "spec",
            "id": id,
            "label": spec_path.name,
            "content": content,
        }

    elif type == "run":
        run = session.get(TestRun, id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run '{id}' not found")
        content = (
            f"Status: {run.status}\n"
            f"Spec: {run.spec_name}\n"
            f"Error: {run.error_message or 'none'}\n"
            f"Steps: {run.steps_completed}/{run.total_steps}\n"
            f"Stage: {run.current_stage or 'n/a'}\n"
            f"Created: {run.created_at.isoformat()}"
        )
        return {
            "type": "run",
            "id": run.id,
            "label": f"Run {run.id[:12]}",
            "content": content,
        }

    elif type == "batch":
        batch = session.get(RegressionBatch, id)
        if not batch:
            raise HTTPException(status_code=404, detail=f"Batch '{id}' not found")
        content = (
            f"Name: {batch.name or batch.id}\n"
            f"Status: {batch.status}\n"
            f"Total: {batch.total_tests}, Passed: {batch.passed}, Failed: {batch.failed}\n"
            f"Browser: {batch.browser}\n"
            f"Created: {batch.created_at.isoformat()}"
        )
        if batch.completed_at:
            content += f"\nCompleted: {batch.completed_at.isoformat()}"
        return {
            "type": "batch",
            "id": batch.id,
            "label": f"Batch: {batch.name}" if batch.name else batch.id,
            "content": content,
        }

    elif type == "requirement":
        req = session.get(Requirement, int(id))
        if not req:
            raise HTTPException(status_code=404, detail=f"Requirement '{id}' not found")
        content = (
            f"Code: {req.req_code}\n"
            f"Title: {req.title}\n"
            f"Category: {req.category}\n"
            f"Priority: {req.priority}\n"
            f"Status: {req.status}\n"
            f"Description: {req.description or 'n/a'}\n"
            f"Acceptance Criteria: {', '.join(req.acceptance_criteria) if req.acceptance_criteria else 'none'}"
        )
        return {
            "type": "requirement",
            "id": str(req.id),
            "label": req.req_code,
            "content": content,
        }

    elif type == "exploration":
        exp = session.get(ExplorationSession, id)
        if not exp:
            raise HTTPException(status_code=404, detail=f"Exploration '{id}' not found")
        content = (
            f"URL: {exp.entry_url}\n"
            f"Status: {exp.status}\n"
            f"Strategy: {exp.strategy}\n"
            f"Pages discovered: {exp.pages_discovered}\n"
            f"Flows discovered: {exp.flows_discovered}\n"
            f"API endpoints discovered: {exp.api_endpoints_discovered}\n"
            f"Created: {exp.created_at.isoformat()}"
        )
        if exp.error_message:
            content += f"\nError: {exp.error_message}"
        return {
            "type": "exploration",
            "id": exp.id,
            "label": exp.id,
            "content": content,
        }

    raise HTTPException(status_code=400, detail=f"Unknown entity type: {type}")
