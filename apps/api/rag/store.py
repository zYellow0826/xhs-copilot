"""Supabase pgvector store for methodology chunks.

CRUD over the `methodology_chunks` table + similarity search via the
`search_methodology_chunks` RPC defined in
`supabase/migrations/0001_methodology_chunks.sql`.

All operations are no-ops / return None when Supabase isn't configured —
upstream code is expected to check `settings.rag_enabled` before calling.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from db import get_client
from rag.chunker import Chunk
from settings import settings

log = logging.getLogger(__name__)

TABLE = "methodology_chunks"
RPC_SEARCH = "search_methodology_chunks"


@dataclass
class RetrievedChunk:
    id: int
    category: str
    section: str
    content: str
    similarity: float

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "section": self.section,
            "content": self.content,
            "similarity": round(self.similarity, 4),
        }


def delete_all() -> int:
    """Wipe the table — used by the ingestion script before reseeding.

    Returns number of rows reported deleted (best-effort; some Supabase
    versions return [] regardless).
    """
    client = get_client()
    if client is None:
        return 0
    # supabase-py requires a filter for delete; use id >= 0 to match everything.
    resp = client.table(TABLE).delete().gte("id", 0).execute()
    data = getattr(resp, "data", []) or []
    return len(data)


def insert_chunks(chunks: list[Chunk], embeddings: list[list[float]]) -> int:
    """Bulk insert chunks with their embeddings."""
    if len(chunks) != len(embeddings):
        raise ValueError(
            f"chunks ({len(chunks)}) and embeddings ({len(embeddings)}) length mismatch"
        )
    client = get_client()
    if client is None:
        raise RuntimeError("Supabase client not available; cannot insert chunks")
    rows = [
        {
            "category": c.category,
            "section": c.section,
            "content": c.content,
            "embedding": emb,
            "metadata": {},
        }
        for c, emb in zip(chunks, embeddings, strict=True)
    ]
    # supabase-py inserts up to ~1000 rows per call; methodology chunks are small.
    resp = client.table(TABLE).insert(rows).execute()
    data = getattr(resp, "data", []) or []
    return len(data)


def search(
    query_embedding: list[float],
    top_k: int | None = None,
    min_similarity: float | None = None,
) -> list[RetrievedChunk]:
    """Cosine-similarity search via Supabase RPC. Returns [] on any failure."""
    client = get_client()
    if client is None:
        return []
    params = {
        "query_embedding": query_embedding,
        "match_count": top_k if top_k is not None else settings.RAG_TOP_K,
        "min_similarity": (
            min_similarity if min_similarity is not None else settings.RAG_MIN_SIMILARITY
        ),
    }
    try:
        resp = client.rpc(RPC_SEARCH, params).execute()
    except Exception as exc:
        log.warning("methodology_chunks RPC search failed: %s", exc)
        return []
    rows = getattr(resp, "data", []) or []
    return [
        RetrievedChunk(
            id=int(r["id"]),
            category=r["category"],
            section=r["section"],
            content=r["content"],
            similarity=float(r["similarity"]),
        )
        for r in rows
    ]


def count() -> int:
    """Return the number of methodology chunks currently in the store."""
    client = get_client()
    if client is None:
        return 0
    try:
        resp = client.table(TABLE).select("id", count="exact").limit(1).execute()
        return int(getattr(resp, "count", 0) or 0)
    except Exception as exc:
        log.warning("methodology_chunks count failed: %s", exc)
        return 0
