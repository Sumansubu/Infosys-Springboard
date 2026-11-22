"""Evidence validation utilities for strict source grounding.

Every extracted financial metric and every red-flag finding must be traceable to
a page of a document that exists in the repository, inside the document's page
range, with a verbatim quote that can be located on that page. This module
implements the deterministic checks used by the orchestration workflow. It never
calls an LLM and never fabricates evidence.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from app.infrastructure.document_processing.parser import PyMuPDFParser

logger = logging.getLogger(__name__)

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "have", "in", "is", "it", "of", "on", "or", "that", "the", "their", "this",
    "to", "was", "were", "with", "we", "our", "its", "which",
}

_CALCULATED_NAME_RE = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")


def normalize_text(text: str) -> str:
    """Lowercase, unicode-normalize, and collapse punctuation for comparison."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", str(text)).lower()
    normalized = normalized.replace("|", " ")
    normalized = re.sub(r"[^a-z0-9.%]+", " ", normalized)
    return " ".join(normalized.split())


def _tokens(text: str) -> List[str]:
    return [t for t in normalize_text(text).split() if t]


def _meaningful_tokens(text: str) -> List[str]:
    return [t for t in _tokens(text) if t not in STOPWORDS and len(t) > 1]


def _numbers(text: str) -> Set[str]:
    """Return normalized numeric literals present in text (commas removed)."""
    compact = re.sub(r"[,\s]", "", text or "")
    return {n.lstrip("0") or "0" for n in re.findall(r"\d+(?:\.\d+)?", compact)}


def _value_variants(value: Any) -> Set[str]:
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return set()

    variants: Set[str] = set()
    plain = format(decimal_value.normalize(), "f")
    variants.add(plain)
    variants.add(f"{decimal_value:.2f}")
    if decimal_value == decimal_value.to_integral_value():
        variants.add(str(int(decimal_value)))
    return {v.lstrip("0") or "0" for v in variants}


def value_present_on_page(value: Any, page_text: str) -> bool:
    """Check whether an exact numeric value occurs on the page.

    Separators (commas/spaces) are ignored; digit boundaries are respected so
    that ``14300`` is not accepted merely because ``143000`` appears.
    """
    variants = _value_variants(value)
    if not variants:
        return False

    compact_page = re.sub(r"[,\s]", "", page_text or "")
    for variant in variants:
        pattern = r"(?<![\d.])" + re.escape(variant) + r"(?:\.0+)?(?![\d])"
        if re.search(pattern, compact_page):
            return True
    return False


@dataclass
class QuoteCheck:
    verified: bool
    reason: str
    coverage: float = 0.0
    direct_match: bool = False


def verify_quote(quote: str, page_text: str) -> QuoteCheck:
    """Verify that a quoted evidence snippet is supported by the cited page.

    First attempts a normalized substring match. If the source extraction has
    reflowed the passage (common in PDF table cells), it falls back to token
    coverage plus numeric-literal agreement. A quote is never accepted purely on
    token overlap if it contains numbers that are absent from the page.
    """
    clean_quote = (quote or "").strip()
    if not clean_quote:
        return QuoteCheck(False, "Evidence quote is empty.")
    if not (page_text or "").strip():
        return QuoteCheck(False, "Cited page text is unavailable.")

    normalized_quote = normalize_text(clean_quote)
    normalized_page = normalize_text(page_text)

    if normalized_quote and normalized_quote in normalized_page:
        return QuoteCheck(True, "Verbatim quote located on cited page.", 1.0, True)

    quote_tokens = _meaningful_tokens(clean_quote)
    if not quote_tokens:
        return QuoteCheck(False, "Evidence quote contains no meaningful tokens.")

    page_tokens = set(_tokens(page_text))
    matched = sum(1 for token in quote_tokens if token in page_tokens)
    coverage = matched / len(quote_tokens)

    quote_numbers = _numbers(clean_quote)
    page_numbers = _numbers(page_text)
    numbers_supported = quote_numbers.issubset(page_numbers)

    if not numbers_supported:
        missing = sorted(quote_numbers - page_numbers)
        return QuoteCheck(
            False,
            f"Quoted numeric value(s) {missing} not found on cited page.",
            coverage,
        )

    threshold = 0.85 if len(quote_tokens) >= 6 else 1.0
    if coverage >= threshold:
        return QuoteCheck(
            True,
            f"Quote supported by cited page (token coverage {coverage:.0%}).",
            coverage,
        )

    return QuoteCheck(
        False,
        f"Quote not found on cited page (token coverage {coverage:.0%}, required {threshold:.0%}).",
        coverage,
    )


def load_page_texts(
    document_id: str,
    file_bytes: Optional[bytes] = None,
    storage_path: Optional[str] = None,
    repository: Any = None,
    storage: Any = None,
) -> Dict[int, str]:
    """Load page text for a document from bytes, disk, or the storage adapter."""
    data: Optional[bytes] = file_bytes
    path = storage_path

    if data is None and path and Path(path).exists():
        try:
            data = Path(path).read_bytes()
        except OSError as exc:
            logger.warning("Could not read storage_path %s: %s", path, exc)

    if data is None and repository is not None:
        doc = repository.get_document_by_id(document_id)
        if doc:
            path = path or doc.get("storage_path")
            meta = doc.get("metadata") or {}
            object_key = meta.get("object_key") or doc.get("stored_filename")
            if storage is not None:
                try:
                    data = storage.get_file_bytes(document_id, object_key=object_key)
                except Exception as exc:  # storage backends raise several types
                    logger.warning("Could not fetch document %s from storage: %s", document_id, exc)

    if data is None and path and Path(path).exists():
        try:
            data = Path(path).read_bytes()
        except OSError:
            data = None

    if not data:
        return {}

    try:
        pages = PyMuPDFParser().parse_pdf(data)
    except Exception as exc:
        logger.warning("Could not parse source document %s for evidence checks: %s", document_id, exc)
        return {}

    texts: Dict[int, str] = {}
    for page in pages:
        table_text = "\n".join(
            str(t.get("markdown", "")) for t in (page.tables or []) if t.get("markdown")
        )
        texts[page.page_number] = f"{page.text}\n{table_text}".strip()
    return texts


@dataclass
class MetricValidation:
    name: str
    verified: bool
    reason: str
    is_calculated: bool = False
    page_number: int = 0
    quote_verified: bool = False
    value_verified: bool = False
    document_verified: bool = False


@dataclass
class ValidationOutcome:
    verified_metrics: Dict[str, MetricValidation] = field(default_factory=dict)
    rejected_metrics: Dict[str, MetricValidation] = field(default_factory=dict)

    @property
    def verified_count(self) -> int:
        return len(self.verified_metrics)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected_metrics)


def validate_metrics(
    metrics: Dict[str, Dict[str, Any]],
    page_texts: Dict[int, str],
    total_pages: int,
    document_id: str,
    document_exists: bool,
) -> ValidationOutcome:
    """Validate every extracted metric and classify it as verified or rejected."""
    outcome = ValidationOutcome()
    validated_names: Set[str] = set()

    def record(name: str, validation: MetricValidation) -> None:
        if validation.verified:
            outcome.verified_metrics[name] = validation
            validated_names.add(name)
        else:
            outcome.rejected_metrics[name] = validation

    # Pass 1: directly sourced metrics.
    for name, metric in metrics.items():
        citation = metric.get("citation") or {}
        is_calculated = bool(citation.get("is_calculated", metric.get("is_calculated", False)))
        if is_calculated:
            continue

        page_number = int(citation.get("page_number") or 0)
        cit_doc = citation.get("document_id")
        validation = MetricValidation(
            name=name,
            verified=False,
            reason="",
            is_calculated=False,
            page_number=page_number,
        )

        if not document_exists:
            validation.reason = "Source document does not exist in the repository."
            record(name, validation)
            continue
        validation.document_verified = True

        if cit_doc and cit_doc != document_id:
            validation.reason = f"Citation references document '{cit_doc}' instead of '{document_id}'."
            record(name, validation)
            continue

        if total_pages <= 0:
            validation.reason = "Document page count is unavailable; page cannot be verified."
            record(name, validation)
            continue

        if page_number < 1 or page_number > total_pages:
            validation.reason = f"Cited page {page_number} is outside document range (1-{total_pages})."
            record(name, validation)
            continue

        page_text = page_texts.get(page_number)
        if page_text is None:
            validation.reason = f"Page {page_number} text is unavailable; quote cannot be verified."
            record(name, validation)
            continue

        quote_check = verify_quote(citation.get("exact_quote", ""), page_text)
        validation.quote_verified = quote_check.verified
        if not quote_check.verified:
            validation.reason = quote_check.reason
            record(name, validation)
            continue

        validation.value_verified = value_present_on_page(metric.get("value"), page_text)
        if not validation.value_verified:
            validation.reason = (
                f"Extracted value {metric.get('value')} does not appear on cited page {page_number}."
            )
            record(name, validation)
            continue

        validation.verified = True
        validation.reason = "Citation page and verbatim evidence verified."
        record(name, validation)

    # Pass 2: calculated ratios. They are accepted only when their stated
    # formula references at least one input metric that was itself verified.
    for name, metric in metrics.items():
        citation = metric.get("citation") or {}
        is_calculated = bool(citation.get("is_calculated", metric.get("is_calculated", False)))
        if not is_calculated:
            continue

        page_number = int(citation.get("page_number") or 0)
        formula = metric.get("formula") or citation.get("calculation_basis") or ""
        validation = MetricValidation(
            name=name,
            verified=False,
            reason="",
            is_calculated=True,
            page_number=page_number,
            document_verified=document_exists,
        )

        if not document_exists:
            validation.reason = "Source document does not exist in the repository."
            record(name, validation)
            continue

        cit_doc = citation.get("document_id")
        if cit_doc and cit_doc != document_id:
            validation.reason = f"Citation references document '{cit_doc}' instead of '{document_id}'."
            record(name, validation)
            continue

        if total_pages > 0 and (page_number < 1 or page_number > total_pages):
            validation.reason = f"Cited page {page_number} is outside document range (1-{total_pages})."
            record(name, validation)
            continue

        referenced = {
            token
            for token in _CALCULATED_NAME_RE.findall(formula or "")
            if token in metrics and token != name
        }
        if not referenced:
            validation.reason = "Calculated metric has no verifiable calculation basis."
            record(name, validation)
            continue

        unverified_inputs = sorted(referenced - validated_names)
        if unverified_inputs:
            validation.reason = (
                "Calculation depends on unverified input metric(s): "
                + ", ".join(unverified_inputs)
            )
            record(name, validation)
            continue

        validation.verified = True
        validation.quote_verified = True
        validation.value_verified = True
        validation.reason = "Deterministic calculation from verified source metrics."
        record(name, validation)

    return outcome


@dataclass
class FindingValidation:
    verified: bool
    reason: str
    quote_verified: bool = False


def validate_red_flag_finding(
    finding: Dict[str, Any],
    page_texts: Dict[int, str],
    total_pages: int,
    document_id: str,
    validated_metric_pages: Set[int],
) -> FindingValidation:
    """Validate that a red-flag finding is grounded in the cited source page."""
    citation = finding.get("citation") or {}
    page_number = int(finding.get("source_page") or citation.get("page_number") or 0)
    cit_doc = citation.get("document_id")
    evidence = (finding.get("supporting_evidence") or "").strip()
    detection_method = str(finding.get("detection_method") or "RULE_BASED").upper()

    if cit_doc and cit_doc != document_id:
        return FindingValidation(False, f"Finding cites document '{cit_doc}', expected '{document_id}'.")

    if total_pages <= 0:
        return FindingValidation(False, "Document page count is unavailable.")

    if page_number < 1 or page_number > total_pages:
        return FindingValidation(False, f"Finding page {page_number} is outside range (1-{total_pages}).")

    if not evidence:
        return FindingValidation(False, "Finding has no supporting evidence.")

    page_text = page_texts.get(page_number)
    if page_text is None:
        return FindingValidation(False, f"Page {page_number} text is unavailable.")

    quote_check = verify_quote(evidence, page_text)
    if quote_check.verified:
        return FindingValidation(True, quote_check.reason, quote_verified=True)

    if detection_method == "LLM_DISCLOSURE":
        return FindingValidation(
            False,
            f"Narrative finding quote is not supported by the cited page: {quote_check.reason}",
        )

    # Rule-based findings may reference a deterministically calculated ratio
    # whose value is not printed on the page (e.g. Debt/Equity). Accept only if
    # the finding page also carries a verified source metric.
    if page_number in validated_metric_pages:
        return FindingValidation(
            True,
            "Rule finding derived from verified metrics cited on the same page.",
            quote_verified=False,
        )

    return FindingValidation(
        False,
        "Rule finding is not backed by verified evidence on the cited page: " + quote_check.reason,
    )
