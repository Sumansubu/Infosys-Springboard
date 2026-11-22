"""Comparison Agent (Milestone 3.2).

Cross-references stored, evidence-backed financial metrics across multiple
company documents. Values are normalized to a common unit (millions) only when
the reporting unit is known; nominal comparisons across different currencies or
reporting periods are explicitly flagged rather than silently performed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.agents.research_agent.service import (
    _METRIC_LABELS,
    _PERCENT_METRICS,
    _RATIO_METRICS,
    format_metric_value,
)
from app.infrastructure.database import DatabaseRepositoryInterface, get_database_repository
from app.schemas.research import (
    AgentCitation,
    ComparisonCompany,
    ComparisonMetricValue,
    ComparisonResponse,
)

logger = logging.getLogger(__name__)

UNIT_TO_MILLIONS: Dict[str, Decimal] = {
    "CRORES": Decimal("10"),
    "CRORE": Decimal("10"),
    "LAKHS": Decimal("0.1"),
    "LAKH": Decimal("0.1"),
    "MILLIONS": Decimal("1"),
    "MILLION": Decimal("1"),
    "BILLIONS": Decimal("1000"),
    "BILLION": Decimal("1000"),
    "THOUSANDS": Decimal("0.001"),
    "THOUSAND": Decimal("0.001"),
}

DEFAULT_COMPARISON_METRICS = [
    "REVENUE",
    "NET_INCOME",
    "TOTAL_ASSETS",
    "TOTAL_LIABILITIES",
    "CURRENT_RATIO",
    "DEBT_TO_EQUITY",
    "OPERATING_MARGIN",
    "OPERATING_CASH_FLOW",
]


def _decimal(value: Any) -> Optional[Decimal]:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


class ComparisonAgentService:
    """Structured, citation-backed cross-company benchmarking."""

    def __init__(self, repository: Optional[DatabaseRepositoryInterface] = None):
        self.repo = repository or get_database_repository()

    def compare_documents(
        self,
        document_ids: List[str],
        metrics: Optional[List[str]] = None,
    ) -> ComparisonResponse:
        if not document_ids or len(document_ids) < 2:
            raise ValueError("At least two document IDs are required for comparison.")

        documents: List[Dict[str, Any]] = []
        missing_docs: List[str] = []
        for document_id in document_ids:
            doc = self.repo.get_document_by_id(document_id)
            if not doc:
                missing_docs.append(document_id)
            else:
                documents.append(doc)
        if missing_docs:
            raise ValueError(f"Document(s) not found: {', '.join(missing_docs)}")

        metric_names = [
            m.strip().upper() for m in (metrics or DEFAULT_COMPARISON_METRICS) if m and m.strip()
        ]

        companies: List[ComparisonCompany] = []
        citations: List[AgentCitation] = []
        warnings: List[str] = []
        limitations: List[str] = []
        periods: List[str] = []
        currencies: set = set()
        years: set = set()

        for doc in documents:
            doc_id = doc["document_id"]
            filename = doc.get("filename", "document.pdf")
            metadata = doc.get("metadata") or {}
            company_name = (
                metadata.get("company_name")
                or filename.rsplit(".", 1)[0].replace("_", " ").title()
            )
            stored_metrics = self.repo.get_financial_metrics(doc_id)
            metric_map = {m["metric_name"]: m for m in stored_metrics}

            fiscal_year = next(
                (m.get("fiscal_year") for m in stored_metrics if m.get("fiscal_year")),
                metadata.get("fiscal_year"),
            )
            if fiscal_year:
                years.add(int(fiscal_year))
                periods.append(f"{company_name}: FY{fiscal_year}")

            currency = next(
                (m.get("currency") for m in stored_metrics if m.get("currency")),
                metadata.get("currency"),
            )
            reported_unit = next(
                (m.get("unit") for m in stored_metrics if m.get("unit")),
                metadata.get("unit"),
            )
            if currency:
                currencies.add(currency)

            company_metrics: List[ComparisonMetricValue] = []
            missing_metrics: List[str] = []

            for metric_name in metric_names:
                metric = metric_map.get(metric_name)
                if not metric:
                    missing_metrics.append(metric_name)
                    company_metrics.append(
                        ComparisonMetricValue(
                            metric_name=metric_name,
                            note="Not found in the source document extraction.",
                        )
                    )
                    continue

                value = _decimal(metric.get("numeric_value"))
                unit = str(metric.get("unit") or reported_unit or "")
                metric_currency = str(metric.get("currency") or currency or "")
                is_calculated = bool(metric.get("is_calculated"))
                normalized: Optional[Decimal] = value
                note: Optional[str] = None

                if value is not None and metric_name not in _RATIO_METRICS and metric_name not in _PERCENT_METRICS:
                    factor = UNIT_TO_MILLIONS.get(unit.upper())
                    if factor is not None:
                        normalized = (value * factor).quantize(Decimal("0.01"))
                        if factor != Decimal("1"):
                            note = f"Normalized from {value} {unit} to {normalized} millions."
                    else:
                        normalized = None
                        note = f"Unrecognized reporting unit '{unit}'; unit normalization not applied."

                display = format_metric_value(metric_name, value, unit, metric_currency)
                if normalized is not None and metric_name not in _RATIO_METRICS and metric_name not in _PERCENT_METRICS:
                    display = f"{display} ({normalized:,.2f} millions)"

                page = (metric.get("citation") or {}).get("page_number")
                company_metrics.append(
                    ComparisonMetricValue(
                        metric_name=metric_name,
                        value=value,
                        normalized_value=normalized,
                        unit=unit,
                        currency=metric_currency,
                        display_value=display,
                        page_number=int(page) if page is not None else None,
                        is_calculated=is_calculated,
                        note=note,
                    )
                )

                if page is not None:
                    citations.append(
                        AgentCitation(
                            document_id=doc_id,
                            document_name=filename,
                            company=company_name,
                            page_number=int(page),
                            exact_quote=str((metric.get("citation") or {}).get("exact_quote") or ""),
                            metric_name=metric_name,
                            is_calculated=is_calculated,
                        )
                    )

            companies.append(
                ComparisonCompany(
                    document_id=doc_id,
                    company_name=company_name,
                    filename=filename,
                    fiscal_year=int(fiscal_year) if fiscal_year else None,
                    currency=currency,
                    reported_unit=reported_unit,
                    metrics=company_metrics,
                    missing_metrics=missing_metrics,
                )
            )

        if len(years) > 1:
            warnings.append(
                "Documents cover different reporting periods ("
                + ", ".join(f"FY{y}" for y in sorted(years))
                + "). Nominal figures are not directly like-for-like; compare trends with caution."
            )
        if len(currencies) > 1:
            warnings.append(
                "Documents report in different currencies ("
                + ", ".join(sorted(currencies))
                + "). No foreign-exchange conversion is applied; nominal cross-currency comparison is not performed."
            )
        if any(c.reported_unit is None for c in companies):
            warnings.append(
                "At least one document does not declare a reporting unit; unit normalization may be incomplete."
            )

        limitations.append(
            "Only values present in the verified extraction are shown. Missing values are marked unavailable, never inferred."
        )
        if len(currencies) > 1:
            limitations.append("Cross-currency totals, deltas, and rankings are intentionally omitted.")
        if len(years) > 1:
            limitations.append("Period differences limit the comparability of absolute values.")
        limitations.append(
            "Calculated ratios are deterministic Python Decimal computations over cited inputs."
        )

        summary = self._build_summary(companies, metric_names, currencies)

        return ComparisonResponse(
            comparison_id=uuid4().hex,
            companies=companies,
            metric_names=metric_names,
            periods=periods,
            warnings=warnings,
            limitations=limitations,
            summary=summary,
            citations=citations,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def _build_summary(
        self,
        companies: List[ComparisonCompany],
        metric_names: List[str],
        currencies: set,
    ) -> str:
        lines: List[str] = []
        for company in companies:
            values = {m.metric_name: m for m in company.metrics}
            revenue = values.get("REVENUE")
            net_income = values.get("NET_INCOME")
            parts = [f"{company.company_name}"]
            if company.fiscal_year:
                parts.append(f"(FY{company.fiscal_year})")
            if revenue and revenue.display_value:
                parts.append(f"reported revenue of {revenue.display_value}")
            if net_income and net_income.display_value:
                parts.append(f"and net income of {net_income.display_value}")
            if company.missing_metrics:
                parts.append(
                    "Missing metrics: " + ", ".join(_METRIC_LABELS.get(m, m) for m in company.missing_metrics)
                )
            lines.append(" ".join(parts) + ".")

        if len(currencies) == 1 and "REVENUE" in metric_names:
            ranked = [
                (c.company_name, next((m.normalized_value for m in c.metrics if m.metric_name == "REVENUE"), None))
                for c in companies
            ]
            ranked = [(name, value) for name, value in ranked if value is not None]
            if len(ranked) >= 2:
                ranked.sort(key=lambda item: item[1], reverse=True)
                lines.append(
                    f"By normalized revenue, {ranked[0][0]} is highest ({ranked[0][1]:,.2f} millions) "
                    f"and {ranked[-1][0]} is lowest ({ranked[-1][1]:,.2f} millions) among the compared filings."
                )

        return " ".join(lines)
