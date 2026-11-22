"""Pydantic contracts for Milestone 3 agents (Research, Comparison, Report)."""

from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ==============================================================================
# Shared citation contract
# ==============================================================================

class AgentCitation(BaseModel):
    document_id: str
    document_name: str
    company: Optional[str] = None
    page_number: int
    exact_quote: str
    section: Optional[str] = None
    metric_name: Optional[str] = None
    is_calculated: bool = False


# ==============================================================================
# M3.1 Research Agent
# ==============================================================================

class ResearchQueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    document_ids: Optional[List[str]] = None
    top_k: int = Field(default=6, ge=1, le=20)


class ResearchStep(BaseModel):
    step: int
    title: str
    detail: str


class ResearchAnswerResponse(BaseModel):
    question: str
    answer: str
    direct_facts: List[str] = Field(default_factory=list)
    calculated_values: List[str] = Field(default_factory=list)
    analytical_conclusions: List[str] = Field(default_factory=list)
    unavailable_information: List[str] = Field(default_factory=list)
    citations: List[AgentCitation] = Field(default_factory=list)
    steps: List[ResearchStep] = Field(default_factory=list)
    documents_used: List[str] = Field(default_factory=list)
    context_used: List[str] = Field(default_factory=list)
    grounding: str = "strict_source_documents"
    session_id: Optional[str] = None
    user_message_id: Optional[str] = None
    message_id: Optional[str] = None


class ResearchMessageResponse(BaseModel):
    message_id: str
    session_id: str
    role: str
    content: str
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str


# ==============================================================================
# M3.2 Comparison Agent
# ==============================================================================

class ComparisonRequest(BaseModel):
    document_ids: List[str] = Field(..., min_length=2, description="Documents to compare")
    metrics: Optional[List[str]] = Field(
        default=None,
        description="Optional canonical metric filter, e.g. REVENUE, NET_INCOME",
    )


class ComparisonMetricValue(BaseModel):
    metric_name: str
    value: Optional[Decimal] = None
    normalized_value: Optional[Decimal] = None
    unit: str = ""
    currency: str = ""
    display_value: Optional[str] = None
    page_number: Optional[int] = None
    is_calculated: bool = False
    note: Optional[str] = None


class ComparisonCompany(BaseModel):
    document_id: str
    company_name: str
    filename: str
    fiscal_year: Optional[int] = None
    currency: Optional[str] = None
    reported_unit: Optional[str] = None
    metrics: List[ComparisonMetricValue] = Field(default_factory=list)
    missing_metrics: List[str] = Field(default_factory=list)


class ComparisonResponse(BaseModel):
    comparison_id: str
    companies: List[ComparisonCompany]
    metric_names: List[str]
    periods: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    summary: str
    citations: List[AgentCitation] = Field(default_factory=list)
    generated_at: str


# ==============================================================================
# M3.4 Report Agent (initial structure)
# ==============================================================================

class ReportSection(BaseModel):
    section_key: str
    title: str
    status: str = "generated"  # generated | planned | unavailable
    content_markdown: str = ""
    citations: List[AgentCitation] = Field(default_factory=list)


class GeneratedReport(BaseModel):
    report_id: str
    document_id: str
    company_name: str
    fiscal_year: Optional[int] = None
    title: str
    generated_at: str
    status: str
    sections: List[ReportSection]
    planned_sections: List[str] = Field(default_factory=list)
    citations: List[AgentCitation] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
