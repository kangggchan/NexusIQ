"""RiskAgent – deployment risk and blast-radius analysis (gemma3:12b)."""
from backend.agents.base_agent import BaseAgent
from backend.agents.prompts import RISK_AGENT_PROMPT
from backend.services.model_router import AgentId


class RiskAgent(BaseAgent):
    AGENT_ID: AgentId = "risk"

    @property
    def system_prompt(self) -> str:
        return RISK_AGENT_PROMPT
