"""
POST /agents/{agent_id}/invoke   – non-streaming single-agent inference
POST /agents/{agent_id}/stream   – SSE streaming single-agent inference
GET  /agents                     – list all registered agents
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Message type: {"role": "system"|"user"|"assistant", "content": str}
Message = dict
from backend.services.model_router import VALID_AGENTS, AgentId
from backend.services.streaming import make_sse_stream

router = APIRouter(prefix="/agents", tags=["agents"])


# ── Request / response schemas ────────────────────────────────────────────────

class AgentRequest(BaseModel):
    messages: list[Message] = Field(..., description="Chat history in OpenAI format")
    context: str = Field(default="", description="Extra context injected above the last user message")


class AgentInvokeResponse(BaseModel):
    agent_id: str
    model: str
    content: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_agent(request: Request, agent_id: str):
    registry: dict = request.app.state.agent_registry
    if agent_id not in registry:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown agent '{agent_id}'. Valid agents: {list(registry)}",
        )
    return registry[agent_id]


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
async def list_agents(request: Request):
    """List all registered agent IDs and their model assignments."""
    router_obj = request.app.state.model_router
    return {
        "agents": [
            {
                "agent_id": cfg.agent_id,
                "model": cfg.model,
                "description": cfg.description,
                "tags": cfg.tags,
            }
            for cfg in router_obj.all_configs()
            if cfg.agent_id != "embedding"
        ]
    }


@router.post("/{agent_id}/invoke", response_model=AgentInvokeResponse)
async def invoke_agent(agent_id: str, body: AgentRequest, request: Request):
    """
    Run a single non-streaming inference with the specified agent.
    """
    agent = _get_agent(request, agent_id)
    try:
        content = await agent.invoke(body.messages, context=body.context)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return AgentInvokeResponse(
        agent_id=agent_id,
        model=agent.config.model,
        content=content,
    )


@router.post("/{agent_id}/stream")
async def stream_agent(agent_id: str, body: AgentRequest, request: Request):
    """
    Stream tokens from the specified agent as Server-Sent Events.

    SSE event types (compatible with the existing Next.js consumer):
      - step-start  { name, agent, at }
      - answer-chunk { text }
      - step-end    { name, agent, at }
      - done        { at }
      - error       { message }
    """
    agent = _get_agent(request, agent_id)

    async def token_gen():
        async for chunk in agent.stream(body.messages, context=body.context):
            yield chunk

    return StreamingResponse(
        make_sse_stream(token_gen(), agent_id=agent_id, step_name="inference"),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
