"""API route for the Milestone 3.4 Report Agent (initial sections)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents.report_agent import ReportAgentService
from app.schemas.research import GeneratedReport

router = APIRouter(tags=["Report Agent"])


class GenerateReportRequest(BaseModel):
    document_id: str = Field(..., description="Document to compile the report for")


@router.post("/reports/generate", response_model=GeneratedReport)
def generate_report(payload: GenerateReportRequest):
    """Generate the Executive Summary and Key Financials report sections."""
    try:
        service = ReportAgentService()
        return service.generate_report(payload.document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Report Agent failed: {exc}") from exc
