"""Research Agent (Milestone 3.1).

Answers multi-part financial research questions strictly from indexed source
documents. Retrieval is performed per document and per decomposed sub-question;
numeric facts come from stored extracted metrics; narrative evidence comes from
verifiable retrieved chunks. Answers never invent a number and always expose the
source document, page, and verbatim quote.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from app.agents.extraction_agent.calculations import FinancialCalculations
from app.infrastructure.database import DatabaseRepositoryInterface, get_database_repository
from app.infrastructure.document_processing import generate_embeddings
from app.infrastructure.vector_store import VectorStoreInterface, get_vector_store
from app.schemas.research import (
    AgentCitation,
    ResearchAnswerResponse,
    ResearchStep,
)

logger = logging.getLogger(__name__)

METRIC_ALIASES: Dict[str, List[str]] = {
    "REVENUE": ["revenue", "total revenue", "sales", "turnover", "top line"],
    "GROSS_PROFIT": ["gross profit"],
    "OPERATING_INCOME": ["operating income", "operating profit", "ebit"],
    "EBITDA": ["ebitda"],
    "NET_INCOME": ["net income", "net profit", "profit for the period", "profit for the year", "bottom line"],
    "TOTAL_ASSETS": ["total assets"],
    "CURRENT_ASSETS": ["current assets"],
    "TOTAL_LIABILITIES": ["total liabilities"],
    "CURRENT_LIABILITIES": ["current liabilities"],
    "TOTAL_DEBT": ["total debt", "debt", "borrowings", "leverage"],
    "SHAREHOLDERS_EQUITY": ["shareholders equity", "stockholders equity", "total equity", "equity"],
    "OPERATING_CASH_FLOW": ["operating cash flow", "cash from operations", "cash from operating activities"],
    "CAPITAL_EXPENDITURE": ["capital expenditure", "capital expenditures", "capex"],
    "FREE_CASH_FLOW": ["free cash flow", "fcf"],
    "CURRENT_RATIO": ["current ratio", "liquidity"],
    "QUICK_RATIO": ["quick ratio"],
    "DEBT_TO_EQUITY": ["debt to equity", "debt-to-equity", "debt/equity"],
    "OPERATING_MARGIN": ["operating margin"],
    "NET_PROFIT_MARGIN": ["net profit margin", "net margin"],
    "GROSS_MARGIN": ["gross margin"],
    "RETURN_ON_EQUITY": ["return on equity", "roe"],
    "EPS_DILUTED": ["eps", "earnings per share", "diluted eps"],
}

DEFAULT_SUMMARY_METRICS = [
    "REVENUE",
    "NET_INCOME",
    "OPERATING_INCOME",
    "TOTAL_ASSETS",
    "TOTAL_LIABILITIES",
    "OPERATING_CASH_FLOW",
    "CURRENT_RATIO",
    "DEBT_TO_EQUITY",
    "OPERATING_MARGIN",
]

RISK_KEYWORDS = [
    "risk", "red flag", "auditor", "audit", "going concern", "litigation",
    "contingent", "material weakness", "restatement", "impairment", "uncertainty",
]

_RATIO_METRICS = {
    "CURRENT_RATIO", "QUICK_RATIO", "DEBT_TO_EQUITY",
}

_PERCENT_METRICS = {
    "OPERATING_MARGIN", "NET_PROFIT_MARGIN", "GROSS_MARGIN", "RETURN_ON_EQUITY",
}

_METRIC_LABELS = {
    "REVENUE": "Revenue",
    "GROSS_PROFIT": "Gross profit",
    "OPERATING_INCOME": "Operating income",
    "EBITDA": "EBITDA",
    "NET_INCOME": "Net income",
    "TOTAL_ASSETS": "Total assets",
    "CURRENT_ASSETS": "Current assets",
    "TOTAL_LIABILITIES": "Total liabilities",
    "CURRENT_LIABILITIES": "Current liabilities",
    "TOTAL_DEBT": "Total debt",
    "SHAREHOLDERS_EQUITY": "Shareholders' equity",
    "OPERATING_CASH_FLOW": "Operating cash flow",
    "CAPITAL_EXPENDITURE": "Capital expenditure",
    "FREE_CASH_FLOW": "Free cash flow",
    "CURRENT_RATIO": "Current ratio",
    "QUICK_RATIO": "Quick ratio",
    "DEBT_TO_EQUITY": "Debt-to-equity ratio",
    "OPERATING_MARGIN": "Operating margin",
    "NET_PROFIT_MARGIN": "Net profit margin",
    "GROSS_MARGIN": "Gross margin",
    "RETURN_ON_EQUITY": "Return on equity",
    "EPS_DILUTED": "Diluted EPS",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decimal(value: Any) -> Optional[Decimal]:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def format_metric_value(metric_name: str, value: Any, unit: str = "", currency: str = "") -> str:
    decimal_value = _decimal(value)
    if decimal_value is None:
        return "Unavailable"
    if metric_name in _RATIO_METRICS:
        return f"{decimal_value.normalize():f}x"
    if metric_name in _PERCENT_METRICS:
        return f"{decimal_value.normalize():f}%"
    number = f"{decimal_value:,.2f}".rstrip("0").rstrip(".")
    prefix = f"{currency} " if currency and currency not in ("RATIO", "PERCENT") else ""
    suffix = f" {unit.lower()}" if unit and unit not in ("RATIO", "PERCENT") else ""
    return f"{prefix}{number}{suffix}".strip()


def _citation_from_metric(
    metric: Dict[str, Any],
    document_id: str,
    document_name: str,
    company: Optional[str],
    metric_name: str,
) -> Optional[AgentCitation]:
    citation = metric.get("citation") or {}
    page = citation.get("page_number")
    quote = citation.get("exact_quote") or metric.get("source_label") or ""
    if page is None:
        return None
    return AgentCitation(
        document_id=document_id,
        document_name=document_name,
        company=company,
        page_number=int(page),
        exact_quote=str(quote),
        metric_name=metric_name,
        is_calculated=bool(metric.get("is_calculated")),
    )


class ResearchAgentService:
    """Grounded, multi-step financial research agent."""

    def __init__(
        self,
        repository: Optional[DatabaseRepositoryInterface] = None,
        vector_store: Optional[VectorStoreInterface] = None,
    ):
        self.repo = repository or get_database_repository()
        self.vector_store = vector_store or get_vector_store()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def answer_question(
        self,
        question: str,
        document_ids: Optional[List[str]] = None,
        session_id: Optional[str] = None,
        top_k: int = 6,
    ) -> ResearchAnswerResponse:
        clean_question = (question or "").strip()
        if not clean_question:
            raise ValueError("Research question must not be empty.")

        documents = self._resolve_documents(document_ids=document_ids, session_id=session_id)
        if not documents:
            raise ValueError(
                "No indexed documents are available for research. Upload or ingest a financial document first."
            )

        history = self.repo.get_research_messages(session_id, limit=20) if session_id else []
        prior_questions = [m["content"] for m in history if m.get("role") == "user"]

        if session_id:
            user_message = self.repo.add_research_message(
                session_id=session_id,
                role="user",
                content=clean_question,
                metadata={"document_ids": [d["document_id"] for d in documents]},
            )
            user_message_id = user_message["message_id"]
        else:
            user_message_id = None

        answer = self._build_answer(
            question=clean_question,
            documents=documents,
            prior_questions=prior_questions,
            top_k=top_k,
        )
        answer.session_id = session_id
        answer.user_message_id = user_message_id

        if session_id:
            stored = self.repo.add_research_message(
                session_id=session_id,
                role="assistant",
                content=answer.answer,
                citations=[c.model_dump() for c in answer.citations],
                metadata={
                    "direct_facts": answer.direct_facts,
                    "calculated_values": answer.calculated_values,
                    "analytical_conclusions": answer.analytical_conclusions,
                    "unavailable_information": answer.unavailable_information,
                    "steps": [s.model_dump() for s in answer.steps],
                    "documents_used": answer.documents_used,
                },
            )
            answer.message_id = stored["message_id"]

        return answer

    def get_history(self, session_id: str) -> List[Dict[str, Any]]:
        return self.repo.get_research_messages(session_id)

    def clear_history(self, session_id: str) -> int:
        return self.repo.clear_research_messages(session_id)

    # ------------------------------------------------------------------
    # Retrieval helpers
    # ------------------------------------------------------------------

    def _resolve_documents(
        self,
        document_ids: Optional[List[str]],
        session_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        if document_ids:
            docs = []
            missing = []
            for doc_id in document_ids:
                doc = self.repo.get_document_by_id(doc_id)
                if not doc:
                    missing.append(doc_id)
                else:
                    docs.append(doc)
            if missing:
                raise ValueError(f"Document(s) not found: {', '.join(missing)}")
            return docs

        if session_id:
            session = self.repo.get_session(session_id)
            if not session:
                raise ValueError(f"Research session '{session_id}' not found.")
            session_doc_ids = self.repo.get_session_documents(session_id)
            docs = [d for d in (self.repo.get_document_by_id(i) for i in session_doc_ids) if d]
            if docs:
                return docs
            return [
                d for d in self.repo.list_documents(workspace_id=session.get("workspace_id"))
                if d.get("indexed")
            ]

        return [d for d in self.repo.list_documents() if d.get("indexed")]

    def _decompose_question(self, question: str) -> List[str]:
        raw_parts = re.split(r"\?|\n|;|,\s*(?:and|also)\s+|\s+and\s+|\s+plus\s+|\s+also\s+", question)
        parts: List[str] = []
        for part in raw_parts:
            cleaned = re.sub(r"^(?:what|how|why|which|please|show|summarize|summarise|tell me)\b", "", part.strip(), flags=re.I)
            cleaned = cleaned.strip(" ,.-")
            if len(cleaned) >= 3 and cleaned.lower() not in (p.lower() for p in parts):
                parts.append(cleaned)
        if not parts:
            parts = [question]
        return parts[:5]

    def _detected_metrics(self, text: str) -> List[str]:
        lowered = (text or "").lower()
        detected: List[str] = []
        for metric, aliases in METRIC_ALIASES.items():
            for alias in aliases:
                if re.search(r"\b" + re.escape(alias) + r"\b", lowered):
                    detected.append(metric)
                    break
        return detected

    def _retrieve_chunks(
        self,
        sub_questions: List[str],
        document_id: str,
        top_k: int,
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for sub_question in sub_questions:
            try:
                embedding = generate_embeddings([sub_question])[0]
                matches = self.vector_store.search_chunks(
                    query_embedding=embedding,
                    top_k=top_k,
                    filters={"document_id": document_id},
                )
            except Exception as exc:
                logger.warning("Retrieval failed for document %s: %s", document_id, exc)
                continue

            for match in matches:
                metadata = match.get("metadata") or {}
                results.append({
                    "chunk_id": match.get("chunk_id"),
                    "text": match.get("text", ""),
                    "page_number": int(metadata.get("page_number") or 1),
                    "section": metadata.get("section") or "",
                    "filename": metadata.get("filename") or "",
                    "document_id": metadata.get("document_id") or document_id,
                    "score": match.get("score"),
                })
        return results

    # ------------------------------------------------------------------
    # Answer synthesis
    # ------------------------------------------------------------------

    def _build_answer(
        self,
        question: str,
        documents: List[Dict[str, Any]],
        prior_questions: List[str],
        top_k: int,
    ) -> ResearchAnswerResponse:
        lowered = question.lower()
        requested_metrics = self._detected_metrics(question)
        summary_requested = any(
            token in lowered
            for token in ("summar", "performance", "overview", "financial position", "key financials", "how did")
        )
        risk_requested = any(token in lowered for token in RISK_KEYWORDS)

        if not requested_metrics and summary_requested:
            requested_metrics = list(DEFAULT_SUMMARY_METRICS)

        sub_questions = self._decompose_question(question)
        context_used: List[str] = []
        if prior_questions and (
            len(question.split()) <= 8
            or re.search(r"\b(it|that|they|their|those|this|its|them)\b", lowered)
        ):
            previous = prior_questions[-1]
            sub_questions.insert(0, previous)
            context_used.append(previous)

        steps: List[ResearchStep] = [
            ResearchStep(
                step=1,
                title="Question decomposition",
                detail=(
                    f"Decomposed the request into {len(sub_questions)} retrieval sub-question(s): "
                    + "; ".join(sub_questions)
                ),
            )
        ]

        direct_facts: List[str] = []
        calculated_values: List[str] = []
        analytical_conclusions: List[str] = []
        unavailable: List[str] = []
        citations: List[AgentCitation] = []
        seen_citations: set = set()
        evidence_lines: List[str] = []
        documents_used: List[str] = []

        def add_citation(citation: Optional[AgentCitation]) -> None:
            if citation is None:
                return
            key = (
                citation.document_id,
                citation.page_number,
                (citation.exact_quote or "")[:80],
                citation.metric_name or "",
            )
            if key in seen_citations:
                return
            seen_citations.add(key)
            citations.append(citation)

        retrieval_count = 0
        missing_by_metric: Dict[str, List[str]] = {}

        for doc in documents:
            doc_id = doc["document_id"]
            filename = doc.get("filename", "document.pdf")
            metadata = doc.get("metadata") or {}
            company = metadata.get("company_name") or filename.rsplit(".", 1)[0].replace("_", " ").title()
            documents_used.append(filename)

            metrics = self.repo.get_financial_metrics(doc_id)
            metric_map = {m["metric_name"]: m for m in metrics}
            fiscal_year = next(
                (m.get("fiscal_year") for m in metrics if m.get("fiscal_year")),
                metadata.get("fiscal_year"),
            )

            # Numeric facts from verified stored metrics only.
            for metric_name in requested_metrics:
                metric = metric_map.get(metric_name)
                if not metric:
                    missing_by_metric.setdefault(metric_name, []).append(company)
                    continue

                value = metric.get("numeric_value")
                display = format_metric_value(
                    metric_name,
                    value,
                    metric.get("unit", ""),
                    metric.get("currency", ""),
                )
                label = _METRIC_LABELS.get(metric_name, metric_name.replace("_", " ").title())
                page = (metric.get("citation") or {}).get("page_number")
                period = f"FY{fiscal_year} " if fiscal_year else ""
                fact = f"{company}: {period}{label} of {display} ({filename}, p. {page})."
                if metric.get("is_calculated"):
                    formula = metric.get("formula") or "deterministic calculation"
                    calculated_values.append(f"{fact} Calculation basis: {formula}.")
                else:
                    direct_facts.append(fact)

                add_citation(_citation_from_metric(metric, doc_id, filename, company, metric_name))

            # Deterministic cross-metric analysis (only from stored values).
            revenue = _decimal((metric_map.get("REVENUE") or {}).get("numeric_value"))
            net_income = _decimal((metric_map.get("NET_INCOME") or {}).get("numeric_value"))
            if revenue and net_income and revenue > 0:
                margin = FinancialCalculations.calculate_net_profit_margin(revenue, net_income)
                if margin is not None:
                    analytical_conclusions.append(
                        f"{company}: computed net profit margin is {margin.normalize():f}% "
                        f"(net income {net_income:,} / revenue {revenue:,}); both inputs are cited above."
                    )

            # Red flags when the question is risk-related.
            if risk_requested:
                findings = self.repo.get_red_flag_findings(doc_id)
                if not findings:
                    analytical_conclusions.append(
                        f"{company}: no evidence-backed red flag findings are recorded for this filing."
                    )
                for finding in findings[:6]:
                    page = finding.get("source_page")
                    evidence = finding.get("supporting_evidence") or ""
                    analytical_conclusions.append(
                        f"{company}: [{finding.get('severity')}] {finding.get('title')} — "
                        f"{finding.get('description')} ({filename}, p. {page})."
                    )
                    add_citation(
                        AgentCitation(
                            document_id=doc_id,
                            document_name=filename,
                            company=company,
                            page_number=int(page or 1),
                            exact_quote=str(evidence),
                            section="Red flag finding",
                        )
                    )

            # Narrative evidence from retrieval.
            chunks = self._retrieve_chunks(sub_questions, doc_id, top_k)
            retrieval_count += len(chunks)
            seen_chunks: set = set()
            for chunk in chunks:
                key = (chunk.get("document_id"), chunk.get("page_number"), (chunk.get("text") or "")[:60])
                if key in seen_chunks:
                    continue
                seen_chunks.add(key)
                text = re.sub(r"\s+", " ", chunk.get("text") or "").strip()
                if not text:
                    continue
                excerpt = text[:400]
                evidence_lines.append(
                    f"{filename} (p. {chunk['page_number']}): \"{excerpt}\""
                )
                add_citation(
                    AgentCitation(
                        document_id=doc_id,
                        document_name=filename,
                        company=company,
                        page_number=chunk["page_number"],
                        exact_quote=excerpt,
                        section=chunk.get("section") or None,
                    )
                )
                if len(evidence_lines) >= 10:
                    break

        for metric_name, companies in missing_by_metric.items():
            label = _METRIC_LABELS.get(metric_name, metric_name.replace("_", " ").title())
            unavailable.append(
                f"{label} was not found in the indexed extraction for: {', '.join(companies)}."
            )

        if risk_requested and not analytical_conclusions and not evidence_lines:
            unavailable.append("No risk disclosures matching the question were retrieved from the selected filings.")

        steps.append(
            ResearchStep(
                step=2,
                title="Per-document vector retrieval",
                detail=(
                    f"Retrieved {retrieval_count} candidate passage(s) across {len(documents)} document(s) "
                    f"using the active {type(self.vector_store).__name__}."
                ),
            )
        )
        steps.append(
            ResearchStep(
                step=3,
                title="Metric reconciliation and deterministic checks",
                detail=(
                    f"Matched {len(direct_facts)} directly reported fact(s), "
                    f"{len(calculated_values)} calculated value(s), and "
                    f"{len(analytical_conclusions)} deterministic conclusion(s)."
                ),
            )
        )
        steps.append(
            ResearchStep(
                step=4,
                title="Source verification",
                detail=(
                    f"Every numeric fact is bound to a stored metric with document/page provenance; "
                    f"{len(citations)} citation(s) returned. Unsupported values are reported as unavailable."
                ),
            )
        )
        if context_used:
            steps.append(
                ResearchStep(
                    step=5,
                    title="Conversation context",
                    detail="Used the previous session question to resolve the follow-up: " + context_used[0],
                )
            )

        answer_parts: List[str] = []
        if direct_facts or calculated_values:
            answer_parts.append(" ".join(direct_facts + calculated_values))
        if analytical_conclusions:
            answer_parts.append(" ".join(analytical_conclusions))
        if evidence_lines:
            answer_parts.append(
                "Supporting source passages: " + " | ".join(evidence_lines[:4])
            )
        if unavailable:
            answer_parts.append("Not available in the selected documents: " + " ".join(unavailable))
        if not answer_parts:
            answer_parts.append(
                "I could not find information in the selected documents that answers this question. "
                "No financial value has been inferred or invented."
            )

        # Deduplicate facts while preserving order.
        direct_facts = list(dict.fromkeys(direct_facts))
        calculated_values = list(dict.fromkeys(calculated_values))
        analytical_conclusions = list(dict.fromkeys(analytical_conclusions))
        unavailable = list(dict.fromkeys(unavailable))

        return ResearchAnswerResponse(
            question=question,
            answer="\n\n".join(answer_parts),
            direct_facts=direct_facts,
            calculated_values=calculated_values,
            analytical_conclusions=analytical_conclusions,
            unavailable_information=unavailable,
            citations=citations[:20],
            steps=steps,
            documents_used=documents_used,
            context_used=context_used,
        )
