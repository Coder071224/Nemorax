"""Conversation history routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from nemorax.backend.api.dependencies import get_services
from nemorax.backend.core.errors import NotFoundError
from nemorax.backend.runtime import ApplicationServices
from nemorax.backend.schemas import ConversationRecord, HistoryListItem


router = APIRouter(tags=["history"])


@router.get("/api/history", response_model=list[HistoryListItem])
async def list_history(
    user_id: str = Query(...),
    services: ApplicationServices = Depends(get_services),
) -> list[HistoryListItem]:
    return services.history_service.list_conversations(user_id)


@router.get("/api/history/{session_id}", response_model=ConversationRecord)
async def get_history(
    session_id: str,
    user_id: str = Query(...),
    services: ApplicationServices = Depends(get_services),
) -> ConversationRecord:
    return services.history_service.get_conversation(session_id, user_id)


@router.delete("/api/history/{session_id}")
async def delete_history(
    session_id: str,
    user_id: str = Query(...),
    services: ApplicationServices = Depends(get_services),
) -> dict[str, str]:
    if not services.history_service.delete_conversation(session_id, user_id):
        raise NotFoundError("Conversation not found")
    return {"deleted": session_id}
