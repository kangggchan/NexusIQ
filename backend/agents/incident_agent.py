"""IncidentAgent – incident timeline reconstruction and root-cause analysis (llama3.1:8b)."""
from backend.agents.base_agent import BaseAgent
from backend.agents.prompts import INCIDENT_AGENT_PROMPT
from backend.services.model_router import AgentId


class IncidentAgent(BaseAgent):
    AGENT_ID: AgentId = "incident"

    @property
    def system_prompt(self) -> str:
        return INCIDENT_AGENT_PROMPT
