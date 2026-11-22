"""Repository layer for Workspace, Session, Document, and Multi-Agent Persistence."""

import json
import logging
import sqlite3
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.config import get_settings
from app.infrastructure.database.models import POSTGRES_SCHEMA_SQL, SQLITE_SCHEMA_SQL
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


class DatabaseRepositoryInterface(ABC):
    """Abstract interface for system persistence."""

    @abstractmethod
    def create_workspace(
        self,
        name: str,
        description: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_workspace(self, workspace_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def list_workspaces(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def create_session(
        self,
        workspace_id: str,
        title: str,
        description: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def list_sessions(self, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def add_document_to_session(self, session_id: str, document_id: str) -> bool:
        pass

    @abstractmethod
    def get_session_documents(self, session_id: str) -> List[str]:
        pass

    @abstractmethod
    def create_document(self, doc_data: Dict[str, Any]) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_document_by_sha256(self, sha256_hash: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_document_by_id(self, document_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def delete_document(self, document_id: str) -> bool:
        pass

    @abstractmethod
    def update_document_indexed(
        self,
        document_id: str,
        indexed: int,
        chunk_count: int,
        total_pages: Optional[int] = None,
        total_characters: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        pass

    @abstractmethod
    def list_documents(self, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def create_processing_job(
        self,
        document_id: str,
        workspace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        status: str = "QUEUED",
        current_stage: str = "INITIALIZING",
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    def update_processing_job(
        self,
        job_id: str,
        status: str,
        current_stage: str,
        error_message: Optional[str] = None,
    ) -> bool:
        pass

    @abstractmethod
    def get_processing_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def claim_next_processing_job(self) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def store_financial_metrics(
        self, document_id: str, metrics: List[Dict[str, Any]]
    ) -> int:
        pass

    @abstractmethod
    def get_financial_metrics(self, document_id: str) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def store_red_flag_findings(
        self,
        document_id: str,
        findings: List[Dict[str, Any]],
        session_id: Optional[str] = None,
    ) -> int:
        pass

    @abstractmethod
    def get_red_flag_findings(self, document_id: str) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def record_agent_run(
        self,
        document_id: str,
        agent_name: str,
        status: str,
        session_id: Optional[str] = None,
        input_payload: Optional[Dict[str, Any]] = None,
        output_payload: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> str:
        pass

    @abstractmethod
    def get_agent_runs(self, document_id: str) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def add_research_message(
        self,
        session_id: str,
        role: str,
        content: str,
        citations: Optional[List[Dict[str, Any]]] = None,
        document_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_research_messages(self, session_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def clear_research_messages(self, session_id: str) -> int:
        pass

    @abstractmethod
    def is_healthy(self) -> bool:
        pass

    @abstractmethod
    def recover_stale_jobs(self) -> int:
        pass

    @abstractmethod
    def get_queue_stats(self) -> Dict[str, int]:
        pass


class SQLiteRepository(DatabaseRepositoryInterface):
    """Zero-dependency local SQLite implementation of the database repository."""

    def __init__(self, db_path: Optional[str] = None):
        self._is_memory = str(db_path) == ":memory:"
        if self._is_memory:
            self.db_path = Path(":memory:")
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row
            self._mem_conn.execute("PRAGMA foreign_keys = ON;")
        else:
            self._mem_conn = None
            self.db_path = Path(db_path or get_settings().sqlite_db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    @contextmanager
    def _get_connection(self):
        if self._is_memory:
            try:
                yield self._mem_conn
                self._mem_conn.commit()
            except Exception:
                self._mem_conn.rollback()
                raise
        else:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def _initialize_schema(self):
        """Run migrations and ensure all tables and columns exist."""
        with self._get_connection() as conn:
            conn.executescript(SQLITE_SCHEMA_SQL)

            # Ensure columns exist on legacy tables
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(documents)").fetchall()
            }
            if "workspace_id" not in columns:
                conn.execute("ALTER TABLE documents ADD COLUMN workspace_id TEXT")
            if "total_pages" not in columns:
                conn.execute("ALTER TABLE documents ADD COLUMN total_pages INTEGER DEFAULT 0")
            if "total_characters" not in columns:
                conn.execute("ALTER TABLE documents ADD COLUMN total_characters INTEGER DEFAULT 0")
            if "storage_path" not in columns:
                conn.execute("ALTER TABLE documents ADD COLUMN storage_path TEXT DEFAULT ''")
            if "mime_type" not in columns:
                conn.execute("ALTER TABLE documents ADD COLUMN mime_type TEXT DEFAULT 'application/pdf'")
            if "metadata" not in columns:
                conn.execute("ALTER TABLE documents ADD COLUMN metadata TEXT DEFAULT '{}'")
            if "updated_at" not in columns:
                conn.execute(f"ALTER TABLE documents ADD COLUMN updated_at TEXT DEFAULT '{utc_now_iso()}'")

            # Ensure default workspace always exists
            default_ws_id = "default-workspace"
            now = utc_now_iso()
            conn.execute(
                """
                INSERT OR IGNORE INTO workspaces (workspace_id, name, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (default_ws_id, "Default Workspace", "System preloaded workspace", now, now),
            )

    def create_workspace(
        self,
        name: str,
        description: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        ws_id = workspace_id or uuid4().hex
        now = utc_now_iso()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO workspaces (workspace_id, name, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    updated_at = excluded.updated_at
                """,
                (ws_id, name, description, now, now),
            )
        return {
            "workspace_id": ws_id,
            "name": name,
            "description": description,
            "created_at": now,
            "updated_at": now,
            "session_count": 0,
            "document_count": 0,
        }

    def get_workspace(self, workspace_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM workspaces WHERE workspace_id = ?", (workspace_id,)
            ).fetchone()
            if not row:
                return None
            res = dict(row)
            res["session_count"] = conn.execute(
                "SELECT COUNT(*) as c FROM research_sessions WHERE workspace_id = ?", (workspace_id,)
            ).fetchone()["c"]
            res["document_count"] = conn.execute(
                "SELECT COUNT(*) as c FROM documents WHERE workspace_id = ?", (workspace_id,)
            ).fetchone()["c"]
            return res

    def list_workspaces(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM workspaces ORDER BY created_at DESC").fetchall()
            results = []
            for row in rows:
                item = dict(row)
                ws_id = item["workspace_id"]
                item["session_count"] = conn.execute(
                    "SELECT COUNT(*) as c FROM research_sessions WHERE workspace_id = ?", (ws_id,)
                ).fetchone()["c"]
                item["document_count"] = conn.execute(
                    "SELECT COUNT(*) as c FROM documents WHERE workspace_id = ?", (ws_id,)
                ).fetchone()["c"]
                results.append(item)
            return results

    def create_session(
        self,
        workspace_id: str,
        title: str,
        description: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        target_session_id = session_id or uuid4().hex
        now = utc_now_iso()
        with self._get_connection() as conn:
            # Verify workspace exists
            ws_row = conn.execute(
                "SELECT 1 FROM workspaces WHERE workspace_id = ?", (workspace_id,)
            ).fetchone()
            if not ws_row:
                raise ValueError(f"Workspace '{workspace_id}' not found. Cannot create research session.")

            conn.execute(
                """
                INSERT INTO research_sessions (session_id, workspace_id, title, description, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    workspace_id = excluded.workspace_id,
                    title = excluded.title,
                    description = excluded.description,
                    updated_at = excluded.updated_at
                """,
                (target_session_id, workspace_id, title, description, now, now),
            )
        return {
            "session_id": target_session_id,
            "workspace_id": workspace_id,
            "title": title,
            "description": description,
            "status": "ACTIVE",
            "created_at": now,
            "updated_at": now,
            "document_ids": [],
        }

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM research_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if not row:
                return None
            res = dict(row)
            doc_rows = conn.execute(
                "SELECT document_id FROM session_documents WHERE session_id = ?", (session_id,)
            ).fetchall()
            res["document_ids"] = [d["document_id"] for d in doc_rows]
            return res

    def list_sessions(self, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            if workspace_id:
                rows = conn.execute(
                    "SELECT * FROM research_sessions WHERE workspace_id = ? ORDER BY created_at DESC",
                    (workspace_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM research_sessions ORDER BY created_at DESC"
                ).fetchall()

            results = []
            for row in rows:
                item = dict(row)
                doc_rows = conn.execute(
                    "SELECT document_id FROM session_documents WHERE session_id = ?",
                    (item["session_id"],),
                ).fetchall()
                item["document_ids"] = [d["document_id"] for d in doc_rows]
                results.append(item)
            return results

    def add_document_to_session(self, session_id: str, document_id: str) -> bool:
        now = utc_now_iso()
        with self._get_connection() as conn:
            # 1. Verify parent research session exists
            session_row = conn.execute(
                "SELECT 1 FROM research_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if not session_row:
                raise ValueError(f"Research session '{session_id}' not found. Cannot associate document.")

            # 2. Verify parent document exists
            doc_row = conn.execute(
                "SELECT 1 FROM documents WHERE document_id = ?", (document_id,)
            ).fetchone()
            if not doc_row:
                doc_row = conn.execute(
                    "SELECT 1 FROM ai_documents WHERE document_id = ?", (document_id,)
                ).fetchone()
            if not doc_row:
                raise ValueError(f"Document '{document_id}' not found. Cannot associate with session.")

            conn.execute(
                """
                INSERT OR IGNORE INTO session_documents (session_id, document_id, added_at)
                VALUES (?, ?, ?)
                """,
                (session_id, document_id, now),
            )
        return True

    def get_session_documents(self, session_id: str) -> List[str]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT document_id FROM session_documents WHERE session_id = ?",
                (session_id,),
            ).fetchall()
            return [r["document_id"] for r in rows]

    def create_document(self, doc_data: Dict[str, Any]) -> Dict[str, Any]:
        document_id = doc_data.get("document_id") or uuid4().hex
        workspace_id = doc_data.get("workspace_id") or "default-workspace"
        session_id = doc_data.get("session_id")
        user_id = doc_data.get("user_id")
        now = utc_now_iso()
        metadata_str = json.dumps(doc_data.get("metadata", {}))

        with self._get_connection() as conn:
            # 1. Clean up any stale records with the same sha256 under a different document_id
            conn.execute(
                "DELETE FROM ai_documents WHERE sha256 = ? AND document_id != ?",
                (doc_data["sha256"], document_id),
            )
            conn.execute(
                "DELETE FROM documents WHERE sha256 = ? AND document_id != ?",
                (doc_data["sha256"], document_id),
            )

            # 2. Check if this document_id already exists in ai_documents (e.g. created as a job placeholder)
            existing_ai = conn.execute(
                "SELECT 1 FROM ai_documents WHERE document_id = ?", (document_id,)
            ).fetchone()

            if existing_ai:
                conn.execute(
                    """
                    UPDATE ai_documents
                    SET workspace_id = ?, session_id = ?, user_id = ?, sha256 = ?,
                        filename = ?, stored_filename = ?, storage_path = ?,
                        total_pages = ?, total_characters = ?, chunk_count = ?,
                        indexed = ?, mime_type = ?, metadata = ?, updated_at = ?
                    WHERE document_id = ?
                    """,
                    (
                        workspace_id,
                        session_id,
                        user_id,
                        doc_data["sha256"],
                        doc_data["filename"],
                        doc_data["stored_filename"],
                        doc_data.get("storage_path", ""),
                        doc_data.get("total_pages", 0),
                        doc_data.get("total_characters", 0),
                        doc_data.get("chunk_count", 0),
                        doc_data.get("indexed", 0),
                        doc_data.get("mime_type", "application/pdf"),
                        metadata_str,
                        now,
                        document_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO ai_documents (
                        document_id, workspace_id, session_id, user_id, sha256,
                        filename, stored_filename, storage_path, total_pages,
                        total_characters, chunk_count, indexed, mime_type, metadata,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        workspace_id,
                        session_id,
                        user_id,
                        doc_data["sha256"],
                        doc_data["filename"],
                        doc_data["stored_filename"],
                        doc_data.get("storage_path", ""),
                        doc_data.get("total_pages", 0),
                        doc_data.get("total_characters", 0),
                        doc_data.get("chunk_count", 0),
                        doc_data.get("indexed", 0),
                        doc_data.get("mime_type", "application/pdf"),
                        metadata_str,
                        now,
                        now,
                    ),
                )

            # 3. Synchronize legacy documents table
            existing_legacy = conn.execute(
                "SELECT 1 FROM documents WHERE document_id = ?", (document_id,)
            ).fetchone()

            if existing_legacy:
                conn.execute(
                    """
                    UPDATE documents
                    SET workspace_id = ?, sha256 = ?, filename = ?,
                        stored_filename = ?, storage_path = ?, total_pages = ?,
                        total_characters = ?, chunk_count = ?, indexed = ?,
                        mime_type = ?, metadata = ?, updated_at = ?
                    WHERE document_id = ?
                    """,
                    (
                        workspace_id,
                        doc_data["sha256"],
                        doc_data["filename"],
                        doc_data["stored_filename"],
                        doc_data.get("storage_path", ""),
                        doc_data.get("total_pages", 0),
                        doc_data.get("total_characters", 0),
                        doc_data.get("chunk_count", 0),
                        doc_data.get("indexed", 0),
                        doc_data.get("mime_type", "application/pdf"),
                        metadata_str,
                        now,
                        document_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO documents (
                        document_id, workspace_id, sha256, filename, stored_filename,
                        storage_path, total_pages, total_characters, chunk_count,
                        indexed, mime_type, metadata, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        workspace_id,
                        doc_data["sha256"],
                        doc_data["filename"],
                        doc_data["stored_filename"],
                        doc_data.get("storage_path", ""),
                        doc_data.get("total_pages", 0),
                        doc_data.get("total_characters", 0),
                        doc_data.get("chunk_count", 0),
                        doc_data.get("indexed", 0),
                        doc_data.get("mime_type", "application/pdf"),
                        metadata_str,
                        now,
                        now,
                    ),
                )

        return self.get_document_by_id(document_id) or doc_data

    def get_document_by_sha256(self, sha256_hash: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM ai_documents WHERE sha256 = ?", (sha256_hash,)
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT * FROM documents WHERE sha256 = ?", (sha256_hash,)
                ).fetchone()
            if not row:
                return None
            res = dict(row)
            try:
                res["metadata"] = json.loads(res.get("metadata") or "{}")
            except Exception:
                res["metadata"] = {}
            return res

    def get_document_by_id(self, document_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM ai_documents WHERE document_id = ?", (document_id,)
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT * FROM documents WHERE document_id = ?", (document_id,)
                ).fetchone()
            if not row:
                return None
            res = dict(row)
            try:
                res["metadata"] = json.loads(res.get("metadata") or "{}")
            except Exception:
                res["metadata"] = {}
            return res

    def delete_document(self, document_id: str) -> bool:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM ai_documents WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM documents WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM session_documents WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM ai_financial_metrics WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM ai_metric_evidence WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM ai_red_flag_findings WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM ai_processing_jobs WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM ai_agent_runs WHERE document_id = ?", (document_id,))
        return True

    def update_document_indexed(
        self,
        document_id: str,
        indexed: int,
        chunk_count: int,
        total_pages: Optional[int] = None,
        total_characters: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        now = utc_now_iso()
        with self._get_connection() as conn:
            current = conn.execute(
                "SELECT * FROM ai_documents WHERE document_id = ?", (document_id,)
            ).fetchone()
            if not current:
                current = conn.execute(
                    "SELECT * FROM documents WHERE document_id = ?", (document_id,)
                ).fetchone()
            if not current:
                return False

            meta_str = json.dumps(metadata) if metadata is not None else current["metadata"]
            pages = total_pages if total_pages is not None else current["total_pages"]
            chars = total_characters if total_characters is not None else current["total_characters"]

            conn.execute(
                """
                UPDATE documents
                SET indexed = ?, chunk_count = ?, total_pages = ?, total_characters = ?,
                    metadata = ?, updated_at = ?
                WHERE document_id = ?
                """,
                (indexed, chunk_count, pages, chars, meta_str, now, document_id),
            )
            conn.execute(
                """
                UPDATE ai_documents
                SET indexed = ?, chunk_count = ?, total_pages = ?, total_characters = ?,
                    metadata = ?, updated_at = ?
                WHERE document_id = ?
                """,
                (indexed, chunk_count, pages, chars, meta_str, now, document_id),
            )
            return True

    def list_documents(self, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            if workspace_id:
                rows = conn.execute(
                    "SELECT * FROM ai_documents WHERE workspace_id = ? ORDER BY created_at DESC",
                    (workspace_id,),
                ).fetchall()
                if not rows:
                    rows = conn.execute(
                        "SELECT * FROM documents WHERE workspace_id = ? ORDER BY created_at DESC",
                        (workspace_id,),
                    ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM ai_documents ORDER BY created_at DESC"
                ).fetchall()
                if not rows:
                    rows = conn.execute(
                        "SELECT * FROM documents ORDER BY created_at DESC"
                    ).fetchall()

            results = []
            for row in rows:
                item = dict(row)
                try:
                    item["metadata"] = json.loads(item.get("metadata") or "{}")
                except Exception:
                    item["metadata"] = {}
                results.append(item)
            return results

    # =========================================================================
    # Milestone 2: Processing Jobs
    # =========================================================================

    def create_processing_job(
        self,
        document_id: str,
        workspace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        status: str = "QUEUED",
        current_stage: str = "INITIALIZING",
    ) -> Dict[str, Any]:
        job_id = uuid4().hex
        now = utc_now_iso()
        with self._get_connection() as conn:
            # Ensure document exists in ai_documents before referencing foreign key
            doc_row = conn.execute(
                "SELECT 1 FROM ai_documents WHERE document_id = ?", (document_id,)
            ).fetchone()
            if not doc_row:
                # If document is only in legacy documents, copy reference to ai_documents
                legacy = conn.execute(
                    "SELECT * FROM documents WHERE document_id = ?", (document_id,)
                ).fetchone()
                if legacy:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO ai_documents (
                            document_id, workspace_id, session_id, sha256, filename,
                            stored_filename, storage_path, total_pages, total_characters,
                            chunk_count, indexed, mime_type, metadata, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            legacy["document_id"],
                            legacy["workspace_id"],
                            session_id,
                            legacy["sha256"],
                            legacy["filename"],
                            legacy["stored_filename"],
                            legacy["storage_path"],
                            legacy["total_pages"],
                            legacy["total_characters"],
                            legacy["chunk_count"],
                            legacy["indexed"],
                            legacy["mime_type"],
                            legacy["metadata"],
                            legacy["created_at"],
                            legacy["updated_at"],
                        ),
                    )
                else:
                    # Create placeholder entry in ai_documents to satisfy foreign key
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO ai_documents (
                            document_id, workspace_id, session_id, sha256, filename,
                            stored_filename, storage_path, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            document_id,
                            workspace_id or "default-workspace",
                            session_id,
                            f"placeholder-{document_id}",
                            "document.pdf",
                            "document.pdf",
                            "",
                            now,
                            now,
                        ),
                    )

            conn.execute(
                """
                INSERT INTO ai_processing_jobs (
                    job_id, document_id, workspace_id, session_id,
                    status, current_stage, error_message, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (job_id, document_id, workspace_id, session_id, status, current_stage, now, now),
            )
        return {
            "job_id": job_id,
            "document_id": document_id,
            "workspace_id": workspace_id,
            "session_id": session_id,
            "status": status,
            "current_stage": current_stage,
            "error_message": None,
            "created_at": now,
            "updated_at": now,
        }

    def update_processing_job(
        self,
        job_id: str,
        status: str,
        current_stage: str,
        error_message: Optional[str] = None,
    ) -> bool:
        now = utc_now_iso()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE ai_processing_jobs
                SET status = ?, current_stage = ?, error_message = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (status, current_stage, error_message, now, job_id),
            )
        return True

    def get_processing_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM ai_processing_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            return dict(row) if row else None

    def claim_next_processing_job(self) -> Optional[Dict[str, Any]]:
        """Atomically claim the next queued processing job for background worker execution."""
        now = utc_now_iso()
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM ai_processing_jobs
                WHERE status = 'QUEUED'
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
            if not row:
                return None

            job = dict(row)
            conn.execute(
                """
                UPDATE ai_processing_jobs
                SET status = 'PROCESSING', current_stage = 'CLAIMED_BY_WORKER', updated_at = ?
                WHERE job_id = ?
                """,
                (now, job["job_id"]),
            )
            job["status"] = "PROCESSING"
            job["current_stage"] = "CLAIMED_BY_WORKER"
            job["updated_at"] = now
            return job

    # =========================================================================
    # Milestone 2: Financial Metrics & Evidence Persistence
    # =========================================================================

    def store_financial_metrics(
        self, document_id: str, metrics: List[Dict[str, Any]]
    ) -> int:
        now = utc_now_iso()
        inserted_count = 0
        with self._get_connection() as conn:
            # Ensure document exists in ai_documents
            doc_row = conn.execute(
                "SELECT 1 FROM ai_documents WHERE document_id = ?", (document_id,)
            ).fetchone()
            if not doc_row:
                legacy = conn.execute(
                    "SELECT * FROM documents WHERE document_id = ?", (document_id,)
                ).fetchone()
                if legacy:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO ai_documents (
                            document_id, workspace_id, sha256, filename,
                            stored_filename, storage_path, total_pages, total_characters,
                            chunk_count, indexed, mime_type, metadata, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            legacy["document_id"],
                            legacy["workspace_id"],
                            legacy["sha256"],
                            legacy["filename"],
                            legacy["stored_filename"],
                            legacy["storage_path"],
                            legacy["total_pages"],
                            legacy["total_characters"],
                            legacy["chunk_count"],
                            legacy["indexed"],
                            legacy["mime_type"],
                            legacy["metadata"],
                            legacy["created_at"],
                            legacy["updated_at"],
                        ),
                    )

            # Clear existing metrics for fresh state
            conn.execute("DELETE FROM ai_metric_evidence WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM ai_financial_metrics WHERE document_id = ?", (document_id,))

            for m in metrics:
                metric_id = m.get("metric_id") or uuid4().hex
                conn.execute(
                    """
                    INSERT INTO ai_financial_metrics (
                        metric_id, document_id, period_type, fiscal_year,
                        statement_type, metric_name, source_label, numeric_value,
                        currency, unit, is_calculated, formula, is_consolidated, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        metric_id,
                        document_id,
                        m.get("period_type", "ANNUAL"),
                        int(m.get("fiscal_year", 2025)),
                        m.get("statement_type", "INCOME_STATEMENT"),
                        m["metric_name"],
                        m.get("source_label", ""),
                        str(m.get("numeric_value", "0")),
                        m.get("currency", "INR"),
                        m.get("unit", "CRORES"),
                        1 if m.get("is_calculated") else 0,
                        m.get("formula"),
                        1 if m.get("is_consolidated", True) else 0,
                        now,
                    ),
                )
                inserted_count += 1

                citation = m.get("citation")
                if citation and isinstance(citation, dict) and citation.get("page_number"):
                    evidence_id = uuid4().hex
                    conn.execute(
                        """
                        INSERT INTO ai_metric_evidence (
                            evidence_id, metric_id, document_id,
                            page_number, exact_quote, table_index, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            evidence_id,
                            metric_id,
                            document_id,
                            citation.get("page_number", 1),
                            citation.get("exact_quote", ""),
                            citation.get("table_index"),
                            now,
                        ),
                    )
        return inserted_count

    def get_financial_metrics(self, document_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT m.*, e.page_number as evidence_page, e.exact_quote, e.table_index
                FROM ai_financial_metrics m
                LEFT JOIN ai_metric_evidence e ON m.metric_id = e.metric_id
                WHERE m.document_id = ?
                ORDER BY m.created_at ASC
                """,
                (document_id,),
            ).fetchall()
            results = []
            for r in rows:
                item = dict(r)
                if item.get("evidence_page") is not None:
                    item["citation"] = {
                        "document_id": document_id,
                        "page_number": item.get("evidence_page"),
                        "exact_quote": item.get("exact_quote", ""),
                        "table_index": item.get("table_index"),
                    }
                results.append(item)
            return results

    def is_healthy(self) -> bool:
        """Check if SQLite database is responsive."""
        try:
            with self._get_connection() as conn:
                res = conn.execute("SELECT 1").fetchone()
                return res is not None
        except Exception:
            return False

    def recover_stale_jobs(self) -> int:
        """Recover jobs left in PROCESSING state from previous crashes."""
        with self._get_connection() as conn:
            res = conn.execute(
                """
                UPDATE ai_processing_jobs
                SET status = 'QUEUED', current_stage = 'RECOVERED_FROM_CRASH'
                WHERE status = 'PROCESSING'
                """
            )
            count = res.rowcount
            if count > 0:
                logger.info("Recovered %d orphaned job(s) from previous run back to QUEUED state.", count)
            return count

    def get_queue_stats(self) -> Dict[str, int]:
        """Return counts of queued and in-flight processing jobs."""
        with self._get_connection() as conn:
            q_row = conn.execute("SELECT COUNT(*) as c FROM ai_processing_jobs WHERE status = 'QUEUED'").fetchone()
            p_row = conn.execute("SELECT COUNT(*) as c FROM ai_processing_jobs WHERE status = 'PROCESSING'").fetchone()
            return {
                "queued_jobs": q_row["c"] if q_row else 0,
                "processing_jobs": p_row["c"] if p_row else 0,
            }

    # =========================================================================
    # Milestone 2: Red Flag Findings Persistence
    # =========================================================================

    def store_red_flag_findings(
        self,
        document_id: str,
        findings: List[Dict[str, Any]],
        session_id: Optional[str] = None,
    ) -> int:
        now = utc_now_iso()
        inserted_count = 0
        with self._get_connection() as conn:
            # Ensure document exists in ai_documents
            doc_row = conn.execute(
                "SELECT 1 FROM ai_documents WHERE document_id = ?", (document_id,)
            ).fetchone()
            if not doc_row:
                legacy = conn.execute(
                    "SELECT * FROM documents WHERE document_id = ?", (document_id,)
                ).fetchone()
                if legacy:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO ai_documents (
                            document_id, workspace_id, sha256, filename,
                            stored_filename, storage_path, total_pages, total_characters,
                            chunk_count, indexed, mime_type, metadata, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            legacy["document_id"],
                            legacy["workspace_id"],
                            legacy["sha256"],
                            legacy["filename"],
                            legacy["stored_filename"],
                            legacy["storage_path"],
                            legacy["total_pages"],
                            legacy["total_characters"],
                            legacy["chunk_count"],
                            legacy["indexed"],
                            legacy["mime_type"],
                            legacy["metadata"],
                            legacy["created_at"],
                            legacy["updated_at"],
                        ),
                    )

            conn.execute("DELETE FROM ai_red_flag_findings WHERE document_id = ?", (document_id,))
            for f in findings:
                finding_id = f.get("finding_id") or uuid4().hex
                conn.execute(
                    """
                    INSERT INTO ai_red_flag_findings (
                        finding_id, document_id, session_id, category, severity,
                        title, description, detection_method, supporting_evidence,
                        source_page, requires_review, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        finding_id,
                        document_id,
                        session_id or f.get("session_id"),
                        f.get("category", "OTHER"),
                        f.get("severity", "MEDIUM"),
                        f.get("title", ""),
                        f.get("description", ""),
                        f.get("detection_method", "RULE_BASED"),
                        f.get("supporting_evidence", ""),
                        f.get("source_page", 1),
                        1 if f.get("requires_review", True) else 0,
                        now,
                    ),
                )
                inserted_count += 1
        return inserted_count

    def get_red_flag_findings(self, document_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ai_red_flag_findings
                WHERE document_id = ?
                ORDER BY created_at ASC
                """,
                (document_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # =========================================================================
    # Milestone 2: Multi-Agent Execution Audit Runs
    # =========================================================================

    def record_agent_run(
        self,
        document_id: str,
        agent_name: str,
        status: str,
        session_id: Optional[str] = None,
        input_payload: Optional[Dict[str, Any]] = None,
        output_payload: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> str:
        run_id = uuid4().hex
        now = utc_now_iso()
        with self._get_connection() as conn:
            # Ensure document exists in ai_documents
            doc_row = conn.execute(
                "SELECT 1 FROM ai_documents WHERE document_id = ?", (document_id,)
            ).fetchone()
            if not doc_row:
                legacy = conn.execute(
                    "SELECT * FROM documents WHERE document_id = ?", (document_id,)
                ).fetchone()
                if legacy:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO ai_documents (
                            document_id, workspace_id, sha256, filename,
                            stored_filename, storage_path, total_pages, total_characters,
                            chunk_count, indexed, mime_type, metadata, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            legacy["document_id"],
                            legacy["workspace_id"],
                            legacy["sha256"],
                            legacy["filename"],
                            legacy["stored_filename"],
                            legacy["storage_path"],
                            legacy["total_pages"],
                            legacy["total_characters"],
                            legacy["chunk_count"],
                            legacy["indexed"],
                            legacy["mime_type"],
                            legacy["metadata"],
                            legacy["created_at"],
                            legacy["updated_at"],
                        ),
                    )

            conn.execute(
                """
                INSERT INTO ai_agent_runs (
                    run_id, document_id, session_id, agent_name, status,
                    input_payload, output_payload, error_message, started_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    document_id,
                    session_id,
                    agent_name,
                    status,
                    json.dumps(input_payload or {}),
                    json.dumps(output_payload or {}),
                    error_message,
                    now,
                    now if status in ("COMPLETED", "FAILED", "SUCCESS") else None,
                ),
            )
        return run_id

    def get_agent_runs(self, document_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ai_agent_runs
                WHERE document_id = ?
                ORDER BY started_at ASC
                """,
                (document_id,),
            ).fetchall()
            results = []
            for r in rows:
                item = dict(r)
                try:
                    item["input_payload"] = json.loads(item.get("input_payload") or "{}")
                except Exception:
                    item["input_payload"] = {}
                try:
                    item["output_payload"] = json.loads(item.get("output_payload") or "{}")
                except Exception:
                    item["output_payload"] = {}
                results.append(item)
            return results

    def is_healthy(self) -> bool:
        """Check if SQLite database is responsive."""
        try:
            with self._get_connection() as conn:
                res = conn.execute("SELECT 1").fetchone()
                return res is not None
        except Exception:
            return False

    def recover_stale_jobs(self) -> int:
        """Recover jobs left in PROCESSING state from previous crashes."""
        with self._get_connection() as conn:
            res = conn.execute(
                """
                UPDATE ai_processing_jobs
                SET status = 'QUEUED', current_stage = 'RECOVERED_FROM_CRASH'
                WHERE status = 'PROCESSING'
                """
            )
            count = res.rowcount
            if count > 0:
                logger.info("Recovered %d orphaned job(s) from previous run back to QUEUED state.", count)
            return count

    def get_queue_stats(self) -> Dict[str, int]:
        """Return counts of queued and in-flight processing jobs."""
        with self._get_connection() as conn:
            q_row = conn.execute("SELECT COUNT(*) as c FROM ai_processing_jobs WHERE status = 'QUEUED'").fetchone()
            p_row = conn.execute("SELECT COUNT(*) as c FROM ai_processing_jobs WHERE status = 'PROCESSING'").fetchone()
            return {
                "queued_jobs": q_row["c"] if q_row else 0,
                "processing_jobs": p_row["c"] if p_row else 0,
            }

    # =========================================================================
    # Milestone 3: Research Session Conversation Context
    # =========================================================================

    def add_research_message(
        self,
        session_id: str,
        role: str,
        content: str,
        citations: Optional[List[Dict[str, Any]]] = None,
        document_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        message_id = uuid4().hex
        now = utc_now_iso()
        citations_json = json.dumps(citations or [])
        metadata_json = json.dumps(metadata or {})
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO ai_research_messages (
                    message_id, session_id, document_id, role, content,
                    citations, metadata, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (message_id, session_id, document_id, role, content, citations_json, metadata_json, now),
            )
        return {
            "message_id": message_id,
            "session_id": session_id,
            "document_id": document_id,
            "role": role,
            "content": content,
            "citations": citations or [],
            "metadata": metadata or {},
            "created_at": now,
        }

    def get_research_messages(self, session_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ai_research_messages
                WHERE session_id = ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (session_id,),
            ).fetchall()

        results: List[Dict[str, Any]] = []
        for row in rows[-limit:] if limit and limit > 0 else rows:
            item = dict(row)
            try:
                item["citations"] = json.loads(item.get("citations") or "[]")
            except Exception:
                item["citations"] = []
            try:
                item["metadata"] = json.loads(item.get("metadata") or "{}")
            except Exception:
                item["metadata"] = {}
            results.append(item)
        return results

    def clear_research_messages(self, session_id: str) -> int:
        with self._get_connection() as conn:
            res = conn.execute(
                "DELETE FROM ai_research_messages WHERE session_id = ?", (session_id,)
            )
            return res.rowcount


class SupabasePostgresRepository(DatabaseRepositoryInterface):
    """Production Supabase PostgreSQL repository interface.

    Connects to Supabase PostgreSQL using SQLAlchemy with connection pooling,
    parameterized SQL statements, and native JSONB data types.
    Transparently falls back to SQLiteRepository if PostgreSQL credentials are
    unreachable or offline, ensuring uninterrupted local operations.
    """

    def __init__(self, database_url: str):
        self.database_url = database_url
        self._fallback_repo = SQLiteRepository()
        self._engine: Optional[Engine] = None
        self._is_connected: bool = False

        try:
            url = database_url
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+psycopg://", 1)
            elif url.startswith("postgresql://") and not url.startswith("postgresql+"):
                url = url.replace("postgresql://", "postgresql+psycopg://", 1)

            self._engine = create_engine(
                url,
                pool_pre_ping=True,
                pool_recycle=300,
                pool_size=5,
                max_overflow=10,
            )
            # Test connectivity
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            self._is_connected = True
            logger.info("SupabasePostgresRepository connected to PostgreSQL: %s", url.split("@")[-1] if "@" in url else "remote")
            self._ensure_tables()
        except Exception as e:
            logger.warning(
                "Could not connect to Supabase PostgreSQL (%s). Operations will gracefully use SQLite fallback.", e
            )
            self._is_connected = False

    def _ensure_tables(self) -> None:
        """Ensure standard and legacy relation tables exist and default workspace is provisioned."""
        if not self._is_connected or not self._engine:
            return
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS workspaces (
                            workspace_id VARCHAR(64) PRIMARY KEY,
                            name VARCHAR(255) NOT NULL,
                            description TEXT,
                            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                        );
                        CREATE TABLE IF NOT EXISTS research_sessions (
                            session_id VARCHAR(64) PRIMARY KEY,
                            workspace_id VARCHAR(64) REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
                            title VARCHAR(255) NOT NULL,
                            description TEXT,
                            status VARCHAR(32) DEFAULT 'ACTIVE',
                            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                        );
                        CREATE TABLE IF NOT EXISTS session_documents (
                            session_id VARCHAR(64) REFERENCES research_sessions(session_id) ON DELETE CASCADE,
                            document_id VARCHAR(64) REFERENCES ai_documents(document_id) ON DELETE CASCADE,
                            added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                            PRIMARY KEY (session_id, document_id)
                        );
                        INSERT INTO workspaces (workspace_id, name, description)
                        VALUES ('default-workspace', 'Default Workspace', 'System preloaded workspace')
                        ON CONFLICT (workspace_id) DO NOTHING;
                        """
                    )
                )
        except Exception as exc:
            logger.debug("PostgreSQL table verification notice: %s", exc)

    def is_healthy(self) -> bool:
        if self._is_connected and self._engine:
            try:
                with self._engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                    return True
            except Exception:
                return False
        return self._fallback_repo.is_healthy()

    def recover_stale_jobs(self) -> int:
        if self._is_connected and self._engine:
            try:
                with self._engine.begin() as conn:
                    res = conn.execute(
                        text(
                            """
                            UPDATE ai_processing_jobs
                            SET status = 'QUEUED', current_stage = 'RECOVERED_FROM_CRASH'
                            WHERE status = 'PROCESSING'
                            """
                        )
                    )
                    count = res.rowcount
                    if count > 0:
                        logger.info("Recovered %d orphaned job(s) in Postgres back to QUEUED state.", count)
                    return count
            except Exception as e:
                logger.warning("Error recovering stale jobs in Postgres: %s", e)
        return self._fallback_repo.recover_stale_jobs()

    def get_queue_stats(self) -> Dict[str, int]:
        if self._is_connected and self._engine:
            try:
                with self._engine.connect() as conn:
                    q = conn.execute(text("SELECT COUNT(*) FROM ai_processing_jobs WHERE status = 'QUEUED'")).scalar() or 0
                    p = conn.execute(text("SELECT COUNT(*) FROM ai_processing_jobs WHERE status = 'PROCESSING'")).scalar() or 0
                    return {"queued_jobs": int(q), "processing_jobs": int(p)}
            except Exception as e:
                logger.debug("Error querying queue stats from Postgres: %s", e)
        return self._fallback_repo.get_queue_stats()

    def _format_row(self, row_mapping: Any) -> Dict[str, Any]:
        """Convert SQLAlchemy row mapping to a JSON-compatible dict with ISO datetime strings."""
        item = dict(row_mapping)
        for k, v in list(item.items()):
            if isinstance(v, (datetime, date)):
                item[k] = v.isoformat()
        if "metadata" in item and isinstance(item["metadata"], str):
            try:
                item["metadata"] = json.loads(item["metadata"])
            except Exception:
                item["metadata"] = {}
        return item

    def create_workspace(
        self,
        name: str,
        description: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        ws_id = workspace_id or uuid4().hex
        if self._is_connected and self._engine:
            try:
                with self._engine.begin() as conn:
                    conn.execute(
                        text(
                            """
                            INSERT INTO workspaces (workspace_id, name, description, created_at, updated_at)
                            VALUES (:ws_id, :name, :description, NOW(), NOW())
                            ON CONFLICT (workspace_id) DO UPDATE SET
                                name = EXCLUDED.name,
                                description = EXCLUDED.description,
                                updated_at = EXCLUDED.updated_at
                            """
                        ),
                        {"ws_id": ws_id, "name": name, "description": description},
                    )
                return {
                    "workspace_id": ws_id,
                    "name": name,
                    "description": description,
                    "created_at": utc_now_iso(),
                    "updated_at": utc_now_iso(),
                    "session_count": 0,
                    "document_count": 0,
                }
            except Exception as e:
                logger.warning("Postgres error in create_workspace: %s", e)
        return self._fallback_repo.create_workspace(name, description, workspace_id)

    def get_workspace(self, workspace_id: str) -> Optional[Dict[str, Any]]:
        if self._is_connected and self._engine:
            try:
                with self._engine.connect() as conn:
                    row = conn.execute(
                        text("SELECT * FROM workspaces WHERE workspace_id = :ws_id"),
                        {"ws_id": workspace_id},
                    ).mappings().first()
                    if not row:
                        return None
                    item = self._format_row(row)
                    s_count = conn.execute(
                        text("SELECT COUNT(*) FROM research_sessions WHERE workspace_id = :ws_id"),
                        {"ws_id": workspace_id},
                    ).scalar() or 0
                    d_count = conn.execute(
                        text("SELECT COUNT(*) FROM ai_documents WHERE workspace_id = :ws_id"),
                        {"ws_id": workspace_id},
                    ).scalar() or 0
                    item["session_count"] = int(s_count)
                    item["document_count"] = int(d_count)
                    return item
            except Exception as e:
                logger.debug("Postgres error in get_workspace: %s", e)
        return self._fallback_repo.get_workspace(workspace_id)

    def list_workspaces(self) -> List[Dict[str, Any]]:
        if self._is_connected and self._engine:
            try:
                with self._engine.connect() as conn:
                    rows = conn.execute(text("SELECT * FROM workspaces ORDER BY created_at DESC")).mappings().all()
                    results = []
                    for r in rows:
                        item = self._format_row(r)
                        ws_id = item["workspace_id"]
                        s_count = conn.execute(
                            text("SELECT COUNT(*) FROM research_sessions WHERE workspace_id = :ws_id"),
                            {"ws_id": ws_id},
                        ).scalar() or 0
                        d_count = conn.execute(
                            text("SELECT COUNT(*) FROM ai_documents WHERE workspace_id = :ws_id"),
                            {"ws_id": ws_id},
                        ).scalar() or 0
                        item["session_count"] = int(s_count)
                        item["document_count"] = int(d_count)
                        results.append(item)
                    return results
            except Exception as e:
                logger.debug("Postgres error in list_workspaces: %s", e)
        return self._fallback_repo.list_workspaces()

    def create_session(
        self,
        workspace_id: str,
        title: str,
        description: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        s_id = session_id or uuid4().hex
        if self._is_connected and self._engine:
            try:
                with self._engine.begin() as conn:
                    conn.execute(
                        text(
                            """
                            INSERT INTO research_sessions (session_id, workspace_id, title, description, status, created_at, updated_at)
                            VALUES (:s_id, :ws_id, :title, :description, 'ACTIVE', NOW(), NOW())
                            ON CONFLICT (session_id) DO UPDATE SET
                                workspace_id = EXCLUDED.workspace_id,
                                title = EXCLUDED.title,
                                description = EXCLUDED.description,
                                updated_at = EXCLUDED.updated_at
                            """
                        ),
                        {"s_id": s_id, "ws_id": workspace_id, "title": title, "description": description},
                    )
                return {
                    "session_id": s_id,
                    "workspace_id": workspace_id,
                    "title": title,
                    "description": description,
                    "status": "ACTIVE",
                    "created_at": utc_now_iso(),
                    "updated_at": utc_now_iso(),
                    "document_ids": [],
                }
            except Exception as e:
                logger.warning("Postgres error in create_session: %s", e)
        return self._fallback_repo.create_session(workspace_id, title, description, session_id)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        if self._is_connected and self._engine:
            try:
                with self._engine.connect() as conn:
                    row = conn.execute(
                        text("SELECT * FROM research_sessions WHERE session_id = :s_id"),
                        {"s_id": session_id},
                    ).mappings().first()
                    if not row:
                        return None
                    item = self._format_row(row)
                    doc_rows = conn.execute(
                        text("SELECT document_id FROM session_documents WHERE session_id = :s_id"),
                        {"s_id": session_id},
                    ).scalars().all()
                    item["document_ids"] = list(doc_rows)
                    return item
            except Exception as e:
                logger.debug("Postgres error in get_session: %s", e)
        return self._fallback_repo.get_session(session_id)

    def list_sessions(self, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if self._is_connected and self._engine:
            try:
                with self._engine.connect() as conn:
                    if workspace_id:
                        rows = conn.execute(
                            text("SELECT * FROM research_sessions WHERE workspace_id = :ws_id ORDER BY created_at DESC"),
                            {"ws_id": workspace_id},
                        ).mappings().all()
                    else:
                        rows = conn.execute(
                            text("SELECT * FROM research_sessions ORDER BY created_at DESC")
                        ).mappings().all()
                    results = []
                    for r in rows:
                        item = self._format_row(r)
                        doc_rows = conn.execute(
                            text("SELECT document_id FROM session_documents WHERE session_id = :s_id"),
                            {"s_id": item["session_id"]},
                        ).scalars().all()
                        item["document_ids"] = list(doc_rows)
                        results.append(item)
                    return results
            except Exception as e:
                logger.debug("Postgres error in list_sessions: %s", e)
        return self._fallback_repo.list_sessions(workspace_id)

    def add_document_to_session(self, session_id: str, document_id: str) -> bool:
        if self._is_connected and self._engine:
            try:
                with self._engine.begin() as conn:
                    conn.execute(
                        text(
                            """
                            INSERT INTO session_documents (session_id, document_id, added_at)
                            VALUES (:s_id, :doc_id, NOW())
                            ON CONFLICT DO NOTHING
                            """
                        ),
                        {"s_id": session_id, "doc_id": document_id},
                    )
                return True
            except Exception as e:
                logger.warning("Postgres error in add_document_to_session: %s", e)
        return self._fallback_repo.add_document_to_session(session_id, document_id)

    def get_session_documents(self, session_id: str) -> List[str]:
        if self._is_connected and self._engine:
            try:
                with self._engine.connect() as conn:
                    rows = conn.execute(
                        text("SELECT document_id FROM session_documents WHERE session_id = :s_id"),
                        {"s_id": session_id},
                    ).scalars().all()
                    return list(rows)
            except Exception as e:
                logger.debug("Postgres error in get_session_documents: %s", e)
        return self._fallback_repo.get_session_documents(session_id)

    def create_document(self, doc_data: Dict[str, Any]) -> Dict[str, Any]:
        document_id = doc_data.get("document_id") or uuid4().hex
        workspace_id = doc_data.get("workspace_id") or "default-workspace"
        session_id = doc_data.get("session_id")
        user_id = doc_data.get("user_id")
        meta_json = json.dumps(doc_data.get("metadata", {}))

        if self._is_connected and self._engine:
            try:
                with self._engine.begin() as conn:
                    conn.execute(
                        text("DELETE FROM ai_documents WHERE sha256 = :sha AND document_id != :doc_id"),
                        {"sha": doc_data["sha256"], "doc_id": document_id},
                    )
                    conn.execute(
                        text(
                            """
                            INSERT INTO ai_documents (
                                document_id, workspace_id, session_id, user_id, sha256,
                                filename, stored_filename, storage_path, total_pages,
                                total_characters, chunk_count, indexed, mime_type, metadata,
                                created_at, updated_at
                            )
                            VALUES (
                                :document_id, :workspace_id, :session_id, :user_id, :sha256,
                                :filename, :stored_filename, :storage_path, :total_pages,
                                :total_characters, :chunk_count, :indexed, :mime_type, CAST(:metadata AS jsonb),
                                NOW(), NOW()
                            )
                            ON CONFLICT (document_id) DO UPDATE SET
                                workspace_id = EXCLUDED.workspace_id,
                                session_id = EXCLUDED.session_id,
                                user_id = EXCLUDED.user_id,
                                sha256 = EXCLUDED.sha256,
                                filename = EXCLUDED.filename,
                                stored_filename = EXCLUDED.stored_filename,
                                storage_path = EXCLUDED.storage_path,
                                total_pages = EXCLUDED.total_pages,
                                total_characters = EXCLUDED.total_characters,
                                chunk_count = EXCLUDED.chunk_count,
                                indexed = EXCLUDED.indexed,
                                mime_type = EXCLUDED.mime_type,
                                metadata = EXCLUDED.metadata,
                                updated_at = NOW()
                            """
                        ),
                        {
                            "document_id": document_id,
                            "workspace_id": workspace_id,
                            "session_id": session_id,
                            "user_id": user_id,
                            "sha256": doc_data["sha256"],
                            "filename": doc_data["filename"],
                            "stored_filename": doc_data["stored_filename"],
                            "storage_path": doc_data.get("storage_path", ""),
                            "total_pages": doc_data.get("total_pages", 0),
                            "total_characters": doc_data.get("total_characters", 0),
                            "chunk_count": doc_data.get("chunk_count", 0),
                            "indexed": doc_data.get("indexed", 0),
                            "mime_type": doc_data.get("mime_type", "application/pdf"),
                            "metadata": meta_json,
                        },
                    )
                self._fallback_repo.create_document(doc_data)
                return self.get_document_by_id(document_id) or doc_data
            except Exception as e:
                logger.warning("Postgres error in create_document: %s", e)
        return self._fallback_repo.create_document(doc_data)

    def get_document_by_sha256(self, sha256_hash: str) -> Optional[Dict[str, Any]]:
        if self._is_connected and self._engine:
            try:
                with self._engine.connect() as conn:
                    row = conn.execute(
                        text("SELECT * FROM ai_documents WHERE sha256 = :sha"),
                        {"sha": sha256_hash},
                    ).mappings().first()
                    if row:
                        return self._format_row(row)
            except Exception as e:
                logger.debug("Postgres error in get_document_by_sha256: %s", e)
        return self._fallback_repo.get_document_by_sha256(sha256_hash)

    def get_document_by_id(self, document_id: str) -> Optional[Dict[str, Any]]:
        if self._is_connected and self._engine:
            try:
                with self._engine.connect() as conn:
                    row = conn.execute(
                        text("SELECT * FROM ai_documents WHERE document_id = :doc_id"),
                        {"doc_id": document_id},
                    ).mappings().first()
                    if row:
                        return self._format_row(row)
            except Exception as e:
                logger.debug("Postgres error in get_document_by_id: %s", e)
        return self._fallback_repo.get_document_by_id(document_id)

    def delete_document(self, document_id: str) -> bool:
        if self._is_connected and self._engine:
            try:
                with self._engine.begin() as conn:
                    conn.execute(
                        text("DELETE FROM ai_documents WHERE document_id = :doc_id"),
                        {"doc_id": document_id},
                    )
                self._fallback_repo.delete_document(document_id)
                return True
            except Exception as e:
                logger.warning("Postgres error in delete_document: %s", e)
        return self._fallback_repo.delete_document(document_id)

    def update_document_indexed(
        self,
        document_id: str,
        indexed: int,
        chunk_count: int,
        total_pages: Optional[int] = None,
        total_characters: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        meta_json = json.dumps(metadata) if metadata is not None else None
        if self._is_connected and self._engine:
            try:
                with self._engine.begin() as conn:
                    conn.execute(
                        text(
                            """
                            UPDATE ai_documents
                            SET indexed = :indexed,
                                chunk_count = :chunk_count,
                                total_pages = COALESCE(:total_pages, total_pages),
                                total_characters = COALESCE(:total_characters, total_characters),
                                metadata = COALESCE(CAST(:metadata AS jsonb), metadata),
                                updated_at = NOW()
                            WHERE document_id = :doc_id
                            """
                        ),
                        {
                            "indexed": indexed,
                            "chunk_count": chunk_count,
                            "total_pages": total_pages,
                            "total_characters": total_characters,
                            "metadata": meta_json,
                            "doc_id": document_id,
                        },
                    )
                self._fallback_repo.update_document_indexed(
                    document_id, indexed, chunk_count, total_pages, total_characters, metadata
                )
                return True
            except Exception as e:
                logger.warning("Postgres error in update_document_indexed: %s", e)
        return self._fallback_repo.update_document_indexed(
            document_id, indexed, chunk_count, total_pages, total_characters, metadata
        )

    def list_documents(self, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if self._is_connected and self._engine:
            try:
                with self._engine.connect() as conn:
                    if workspace_id:
                        rows = conn.execute(
                            text("SELECT * FROM ai_documents WHERE workspace_id = :ws_id ORDER BY created_at DESC"),
                            {"ws_id": workspace_id},
                        ).mappings().all()
                    else:
                        rows = conn.execute(
                            text("SELECT * FROM ai_documents ORDER BY created_at DESC")
                        ).mappings().all()
                    return [self._format_row(r) for r in rows]
            except Exception as e:
                logger.debug("Postgres error in list_documents: %s", e)
        return self._fallback_repo.list_documents(workspace_id)

    def create_processing_job(
        self,
        document_id: str,
        workspace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        status: str = "QUEUED",
        current_stage: str = "INITIALIZING",
    ) -> Dict[str, Any]:
        job_id = uuid4().hex
        if self._is_connected and self._engine:
            try:
                with self._engine.begin() as conn:
                    # Ensure document placeholder exists to satisfy foreign key
                    conn.execute(
                        text(
                            """
                            INSERT INTO ai_documents (document_id, workspace_id, session_id, sha256, filename, stored_filename, storage_path, created_at, updated_at)
                            VALUES (:doc_id, :ws_id, :s_id, :doc_id, 'document.pdf', 'document.pdf', '', NOW(), NOW())
                            ON CONFLICT (document_id) DO NOTHING
                            """
                        ),
                        {"doc_id": document_id, "ws_id": workspace_id or "default-workspace", "s_id": session_id},
                    )
                    conn.execute(
                        text(
                            """
                            INSERT INTO ai_processing_jobs (
                                job_id, document_id, workspace_id, session_id, status, current_stage, created_at, updated_at
                            )
                            VALUES (
                                :job_id, :doc_id, :ws_id, :s_id, :status, :stage, NOW(), NOW()
                            )
                            """
                        ),
                        {
                            "job_id": job_id,
                            "doc_id": document_id,
                            "ws_id": workspace_id,
                            "s_id": session_id,
                            "status": status,
                            "stage": current_stage,
                        },
                    )
                self._fallback_repo.create_processing_job(
                    document_id, workspace_id, session_id, status, current_stage
                )
                return {
                    "job_id": job_id,
                    "document_id": document_id,
                    "workspace_id": workspace_id,
                    "session_id": session_id,
                    "status": status,
                    "current_stage": current_stage,
                    "created_at": utc_now_iso(),
                    "updated_at": utc_now_iso(),
                }
            except Exception as e:
                logger.warning("Postgres error in create_processing_job: %s", e)
        return self._fallback_repo.create_processing_job(
            document_id, workspace_id, session_id, status, current_stage
        )

    def update_processing_job(
        self,
        job_id: str,
        status: str,
        current_stage: str,
        error_message: Optional[str] = None,
    ) -> bool:
        if self._is_connected and self._engine:
            try:
                with self._engine.begin() as conn:
                    conn.execute(
                        text(
                            """
                            UPDATE ai_processing_jobs
                            SET status = :status,
                                current_stage = :stage,
                                error_message = :err,
                                updated_at = NOW()
                            WHERE job_id = :job_id
                            """
                        ),
                        {"status": status, "stage": current_stage, "err": error_message, "job_id": job_id},
                    )
                self._fallback_repo.update_processing_job(job_id, status, current_stage, error_message)
                return True
            except Exception as e:
                logger.warning("Postgres error in update_processing_job: %s", e)
        return self._fallback_repo.update_processing_job(job_id, status, current_stage, error_message)

    def get_processing_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        if self._is_connected and self._engine:
            try:
                with self._engine.connect() as conn:
                    row = conn.execute(
                        text("SELECT * FROM ai_processing_jobs WHERE job_id = :job_id"),
                        {"job_id": job_id},
                    ).mappings().first()
                    if row:
                        return self._format_row(row)
            except Exception as e:
                logger.debug("Postgres error in get_processing_job: %s", e)
        return self._fallback_repo.get_processing_job(job_id)

    def claim_next_processing_job(self) -> Optional[Dict[str, Any]]:
        if self._is_connected and self._engine:
            try:
                with self._engine.begin() as conn:
                    row = conn.execute(
                        text(
                            """
                            UPDATE ai_processing_jobs
                            SET status = 'PROCESSING',
                                current_stage = 'CLAIMED_BY_WORKER',
                                updated_at = NOW()
                            WHERE job_id = (
                                SELECT job_id FROM ai_processing_jobs
                                WHERE status = 'QUEUED'
                                ORDER BY created_at ASC
                                LIMIT 1
                                FOR UPDATE SKIP LOCKED
                            )
                            RETURNING *
                            """
                        )
                    ).mappings().first()
                    if row:
                        return self._format_row(row)
            except Exception as e:
                logger.debug("Postgres error in claim_next_processing_job: %s", e)
        return self._fallback_repo.claim_next_processing_job()

    def store_financial_metrics(
        self, document_id: str, metrics: List[Dict[str, Any]]
    ) -> int:
        if self._is_connected and self._engine:
            try:
                with self._engine.begin() as conn:
                    conn.execute(
                        text(
                            """
                            INSERT INTO ai_documents (document_id, workspace_id, session_id, sha256, filename, stored_filename, storage_path, created_at, updated_at)
                            VALUES (:doc_id, 'default-workspace', NULL, :doc_id, 'document.pdf', 'document.pdf', '', NOW(), NOW())
                            ON CONFLICT (document_id) DO NOTHING
                            """
                        ),
                        {"doc_id": document_id},
                    )
                    conn.execute(
                        text("DELETE FROM ai_financial_metrics WHERE document_id = :doc_id"),
                        {"doc_id": document_id},
                    )
                    count = 0
                    for m in metrics:
                        m_id = uuid4().hex
                        conn.execute(
                            text(
                                """
                                INSERT INTO ai_financial_metrics (
                                    metric_id, document_id, period_type, fiscal_year,
                                    statement_type, metric_name, source_label, numeric_value,
                                    currency, unit, is_calculated, formula, is_consolidated, created_at
                                )
                                VALUES (
                                    :m_id, :doc_id, :period, :year, :stmt, :name, :label,
                                    :val, :curr, :unit, :is_calc, :formula, :is_cons, NOW()
                                )
                                """
                            ),
                            {
                                "m_id": m_id,
                                "doc_id": document_id,
                                "period": m.get("period_type", "ANNUAL"),
                                "year": m.get("fiscal_year", 2024),
                                "stmt": m.get("statement_type", "INCOME_STATEMENT"),
                                "name": m.get("metric_name", "UNKNOWN"),
                                "label": m.get("source_label"),
                                "val": float(m.get("numeric_value", 0.0)),
                                "curr": m.get("currency", "INR"),
                                "unit": m.get("unit", "CRORES"),
                                "is_calc": bool(m.get("is_calculated", False)),
                                "formula": m.get("formula"),
                                "is_cons": bool(m.get("is_consolidated", True)),
                            },
                        )
                        cit = m.get("citation")
                        if cit and cit.get("page_number"):
                            conn.execute(
                                text(
                                    """
                                    INSERT INTO ai_metric_evidence (
                                        evidence_id, metric_id, document_id, page_number,
                                        exact_quote, table_index, created_at
                                    )
                                    VALUES (
                                        :ev_id, :m_id, :doc_id, :page, :quote, :table_idx, NOW()
                                    )
                                    """
                                ),
                                {
                                    "ev_id": uuid4().hex,
                                    "m_id": m_id,
                                    "doc_id": document_id,
                                    "page": cit.get("page_number", 1),
                                    "quote": cit.get("exact_quote", ""),
                                    "table_idx": cit.get("table_index"),
                                },
                            )
                        count += 1
                self._fallback_repo.store_financial_metrics(document_id, metrics)
                return count
            except Exception as e:
                logger.warning("Postgres error in store_financial_metrics: %s", e)
        return self._fallback_repo.store_financial_metrics(document_id, metrics)

    def get_financial_metrics(self, document_id: str) -> List[Dict[str, Any]]:
        if self._is_connected and self._engine:
            try:
                with self._engine.connect() as conn:
                    rows = conn.execute(
                        text(
                            """
                            SELECT m.*, e.page_number, e.exact_quote, e.table_index
                            FROM ai_financial_metrics m
                            LEFT JOIN ai_metric_evidence e ON m.metric_id = e.metric_id
                            WHERE m.document_id = :doc_id
                            ORDER BY m.created_at ASC
                            """
                        ),
                        {"doc_id": document_id},
                    ).mappings().all()
                    results = []
                    for r in rows:
                        item = self._format_row(r)
                        if item.get("page_number"):
                            item["citation"] = {
                                "document_id": document_id,
                                "page_number": item["page_number"],
                                "exact_quote": item.get("exact_quote", ""),
                                "table_index": item.get("table_index"),
                            }
                        results.append(item)
                    return results
            except Exception as e:
                logger.debug("Postgres error in get_financial_metrics: %s", e)
        return self._fallback_repo.get_financial_metrics(document_id)

    def store_red_flag_findings(
        self,
        document_id: str,
        findings: List[Dict[str, Any]],
        session_id: Optional[str] = None,
    ) -> int:
        if self._is_connected and self._engine:
            try:
                with self._engine.begin() as conn:
                    conn.execute(
                        text(
                            """
                            INSERT INTO ai_documents (document_id, workspace_id, session_id, sha256, filename, stored_filename, storage_path, created_at, updated_at)
                            VALUES (:doc_id, 'default-workspace', :s_id, :doc_id, 'document.pdf', 'document.pdf', '', NOW(), NOW())
                            ON CONFLICT (document_id) DO NOTHING
                            """
                        ),
                        {"doc_id": document_id, "s_id": session_id},
                    )
                    conn.execute(
                        text("DELETE FROM ai_red_flag_findings WHERE document_id = :doc_id"),
                        {"doc_id": document_id},
                    )
                    count = 0
                    for f in findings:
                        conn.execute(
                            text(
                                """
                                INSERT INTO ai_red_flag_findings (
                                    finding_id, document_id, session_id, category, severity,
                                    title, description, detection_method, supporting_evidence,
                                    source_page, requires_review, created_at
                                )
                                VALUES (
                                    :f_id, :doc_id, :s_id, :cat, :sev, :title, :desc,
                                    :method, :evidence, :page, :review, NOW()
                                )
                                """
                            ),
                            {
                                "f_id": f.get("finding_id") or uuid4().hex,
                                "doc_id": document_id,
                                "s_id": session_id or f.get("session_id"),
                                "cat": f.get("category", "OTHER"),
                                "sev": f.get("severity", "MEDIUM"),
                                "title": f.get("title", ""),
                                "desc": f.get("description", ""),
                                "method": f.get("detection_method", "RULE_BASED"),
                                "evidence": f.get("supporting_evidence", ""),
                                "page": f.get("source_page", 1),
                                "review": bool(f.get("requires_review", True)),
                            },
                        )
                        count += 1
                self._fallback_repo.store_red_flag_findings(document_id, findings, session_id)
                return count
            except Exception as e:
                logger.warning("Postgres error in store_red_flag_findings: %s", e)
        return self._fallback_repo.store_red_flag_findings(document_id, findings, session_id)

    def get_red_flag_findings(self, document_id: str) -> List[Dict[str, Any]]:
        if self._is_connected and self._engine:
            try:
                with self._engine.connect() as conn:
                    rows = conn.execute(
                        text(
                            """
                            SELECT * FROM ai_red_flag_findings
                            WHERE document_id = :doc_id
                            ORDER BY created_at ASC
                            """
                        ),
                        {"doc_id": document_id},
                    ).mappings().all()
                    return [self._format_row(r) for r in rows]
            except Exception as e:
                logger.debug("Postgres error in get_red_flag_findings: %s", e)
        return self._fallback_repo.get_red_flag_findings(document_id)

    def record_agent_run(
        self,
        document_id: str,
        agent_name: str,
        status: str,
        session_id: Optional[str] = None,
        input_payload: Optional[Dict[str, Any]] = None,
        output_payload: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> str:
        run_id = uuid4().hex
        is_finished = status in ("COMPLETED", "FAILED", "SUCCESS")
        if self._is_connected and self._engine:
            try:
                with self._engine.begin() as conn:
                    conn.execute(
                        text(
                            """
                            INSERT INTO ai_documents (document_id, workspace_id, session_id, sha256, filename, stored_filename, storage_path, created_at, updated_at)
                            VALUES (:doc_id, 'default-workspace', :s_id, :doc_id, 'document.pdf', 'document.pdf', '', NOW(), NOW())
                            ON CONFLICT (document_id) DO NOTHING
                            """
                        ),
                        {"doc_id": document_id, "s_id": session_id},
                    )
                    conn.execute(
                        text(
                            """
                            INSERT INTO ai_agent_runs (
                                run_id, document_id, session_id, agent_name, status,
                                input_payload, output_payload, error_message, started_at, completed_at
                            )
                            VALUES (
                                :run_id, :doc_id, :s_id, :name, :status,
                                CAST(:in_payload AS jsonb), CAST(:out_payload AS jsonb), :err, NOW(),
                                CASE WHEN :is_finished THEN NOW() ELSE NULL END
                            )
                            """
                        ),
                        {
                            "run_id": run_id,
                            "doc_id": document_id,
                            "s_id": session_id,
                            "name": agent_name,
                            "status": status,
                            "in_payload": json.dumps(input_payload or {}),
                            "out_payload": json.dumps(output_payload or {}),
                            "err": error_message,
                            "is_finished": is_finished,
                        },
                    )
                self._fallback_repo.record_agent_run(
                    document_id, agent_name, status, session_id, input_payload, output_payload, error_message
                )
                return run_id
            except Exception as e:
                logger.warning("Postgres error in record_agent_run: %s", e)
        return self._fallback_repo.record_agent_run(
            document_id, agent_name, status, session_id, input_payload, output_payload, error_message
        )

    def get_agent_runs(self, document_id: str) -> List[Dict[str, Any]]:
        if self._is_connected and self._engine:
            try:
                with self._engine.connect() as conn:
                    rows = conn.execute(
                        text(
                            """
                            SELECT * FROM ai_agent_runs
                            WHERE document_id = :doc_id
                            ORDER BY started_at ASC
                            """
                        ),
                        {"doc_id": document_id},
                    ).mappings().all()
                    results = []
                    for r in rows:
                        item = self._format_row(r)
                        if isinstance(item.get("input_payload"), str):
                            try:
                                item["input_payload"] = json.loads(item["input_payload"])
                            except Exception:
                                item["input_payload"] = {}
                        if isinstance(item.get("output_payload"), str):
                            try:
                                item["output_payload"] = json.loads(item["output_payload"])
                            except Exception:
                                item["output_payload"] = {}
                        results.append(item)
                    return results
            except Exception as e:
                logger.debug("Postgres error in get_agent_runs: %s", e)
        return self._fallback_repo.get_agent_runs(document_id)

    def add_research_message(
        self,
        session_id: str,
        role: str,
        content: str,
        citations: Optional[List[Dict[str, Any]]] = None,
        document_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        message_id = uuid4().hex
        now = utc_now_iso()
        if self._is_connected and self._engine:
            try:
                with self._engine.begin() as conn:
                    conn.execute(
                        text(
                            """
                            INSERT INTO ai_research_messages (
                                message_id, session_id, document_id, role, content,
                                citations, metadata, created_at
                            )
                            VALUES (
                                :message_id, :session_id, :document_id, :role, :content,
                                CAST(:citations AS JSONB), CAST(:metadata AS JSONB), :created_at
                            )
                            """
                        ),
                        {
                            "message_id": message_id,
                            "session_id": session_id,
                            "document_id": document_id,
                            "role": role,
                            "content": content,
                            "citations": json.dumps(citations or []),
                            "metadata": json.dumps(metadata or {}),
                            "created_at": now,
                        },
                    )
                return {
                    "message_id": message_id,
                    "session_id": session_id,
                    "document_id": document_id,
                    "role": role,
                    "content": content,
                    "citations": citations or [],
                    "metadata": metadata or {},
                    "created_at": now,
                }
            except Exception as e:
                logger.warning("Postgres error in add_research_message: %s", e)
        return self._fallback_repo.add_research_message(
            session_id, role, content, citations, document_id, metadata
        )

    def get_research_messages(self, session_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        if self._is_connected and self._engine:
            try:
                with self._engine.connect() as conn:
                    rows = conn.execute(
                        text(
                            """
                            SELECT * FROM ai_research_messages
                            WHERE session_id = :session_id
                            ORDER BY created_at ASC
                            """
                        ),
                        {"session_id": session_id},
                    ).mappings().all()
                    results = []
                    for r in rows[-limit:] if limit and limit > 0 else rows:
                        item = self._format_row(r)
                        for field_name, default in (("citations", []), ("metadata", {})):
                            if isinstance(item.get(field_name), str):
                                try:
                                    item[field_name] = json.loads(item[field_name])
                                except Exception:
                                    item[field_name] = default
                        results.append(item)
                    return results
            except Exception as e:
                logger.debug("Postgres error in get_research_messages: %s", e)
        return self._fallback_repo.get_research_messages(session_id, limit)

    def clear_research_messages(self, session_id: str) -> int:
        if self._is_connected and self._engine:
            try:
                with self._engine.begin() as conn:
                    res = conn.execute(
                        text("DELETE FROM ai_research_messages WHERE session_id = :session_id"),
                        {"session_id": session_id},
                    )
                    return res.rowcount or 0
            except Exception as e:
                logger.debug("Postgres error in clear_research_messages: %s", e)
        return self._fallback_repo.clear_research_messages(session_id)


_repository_instance: Optional[DatabaseRepositoryInterface] = None


def get_database_repository() -> DatabaseRepositoryInterface:
    """Singleton factory returning the configured DatabaseRepository."""
    global _repository_instance
    if _repository_instance is None:
        settings = get_settings()
        if settings.database_url:
            _repository_instance = SupabasePostgresRepository(settings.database_url)
        else:
            _repository_instance = SQLiteRepository(settings.sqlite_db_path)
    return _repository_instance
