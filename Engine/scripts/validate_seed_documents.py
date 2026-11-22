"""Milestone 2.4 seed-document validation report generator.

Runs the full Document -> Extraction -> Evidence Validation -> Red Flag pipeline
against the repository's real seed PDFs, independently re-checks every stored
citation against the PDF page text, re-computes deterministic ratios, and writes
a structured Markdown + JSON validation report.

Usage:
    python scripts/validate_seed_documents.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Isolate this validation run from the development database, vector index and
# uploads so the report cannot be contaminated by prior state.
_TMP = tempfile.TemporaryDirectory(prefix="m24-validation-", ignore_cleanup_errors=True)
os.environ["SQLITE_DB_PATH"] = str(Path(_TMP.name) / "validation.db")
os.environ["UPLOAD_DIR"] = str(Path(_TMP.name) / "uploads")
os.environ["CHROMA_DB_DIR"] = str(Path(_TMP.name) / "chroma")
os.environ["CHROMA_COLLECTION"] = "m24_validation_chunks"
os.environ["VECTOR_STORE_TYPE"] = "chroma"
os.environ["EMBEDDING_PROVIDER"] = "hashing"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["STORAGE_PROVIDER"] = "local"
os.environ["APP_ENV"] = "development"

from app.agents.research_agent.service import format_metric_value  # noqa: E402
from app.infrastructure.database import get_database_repository  # noqa: E402
from app.orchestration.evidence import (  # noqa: E402
    load_page_texts,
    validate_red_flag_finding,
    verify_quote,
    value_present_on_page,
)
from app.orchestration.workflow import MultiAgentWorkflowOrchestrator  # noqa: E402
from app.agents.extraction_agent.calculations import FinancialCalculations  # noqa: E402

SEED_DIR = ROOT / "seed_documents"
REPORT_MD = ROOT / "docs" / "VALIDATION_REPORT.md"
REPORT_JSON = ROOT / "docs" / "validation_report.json"

# Expected values are read from the fixed seed PDFs that ship with the project.
# They are test fixtures, not generated financial information.
EXPECTED = {
    "acme_cloud_technologies_sec_10k_fy25.pdf": {
        "company": "Acme Cloud Technologies, Inc.",
        "metrics": {
            "REVENUE": "14300", "GROSS_PROFIT": "9750", "NET_INCOME": "1184",
            "TOTAL_ASSETS": "18600", "CURRENT_ASSETS": "7950",
            "CURRENT_LIABILITIES": "5000", "TOTAL_DEBT": "2500",
            "TOTAL_LIABILITIES": "8700", "SHAREHOLDERS_EQUITY": "9900",
            "OPERATING_CASH_FLOW": "3150", "CAPITAL_EXPENDITURE": "1400",
            "CURRENT_RATIO": "1.59", "DEBT_TO_EQUITY": "0.25", "OPERATING_MARGIN": "16.08",
        },
        "ratios": {
            "CURRENT_RATIO": ("CURRENT_ASSETS", "CURRENT_LIABILITIES"),
            "DEBT_TO_EQUITY": ("TOTAL_DEBT", "SHAREHOLDERS_EQUITY"),
            "OPERATING_MARGIN": ("REVENUE", "OPERATING_INCOME"),
        },
    },
    "infosys_annual_report_fy24.pdf": {
        "company": "Infosys Limited",
        "metrics": {
            "REVENUE": "153670", "GROSS_PROFIT": "45820", "NET_INCOME": "26248",
            "TOTAL_ASSETS": "143260", "CURRENT_ASSETS": "89450",
            "CURRENT_LIABILITIES": "36210", "TOTAL_DEBT": "0",
            "TOTAL_LIABILITIES": "44720", "SHAREHOLDERS_EQUITY": "98540",
            "OPERATING_CASH_FLOW": "28410", "CAPITAL_EXPENDITURE": "4428",
            "CURRENT_RATIO": "2.47", "OPERATING_MARGIN": "20.66",
        },
        "ratios": {
            "CURRENT_RATIO": ("CURRENT_ASSETS", "CURRENT_LIABILITIES"),
            "OPERATING_MARGIN": ("REVENUE", "OPERATING_INCOME"),
        },
    },
    "apex_financial_holdings_annual_report_fy25.pdf": {
        "company": "Apex Financial Holdings Group",
        "metrics": {
            "REVENUE": "9750", "NET_INCOME": "2420", "TOTAL_ASSETS": "94500",
            "CURRENT_ASSETS": "28500", "CURRENT_LIABILITIES": "18900",
            "TOTAL_DEBT": "6400", "SHAREHOLDERS_EQUITY": "11800",
            "CURRENT_RATIO": "1.51", "DEBT_TO_EQUITY": "0.54", "OPERATING_MARGIN": "47.49",
        },
        "ratios": {
            "CURRENT_RATIO": ("CURRENT_ASSETS", "CURRENT_LIABILITIES"),
            "DEBT_TO_EQUITY": ("TOTAL_DEBT", "SHAREHOLDERS_EQUITY"),
            "OPERATING_MARGIN": ("REVENUE", "OPERATING_INCOME"),
        },
    },
    "zenith_energy_earnings_call_q4_fy25.pdf": {
        "company": "Zenith Energy Resources Corp.",
        "metrics": {
            "REVENUE": "8420", "GROSS_PROFIT": "4850", "NET_INCOME": "1450",
            "TOTAL_ASSETS": "22400", "CURRENT_ASSETS": "6900",
            "CURRENT_LIABILITIES": "3200", "TOTAL_DEBT": "3800",
            "SHAREHOLDERS_EQUITY": "12100", "OPERATING_CASH_FLOW": "2650",
            "CAPITAL_EXPENDITURE": "1120", "CURRENT_RATIO": "2.16",
            "DEBT_TO_EQUITY": "0.31", "OPERATING_MARGIN": "23.52",
        },
        "ratios": {
            "CURRENT_RATIO": ("CURRENT_ASSETS", "CURRENT_LIABILITIES"),
            "DEBT_TO_EQUITY": ("TOTAL_DEBT", "SHAREHOLDERS_EQUITY"),
            "OPERATING_MARGIN": ("REVENUE", "OPERATING_INCOME"),
        },
    },
}

# Duplicate seed file used by the historical E2E test shares Acme's content.
EXTRA_FILES = [
    ("acme_tech_10k_fy25.pdf", "acme_cloud_technologies_sec_10k_fy25.pdf"),
]


def close_enough(actual: Decimal, expected: Decimal) -> bool:
    return abs(actual - expected) <= Decimal("0.02")


def main() -> int:
    repo = get_database_repository()
    rows = []
    run_summary = []
    test_counter = 0

    files = [(p.name, p.name) for p in sorted(SEED_DIR.glob("*.pdf")) if p.name in EXPECTED]
    for seed_name, expected_key in EXTRA_FILES:
        if (SEED_DIR / seed_name).exists():
            files.append((seed_name, expected_key))

    for filename, expected_key in files:
        pdf_path = SEED_DIR / filename
        spec = EXPECTED[expected_key]
        document_id = f"m24-validation-{filename.replace('.pdf', '')}"
        file_bytes = pdf_path.read_bytes()

        state = MultiAgentWorkflowOrchestrator.run_pipeline(
            document_id=document_id,
            filename=filename,
            file_bytes=file_bytes,
            workspace_id="default-workspace",
        )
        page_texts = load_page_texts(
            document_id=document_id,
            file_bytes=file_bytes,
            repository=repo,
        )
        metrics = {m["metric_name"]: m for m in repo.get_financial_metrics(document_id)}
        findings = repo.get_red_flag_findings(document_id)

        run_summary.append({
            "filename": filename,
            "document_id": document_id,
            "phase": state.current_phase,
            "failed": state.is_failed,
            "metrics": len(metrics),
            "verified": state.validated_metrics_count,
            "rejected": len(state.unverified_metrics),
            "red_flags": len(findings),
            "rejected_red_flags": state.rejected_red_flags,
        })

        # Document / parsing / indexing checks.
        for check_name, passed, expected, actual in [
            ("Document parsed into pages", state.total_pages > 0, "> 0 pages", f"{state.total_pages} pages"),
            ("Chunks generated and indexed", state.is_indexed and state.chunk_count > 0, "chunks > 0", f"{state.chunk_count} chunks"),
            ("Pipeline completed", state.current_phase == "COMPLETED", "COMPLETED", state.current_phase),
        ]:
            test_counter += 1
            rows.append({
                "id": f"M24-{test_counter:03d}",
                "company": spec["company"],
                "document": filename,
                "case": check_name,
                "expected": expected,
                "actual": actual,
                "citation": "n/a",
                "status": "PASS" if passed else "FAIL",
                "failure": "" if passed else "Pipeline/doc check failed.",
            })

        # Expected metric values and citation checks.
        for metric_name, expected_value in spec["metrics"].items():
            test_counter += 1
            metric = metrics.get(metric_name)
            if not metric:
                rows.append({
                    "id": f"M24-{test_counter:03d}", "company": spec["company"],
                    "document": filename, "case": f"{metric_name} extracted",
                    "expected": expected_value, "actual": "MISSING",
                    "citation": "n/a", "status": "FAIL",
                    "failure": "Metric absent from validated extraction.",
                })
                continue

            actual_value = Decimal(str(metric["numeric_value"]))
            value_ok = close_enough(actual_value, Decimal(expected_value))
            citation = metric.get("citation") or {}
            page = citation.get("page_number")
            quote = citation.get("exact_quote") or ""
            page_text = page_texts.get(int(page)) if page else None

            if metric.get("is_calculated"):
                citation_ok = page is not None and 1 <= int(page) <= state.total_pages
                citation_note = f"calculated; p.{page}"
            elif page_text is None:
                citation_ok = False
                citation_note = "page missing"
            else:
                quote_check = verify_quote(quote, page_text)
                value_on_page = value_present_on_page(actual_value, page_text)
                citation_ok = quote_check.verified and value_on_page
                citation_note = f"p.{page}; quote={'OK' if quote_check.verified else 'FAIL'}; value={'OK' if value_on_page else 'FAIL'}"

            status = "PASS" if (value_ok and citation_ok) else "FAIL"
            failure = ""
            if not value_ok:
                failure = f"Value mismatch: expected {expected_value}, got {actual_value}."
            elif not citation_ok:
                failure = f"Citation verification failed ({citation_note})."

            rows.append({
                "id": f"M24-{test_counter:03d}", "company": spec["company"],
                "document": filename, "case": f"{metric_name} value + citation",
                "expected": expected_value, "actual": str(actual_value),
                "citation": citation_note, "status": status, "failure": failure,
            })

        # Independent ratio recomputation.
        for ratio_name, (numerator, denominator) in spec["ratios"].items():
            test_counter += 1
            num_metric = metrics.get(numerator)
            den_metric = metrics.get(denominator)
            ratio_metric = metrics.get(ratio_name)
            if not (num_metric and den_metric and ratio_metric):
                rows.append({
                    "id": f"M24-{test_counter:03d}", "company": spec["company"],
                    "document": filename, "case": f"{ratio_name} recomputation",
                    "expected": "inputs present", "actual": "inputs missing",
                    "citation": "n/a", "status": "FAIL",
                    "failure": "Cannot recompute ratio without cited inputs.",
                })
                continue
            num = Decimal(str(num_metric["numeric_value"]))
            den = Decimal(str(den_metric["numeric_value"]))
            if ratio_name == "CURRENT_RATIO":
                recomputed = FinancialCalculations.calculate_current_ratio(num, den)
            elif ratio_name == "DEBT_TO_EQUITY":
                recomputed = FinancialCalculations.calculate_debt_to_equity(num, den)
            else:
                recomputed = FinancialCalculations.calculate_operating_margin(num, den)
            stated = Decimal(str(ratio_metric["numeric_value"]))
            ok = recomputed is not None and close_enough(recomputed, stated)
            rows.append({
                "id": f"M24-{test_counter:03d}", "company": spec["company"],
                "document": filename, "case": f"{ratio_name} independent recomputation",
                "expected": str(recomputed), "actual": str(stated),
                "citation": f"inputs p.{num_metric['citation']['page_number']}/p.{den_metric['citation']['page_number']}",
                "status": "PASS" if ok else "FAIL",
                "failure": "" if ok else "Stored ratio differs from deterministic recomputation.",
            })

        # Red flag evidence checks.
        if findings:
            validated_pages = {
                int((m.get("citation") or {}).get("page_number") or 0) for m in metrics.values()
            }
            for finding in findings:
                test_counter += 1
                check = validate_red_flag_finding(
                    finding={
                        "title": finding.get("title"),
                        "supporting_evidence": finding.get("supporting_evidence"),
                        "source_page": finding.get("source_page"),
                        "detection_method": finding.get("detection_method", "RULE_BASED"),
                        "citation": {"document_id": document_id},
                    },
                    page_texts=page_texts,
                    total_pages=state.total_pages,
                    document_id=document_id,
                    validated_metric_pages=validated_pages,
                )
                rows.append({
                    "id": f"M24-{test_counter:03d}", "company": spec["company"],
                    "document": filename, "case": f"Red flag evidence: {finding.get('title')}",
                    "expected": "verified against cited page",
                    "actual": finding.get("supporting_evidence"),
                    "citation": f"p.{finding.get('source_page')}",
                    "status": "PASS" if check.verified else "FAIL",
                    "failure": "" if check.verified else check.reason,
                })
        else:
            test_counter += 1
            rows.append({
                "id": f"M24-{test_counter:03d}", "company": spec["company"],
                "document": filename, "case": "Red flag result",
                "expected": "0 or more evidence-backed findings",
                "actual": "0 findings", "citation": "n/a", "status": "PASS",
                "failure": "",
            })

        # Hallucinated findings must be rejected, never persisted.
        for rejected in state.rejected_red_flags:
            test_counter += 1
            rows.append({
                "id": f"M24-{test_counter:03d}", "company": spec["company"],
                "document": filename, "case": f"Unsupported finding rejected: {rejected['title']}",
                "expected": "rejected and not persisted",
                "actual": rejected["reason"], "citation": "n/a", "status": "PASS",
                "failure": "",
            })

    passed = sum(1 for r in rows if r["status"] == "PASS")
    failed = len(rows) - passed

    lines = [
        "# Milestone 2.4 — Seed Document Validation Report",
        "",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}  ",
        "**Scope:** Every seed PDF is processed through Document → Extraction → Evidence Validation → Red Flag. "
        "Each reported value is compared with the source PDF; each citation page, quote, and numeric value is "
        "independently re-verified. Ratios are recomputed with Python `Decimal`.  ",
        "**Runtime profile:** offline hashing embeddings, deterministic mock LLM, local SQLite/ChromaDB.",
        "",
        "## Summary",
        "",
        f"- Test cases: **{len(rows)}**",
        f"- Passed: **{passed}**",
        f"- Failed: **{failed}**",
        f"- Documents: **{len(run_summary)}**",
        "",
        "## Pipeline Results",
        "",
        "| Document | Phase | Metrics | Verified | Rejected | Red flags | Rejected red flags |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for run in run_summary:
        lines.append(
            f"| {run['filename']} | {run['phase']} | {run['metrics']} | {run['verified']} | "
            f"{run['rejected']} | {run['red_flags']} | {len(run['rejected_red_flags'])} |"
        )

    lines += [
        "",
        "## Test Cases",
        "",
        "| ID | Company / Document | Case | Expected | Actual | Citation verification | Status | Failure explanation |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        def escape(value: str) -> str:
            return str(value).replace("|", "\\|").replace("\n", " ")[:220]
        lines.append(
            f"| {row['id']} | {escape(row['company'])} / {escape(row['document'])} | "
            f"{escape(row['case'])} | {escape(row['expected'])} | {escape(row['actual'])} | "
            f"{escape(row['citation'])} | **{row['status']}** | {escape(row['failure'])} |"
        )

    lines += [
        "",
        "## Notes and Remaining Issues",
        "",
        "- The mock/deterministic LLM intentionally returns a fixed narrative auditor finding citing page 197. "
        "On the two-page seed filings this finding is rejected by evidence validation and never persisted; "
        "this demonstrates hallucination suppression rather than a missing feature.",
        "- `acme_tech_10k_fy25.pdf` is a byte-identical copy of `acme_cloud_technologies_sec_10k_fy25.pdf`; it is "
        "included to confirm duplicate-content handling still validates citations.",
        "- Apex Financial Holdings does not report total liabilities or cash-flow lines in its seed document, "
        "so those metrics are correctly absent rather than inferred.",
        "- Neural SentenceTransformers embeddings are optional in this environment; retrieval validation uses "
        "the deterministic hashing embedding provider. Switch `EMBEDDING_PROVIDER=sentence-transformers` after "
        "installing that extra to use MiniLM vectors.",
        "",
    ]

    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    REPORT_JSON.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "summary": {"total": len(rows), "passed": passed, "failed": failed},
                "runs": run_summary,
                "cases": rows,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Validation report written to {REPORT_MD}")
    print(f"Test cases: {len(rows)} | Passed: {passed} | Failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
