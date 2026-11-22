"""API route for the Milestone 3.2 Comparison Agent."""

from fastapi import APIRouter, HTTPException

from app.agents.comparison_agent import ComparisonAgentService
from app.schemas.research import ComparisonRequest, ComparisonResponse

router = APIRouter(tags=["Comparison Agent"])


@router.post("/comparison", response_model=ComparisonResponse)
def compare_companies(payload: ComparisonRequest):
    """Compare evidence-backed financial metrics across company documents."""
    try:
        service = ComparisonAgentService()
        return service.compare_documents(
            document_ids=payload.document_ids,
            metrics=payload.metrics,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Comparison Agent failed: {exc}") from exc
