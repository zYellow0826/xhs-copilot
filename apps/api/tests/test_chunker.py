"""Tests for the methodology markdown chunker."""

from pathlib import Path

from rag.chunker import (
    MANDATORY_CATEGORIES,
    extract_mandatory,
    parse_methodology,
)


METHODOLOGY_PATH = Path(__file__).resolve().parent.parent / "prompts" / "methodology.md"


def test_chunker_produces_non_empty_chunks():
    chunks = parse_methodology(METHODOLOGY_PATH.read_text(encoding="utf-8"))
    assert chunks, "expected at least one chunk parsed from methodology.md"
    for c in chunks:
        assert c.category
        assert c.section
        assert c.content.strip()


def test_chunker_skips_mandatory_categories():
    chunks = parse_methodology(METHODOLOGY_PATH.read_text(encoding="utf-8"))
    categories = {c.category for c in chunks}
    assert not (categories & MANDATORY_CATEGORIES), (
        f"mandatory categories {MANDATORY_CATEGORIES} must not leak into chunks; "
        f"got: {categories & MANDATORY_CATEGORIES}"
    )


def test_chunker_finds_at_least_each_non_mandatory_category():
    chunks = parse_methodology(METHODOLOGY_PATH.read_text(encoding="utf-8"))
    expected = {"一、底层逻辑", "三、套路", "四、反面案例", "五、特殊场景"}
    found = {c.category for c in chunks}
    missing = {e for e in expected if not any(e in f for f in found)}
    assert not missing, f"missing expected categories: {missing}"


def test_chunk_for_embedding_includes_heading_signal():
    text = "## 三、套路\n### 1. 选题方法论\n这里是套路内容。"
    chunks = parse_methodology(text)
    assert chunks
    rendered = chunks[0].for_embedding()
    assert "三、套路" in rendered
    assert "选题方法论" in rendered
    assert "这里是套路内容" in rendered


def test_extract_mandatory_contains_hard_rules_and_checklist():
    text = extract_mandatory(METHODOLOGY_PATH.read_text(encoding="utf-8"))
    assert "硬规则" in text
    assert "自检清单" in text
    # And does NOT contain the retrievable bits
    assert "反面 A" not in text
