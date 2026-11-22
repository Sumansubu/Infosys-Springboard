"""Dependency-free persistent vector index.

Used when the optional ``chromadb`` package is not installed. ChromaDB is a
large native dependency that is not available on every Python version or
air-gapped/CI machine. The rest of the system only needs deterministic local
similarity search over a few thousand chunks, so this adapter stores chunks and
their embeddings in a single JSON file per collection and ranks them with
cosine similarity.

It is a drop-in implementation of :class:`VectorStoreInterface` and is selected
automatically by ``ChromaVectorStore`` when ``import chromadb`` fails. For
production-sized corpora, install ChromaDB (or use Qdrant) so the HNSW index is
used instead.
"""

import json
import logging
import math
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.infrastructure.vector_store.base import VectorStoreInterface

logger = logging.getLogger(__name__)


def _safe_filename(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in name) or "chunks"


class LocalJSONVectorStore(VectorStoreInterface):
    """File-backed cosine-similarity index with Chroma-compatible semantics."""

    def __init__(self, persist_dir: str, collection_name: str):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self._path = self.persist_dir / f"{_safe_filename(collection_name)}.json"
        self._lock = threading.Lock()
        self._records: Dict[str, Dict[str, Any]] = {}
        self._load()

    # ------------------------------------------------------------------ storage
    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            records = payload.get("records", {})
            if isinstance(records, dict):
                self._records = records
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read local vector index %s: %s", self._path, exc)

    def _persist(self) -> None:
        payload = {"collection": self.collection_name, "records": self._records}
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            os.replace(tmp_path, self._path)
        except OSError as exc:
            logger.warning("Could not persist local vector index %s: %s", self._path, exc)

    # ----------------------------------------------------------------- interface
    def is_healthy(self) -> bool:
        return self.persist_dir.exists()

    def upsert_chunks(
        self,
        chunks: List[Dict[str, Any]],
        embeddings: List[List[float]],
    ) -> int:
        if len(chunks) != len(embeddings):
            raise ValueError("Each chunk must have exactly one embedding.")
        if not chunks:
            return 0

        with self._lock:
            for chunk, embedding in zip(chunks, embeddings):
                chunk_id = str(chunk["chunk_id"])
                self._records[chunk_id] = {
                    "text": chunk["text"],
                    "embedding": [float(v) for v in embedding],
                    "metadata": {
                        "document_id": str(chunk["document_id"]),
                        "filename": str(chunk.get("filename", "")),
                        "page_number": int(chunk.get("page_number", 1)),
                        "page_chunk_index": int(chunk.get("page_chunk_index", 1)),
                        "section": str(chunk.get("section") or ""),
                        "is_table": bool(chunk.get("is_table", False)),
                    },
                }
            self._persist()
        return len(chunks)

    def search_chunks(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if not self._records:
            return []

        where = self._matches(filters)
        scored = []
        for chunk_id, record in self._records.items():
            if not where(record["metadata"]):
                continue
            similarity = self._cosine(query_embedding, record["embedding"])
            distance = max(0.0, min(1.0, 1.0 - similarity))
            scored.append(
                {
                    "chunk_id": chunk_id,
                    "text": record["text"],
                    "metadata": record["metadata"],
                    "distance": distance,
                    "score": round(similarity, 4),
                }
            )

        scored.sort(key=lambda item: item["distance"])
        return scored[: max(0, top_k)]

    def count_chunks(self) -> int:
        return len(self._records)

    def get_chunks_by_document(self, document_id: str) -> List[Dict[str, Any]]:
        matches = []
        for chunk_id, record in self._records.items():
            metadata = record["metadata"]
            if metadata.get("document_id") != str(document_id):
                continue
            matches.append(
                {
                    "chunk_id": chunk_id,
                    "text": record["text"],
                    "page_number": metadata.get("page_number", 1),
                    "is_table": metadata.get("is_table", False),
                    "section": metadata.get("section", ""),
                    "metadata": metadata,
                }
            )
        matches.sort(key=lambda item: (item["page_number"], item["metadata"].get("page_chunk_index", 1)))
        return matches

    # -------------------------------------------------------------------- helpers
    @staticmethod
    def _matches(filters: Optional[Dict[str, Any]]):
        if not filters:
            return lambda metadata: True

        document_id = filters.get("document_id")
        is_table = filters.get("is_table")

        def predicate(metadata: Dict[str, Any]) -> bool:
            if document_id and metadata.get("document_id") != str(document_id):
                return False
            if is_table is not None and bool(metadata.get("is_table")) is not bool(is_table):
                return False
            return True

        return predicate

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        if not a or not b:
            return 0.0
        length = min(len(a), len(b))
        dot = sum(float(a[i]) * float(b[i]) for i in range(length))
        norm_a = math.sqrt(sum(float(a[i]) ** 2 for i in range(length)))
        norm_b = math.sqrt(sum(float(b[i]) ** 2 for i in range(length)))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)
