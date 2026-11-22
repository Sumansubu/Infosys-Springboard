"""Milestone 2.4 comprehensive validation tests.

Covers the Document Agent, Extraction Agent, Red Flag Agent, evidence
verification, and orchestration failure handling required by the milestone.
Each test asserts on real behaviour; no assertions are weakened to force a pass.
"""

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pymupdf

from app.agents.document_agent import DocumentAgentService
from app.agents.extraction_agent import ExtractionAgentService
from app.agents.extraction_agent.calculations import FinancialCalculations
from app.agents.extraction_agent.normalizer import FinancialNormalizer
from app.agents.red_flag_agent import RedFlagAgentService
from app.agents.red_flag_agent.rule_engine import RuleEngine
from app.infrastructure.database import SQLiteRepository, get_database_repository
from app.infrastructure.storage import LocalFileStorage
from app.infrastructure.vector_store.base import VectorStoreInterface
from app.orchestration.evidence import (
    load_page_texts,
    validate_metrics,
    validate_red_flag_finding,
    verify_quote,
)
from app.orchestration.workflow import MultiAgentWorkflowOrchestrator
from app.schemas.agents import (
    ExtractedFinancials,
    ExtractedMetric,
    ReportingPeriod,
    RiskCategory,
    SourceCitation,
)


class InMemoryVectorStore(VectorStoreInterface):
    """Deterministic in-memory vector store for isolated Document Agent tests."""

    def __init__(self):
        self.chunks = {}
        self.embeddings = {}

    def upsert_chunks(self, chunks, embeddings):
        for chunk, embedding in zip(chunks, embeddings):
            self.chunks[chunk["chunk_id"]] = dict(chunk)
            self.embeddings[chunk["chunk_id"]] = list(embedding)
        return len(chunks)

    def search_chunks(self, query_embedding, top_k=5, filters=None):
        results = []
        for chunk_id, chunk in self.chunks.items():
            if filters and filters.get("document_id") and chunk["document_id"] != filters["document_id"]:
                continue
            results.append({
                "chunk_id": chunk_id,
                "text": chunk["text"],
                "metadata": {
                    "document_id": chunk["document_id"],
                    "page_number": chunk["page_number"],
                    "is_table": chunk.get("is_table", False),
                },
                "distance": 0.1,
                "score": 0.9,
            })
        return results[:top_k]

    def count_chunks(self):
        return len(self.chunks)

    def is_healthy(self):
        return True

    def get_chunks_by_document(self, document_id):
        return [
            {
                "chunk_id": cid,
                "text": chunk["text"],
                "page_number": chunk["page_number"],
                "is_table": chunk.get("is_table", False),
                "metadata": chunk,
            }
            for cid, chunk in self.chunks.items()
            if chunk["document_id"] == document_id
        ]


def make_pdf_bytes(pages):
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text(pymupdf.Point(50, 60), text, fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data


class TestDocumentAgentM24(unittest.TestCase):
    """Document Agent parsing, validation, duplicate, chunking, indexing."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = SQLiteRepository(db_path=str(Path(self.temp_dir.name) / "doc.db"))
        self.storage = LocalFileStorage(upload_dir=str(Path(self.temp_dir.name) / "uploads"))
        self.vector = InMemoryVectorStore()
        self.service = DocumentAgentService(
            repository=self.repo,
            storage=self.storage,
            vector_store=self.vector,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_valid_pdf_upload_indexes_chunks(self):
        data = make_pdf_bytes([
            "ACME TEST CORP\nTotal Revenue: 1,000\nNet Income: 120",
            "ACME TEST CORP BALANCE SHEET\nTotal Assets: 4,000\nTotal Liabilities: 1,500",
        ])
        response = self.service.process_pdf_upload(data, "acme_test.pdf", workspace_id="ws-t")
        self.assertTrue(response.indexed)
        self.assertEqual(response.total_pages, 2)
        self.assertGreater(response.chunk_count, 0)
        self.assertEqual(response.characters_extracted > 0, True)
        stored = self.vector.get_chunks_by_document(response.document_id)
        self.assertEqual(len(stored), response.chunk_count)
        for chunk in stored:
            self.assertIn("page_number", chunk)
            self.assertGreaterEqual(chunk["page_number"], 1)

    def test_invalid_pdf_bytes_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self.service.process_pdf_upload(b"this is not a pdf", "broken.pdf")
        self.assertIn("Unable to parse PDF", str(ctx.exception))

    def test_empty_pdf_is_saved_but_not_indexed(self):
        # A "zero-content" PDF is represented by one page with no extractable
        # text (PyMuPDF cannot serialize a zero-page document).
        data = make_pdf_bytes([""])
        response = self.service.process_pdf_upload(data, "blank.pdf")
        self.assertFalse(response.indexed)
        self.assertEqual(response.total_pages, 1)
        self.assertEqual(response.chunk_count, 0)
        self.assertIn("no selectable text", response.message.lower())

    def test_duplicate_upload_is_idempotent(self):
        data = make_pdf_bytes(["DUP CORP\nRevenue: 500"])
        first = self.service.process_pdf_upload(data, "dup.pdf")
        second = self.service.process_pdf_upload(data, "dup.pdf")
        self.assertEqual(first.document_id, second.document_id)
        self.assertTrue(second.already_exists)
        self.assertEqual(len(self.repo.list_documents()), 1)

    def test_chunk_metadata_preserves_page_and_table_flag(self):
        data = make_pdf_bytes(["CHUNK CORP\nRevenue: 800\nNet Income: 80"])
        response = self.service.process_pdf_upload(data, "chunk.pdf")
        chunks = self.vector.get_chunks_by_document(response.document_id)
        self.assertTrue(any(c["page_number"] == 1 for c in chunks))
        self.assertTrue(all("is_table" in c for c in chunks))
        self.assertTrue(all(c["metadata"].get("filename") == "chunk.pdf" for c in chunks))

    def test_embeddings_have_expected_dimension(self):
        data = make_pdf_bytes(["EMBED CORP\nRevenue: 900"])
        response = self.service.process_pdf_upload(data, "embed.pdf")
        chunks = self.vector.get_chunks_by_document(response.document_id)
        self.assertGreater(len(chunks), 0)
        for chunk in chunks:
            embedding = self.vector.embeddings[chunk["chunk_id"]]
            self.assertEqual(len(embedding), 384)


class TestExtractionM24(unittest.TestCase):
    """Extraction accuracy, ratios, missing data, and unsupported rejection."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = SQLiteRepository(db_path=str(Path(self.temp_dir.name) / "extract.db"))
        self.repo.create_document({
            "document_id": "doc-extract-m24",
            "sha256": "hash-extract-m24",
            "filename": "annual.pdf",
            "stored_filename": "annual.pdf",
            "storage_path": "",
            "total_pages": 2,
        })
        self.service = ExtractionAgentService(repository=self.repo, vector_store=InMemoryVectorStore())

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_extracts_revenue_income_assets_liabilities(self):
        chunks = [
            {
                "chunk_id": "c1", "document_id": "doc-extract-m24", "filename": "annual.pdf",
                "page_number": 1, "is_table": False,
                "text": "Total Revenue: 10,000\nNet Income: 1,200\nOperating Income: 2,000",
            },
            {
                "chunk_id": "c2", "document_id": "doc-extract-m24", "filename": "annual.pdf",
                "page_number": 2, "is_table": False,
                "text": "Total Assets: 40,000\nTotal Liabilities: 15,000\nCurrent Assets: 9,000\nCurrent Liabilities: 5,000\nShareholders Equity: 25,000\nTotal Debt: 4,000",
            },
        ]
        financials = self.service.extract_document_financials("doc-extract-m24", chunks=chunks)
        self.assertEqual(financials.income_statement["REVENUE"].value, Decimal("10000"))
        self.assertEqual(financials.income_statement["NET_INCOME"].value, Decimal("1200"))
        self.assertEqual(financials.balance_sheet["TOTAL_ASSETS"].value, Decimal("40000"))
        self.assertEqual(financials.balance_sheet["TOTAL_LIABILITIES"].value, Decimal("15000"))
        self.assertEqual(financials.ratios["CURRENT_RATIO"].value, Decimal("1.8"))
        self.assertEqual(financials.ratios["DEBT_TO_EQUITY"].value, Decimal("0.16"))

    def test_ratios_are_deterministic(self):
        self.assertEqual(
            FinancialCalculations.calculate_current_ratio(Decimal("7950"), Decimal("5000")),
            Decimal("1.59"),
        )
        self.assertEqual(
            FinancialCalculations.calculate_debt_to_equity(Decimal("2500"), Decimal("9900")),
            Decimal("0.25"),
        )
        self.assertEqual(
            FinancialCalculations.calculate_operating_margin(Decimal("14300"), Decimal("2300")),
            Decimal("16.08"),
        )
        self.assertIsNone(
            FinancialCalculations.calculate_current_ratio(Decimal("100"), Decimal("0"))
        )

    def test_missing_document_raises(self):
        with self.assertRaises(ValueError):
            self.service.extract_document_financials("missing-doc")

    def test_invalid_numeric_values_are_rejected(self):
        self.assertIsNone(FinancialNormalizer.parse_numeric_value("N/A"))
        self.assertIsNone(FinancialNormalizer.parse_numeric_value(""))
        self.assertEqual(FinancialNormalizer.parse_numeric_value("(1,200.50)"), Decimal("-1200.50"))

    def test_prepaid_current_assets_does_not_override_total(self):
        chunks = [
            {
                "chunk_id": "c1", "document_id": "doc-extract-m24", "filename": "annual.pdf",
                "page_number": 2, "is_table": False,
                "text": "Prepaid and Other Current Assets: 1,700\nCurrent Assets: 7,950",
            }
        ]
        financials = self.service.extract_document_financials("doc-extract-m24", chunks=chunks)
        self.assertEqual(financials.balance_sheet["CURRENT_ASSETS"].value, Decimal("7950"))

    def test_unsupported_metric_is_rejected_by_evidence_validation(self):
        metrics = {
            "REVENUE": {
                "name": "REVENUE",
                "value": "10000",
                "formula": None,
                "citation": {
                    "document_id": "doc-extract-m24",
                    "page_number": 1,
                    "exact_quote": "Total Revenue: 10,000",
                    "is_calculated": False,
                },
            },
            "NET_INCOME": {
                "name": "NET_INCOME",
                "value": "9999",
                "formula": None,
                "citation": {
                    "document_id": "doc-extract-m24",
                    "page_number": 1,
                    "exact_quote": "Net Income: 9999",
                    "is_calculated": False,
                },
            },
            "CURRENT_RATIO": {
                "name": "CURRENT_RATIO",
                "value": "1.8",
                "formula": "CURRENT_ASSETS / CURRENT_LIABILITIES",
                "citation": {
                    "document_id": "doc-extract-m24",
                    "page_number": 1,
                    "exact_quote": "Calculated",
                    "is_calculated": True,
                },
            },
        }
        outcome = validate_metrics(
            metrics=metrics,
            page_texts={1: "Total Revenue: 10,000\nNet Income: 1,200"},
            total_pages=1,
            document_id="doc-extract-m24",
            document_exists=True,
        )
        self.assertIn("REVENUE", outcome.verified_metrics)
        self.assertIn("NET_INCOME", outcome.rejected_metrics)
        self.assertIn("CURRENT_RATIO", outcome.rejected_metrics)


class TestEvidenceM24(unittest.TestCase):
    """Citation and quote verification unit tests."""

    PAGE = "INFOSYS LIMITED\nRevenue from operations 153,670 146,767\nProfit for the period 26,248 24,095"

    def test_verbatim_quote_verified(self):
        self.assertTrue(verify_quote("Revenue from operations 153,670", self.PAGE).verified)

    def test_wrong_page_quote_rejected(self):
        result = verify_quote("Operating margin 55%", self.PAGE)
        self.assertFalse(result.verified)

    def test_quote_with_missing_number_rejected(self):
        result = verify_quote("Revenue from operations 999,999", self.PAGE)
        self.assertFalse(result.verified)

    def test_citation_page_out_of_bounds_rejected(self):
        outcome = validate_metrics(
            metrics={"REVENUE": {
                "name": "REVENUE", "value": "153670",
                "citation": {"document_id": "d1", "page_number": 9, "exact_quote": "Revenue from operations 153,670"},
            }},
            page_texts={1: self.PAGE},
            total_pages=2,
            document_id="d1",
            document_exists=True,
        )
        self.assertEqual(outcome.verified_count, 0)
        self.assertIn("outside document range", outcome.rejected_metrics["REVENUE"].reason)

    def test_citation_document_mismatch_rejected(self):
        outcome = validate_metrics(
            metrics={"REVENUE": {
                "name": "REVENUE", "value": "153670",
                "citation": {"document_id": "other-doc", "page_number": 1, "exact_quote": "Revenue from operations 153,670"},
            }},
            page_texts={1: self.PAGE},
            total_pages=2,
            document_id="d1",
            document_exists=True,
        )
        self.assertIn("document", outcome.rejected_metrics["REVENUE"].reason.lower())

    def test_missing_document_rejected(self):
        outcome = validate_metrics(
            metrics={"REVENUE": {"name": "REVENUE", "value": "1", "citation": {"page_number": 1}}},
            page_texts={},
            total_pages=1,
            document_id="ghost",
            document_exists=False,
        )
        self.assertEqual(outcome.verified_count, 0)

    def test_red_flag_with_unverifiable_evidence_rejected(self):
        finding = {
            "title": "Hallucinated auditor issue",
            "supporting_evidence": "The auditor issued an adverse opinion on page 197",
            "source_page": 1,
            "detection_method": "LLM_DISCLOSURE",
            "citation": {"document_id": "d1", "page_number": 1},
        }
        check = validate_red_flag_finding(
            finding=finding,
            page_texts={1: self.PAGE},
            total_pages=2,
            document_id="d1",
            validated_metric_pages={1},
        )
        self.assertFalse(check.verified)

    def test_rule_finding_on_verified_metric_page_accepted(self):
        finding = {
            "title": "Elevated leverage",
            "supporting_evidence": "Debt-to-Equity: 2.80x",
            "source_page": 1,
            "detection_method": "RULE_BASED",
            "citation": {"document_id": "d1", "page_number": 1},
        }
        check = validate_red_flag_finding(
            finding=finding,
            page_texts={1: self.PAGE},
            total_pages=2,
            document_id="d1",
            validated_metric_pages={1},
        )
        self.assertTrue(check.verified)


class TestRedFlagsM24(unittest.TestCase):
    """Red Flag Agent rule coverage including false-positive avoidance."""

    def setUp(self):
        self.engine = RuleEngine()

    def metric(self, name, value, is_calc=False):
        return ExtractedMetric(
            name=name,
            value=Decimal(value),
            raw_text=value,
            currency="USD",
            unit="MILLIONS",
            fiscal_year=2025,
            period=ReportingPeriod.ANNUAL,
            is_consolidated=True,
            citation=SourceCitation(
                document_id="rf-doc", filename="rf.pdf", page_number=1,
                exact_quote=f"{name}: {value}", is_calculated=is_calc,
            ),
            is_calculated=is_calc,
        )

    def test_high_debt_to_equity_detected(self):
        financials = ExtractedFinancials(
            document_id="rf-doc", company_name="Levered", fiscal_year=2025, is_consolidated=True,
            ratios={"DEBT_TO_EQUITY": self.metric("DEBT_TO_EQUITY", "3.50", True)},
        )
        findings = self.engine.evaluate_financials(financials)
        self.assertTrue(any(f.category == RiskCategory.DEBT_AND_LEVERAGE for f in findings))

    def test_falling_operating_margin_detected(self):
        financials = ExtractedFinancials(
            document_id="rf-doc", company_name="Compressed", fiscal_year=2025, is_consolidated=True,
            ratios={"OPERATING_MARGIN": self.metric("OPERATING_MARGIN", "1.20", True)},
        )
        findings = self.engine.evaluate_financials(financials)
        self.assertTrue(any(f.category == RiskCategory.PROFITABILITY_DECLINE for f in findings))

    def test_negative_operating_cash_flow_with_profit_detected(self):
        financials = ExtractedFinancials(
            document_id="rf-doc", company_name="Accrual", fiscal_year=2025, is_consolidated=True,
            income_statement={"NET_INCOME": self.metric("NET_INCOME", "500")},
            cash_flow={"OPERATING_CASH_FLOW": self.metric("OPERATING_CASH_FLOW", "-200")},
        )
        findings = self.engine.evaluate_financials(financials)
        self.assertTrue(any(f.category == RiskCategory.CASH_FLOW_DIVERGENCE for f in findings))

    def test_negative_free_cash_flow_detected(self):
        financials = ExtractedFinancials(
            document_id="rf-doc", company_name="Capex Heavy", fiscal_year=2025, is_consolidated=True,
            ratios={"FREE_CASH_FLOW": self.metric("FREE_CASH_FLOW", "-450", True)},
        )
        findings = self.engine.evaluate_financials(financials)
        self.assertTrue(any(f.category == RiskCategory.CASH_FLOW_DIVERGENCE for f in findings))

    def test_low_liquidity_detected(self):
        financials = ExtractedFinancials(
            document_id="rf-doc", company_name="Illiquid", fiscal_year=2025, is_consolidated=True,
            ratios={"CURRENT_RATIO": self.metric("CURRENT_RATIO", "0.65", True)},
        )
        findings = self.engine.evaluate_financials(financials)
        self.assertTrue(any(f.category == RiskCategory.LIQUIDITY_DETERIORATION for f in findings))

    def test_missing_information_produces_no_findings(self):
        financials = ExtractedFinancials(
            document_id="rf-doc", company_name="Sparse", fiscal_year=2025, is_consolidated=True,
        )
        self.assertEqual(self.engine.evaluate_financials(financials), [])

    def test_healthy_company_produces_no_false_positives(self):
        financials = ExtractedFinancials(
            document_id="rf-doc", company_name="Healthy", fiscal_year=2025, is_consolidated=True,
            income_statement={"NET_INCOME": self.metric("NET_INCOME", "1000")},
            cash_flow={"OPERATING_CASH_FLOW": self.metric("OPERATING_CASH_FLOW", "1500")},
            ratios={
                "CURRENT_RATIO": self.metric("CURRENT_RATIO", "2.10", True),
                "DEBT_TO_EQUITY": self.metric("DEBT_TO_EQUITY", "0.30", True),
                "OPERATING_MARGIN": self.metric("OPERATING_MARGIN", "18.00", True),
                "FREE_CASH_FLOW": self.metric("FREE_CASH_FLOW", "600", True),
            },
        )
        self.assertEqual(self.engine.evaluate_financials(financials), [])


class TestOrchestrationFailuresM24(unittest.TestCase):
    """Workflow failure handling, status persistence, and partial-output safety."""

    def setUp(self):
        self.repo = get_database_repository()
        self.seed_file = Path("seed_documents/acme_cloud_technologies_sec_10k_fy25.pdf")
        if not self.seed_file.exists():
            from app.infrastructure.document_processing.seed_generator import generate_seed_pdf_files
            generate_seed_pdf_files(Path("seed_documents"))

    def _run(self, doc_id, data):
        return MultiAgentWorkflowOrchestrator.run_pipeline(
            document_id=doc_id,
            filename="acme_cloud_technologies_sec_10k_fy25.pdf",
            file_bytes=data,
            workspace_id="default-workspace",
        )

    def test_document_agent_failure_marks_job_failed(self):
        state = self._run("m24-doc-failure", b"not a pdf")
        self.assertTrue(state.is_failed)
        self.assertEqual(state.current_phase, "FAILED")
        job = self.repo.get_processing_job(state.job_id)
        self.assertEqual(job["status"], "FAILED")
        self.assertIn("PIPELINE", job["current_stage"])

    def test_extraction_agent_failure_marks_job_failed(self):
        data = self.seed_file.read_bytes()
        with patch.object(
            ExtractionAgentService,
            "extract_document_financials",
            side_effect=RuntimeError("simulated extraction failure"),
        ):
            state = self._run("m24-extraction-failure", data)
        self.assertTrue(state.is_failed)
        self.assertFalse(state.validation_passed)
        job = self.repo.get_processing_job(state.job_id)
        self.assertEqual(job["status"], "FAILED")
        self.assertIn("Extraction", job.get("error_message") or "")

    def test_red_flag_agent_failure_marks_job_failed_and_discards_findings(self):
        data = self.seed_file.read_bytes()
        with patch.object(
            RedFlagAgentService,
            "analyze_document_risks",
            side_effect=RuntimeError("simulated red flag failure"),
        ):
            state = self._run("m24-redflag-failure", data)
        self.assertTrue(state.is_failed)
        self.assertEqual(state.red_flag_findings, [])
        job = self.repo.get_processing_job(state.job_id)
        self.assertEqual(job["status"], "FAILED")
        self.assertIn("Red Flag", job.get("error_message") or "")
        runs = [r for r in self.repo.get_agent_runs("m24-redflag-failure") if r["agent_name"] == "RED_FLAG_AGENT"]
        self.assertTrue(any(r["status"] == "FAILED" for r in runs))

    def test_successful_pipeline_records_all_agents_and_citations(self):
        data = self.seed_file.read_bytes()
        state = self._run("m24-success", data)
        self.assertEqual(state.current_phase, "COMPLETED")
        self.assertFalse(state.is_failed)
        self.assertTrue(state.validation_passed)
        self.assertEqual(state.validated_metrics_count, state.extracted_metrics_count)
        job = self.repo.get_processing_job(state.job_id)
        self.assertEqual(job["status"], "COMPLETED")
        self.assertEqual(job["current_stage"], "PIPELINE_COMPLETED")
        agents = {r["agent_name"] for r in self.repo.get_agent_runs("m24-success")}
        self.assertIn("EXTRACTION_AGENT", agents)
        self.assertIn("EVIDENCE_VALIDATION", agents)
        self.assertIn("RED_FLAG_AGENT", agents)

    def test_seed_document_pages_are_loadable_for_evidence(self):
        pages = load_page_texts(
            document_id="m24-success",
            file_bytes=self.seed_file.read_bytes(),
            repository=self.repo,
        )
        self.assertEqual(len(pages), 2)
        self.assertIn("Total Revenue", pages[1])


if __name__ == "__main__":
    unittest.main()
