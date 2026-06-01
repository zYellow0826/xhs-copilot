"""System prompt builder.

Splits methodology.md into:
  - MANDATORY: hard rules + self-check checklist. Always present in system
    prompt, so DeepSeek's Context Caching keeps the prefix stable.
  - Everything else (底层逻辑 / 套路 / 反面案例 / 特殊场景) — retrieved per
    request when RAG is enabled, otherwise baked into system as v1.0
    fallback (also stable prefix).

The user message carries retrieved chunks + the actual user input — this is
the per-request varying part, kept out of the cacheable system prefix.
"""

from __future__ import annotations

from pathlib import Path

from rag.chunker import extract_mandatory
from schemas import GenerationInput

_METHODOLOGY_PATH = Path(__file__).parent / "methodology.md"
_METHODOLOGY_RAW = _METHODOLOGY_PATH.read_text(encoding="utf-8")

MANDATORY_METHODOLOGY = extract_mandatory(_METHODOLOGY_RAW)

_OUTPUT_RULES = """# 输出要求

- 每篇笔记必须遵守上述方法论的全部硬规则
- 标题严格 <= 20 字，且必须包含至少一个钩子（数字/反差/痛点）
- 正文 200-500 字，符合小红书的口语化、短段落、emoji 适度风格
- 标签 3-10 个，混合大词 + 长尾词
- 必须调用 submit_notes 工具返回结构化结果"""


def build_system_prompt(*, rag_enabled: bool) -> str:
    """Stable per-deployment, NOT per-request. Safe to cache.

    When RAG is on, only mandatory sections live in system; the rest comes
    from retrieval via user message. When RAG is off, the entire methodology
    is in system (v1.0 behaviour).
    """
    if rag_enabled:
        body = MANDATORY_METHODOLOGY
    else:
        body = _METHODOLOGY_RAW
    return (
        "你是一个资深小红书运营顾问，专门为单人店铺老板生成爆款笔记。\n\n"
        "# 你必须遵守的方法论\n\n"
        f"{body}\n\n"
        f"{_OUTPUT_RULES}\n"
    )


# Eagerly built for the common (RAG on/off) cases. Pick at call time.
SYSTEM_PROMPT_RAG = build_system_prompt(rag_enabled=True)
SYSTEM_PROMPT_NO_RAG = build_system_prompt(rag_enabled=False)

# Back-compat export — older tests import SYSTEM_PROMPT directly.
SYSTEM_PROMPT = SYSTEM_PROMPT_NO_RAG


def build_user_message(
    payload: GenerationInput,
    retrieved_chunks: list[dict] | None,
) -> str:
    """Compose the per-request user message: retrieved context + structured input."""
    sections: list[str] = []
    if retrieved_chunks:
        sections.append("# 与本次需求相关的方法论补充（来自检索）")
        sections.append(_format_chunks(retrieved_chunks))
        sections.append(
            "上述补充用于参考具体套路与反面案例；"
            "硬规则与自检清单已在系统提示中给出，所有硬规则**必须**优先满足。"
        )
    sections.append("# 本次生成需求")
    sections.append(payload.model_dump_json(indent=2))
    sections.append("请调用 submit_notes 工具返回结构化结果。")
    return "\n\n".join(sections)


def _format_chunks(chunks: list[dict]) -> str:
    lines: list[str] = []
    for i, c in enumerate(chunks, start=1):
        category = c.get("category", "")
        section = c.get("section", "")
        content = c.get("content", "").strip()
        lines.append(f"## {i}. [{category} / {section}]")
        lines.append(content)
    return "\n\n".join(lines)
