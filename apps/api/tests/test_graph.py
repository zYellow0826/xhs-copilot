"""Smoke tests for the LangGraph creation workflow.

We don't hit the real DeepSeek API — `graphs.creation._call_model` is monkey-
patched to return a canned `GenerationOutput`, which lets us exercise the
graph wiring, state propagation, and astream_events plumbing in isolation.
"""

import pytest

from graphs import creation
from schemas import GenerationInput, GenerationOutput, XhsNote


def _canned_output() -> GenerationOutput:
    return GenerationOutput(
        notes=[
            XhsNote(
                title="3 个小习惯，让指甲半年不脱",
                body="姐妹们，最近总有人问我..." + "正文内容" * 30,
                tags=["美甲", "夏季美甲", "上海美甲推荐"],
                cover_copy="半年不脱的秘密",
            )
        ],
        reasoning="围绕单一痛点（脱甲）切入，标题用数字钩子。",
    )


def test_build_graph_structure():
    g = creation.build_graph()
    assert g is not None
    # compiled graph exposes the node names
    nodes = set(g.get_graph().nodes)
    assert "generate" in nodes
    assert "retrieve" in nodes


def test_generate_node_happy_path(monkeypatch):
    canned = _canned_output()
    monkeypatch.setattr(creation, "_call_model", lambda messages: canned)

    state = {
        "input": GenerationInput(
            shop_type="美甲店",
            product_info="夏季果冻甲",
            target_audience="20-30 岁女性",
        ),
        "output": None,
    }
    result = creation.generate_node(state)
    assert result["output"] is canned


def test_generate_node_retries_on_validation_error(monkeypatch):
    from pydantic import ValidationError

    calls = {"n": 0}
    canned = _canned_output()

    def fake_call(messages):
        calls["n"] += 1
        if calls["n"] == 1:
            try:
                XhsNote(title="x" * 30, body="b", tags=["a"], cover_copy="c")
            except ValidationError as exc:
                raise exc
        return canned

    monkeypatch.setattr(creation, "_call_model", fake_call)

    state = {
        "input": GenerationInput(
            shop_type="x", product_info="y", target_audience="z"
        ),
        "output": None,
    }
    result = creation.generate_node(state)
    assert calls["n"] == 2
    assert result["output"] is canned


def test_generate_node_raises_after_max_retries(monkeypatch):
    from pydantic import ValidationError

    def always_fail(messages):
        try:
            XhsNote(title="x" * 30, body="b", tags=["a"], cover_copy="c")
        except ValidationError as exc:
            raise exc
        raise AssertionError("unreachable")

    monkeypatch.setattr(creation, "_call_model", always_fail)

    state = {
        "input": GenerationInput(
            shop_type="x", product_info="y", target_audience="z"
        ),
        "output": None,
    }
    with pytest.raises(creation.GenerationError):
        creation.generate_node(state)
