"""GraphAgent – service dependency graph analysis (qwen2.5:7b)."""
from backend.agents.base_agent import BaseAgent
from backend.agents.prompts import GRAPH_AGENT_PROMPT
from backend.services.model_router import AgentId


class GraphAgent(BaseAgent):
    AGENT_ID: AgentId = "graph"

    @property
    def system_prompt(self) -> str:
        return GRAPH_AGENT_PROMPT
