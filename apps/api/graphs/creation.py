"""Creation workflow — v1.1.

LangGraph:

    START → retrieve → generate → END

`retrieve` (new in v1.1): embeds the user input and pulls top-k methodology
chunks from pgvector. No-op when RAG is disabled — the system prompt then
contains the full hardcoded methodology (v1.0 behaviour).

`generate` calls DeepSeek with a forced `submit_notes` tool call and validates
the structured payload through `GenerationOutput`. If the model returns
malformed JSON or schema-invalid content, we retry up to
`settings.DEEPSEEK_RETRY_MAX` times with an injected correction message.
"""

from __future__ import annotations

import json
import logging
from typing import TypedDict

import httpx
from langgraph.graph import END, START, StateGraph
from openai import APIError, APITimeoutError, OpenAI, RateLimitError
from pydantic import ValidationError

from prompts.system import SYSTEM_PROMPT_NO_RAG, SYSTEM_PROMPT_RAG, build_user_message
from schemas import GenerationInput, GenerationOutput
from settings import settings

log = logging.getLogger(__name__)

client = OpenAI(
    api_key=settings.DEEPSEEK_API_KEY,
    base_url=settings.DEEPSEEK_BASE_URL,
    timeout=httpx.Timeout(settings.DEEPSEEK_TIMEOUT_SECONDS),
)


class CreationState(TypedDict, total=False):
    input: GenerationInput
    retrieved_chunks: list[dict] | None
    output: GenerationOutput | None


SUBMIT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_notes",
        "description": "提交生成的小红书笔记",
        "parameters": GenerationOutput.model_json_schema(),
    },
}


class GenerationError(RuntimeError):
    """Raised when DeepSeek cannot produce a valid GenerationOutput after retries."""


def _extract_tool_arguments(response) -> str:
    """Pull the JSON-string arguments off the first tool call, or raise."""
    choices = response.choices or []
    if not choices:
        raise GenerationError("model returned no choices")
    msg = choices[0].message
    tool_calls = getattr(msg, "tool_calls", None) or []
    if not tool_calls:
        raise GenerationError("model returned no tool_calls; refused to submit_notes")
    return tool_calls[0].function.arguments


def _call_model(messages: list[dict]) -> GenerationOutput:
    response = client.chat.completions.create(
        model=settings.DEEPSEEK_MODEL_CHAT,
        max_tokens=settings.DEEPSEEK_MAX_TOKENS,
        messages=messages,
        tools=[SUBMIT_TOOL],
        tool_choice={"type": "function", "function": {"name": "submit_notes"}},
    )

    usage = getattr(response, "usage", None)
    if usage is not None:
        cache_hit = getattr(usage, "prompt_cache_hit_tokens", 0)
        log.info(
            "deepseek usage: cache_hit=%s prompt_tokens=%s completion_tokens=%s",
            cache_hit,
            getattr(usage, "prompt_tokens", "?"),
            getattr(usage, "completion_tokens", "?"),
        )

    raw_args = _extract_tool_arguments(response)
    return GenerationOutput.model_validate_json(raw_args)


def _build_retrieval_query(payload: GenerationInput) -> str:
    parts = [
        payload.shop_type,
        payload.style_preference,
        payload.target_audience,
        payload.product_info,
    ]
    if payload.extra_context:
        parts.append(payload.extra_context)
    return " ".join(p for p in parts if p)


def retrieve_node(state: CreationState) -> CreationState:
    """Embed input → search pgvector → stash top-k chunks in state.

    When RAG is disabled or anything fails, return state with
    retrieved_chunks=None so the prompt builder falls back to the full
    hardcoded methodology.
    """
    if not settings.rag_enabled:
        return {**state, "retrieved_chunks": None}

    try:
        # Lazy imports — keep the graph importable even if the packages
        # aren't installed in fallback environments.
        from rag import embedder, store
    except ImportError as exc:
        log.warning("RAG modules unavailable, falling back: %s", exc)
        return {**state, "retrieved_chunks": None}

    payload = state["input"]
    query = _build_retrieval_query(payload)
    try:
        query_vec = embedder.embed_query(query)
    except Exception as exc:
        log.warning("embedding failed, falling back to hardcoded methodology: %s", exc)
        return {**state, "retrieved_chunks": None}

    hits = store.search(query_vec)
    log.info("RAG retrieved %d chunks for query=%r", len(hits), query[:80])
    chunks = [h.to_payload() for h in hits]
    return {**state, "retrieved_chunks": chunks}


def generate_node(state: CreationState) -> CreationState:
    retrieved = state.get("retrieved_chunks")
    system_prompt = SYSTEM_PROMPT_RAG if retrieved else SYSTEM_PROMPT_NO_RAG
    user_message = build_user_message(state["input"], retrieved)

    base_messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    messages = list(base_messages)

    last_error: Exception | None = None
    for attempt in range(settings.DEEPSEEK_RETRY_MAX + 1):
        try:
            output = _call_model(messages)
            return {**state, "output": output}
        except ValidationError as exc:
            last_error = exc
            log.warning("attempt %s: schema validation failed: %s", attempt + 1, exc)
            messages = list(base_messages) + [
                {
                    "role": "user",
                    "content": (
                        "你上一次的输出未通过 schema 校验，错误："
                        f"{exc.errors()[:3]}。请严格按 submit_notes 工具的参数 schema 重新生成，"
                        "确保字段齐全、类型正确、约束（长度/数量）全部满足。"
                    ),
                }
            ]
        except json.JSONDecodeError as exc:
            last_error = exc
            log.warning("attempt %s: tool args were not valid JSON: %s", attempt + 1, exc)
            messages = list(base_messages) + [
                {
                    "role": "user",
                    "content": "你上一次工具调用的 arguments 不是合法 JSON。请重新生成，确保是严格的 JSON。",
                }
            ]
        except (APITimeoutError, RateLimitError) as exc:
            last_error = exc
            log.warning("attempt %s: transient API error: %s", attempt + 1, exc)
        except APIError as exc:
            log.error("non-retryable DeepSeek API error: %s", exc)
            raise GenerationError(f"DeepSeek API error: {exc}") from exc

    raise GenerationError(
        f"failed to produce valid GenerationOutput after "
        f"{settings.DEEPSEEK_RETRY_MAX + 1} attempts: {last_error}"
    )


def build_graph():
    g = StateGraph(CreationState)
    g.add_node("retrieve", retrieve_node)
    g.add_node("generate", generate_node)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "generate")
    g.add_edge("generate", END)
    return g.compile()
