"""
SSE streaming helpers for FastAPI.

Converts async generators into properly formatted Server-Sent Events streams
that are compatible with the EventSource API and the existing Next.js
`app/api/chat/stream` SSE consumer format.
"""
from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse


def sse_event(event: str, data: Any) -> str:
    """
    Format a single SSE event frame.

    Output format::

        event: <event>\\n
        data: <json>\\n
        \\n
    """
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def sse_error(message: str) -> str:
    return sse_event("error", {"message": message, "at": int(time.time() * 1000)})


def sse_done() -> str:
    return sse_event("done", {"at": int(time.time() * 1000)})


async def make_sse_stream(
    token_gen: AsyncIterator[str],
    agent_id: str = "orchestrator",
    step_name: str = "inference",
) -> AsyncIterator[str]:
    """
    Wrap a raw text-chunk generator as SSE events.

    Emits:
      - ``step-start``   once at the beginning
      - ``answer-chunk`` for each text token
      - ``step-end``     once at the end
      - ``done``         final sentinel
    """
    yield sse_event("step-start", {"name": step_name, "agent": agent_id, "at": int(time.time() * 1000)})
    try:
        async for chunk in token_gen:
            if chunk:
                yield sse_event("answer-chunk", {"text": chunk})
    except Exception as exc:
        yield sse_error(str(exc))
        return
    yield sse_event("step-end", {"name": step_name, "agent": agent_id, "at": int(time.time() * 1000)})
    yield sse_done()


def streaming_response(
    token_gen: AsyncIterator[str],
    agent_id: str = "orchestrator",
    step_name: str = "inference",
) -> StreamingResponse:
    """
    Convenience wrapper that returns a FastAPI StreamingResponse for SSE.
    """
    return StreamingResponse(
        make_sse_stream(token_gen, agent_id=agent_id, step_name=step_name),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def client_disconnected(request: Request) -> bool:
    """Returns True if the HTTP client has already disconnected."""
    return await request.is_disconnected()
