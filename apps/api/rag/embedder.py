"""Embedding client — OpenAI-compatible.

Works with any provider that exposes an `/embeddings` endpoint in the
OpenAI shape: Zhipu (BigModel), Aliyun DashScope, OpenAI itself, etc.

Default target: Zhipu `embedding-3` (`base_url=https://open.bigmodel.cn/api/paas/v4`).

`embed_query` returns a single vector; `embed_texts` returns a list of vectors,
batched. The client is lazily constructed so importing this module without
`EMBEDDING_API_KEY` set does not crash.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from settings import settings

log = logging.getLogger(__name__)

_client: Any | None = None

_BATCH_SIZE = 32


def _get_client() -> Any:
    global _client
    if _client is not None:
        return _client
    if not settings.EMBEDDING_API_KEY:
        raise RuntimeError(
            "EMBEDDING_API_KEY not configured; cannot use embedder. "
            "Set it in .env or skip RAG (RAG falls back to v1.0 hardcoded mode)."
        )
    from openai import OpenAI

    _client = OpenAI(
        api_key=settings.EMBEDDING_API_KEY,
        base_url=settings.EMBEDDING_BASE_URL,
        timeout=httpx.Timeout(settings.EMBEDDING_TIMEOUT_SECONDS),
    )
    return _client


def _embed_batch(client: Any, texts: list[str]) -> list[list[float]]:
    kwargs: dict[str, Any] = {
        "model": settings.EMBEDDING_MODEL,
        "input": texts,
    }
    # Zhipu / OpenAI both accept `dimensions` on newer models. Aliyun ignores it.
    if settings.EMBEDDING_DIMENSIONS:
        kwargs["dimensions"] = settings.EMBEDDING_DIMENSIONS
    resp = client.embeddings.create(**kwargs)
    return [item.embedding for item in resp.data]


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    client = _get_client()
    out: list[list[float]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        out.extend(_embed_batch(client, batch))
    return out


def embed_query(text: str) -> list[float]:
    vectors = embed_texts([text])
    if not vectors:
        raise RuntimeError("embedder returned no vector for query")
    return vectors[0]
