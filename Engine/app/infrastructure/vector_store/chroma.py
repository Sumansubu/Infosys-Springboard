"""ChromaDB Vector Store Adapter (Safe Migration Fallback).

``chromadb`` is imported lazily so the backend and its test suite still start on
machines where the optional native dependency is unavailable. In that case the
adapter transparently delegates to :class:`LocalJSONVectorStore`, a persistent
cosine-similarity index with no third-party requirements.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.infrastructure.vector_store.base import VectorStoreInterface
from app.infrastructure.vector_store.fallback import LocalJSONVectorStore

logger = logging.getLogger(__name__)


class ChromaVectorStore(VectorStoreInterface):
    """Adapter wrapping the existing ChromaDB persistent client."""

    def __init__(
        self,
        persist_dir: Optional[str] = None,
        collection_name: Optional[str] = None,
    ):
        settings = get_settings()
        self.persist_dir = Path(persist_dir or settings.chroma_db_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name or settings.chroma_collection

        self.client = None
        self.collection = None
        self._fallback: Optional[LocalJSONVectorStore] = None

        try:
            import chromadb
        except ImportError:
            logger.warning(
                "ChromaDB is not installed; using the dependency-free local JSON "
                "vector index at %s. Install 'chromadb' (or configure Qdrant) for "
                "an HNSW-backed index.",
                self.persist_dir,
            )
            self._fallback = LocalJSONVectorStore(
                persist_dir=str(self.persist_dir),
                collection_name=self.collection_name,
            )
            return

        self.client = chromadb.PersistentClient(path=str(self.persist_dir))
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def backend(self) -> str:
        """Name of the active retrieval backend (useful for health/diagnostics)."""
        return LocalJSONVectorStore.__name__ if self._fallback else "ChromaDB"

    def is_healthy(self) -> bool:
        if self._fallback is not None:
            return self._fallback.is_healthy()
        try:
            return self.collection is not None
        except Exception:
            return False

    def upsert_chunks(
        self,
        chunks: List[Dict[str, Any]],
        embeddings: List[List[float]],
    ) -> int:
        if self._fallback is not None:
            return self._fallback.upsert_chunks(chunks, embeddings)

        if len(chunks) != len(embeddings):
            raise ValueError("Each chunk must have exactly one embedding.")
        if not chunks:
            return 0

        ids = [str(c["chunk_id"]) for c in chunks]
        documents = [c["text"] for c in chunks]
        metadatas = [
            {
                "document_id": str(c["document_id"]),
                "filename": str(c.get("filename", "")),
                "page_number": int(c.get("page_number", 1)),
                "page_chunk_index": int(c.get("page_chunk_index", 1)),
                "section": str(c.get("section") or ""),
                "is_table": bool(c.get("is_table", False)),
            }
            for c in chunks
        ]

        batch_size = 500
        for start in range(0, len(ids), batch_size):
            end = start + batch_size
            self.collection.upsert(
                ids=ids[start:end],
                embeddings=embeddings[start:end],
                documents=documents[start:end],
                metadatas=metadatas[start:end],
            )

        return len(ids)

    def search_chunks(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if self._fallback is not None:
            return self._fallback.search_chunks(
                query_embedding, top_k=top_k, filters=filters
            )

        total = self.collection.count()
        if total == 0:
            return []

        where_clause = None
        if filters:
            conditions = []
            if "document_id" in filters and filters["document_id"]:
                conditions.append({"document_id": str(filters["document_id"])})
            if "is_table" in filters and filters["is_table"] is not None:
                conditions.append({"is_table": bool(filters["is_table"])})

            if len(conditions) == 1:
                where_clause = conditions[0]
            elif len(conditions) > 1:
                where_clause = {"$and": conditions}

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, total),
            where=where_clause,
            include=["documents", "metadatas", "distances"],
        )

        matches = []
        if results and results.get("ids") and results["ids"][0]:
            for idx, chunk_id in enumerate(results["ids"][0]):
                matches.append({
                    "chunk_id": chunk_id,
                    "text": results["documents"][0][idx],
                    "metadata": results["metadatas"][0][idx],
                    "distance": float(results["distances"][0][idx]),
                    "score": round(1.0 - float(results["distances"][0][idx]), 4),
                })

        return matches

    def count_chunks(self) -> int:
        if self._fallback is not None:
            return self._fallback.count_chunks()
        return self.collection.count()

    def get_chunks_by_document(self, document_id: str) -> List[Dict[str, Any]]:
        """Retrieve all chunks belonging to a document directly."""
        if self._fallback is not None:
            return self._fallback.get_chunks_by_document(document_id)
        try:
            total = self.collection.count()
            if total == 0:
                return []
            res = self.collection.get(
                where={"document_id": str(document_id)},
                include=["documents", "metadatas"],
            )
            chunks = []
            if res and res.get("ids"):
                for idx, chunk_id in enumerate(res["ids"]):
                    meta = res["metadatas"][idx] if res.get("metadatas") else {}
                    chunks.append({
                        "chunk_id": chunk_id,
                        "text": res["documents"][idx] if res.get("documents") else "",
                        "page_number": meta.get("page_number", 1),
                        "is_table": meta.get("is_table", False),
                        "section": meta.get("section", ""),
                        "metadata": meta,
                    })
            return chunks
        except Exception as e:
            logger.warning("Error fetching chunks by document %s: %s", document_id, e)
            return []

