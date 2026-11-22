"""API routes for the Milestone 3 Research Agent and session context."""

from typing import List

from fastapi import APIRouter, HTTPException

from app.agents.research_agent import ResearchAgentService
from app.schemas.research import (
    ResearchAnswerResponse,
    ResearchMessageResponse,
    ResearchQueryRequest,
)

router = APIRouter(tags=["Research Agent"])


def _run_query(
    session_id: str,
    payload: ResearchQueryRequest,
) -> ResearchAnswerResponse:
    try:
        service = ResearchAgentService()
        return service.answer_question(
            question=payload.question,
            document_ids=payload.document_ids,
            session_id=session_id,
            top_k=payload.top_k,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Research Agent failed: {exc}") from exc


@router.post("/research/sessions/{session_id}/query", response_model=ResearchAnswerResponse)
def query_research_session(session_id: str, payload: ResearchQueryRequest):
    """Answer a grounded, multi-part question within a research session."""
    return _run_query(session_id, payload)


@router.post("/research/query", response_model=ResearchAnswerResponse)
def query_research(payload: ResearchQueryRequest):
    """Stateless grounded research query across indexed documents."""
    return _run_query(None, payload)


@router.get(
    "/research/sessions/{session_id}/messages",
    response_model=List[ResearchMessageResponse],
)
def list_research_messages(session_id: str):
    """Return persisted conversation turns for a research session."""
    service = ResearchAgentService()
    return service.get_history(session_id)


@router.delete("/research/sessions/{session_id}/messages")
def clear_research_messages(session_id: str):
    """Clear the conversation context for a research session."""
    service = ResearchAgentService()
    deleted = service.clear_history(session_id)
    return {"session_id": session_id, "deleted": deleted}
