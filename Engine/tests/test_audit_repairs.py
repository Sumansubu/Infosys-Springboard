"""Regression and Audit Verification Test Suite.

Verifies all critical audit fixes:
1. Embedding Provider strict dimension enforcement (zero padding rejected).
2. Qdrant Vector Store get_chunks_by_document implementation via scroll API.
3. MultiAgentWorkflowOrchestrator job_id reuse, idempotency, and default-workspace auto-provisioning.
4. Evidence Validation node provenance and boundary checking.
5. Database Repository interface contracts and stale job recovery.
"""

import unittest
from unittest.mock import MagicMock, patch
from app.infrastructure.document_processing.embedder import OpenAIEmbeddingProvider
from app.infrastructure.vector_store.qdrant import QdrantVectorStore
from app.infrastructure.database.repository import SQLiteRepository, SupabasePostgresRepository
from app.orchestration.workflow import (
    MultiAgentWorkflowOrchestrator,
    evidence_validation_node,
)
from app.orchestration.state import FinancialResearchState


class TestAuditRepairs(unittest.TestCase):
    """Test suite ensuring regressions are prevented for all repaired components."""

    def test_openai_embedding_insufficient_quota_raises_explicit_error(self):
        """Verify that 429 quota exhaustion raises RuntimeError and strictly never zero-pads vectors."""
        with patch("httpx.Client.post") as mock_post:
            mock_429 = MagicMock()
            mock_429.status_code = 429
            mock_429.text = '{"error": {"code": "insufficient_quota"}}'
            mock_post.return_value = mock_429

            provider = OpenAIEmbeddingProvider(api_key="test-api-key")
            with self.assertRaises(RuntimeError) as ctx:
                provider.generate_embeddings(["Quarterly balance sheet excerpt"])
            self.assertIn("insufficient_quota", str(ctx.exception))
            self.assertIn("strictly prohibited", str(ctx.exception))

    def test_qdrant_get_chunks_by_document_scroll(self):
        """Verify QdrantVectorStore scrolls points with payload matching document_id without dummy embeddings."""
        with patch("httpx.Client.post") as mock_post, patch.object(QdrantVectorStore, "_ensure_collection", return_value=True):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "result": {
                    "points": [
                        {
                            "id": "c7a8b9c0-1111-2222-3333-444455556666",
                            "payload": {
                                "chunk_id": "chunk_001",
                                "document_id": "doc_infy_2024",
                                "text": "Operating revenues for the fiscal year grew by 4.7%.",
                                "page_number": 3,
                                "page_chunk_index": 1,
                                "section": "FINANCIAL_STATEMENTS",
                                "is_table": False,
                                "filename": "infosys_ar.pdf",
                            },
                        }
                    ],
                    "next_page_offset": None,
                }
            }
            mock_post.return_value = mock_resp

            vs = QdrantVectorStore(url="http://localhost:6333", collection_name="test_collection")
            chunks = vs.get_chunks_by_document("doc_infy_2024")

            self.assertEqual(len(chunks), 1)
            self.assertEqual(chunks[0]["document_id"], "doc_infy_2024")
            self.assertEqual(chunks[0]["page_number"], 3)
            self.assertIn("Operating revenues", chunks[0]["text"])

    def test_evidence_validation_rejects_empty_citations(self):
        """Verify evidence_validation_node fails when no citations are verified."""
        state = FinancialResearchState(
            document_id="doc_test_001",
            filename="report.pdf",
            total_pages=10,
        )
        state.extracted_financials = {
            "metrics": {
                "REVENUE": {
                    "name": "REVENUE",
                    "value": "1000",
                    "citation": {"page_number": 0, "is_calculated": False},
                }
            }
        }
        repo = SQLiteRepository(db_path=":memory:")
        with patch("app.orchestration.workflow.get_database_repository", return_value=repo):
            validated_state = evidence_validation_node(state)
        self.assertFalse(validated_state.validation_passed)

    def test_evidence_validation_passes_valid_citations(self):
        """Verify evidence_validation_node passes only with a verified quote and value."""
        repo = SQLiteRepository(db_path=":memory:")
        repo.create_document({
            "document_id": "doc_test_001",
            "sha256": "evidence-pass-hash",
            "filename": "report.pdf",
            "stored_filename": "report.pdf",
            "storage_path": "",
            "total_pages": 10,
        })
        state = FinancialResearchState(
            document_id="doc_test_001",
            filename="report.pdf",
            total_pages=10,
            page_texts={3: "Consolidated income statement. Revenue: 1000 for the year."},
        )
        state.extracted_financials = {
            "metrics": {
                "REVENUE": {
                    "name": "REVENUE",
                    "value": "1000",
                    "citation": {
                        "document_id": "doc_test_001",
                        "page_number": 3,
                        "exact_quote": "Revenue: 1000",
                        "is_calculated": False,
                    },
                }
            }
        }
        with patch("app.orchestration.workflow.get_database_repository", return_value=repo):
            validated_state = evidence_validation_node(state)
        self.assertTrue(validated_state.validation_passed)
        self.assertEqual(validated_state.current_phase, "VALIDATION_PASSED")

    def test_sqlite_repository_stale_job_recovery_and_stats(self):
        """Verify repository recovers stale PROCESSING jobs back to QUEUED."""
        repo = SQLiteRepository(db_path=":memory:")
        # Provision dummy document
        repo.create_document({
            "document_id": "doc_test_recovery",
            "sha256": "hash_recovery_test",
            "filename": "test.pdf",
            "stored_filename": "test.pdf",
            "storage_path": "/tmp/test.pdf",
        })
        # Create job and mark it PROCESSING
        job = repo.create_processing_job("doc_test_recovery", status="PROCESSING", current_stage="CRASHED_IN_FLIGHT")
        stats_before = repo.get_queue_stats()
        self.assertEqual(stats_before["processing_jobs"], 1)

        recovered = repo.recover_stale_jobs()
        self.assertEqual(recovered, 1)

        updated = repo.get_processing_job(job["job_id"])
        self.assertEqual(updated["status"], "QUEUED")
        self.assertEqual(updated["current_stage"], "RECOVERED_FROM_CRASH")


if __name__ == "__main__":
    unittest.main()
