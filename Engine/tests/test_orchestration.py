"""Unit tests for Multi-Agent Workflow Orchestrator."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.infrastructure.database import SQLiteRepository
from app.infrastructure.llm import MockLLMProvider
from app.orchestration.state import FinancialResearchState
from app.orchestration.workflow import (
    MultiAgentWorkflowOrchestrator,
    document_agent_node,
    evidence_validation_node,
    extraction_agent_node,
    persistence_node,
    red_flag_agent_node,
)


class TestWorkflowOrchestration(unittest.TestCase):
    """Test suite verifying the 3-agent sequential LangGraph workflow."""

    def test_evidence_validation_node_logic(self):
        repo = SQLiteRepository(db_path=":memory:")
        repo.create_document({
            "document_id": "doc-orch-1",
            "sha256": "orch1",
            "filename": "report.pdf",
            "stored_filename": "report.pdf",
            "storage_path": "",
            "total_pages": 1,
        })
        state = FinancialResearchState(
            document_id="doc-orch-1",
            filename="report.pdf",
            is_indexed=True,
            total_pages=1,
            page_texts={1: "Revenue: 1000 for the fiscal year"},
            extracted_financials={
                "metrics": {
                    "REVENUE": {
                        "name": "REVENUE",
                        "value": "1000",
                        "citation": {
                            "document_id": "doc-orch-1",
                            "page_number": 1,
                            "exact_quote": "Revenue: 1000",
                        },
                    }
                }
            },
        )
        with patch("app.orchestration.workflow.get_database_repository", return_value=repo):
            validated = evidence_validation_node(state)
        self.assertTrue(validated.validation_passed)
        self.assertEqual(validated.current_phase, "VALIDATION_PASSED")
        self.assertEqual(validated.validated_metrics_count, 1)

    def test_evidence_validation_fails_on_empty_metrics(self):
        repo = SQLiteRepository(db_path=":memory:")
        state = FinancialResearchState(
            document_id="doc-orch-2",
            filename="report.pdf",
            is_indexed=True,
            extracted_financials={"metrics": {}},
        )
        with patch("app.orchestration.workflow.get_database_repository", return_value=repo):
            validated = evidence_validation_node(state)
        self.assertFalse(validated.validation_passed)
        self.assertTrue(validated.is_failed)

    def test_persistence_node_updates_summary(self):
        state = FinancialResearchState(
            document_id="doc-orch-3",
            filename="report.pdf",
            total_pages=10,
            chunk_count=25,
            extracted_metrics_count=8,
            red_flag_count=2,
            is_failed=False,
            validation_passed=True,
        )
        final_state = persistence_node(state)
        self.assertEqual(final_state.current_phase, "COMPLETED")
        self.assertIsNotNone(final_state.final_summary)
        self.assertEqual(final_state.final_summary["metrics_extracted"], 8)
        self.assertEqual(final_state.final_summary["red_flags_identified"], 2)

    def test_pipeline_missing_session_raises(self):
        """Verify MultiAgentWorkflowOrchestrator rejects a non-existent session_id upfront."""
        with self.assertRaises(ValueError) as ctx:
            MultiAgentWorkflowOrchestrator.run_pipeline(
                document_id="doc-fail-session",
                filename="test.pdf",
                workspace_id="default-workspace",
                session_id="non-existent-session-abc",
            )
        self.assertIn("not found", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()

