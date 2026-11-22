"""LangGraph Multi-Agent Orchestration Workflow.

Coordinates Document Agent -> Extraction Agent -> Validation -> Red Flag Agent -> Persistence.
Supports both native LangGraph StateGraph (when installed) and a pure Python workflow engine fallback.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.agents.document_agent import DocumentAgentService
from app.agents.extraction_agent import ExtractionAgentService
from app.agents.red_flag_agent import RedFlagAgentService
from app.infrastructure.database import get_database_repository
from app.infrastructure.storage import get_file_storage
from app.orchestration.evidence import (
    load_page_texts,
    validate_metrics,
    validate_red_flag_finding,
)
from app.orchestration.state import AgentExecutionLog, FinancialResearchState
from app.schemas.agents import ExtractedFinancials

logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ==============================================================================
# Node Implementations
# ==============================================================================

def document_agent_node(state: FinancialResearchState) -> FinancialResearchState:
    """Step 1: Document Ingestion, Parsing, Table Extraction, Chunking, Embedding, Indexing."""
    logger.info("Executing Document Agent node for doc: %s", state.document_id)
    repo = get_database_repository()
    doc_service = DocumentAgentService()

    start_time = utc_now()
    try:
        # If file bytes are provided directly:
        if state.file_bytes:
            upload_resp = doc_service.process_pdf_upload(
                file_bytes=state.file_bytes,
                filename=state.filename,
                workspace_id=state.workspace_id,
                session_id=state.session_id,
                document_id=state.document_id,
            )
            state.document_id = upload_resp.document_id
            state.total_pages = upload_resp.total_pages
            state.total_characters = upload_resp.characters_extracted
            state.chunk_count = upload_resp.chunk_count
            state.is_indexed = upload_resp.indexed
        elif state.storage_path and Path(state.storage_path).exists():
            file_bytes = Path(state.storage_path).read_bytes()
            upload_resp = doc_service.process_pdf_upload(
                file_bytes=file_bytes,
                filename=state.filename,
                workspace_id=state.workspace_id,
                session_id=state.session_id,
                document_id=state.document_id,
            )
            state.document_id = upload_resp.document_id
            state.total_pages = upload_resp.total_pages
            state.total_characters = upload_resp.characters_extracted
            state.chunk_count = upload_resp.chunk_count
            state.is_indexed = upload_resp.indexed
        else:
            # Check if document already exists in DB and is indexed
            existing = repo.get_document_by_id(state.document_id)
            if existing and existing.get("indexed"):
                state.total_pages = existing.get("total_pages", 0)
                state.chunk_count = existing.get("chunk_count", 0)
                state.is_indexed = True
            else:
                # Retrieve from storage abstraction (Supabase Storage or Local)
                storage = get_file_storage()
                obj_key = (existing.get("metadata") or {}).get("object_key") if existing else None
                file_bytes = None
                try:
                    file_bytes = storage.get_file_bytes(state.document_id, object_key=obj_key)
                except Exception as exc:
                    logger.debug("Storage retrieval in workflow: %s", exc)

                if file_bytes:
                    upload_resp = doc_service.process_pdf_upload(
                        file_bytes=file_bytes,
                        filename=state.filename,
                        workspace_id=state.workspace_id,
                        session_id=state.session_id,
                        document_id=state.document_id,
                    )
                    state.document_id = upload_resp.document_id
                    state.total_pages = upload_resp.total_pages
                    state.total_characters = upload_resp.characters_extracted
                    state.chunk_count = upload_resp.chunk_count
                    state.is_indexed = upload_resp.indexed
                else:
                    raise ValueError(
                        f"Cannot process document '{state.document_id}': file not found in storage or on disk."
                    )

        state.current_phase = "PARSED_AND_INDEXED"
        state.execution_steps.append(
            AgentExecutionLog(
                step_name="document_agent_node",
                agent="DOCUMENT_AGENT",
                status="SUCCESS",
                timestamp=start_time,
                message=f"Indexed {state.total_pages} pages and {state.chunk_count} chunks.",
            )
        )
        if state.job_id:
            repo.update_processing_job(state.job_id, status="PROCESSING", current_stage="DOCUMENT_AGENT_COMPLETED")

    except Exception as e:
        logger.exception("Error in document_agent_node: %s", e)
        state.is_failed = True
        state.errors.append(f"Document Agent Error: {e}")
        state.execution_steps.append(
            AgentExecutionLog(
                step_name="document_agent_node",
                agent="DOCUMENT_AGENT",
                status="FAILED",
                timestamp=start_time,
                message=str(e),
            )
        )
        if state.job_id:
            repo.update_processing_job(state.job_id, status="FAILED", current_stage="DOCUMENT_AGENT", error_message=str(e))

    return state


def extraction_agent_node(state: FinancialResearchState) -> FinancialResearchState:
    """Step 2: Financial Metric Extraction & Python Decimal Ratio Computations."""
    if state.is_failed or not state.is_indexed:
        logger.warning("Skipping extraction_agent_node due to upstream failure.")
        return state

    logger.info("Executing Extraction Agent node for doc: %s", state.document_id)
    repo = get_database_repository()
    ext_service = ExtractionAgentService()
    start_time = utc_now()

    try:
        financials: ExtractedFinancials = ext_service.extract_document_financials(
            document_id=state.document_id,
            session_id=state.session_id,
        )

        all_metrics_dict = {}
        for cat in (financials.income_statement, financials.balance_sheet, financials.cash_flow, financials.ratios):
            for name, m in cat.items():
                all_metrics_dict[name] = {
                    "name": m.name,
                    "value": str(m.value),
                    "statement": "KEY_RATIOS" if m.is_calculated else "STATEMENT",
                    "unit": m.unit,
                    "currency": m.currency,
                    "is_calculated": m.is_calculated,
                    "formula": m.formula,
                    "citation": {
                        "document_id": m.citation.document_id,
                        "page_number": m.citation.page_number,
                        "exact_quote": m.citation.exact_quote,
                        "is_calculated": m.citation.is_calculated,
                        "calculation_basis": m.citation.calculation_basis,
                    },
                }

        state.extracted_financials = {
            "company_name": financials.company_name,
            "fiscal_year": financials.fiscal_year,
            "is_consolidated": financials.is_consolidated,
            "metrics": all_metrics_dict,
            "_model": financials,
        }
        state.extracted_metrics_count = len(all_metrics_dict)
        state.current_phase = "EXTRACTION_COMPLETED"
        state.execution_steps.append(
            AgentExecutionLog(
                step_name="extraction_agent_node",
                agent="EXTRACTION_AGENT",
                status="SUCCESS",
                timestamp=start_time,
                message=f"Extracted {state.extracted_metrics_count} metrics.",
            )
        )
        if state.job_id:
            repo.update_processing_job(state.job_id, status="PROCESSING", current_stage="EXTRACTION_COMPLETED")

    except Exception as e:
        logger.exception("Error in extraction_agent_node: %s", e)
        state.is_failed = True
        state.errors.append(f"Extraction Agent Error: {e}")
        state.execution_steps.append(
            AgentExecutionLog(
                step_name="extraction_agent_node",
                agent="EXTRACTION_AGENT",
                status="FAILED",
                timestamp=start_time,
                message=str(e),
            )
        )
        if state.job_id:
            repo.update_processing_job(state.job_id, status="FAILED", current_stage="EXTRACTION_AGENT", error_message=str(e))

    return state


def _metric_rows_from_financials(model: ExtractedFinancials, allowed_names: set) -> List[Dict[str, Any]]:
    """Convert validated ExtractedFinancials metrics back into repository rows."""
    rows: List[Dict[str, Any]] = []
    groups = [
        (model.income_statement, "INCOME_STATEMENT"),
        (model.balance_sheet, "BALANCE_SHEET"),
        (model.cash_flow, "CASH_FLOW"),
        (model.ratios, "KEY_RATIOS"),
    ]
    for group, statement_type in groups:
        for name, metric in group.items():
            if name not in allowed_names:
                continue
            rows.append({
                "metric_name": metric.name,
                "source_label": metric.raw_text,
                "numeric_value": str(metric.value),
                "currency": metric.currency,
                "unit": metric.unit,
                "period_type": metric.period.value,
                "fiscal_year": metric.fiscal_year,
                "statement_type": statement_type,
                "is_calculated": metric.is_calculated,
                "formula": metric.formula,
                "is_consolidated": metric.is_consolidated,
                "citation": {
                    "document_id": metric.citation.document_id,
                    "page_number": metric.citation.page_number,
                    "exact_quote": metric.citation.exact_quote,
                    "table_index": metric.citation.table_index,
                },
            })
    return rows


def _apply_validated_metrics(
    state: FinancialResearchState,
    repo: Any,
    allowed_names: set,
) -> None:
    """Remove rejected metrics from state and replace the persisted metric set."""
    metrics = (state.extracted_financials or {}).get("metrics", {})
    state.extracted_financials["metrics"] = {
        name: value for name, value in metrics.items() if name in allowed_names
    }

    model = (state.extracted_financials or {}).get("_model")
    if isinstance(model, ExtractedFinancials):
        filtered = model.model_copy(deep=True)
        filtered.income_statement = {k: v for k, v in filtered.income_statement.items() if k in allowed_names}
        filtered.balance_sheet = {k: v for k, v in filtered.balance_sheet.items() if k in allowed_names}
        filtered.cash_flow = {k: v for k, v in filtered.cash_flow.items() if k in allowed_names}
        filtered.ratios = {k: v for k, v in filtered.ratios.items() if k in allowed_names}
        state.extracted_financials["_model"] = filtered
        rows = _metric_rows_from_financials(filtered, allowed_names)
        repo.store_financial_metrics(state.document_id, rows)

    state.extracted_metrics_count = len(state.extracted_financials["metrics"])


def evidence_validation_node(state: FinancialResearchState) -> FinancialResearchState:
    """Step 3: Verify every metric citation against the source document.

    Rejects metrics whose document, page, verbatim quote, or numeric value cannot
    be verified. Calculated ratios are accepted only when their calculation basis
    is itself built from verified source metrics. The pipeline fails when no
    metric can be grounded, rather than silently accepting unsupported claims.
    """
    start_time = utc_now()
    repo = get_database_repository()

    if state.is_failed or not state.extracted_financials:
        state.validation_passed = False
        return state

    metrics = state.extracted_financials.get("metrics", {})
    if not metrics:
        state.validation_passed = False
        state.is_failed = True
        err_msg = "Evidence validation failed: No financial metrics were extracted."
        state.errors.append(err_msg)
        state.validation_issues.append(err_msg)
        state.execution_steps.append(
            AgentExecutionLog(
                step_name="evidence_validation_node",
                agent="EVIDENCE_VALIDATION",
                status="FAILED",
                timestamp=start_time,
                message=err_msg,
            )
        )
        if state.job_id:
            repo.update_processing_job(
                state.job_id, status="FAILED", current_stage="EVIDENCE_VALIDATION", error_message=err_msg
            )
        return state

    document = repo.get_document_by_id(state.document_id)
    document_exists = document is not None
    total_pages = state.total_pages or int((document or {}).get("total_pages") or 0)
    state.total_pages = total_pages

    page_texts = state.page_texts
    if not page_texts and document_exists:
        page_texts = load_page_texts(
            document_id=state.document_id,
            file_bytes=state.file_bytes,
            storage_path=state.storage_path,
            repository=repo,
            storage=get_file_storage(),
        )
    state.page_texts = page_texts

    outcome = validate_metrics(
        metrics=metrics,
        page_texts=page_texts,
        total_pages=total_pages,
        document_id=state.document_id,
        document_exists=document_exists,
    )

    state.validated_metrics_count = outcome.verified_count
    state.unverified_metrics = [
        {"name": name, "reason": validation.reason}
        for name, validation in outcome.rejected_metrics.items()
    ]
    for item in state.unverified_metrics:
        state.validation_issues.append(f"Metric '{item['name']}' rejected: {item['reason']}")

    if outcome.verified_count == 0:
        state.validation_passed = False
        state.is_failed = True
        err_msg = "Evidence validation failed: no metric could be verified against the source document."
        if state.unverified_metrics:
            err_msg += " " + "; ".join(
                f"{item['name']}: {item['reason']}" for item in state.unverified_metrics[:5]
            )
        state.errors.append(err_msg)
        state.execution_steps.append(
            AgentExecutionLog(
                step_name="evidence_validation_node",
                agent="EVIDENCE_VALIDATION",
                status="FAILED",
                timestamp=start_time,
                message=err_msg,
            )
        )
        if state.job_id:
            repo.update_processing_job(
                state.job_id, status="FAILED", current_stage="EVIDENCE_VALIDATION", error_message=err_msg
            )
        if document_exists:
            try:
                repo.record_agent_run(
                    document_id=state.document_id,
                    session_id=state.session_id,
                    agent_name="EVIDENCE_VALIDATION",
                    status="FAILED",
                    input_payload={"metrics_evaluated": len(metrics)},
                    output_payload={"metrics_verified": 0, "metrics_rejected": outcome.rejected_count},
                    error_message=err_msg,
                )
            except Exception:
                logger.exception("Could not record failed evidence validation run")
        return state

    try:
        _apply_validated_metrics(state, repo, set(outcome.verified_metrics.keys()))
    except Exception as exc:
        logger.exception("Failed to persist validated metrics: %s", exc)
        state.is_failed = True
        state.validation_passed = False
        err_msg = f"Evidence validation failed while persisting verified metrics: {exc}"
        state.errors.append(err_msg)
        if state.job_id:
            repo.update_processing_job(
                state.job_id, status="FAILED", current_stage="EVIDENCE_VALIDATION", error_message=err_msg
            )
        return state

    state.validation_passed = True
    state.current_phase = "VALIDATION_PASSED"
    rejected_note = (
        f" {outcome.rejected_count} unsupported metric(s) were rejected and not persisted."
        if outcome.rejected_count
        else ""
    )
    state.execution_steps.append(
        AgentExecutionLog(
            step_name="evidence_validation_node",
            agent="EVIDENCE_VALIDATION",
            status="SUCCESS",
            timestamp=start_time,
            message=(
                f"Verified {outcome.verified_count} metric citations against source pages."
                + rejected_note
            ),
        )
    )

    try:
        repo.record_agent_run(
            document_id=state.document_id,
            session_id=state.session_id,
            agent_name="EVIDENCE_VALIDATION",
            status="COMPLETED",
            input_payload={"metrics_evaluated": len(metrics)},
            output_payload={
                "metrics_verified": outcome.verified_count,
                "metrics_rejected": outcome.rejected_count,
                "rejected": state.unverified_metrics,
            },
        )
    except Exception:
        logger.exception("Could not record evidence validation run")

    if state.job_id:
        repo.update_processing_job(
            state.job_id, status="PROCESSING", current_stage="EVIDENCE_VALIDATION_COMPLETED"
        )

    return state


def red_flag_agent_node(state: FinancialResearchState) -> FinancialResearchState:
    """Step 4: Hybrid Financial Risk Detection with evidence validation.

    Any exception marks the workflow as failed, records a failed agent run, and
    prevents partial findings from being presented or persisted as validated.
    """
    if state.is_failed or not state.validation_passed:
        logger.warning("Skipping red_flag_agent_node due to upstream validation failure.")
        return state

    logger.info("Executing Red Flag Agent node for doc: %s", state.document_id)
    repo = get_database_repository()
    rf_service = RedFlagAgentService()
    ext_service = ExtractionAgentService()
    start_time = utc_now()

    try:
        # Reuse ExtractedFinancials model from state if available; avoid duplicate LLM re-extraction
        financials = (state.extracted_financials or {}).get("_model")
        if not financials:
            financials = ext_service.extract_document_financials(
                document_id=state.document_id,
                session_id=state.session_id,
            )

        findings = rf_service.analyze_document_risks(
            document_id=state.document_id,
            financials=financials,
            session_id=state.session_id,
        )

        candidate_findings = [
            {
                "finding_id": f.finding_id,
                "category": f.category.value,
                "severity": f.severity.value,
                "title": f.title,
                "description": f.description,
                "supporting_evidence": f.supporting_evidence,
                "source_page": f.source_citation.page_number,
                "detection_method": getattr(f, "detection_method", "RULE_BASED"),
                "citation": {
                    "document_id": f.source_citation.document_id,
                    "page_number": f.source_citation.page_number,
                    "exact_quote": f.source_citation.exact_quote,
                    "is_calculated": f.source_citation.is_calculated,
                },
            }
            for f in findings
        ]

        # Verify each finding against the cited page before exposing it.
        page_texts = state.page_texts
        if not page_texts:
            page_texts = load_page_texts(
                document_id=state.document_id,
                file_bytes=state.file_bytes,
                storage_path=state.storage_path,
                repository=repo,
                storage=get_file_storage(),
            )
            state.page_texts = page_texts

        validated_metric_pages = {
            int((m.get("citation") or {}).get("page_number") or 0)
            for m in (state.extracted_financials or {}).get("metrics", {}).values()
        }

        verified_findings: List[Dict[str, Any]] = []
        rejected_findings: List[Dict[str, str]] = []
        for finding in candidate_findings:
            check = validate_red_flag_finding(
                finding=finding,
                page_texts=page_texts,
                total_pages=state.total_pages,
                document_id=state.document_id,
                validated_metric_pages=validated_metric_pages,
            )
            if check.verified:
                verified_findings.append(finding)
            else:
                rejected_findings.append(
                    {
                        "title": str(finding.get("title", "")),
                        "reason": check.reason,
                    }
                )

        state.rejected_red_flags = rejected_findings
        for item in rejected_findings:
            state.validation_issues.append(
                f"Red flag '{item['title']}' rejected: {item['reason']}"
            )

        if rejected_findings:
            repo.store_red_flag_findings(
                document_id=state.document_id,
                findings=verified_findings,
                session_id=state.session_id,
            )

        state.red_flag_findings = verified_findings
        state.red_flag_count = len(verified_findings)
        state.current_phase = "RED_FLAGS_IDENTIFIED"

        repo.record_agent_run(
            document_id=state.document_id,
            session_id=state.session_id,
            agent_name="FINDING_EVIDENCE_VALIDATION",
            status="COMPLETED",
            input_payload={"findings_evaluated": len(candidate_findings)},
            output_payload={
                "findings_verified": len(verified_findings),
                "findings_rejected": len(rejected_findings),
                "rejected": rejected_findings,
            },
        )

        state.execution_steps.append(
            AgentExecutionLog(
                step_name="red_flag_agent_node",
                agent="RED_FLAG_AGENT",
                status="SUCCESS",
                timestamp=start_time,
                message=(
                    f"Identified {len(candidate_findings)} risk findings; "
                    f"{len(verified_findings)} verified against source pages"
                    + (
                        f", {len(rejected_findings)} rejected for insufficient evidence."
                        if rejected_findings
                        else "."
                    )
                ),
            )
        )
        if state.job_id:
            repo.update_processing_job(state.job_id, status="PROCESSING", current_stage="RED_FLAGS_COMPLETED")

    except Exception as e:
        logger.exception("Error in red_flag_agent_node: %s", e)
        state.is_failed = True
        state.validation_passed = False
        state.red_flag_findings = []
        state.red_flag_count = 0
        state.errors.append(f"Red Flag Agent Error: {e}")
        state.execution_steps.append(
            AgentExecutionLog(
                step_name="red_flag_agent_node",
                agent="RED_FLAG_AGENT",
                status="FAILED",
                timestamp=start_time,
                message=str(e),
            )
        )
        if state.job_id:
            repo.update_processing_job(
                state.job_id,
                status="FAILED",
                current_stage="RED_FLAG_AGENT",
                error_message=str(e),
            )
        try:
            repo.record_agent_run(
                document_id=state.document_id,
                session_id=state.session_id,
                agent_name="RED_FLAG_AGENT",
                status="FAILED",
                error_message=str(e),
            )
        except Exception:
            logger.exception("Could not record failed Red Flag agent run for %s", state.document_id)

    return state


def persistence_node(state: FinancialResearchState) -> FinancialResearchState:
    """Step 5: Final state persistence and job status update."""
    logger.info("Executing persistence node for doc: %s", state.document_id)
    repo = get_database_repository()

    succeeded = not state.is_failed and state.validation_passed
    status_str = "COMPLETED" if succeeded else "FAILED"
    err_str = "; ".join(state.errors) if state.errors else None

    if state.job_id:
        repo.update_processing_job(
            job_id=state.job_id,
            status=status_str,
            current_stage="PIPELINE_COMPLETED" if succeeded else "PIPELINE_FAILED",
            error_message=err_str,
        )

    state.current_phase = "COMPLETED" if succeeded else "FAILED"
    state.final_summary = {
        "document_id": state.document_id,
        "filename": state.filename,
        "total_pages": state.total_pages,
        "chunk_count": state.chunk_count,
        "metrics_extracted": state.extracted_metrics_count,
        "metrics_verified": state.validated_metrics_count,
        "metrics_rejected": len(state.unverified_metrics),
        "red_flags_identified": state.red_flag_count,
        "red_flags_rejected": len(state.rejected_red_flags),
        "validation_issues": state.validation_issues,
        "status": status_str,
    }

    return state


# ==============================================================================
# Workflow Orchestrator
# ==============================================================================

class MultiAgentWorkflowOrchestrator:
    """Executes the 3-agent sequential workflow."""

    @staticmethod
    def run_pipeline(
        document_id: str,
        filename: str,
        file_bytes: Optional[bytes] = None,
        storage_path: Optional[str] = None,
        workspace_id: Optional[str] = "default-workspace",
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> FinancialResearchState:
        """Run Document Agent -> Extraction Agent -> Validation -> Red Flag Agent -> Persistence."""
        repo = get_database_repository()

        # Ensure default-workspace exists if targeted, or validate existence
        if workspace_id:
            ws = repo.get_workspace(workspace_id)
            if not ws:
                if workspace_id == "default-workspace":
                    repo.create_workspace(
                        workspace_id="default-workspace",
                        name="Default Workspace",
                        description="System preloaded workspace",
                    )
                else:
                    raise ValueError(f"Workspace '{workspace_id}' not found.")

        # Validate that research session exists and references workspace if provided
        if session_id:
            session = repo.get_session(session_id)
            if not session:
                raise ValueError(f"Research session '{session_id}' not found.")
            if workspace_id and session.get("workspace_id") != workspace_id:
                raise ValueError(
                    f"Research session '{session_id}' does not belong to workspace '{workspace_id}'."
                )

        # Initialize or link tracking job
        active_job_id = job_id
        if active_job_id:
            existing_job = repo.get_processing_job(active_job_id)
            if existing_job:
                repo.update_processing_job(
                    job_id=active_job_id,
                    status="PROCESSING",
                    current_stage="INITIALIZED",
                )
            else:
                job = repo.create_processing_job(
                    document_id=document_id,
                    workspace_id=workspace_id,
                    session_id=session_id,
                    status="PROCESSING",
                    current_stage="INITIALIZED",
                )
                active_job_id = job["job_id"]
        else:
            job = repo.create_processing_job(
                document_id=document_id,
                workspace_id=workspace_id,
                session_id=session_id,
                status="PROCESSING",
                current_stage="INITIALIZED",
            )
            active_job_id = job["job_id"]

        state = FinancialResearchState(
            document_id=document_id,
            filename=filename,
            file_bytes=file_bytes,
            storage_path=storage_path,
            workspace_id=workspace_id,
            session_id=session_id,
            user_id=user_id,
            job_id=active_job_id,
        )

        # Sequential Node Execution
        state = document_agent_node(state)
        if not state.is_failed:
            state = extraction_agent_node(state)
            state = evidence_validation_node(state)
            if state.validation_passed:
                state = red_flag_agent_node(state)

        state = persistence_node(state)
        return state

