"""
POST /chat/invoke    – non-streaming orchestrator chat (JSON response)
POST /chat/stream    – SSE streaming orchestrator chat
POST /chat/pipeline  – full multi-agent pipeline (orchestrator → sub-agents → synthesis)
"""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Message type: {"role": "system"|"user"|"assistant", "content": str}
Message = dict
from backend.services.streaming import make_sse_stream, sse_event, sse_done

router = APIRouter(prefix="/chat", tags=["chat"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    messages: list[Message] = Field(..., description="Chat history")
    context: str = Field(default="", description="Additional KG / dataset context")
    agent_id: str = Field(
        default="orchestrator",
        description="Which agent to route the request to",
    )


class ChatResponse(BaseModel):
    agent_id: str
    model: str
    content: str
    at: int


class PipelineRequest(BaseModel):
    question: str = Field(..., description="Investigation question")
    context: str = Field(default="", description="Additional context to inject")


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/invoke", response_model=ChatResponse)
async def chat_invoke(body: ChatRequest, request: Request):
    """
    Non-streaming chat via the specified agent (default: orchestrator).
    Returns a JSON object with the full response.
    """
    registry: dict = request.app.state.agent_registry
    if body.agent_id not in registry:
        raise HTTPException(status_code=404, detail=f"Unknown agent '{body.agent_id}'")

    agent = registry[body.agent_id]
    try:
        content = await agent.invoke(body.messages, context=body.context)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return ChatResponse(
        agent_id=body.agent_id,
        model=agent.config.model,
        content=content,
        at=int(time.time() * 1000),
    )


@router.post("/stream")
async def chat_stream(body: ChatRequest, request: Request):
    """
    Streaming chat via the specified agent.

    Emits SSE events compatible with the existing Next.js `InvestigationChat` component:
      step-start → answer-chunk (N) → step-end → done
    """
    registry: dict = request.app.state.agent_registry
    if body.agent_id not in registry:
        raise HTTPException(status_code=404, detail=f"Unknown agent '{body.agent_id}'")

    agent = registry[body.agent_id]

    async def token_gen():
        async for chunk in agent.stream(body.messages, context=body.context):
            yield chunk

    return StreamingResponse(
        make_sse_stream(token_gen(), agent_id=body.agent_id, step_name="inference"),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/pipeline")
async def chat_pipeline(body: PipelineRequest, request: Request):
    """
    Multi-agent investigation pipeline (streaming SSE).

    Workflow:
      1. Graph Agent  – analyze service dependencies
      2. Incident Agent – timeline & root-cause
      3. Risk Agent    – deployment risk
      4. Orchestrator  – synthesize into final answer
    
    Each agent step emits separate step-start / answer-chunk / step-end events
    so the frontend AgentActivity component can animate each stage.
    """
    registry: dict = request.app.state.agent_registry
    question = body.question
    context = body.context

    async def pipeline_gen():
        full_responses: dict[str, str] = {}

        pipeline_steps = [
            ("graph",       "graph-analysis",    "Analyzing service dependencies…"),
            ("incident",    "incident-analysis",  "Reconstructing incident timeline…"),
            ("risk",        "risk-assessment",    "Assessing deployment risk…"),
        ]

        # Run graph, incident, and risk agents sequentially, streaming each
        for agent_id, step_name, status_msg in pipeline_steps:
            agent = registry.get(agent_id)
            if not agent:
                continue

            yield sse_event("status", {"message": status_msg, "agent": agent_id})
            yield sse_event("step-start", {"name": step_name, "agent": agent_id, "at": int(time.time() * 1000)})

            chunks: list[str] = []
            user_messages: list[Message] = [{"role": "user", "content": question}]
            async for chunk in agent.stream(user_messages, context=context):
                chunks.append(chunk)
                yield sse_event("answer-chunk", {"text": chunk, "agent": agent_id})

            full_responses[agent_id] = "".join(chunks)
            yield sse_event("step-end", {"name": step_name, "agent": agent_id, "at": int(time.time() * 1000)})

        # Orchestrator synthesis
        orchestrator = registry.get("orchestrator")
        if orchestrator:
            sub_context = "\n\n".join(
                f"[{aid.upper()} AGENT FINDINGS]\n{text}"
                for aid, text in full_responses.items()
                if text
            )
            combined_context = f"{context}\n\n{sub_context}".strip() if context else sub_context

            yield sse_event("status", {"message": "Synthesizing findings…", "agent": "orchestrator"})
            yield sse_event("step-start", {"name": "synthesis", "agent": "orchestrator", "at": int(time.time() * 1000)})

            orchestrator_messages: list[Message] = [{"role": "user", "content": question}]
            async for chunk in orchestrator.stream(orchestrator_messages, context=combined_context):
                yield sse_event("answer-chunk", {"text": chunk, "agent": "orchestrator"})

            yield sse_event("step-end", {"name": "synthesis", "agent": "orchestrator", "at": int(time.time() * 1000)})

        yield sse_done()

    return StreamingResponse(
        pipeline_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
