"""OrchestratorAgent – coordinates multi-agent investigation workflows (llama3.1:8b)."""
from backend.agents.base_agent import BaseAgent
from backend.agents.prompts import ORCHESTRATOR_PROMPT
from backend.services.model_router import AgentId


class OrchestratorAgent(BaseAgent):
    AGENT_ID: AgentId = "orchestrator"

    @property
    def system_prompt(self) -> str:
        return ORCHESTRATOR_PROMPT
