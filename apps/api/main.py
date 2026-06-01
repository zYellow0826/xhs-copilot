"""FastAPI entrypoint.

`POST /generate` streams LangGraph events as SSE. Any internal error is
serialised into a final `event: error` frame instead of crashing the stream,
so the browser can render a useful message even when SSE has already started.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from db import save_generation
from graphs.creation import GenerationError, build_graph
from schemas import GenerationInput
from settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("xhs-copilot")

app = FastAPI(title="xhs-copilot api", version="1.1.0")

_origins = [o.strip() for o in settings.CORS_ALLOW_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

graph = build_graph()


def _json_default(obj: Any) -> Any:
    # Pydantic v2 models must be dumped to dict, not stringified — otherwise
    # the SSE event's `data.output.output` arrives at the browser as a `repr()`
    # string and the frontend crashes on `output.notes.map`.
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    return str(obj)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=_json_default, ensure_ascii=False)}\n\n"


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "version": app.version,
        "supabase": settings.supabase_enabled,
        "rag": settings.rag_enabled,
    }


@app.post("/generate")
async def generate(payload: GenerationInput) -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        final_output = None
        try:
            async for event in graph.astream_events(
                {"input": payload, "retrieved_chunks": None, "output": None}, version="v2"
            ):
                yield _sse(event)
                if (
                    event.get("event") == "on_chain_end"
                    and event.get("name") == "LangGraph"
                ):
                    data = event.get("data") or {}
                    state = data.get("output") or {}
                    final_output = state.get("output")
        except GenerationError as exc:
            log.exception("generation failed")
            yield _sse({"event": "error", "name": "GenerationError", "message": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 — last-resort SSE error frame
            log.exception("unexpected error in /generate stream")
            yield _sse({"event": "error", "name": exc.__class__.__name__, "message": str(exc)})
            return

        if final_output:
            await save_generation(
                payload, final_output, model=settings.DEEPSEEK_MODEL_CHAT
            )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "cache-control": "no-cache, no-transform",
            "x-accel-buffering": "no",
        },
    )
