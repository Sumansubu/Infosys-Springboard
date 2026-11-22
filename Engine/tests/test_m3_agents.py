"""Milestone 3 agent tests: Research, Comparison, and Report."""

import unittest
from pathlib import Path

from app.agents.comparison_agent import ComparisonAgentService
from app.agents.report_agent import ReportAgentService
from app.agents.research_agent import ResearchAgentService
from app.infrastructure.database import get_database_repository
from app.orchestration.workflow import MultiAgentWorkflowOrchestrator

WORKSPACE_ID = "m3-test-workspace"
SESSION_ID = "m3-test-session"
DOCS = {
    "acme": ("acme_cloud_technologies_sec_10k_fy25.pdf", "m3-doc-acme"),
    "infosys": ("infosys_annual_report_fy24.pdf", "m3-doc-infosys"),
    "zenith": ("zenith_energy_earnings_call_q4_fy25.pdf", "m3-doc-zenith"),
}


class TestMilestone3Agents(unittest.TestCase):
    """Uses the real seed documents processed through the M2 pipeline."""

    @classmethod
    def setUpClass(cls):
        cls.repo = get_database_repository()
        if not cls.repo.get_workspace(WORKSPACE_ID):
            cls.repo.create_workspace(
                workspace_id=WORKSPACE_ID,
                name="M3 Test Workspace",
                description="Isolated workspace for M3 agent tests",
            )
        if not cls.repo.get_session(SESSION_ID):
            cls.repo.create_session(
                workspace_id=WORKSPACE_ID,
                title="M3 Research Session",
                description="Session context tests",
                session_id=SESSION_ID,
            )

        cls.doc_ids = {}
        for key, (filename, document_id) in DOCS.items():
            path = Path("seed_documents") / filename
            if not path.exists():
                from app.infrastructure.document_processing.seed_generator import generate_seed_pdf_files
                generate_seed_pdf_files(Path("seed_documents"))
            state = MultiAgentWorkflowOrchestrator.run_pipeline(
                document_id=document_id,
                filename=filename,
                file_bytes=path.read_bytes(),
                workspace_id=WORKSPACE_ID,
                session_id=SESSION_ID,
            )
            if state.is_failed:
                raise AssertionError(f"Seed ingestion failed for {filename}: {state.errors}")
            cls.doc_ids[key] = document_id

    def setUp(self):
        self.research = ResearchAgentService()
        self.comparison = ComparisonAgentService()
        self.report = ReportAgentService()

    # ------------------------------------------------------------------
    # Research Agent
    # ------------------------------------------------------------------

    def test_multi_metric_question_returns_grounded_values(self):
        answer = self.research.answer_question(
            "What was the revenue and net income of Acme Cloud Technologies?",
            document_ids=[self.doc_ids["acme"]],
        )
        self.assertIn("14,300", answer.answer)
        self.assertIn("1,184", answer.answer)
        self.assertTrue(any("REVENUE" in c.metric_name for c in answer.citations if c.metric_name))
        self.assertTrue(any(c.metric_name == "NET_INCOME" for c in answer.citations))
        self.assertTrue(all(c.page_number >= 1 for c in answer.citations))
        self.assertGreaterEqual(len(answer.steps), 4)

    def test_summary_question_covers_multiple_sections(self):
        answer = self.research.answer_question(
            "Summarize the financial performance of Infosys based on its annual report.",
            document_ids=[self.doc_ids["infosys"]],
        )
        self.assertIn("153,670", answer.answer)
        self.assertTrue(any("TOTAL_ASSETS" == c.metric_name for c in answer.citations))
        self.assertTrue(any(c.page_number == 2 for c in answer.citations))

    def test_unavailable_information_is_reported_not_invented(self):
        answer = self.research.answer_question(
            "What was the EBITDA of Acme Cloud Technologies?",
            document_ids=[self.doc_ids["acme"]],
        )
        self.assertTrue(
            any("EBITDA" in item for item in answer.unavailable_information),
            answer.unavailable_information,
        )
        self.assertNotIn("Invented", answer.answer)

    def test_risk_question_uses_recorded_findings(self):
        answer = self.research.answer_question(
            "What are the major financial risks?",
            document_ids=[self.doc_ids["acme"]],
        )
        self.assertTrue(answer.answer)
        self.assertTrue(
            any("no evidence-backed red flag" in line.lower() for line in answer.analytical_conclusions)
        )

    def test_follow_up_uses_session_context(self):
        self.research.clear_history(SESSION_ID)
        self.research.answer_question(
            "What was the revenue of Zenith Energy?",
            document_ids=[self.doc_ids["zenith"]],
            session_id=SESSION_ID,
        )
        answer = self.research.answer_question(
            "How did it change compared with the prior year?",
            document_ids=[self.doc_ids["zenith"]],
            session_id=SESSION_ID,
        )
        self.assertTrue(answer.context_used)
        self.assertIn("Zenith", answer.context_used[0])
        history = self.research.get_history(SESSION_ID)
        self.assertEqual(len(history), 4)
        roles = [m["role"] for m in history]
        self.assertEqual(roles, ["user", "assistant", "user", "assistant"])
        self.assertTrue(history[1]["citations"])

    # ------------------------------------------------------------------
    # Comparison Agent
    # ------------------------------------------------------------------

    def test_comparison_same_currency(self):
        result = self.comparison.compare_documents(
            [self.doc_ids["acme"], self.doc_ids["zenith"]],
        )
        self.assertEqual(len(result.companies), 2)
        acme = next(c for c in result.companies if "Acme" in c.company_name)
        revenue = next(m for m in acme.metrics if m.metric_name == "REVENUE")
        self.assertEqual(str(revenue.value), "14300.00")
        self.assertEqual(str(revenue.normalized_value), "14300.00")
        self.assertEqual(revenue.page_number, 1)
        self.assertIn("highest", result.summary.lower())
        self.assertFalse(any("different currencies" in w for w in result.warnings))

    def test_comparison_cross_currency_warns_and_does_not_rank(self):
        result = self.comparison.compare_documents(
            [self.doc_ids["acme"], self.doc_ids["infosys"]],
        )
        self.assertTrue(any("different currencies" in w for w in result.warnings))
        self.assertTrue(any("Cross-currency" in limitation for limitation in result.limitations))
        self.assertNotIn("highest", result.summary.lower())

    def test_comparison_marks_missing_metrics(self):
        result = self.comparison.compare_documents(
            [self.doc_ids["acme"], self.doc_ids["zenith"]],
            metrics=["REVENUE", "TOTAL_LIABILITIES"],
        )
        zenith = next(c for c in result.companies if "Zenith" in c.company_name)
        liabilities = next(m for m in zenith.metrics if m.metric_name == "TOTAL_LIABILITIES")
        self.assertIsNone(liabilities.value)
        self.assertIn("TOTAL_LIABILITIES", zenith.missing_metrics)
        self.assertIn("Not found", liabilities.note)

    # ------------------------------------------------------------------
    # Report Agent
    # ------------------------------------------------------------------

    def test_report_generates_executive_summary_and_key_financials(self):
        report = self.report.generate_report(self.doc_ids["acme"])
        keys = [section.section_key for section in report.sections]
        self.assertEqual(keys, ["executive_summary", "key_financials"])
        summary = report.sections[0]
        self.assertIn("Acme", summary.content_markdown)
        self.assertIn("14,300", summary.content_markdown)
        key_financials = report.sections[1]
        self.assertIn("| Metric | Reported Value |", key_financials.content_markdown)
        self.assertIn("Revenue", key_financials.content_markdown)
        self.assertGreater(len(report.citations), 0)
        self.assertTrue(all(c.page_number >= 1 for c in report.citations))
        for citation in report.citations:
            self.assertTrue(citation.document_id)
            self.assertTrue(citation.document_name)
        self.assertIn("Red Flags", report.planned_sections)
        self.assertIn("Outlook", report.planned_sections)

    def test_report_requires_validated_metrics(self):
        self.repo.create_document({
            "document_id": "m3-doc-empty",
            "workspace_id": WORKSPACE_ID,
            "sha256": "m3-empty-doc-hash",
            "filename": "empty_filing.pdf",
            "stored_filename": "empty_filing.pdf",
            "storage_path": "",
            "total_pages": 1,
        })
        with self.assertRaises(ValueError):
            self.report.generate_report("m3-doc-empty")


if __name__ == "__main__":
    unittest.main()
