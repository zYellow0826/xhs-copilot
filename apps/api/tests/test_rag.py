"""Tests for the retrieve node and RAG fallback behaviour."""

from graphs import creation
from schemas import GenerationInput


def _input() -> GenerationInput:
    return GenerationInput(
        shop_type="美甲店",
        product_info="夏季果冻甲",
        target_audience="20-30 岁女性",
    )


def test_retrieve_node_returns_none_when_rag_disabled(monkeypatch):
    # tests/conftest sets only DEEPSEEK_API_KEY, so rag_enabled should be False.
    from settings import settings

    assert settings.rag_enabled is False
    state = {"input": _input(), "retrieved_chunks": None, "output": None}
    result = creation.retrieve_node(state)
    assert result["retrieved_chunks"] is None


def test_retrieve_node_falls_back_on_embedder_failure(monkeypatch):
    """If RAG is on paper enabled but the embedder throws, we should still
    proceed without retrieved chunks rather than crashing."""
    from settings import settings

    monkeypatch.setattr(settings, "SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_KEY", "fake-key")
    monkeypatch.setattr(settings, "EMBEDDING_API_KEY", "fake-embedding-key")
    assert settings.rag_enabled is True

    from rag import embedder

    def boom(_text):
        raise RuntimeError("embedder offline")

    monkeypatch.setattr(embedder, "embed_query", boom)

    state = {"input": _input(), "retrieved_chunks": None, "output": None}
    result = creation.retrieve_node(state)
    assert result["retrieved_chunks"] is None


def test_retrieve_node_passes_chunks_through(monkeypatch):
    from settings import settings

    monkeypatch.setattr(settings, "SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_KEY", "fake-key")
    monkeypatch.setattr(settings, "EMBEDDING_API_KEY", "fake-embedding-key")

    from rag import embedder, store

    monkeypatch.setattr(embedder, "embed_query", lambda _t: [0.0] * 8)
    monkeypatch.setattr(
        store,
        "search",
        lambda *a, **kw: [
            store.RetrievedChunk(
                id=1,
                category="三、套路",
                section="1. 选题方法论",
                content="痛点 + 反差是高命中模板",
                similarity=0.91,
            )
        ],
    )

    state = {"input": _input(), "retrieved_chunks": None, "output": None}
    result = creation.retrieve_node(state)
    chunks = result["retrieved_chunks"]
    assert isinstance(chunks, list)
    assert len(chunks) == 1
    assert chunks[0]["category"] == "三、套路"
    assert chunks[0]["section"] == "1. 选题方法论"
    assert chunks[0]["similarity"] == 0.91


def test_build_user_message_injects_chunks():
    from prompts.system import build_user_message

    payload = _input()
    msg_with_rag = build_user_message(
        payload,
        [
            {
                "category": "三、套路",
                "section": "1. 选题方法论",
                "content": "用痛点钩子",
                "similarity": 0.9,
            }
        ],
    )
    assert "套路" in msg_with_rag
    assert "用痛点钩子" in msg_with_rag
    assert "美甲店" in msg_with_rag

    msg_no_rag = build_user_message(payload, None)
    assert "用痛点钩子" not in msg_no_rag
    assert "美甲店" in msg_no_rag


def test_system_prompt_contains_hard_rules_in_both_modes():
    from prompts.system import SYSTEM_PROMPT_NO_RAG, SYSTEM_PROMPT_RAG

    for prompt in (SYSTEM_PROMPT_NO_RAG, SYSTEM_PROMPT_RAG):
        assert "硬规则" in prompt
        assert "submit_notes" in prompt
    # RAG version is strictly shorter — the retrievable sections are excised.
    assert len(SYSTEM_PROMPT_RAG) < len(SYSTEM_PROMPT_NO_RAG)
    # And RAG version must NOT contain the retrievable sections that should
    # come via RAG (the chunker drops 反面 A under 反面案例)
    assert "反面 A" not in SYSTEM_PROMPT_RAG
    assert "反面 A" in SYSTEM_PROMPT_NO_RAG
