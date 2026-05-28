"""
ModelRouter – maps agent IDs to Ollama model names and inference parameters.

Each agent entry defines:
  - model: the Ollama model tag to use
  - temperature: generation temperature (creativity vs determinism)
  - max_tokens: max output tokens
  - description: human-readable summary shown in the API /models/status response
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from backend.config import settings

AgentId = Literal["orchestrator", "graph", "incident", "risk", "embedding"]

VALID_AGENTS: tuple[AgentId, ...] = ("orchestrator", "graph", "incident", "risk", "embedding")


@dataclass(frozen=True)
class AgentConfig:
    agent_id: AgentId
    model: str
    temperature: float = 0.7
    max_tokens: int = 2048
    description: str = ""
    tags: list[str] = field(default_factory=list)


class ModelRouter:
    """
    Central registry that maps agent IDs → AgentConfig.

    Models are read from Settings so they can be overridden via env vars
    without changing code.
    """

    def __init__(self) -> None:
        self._registry: dict[AgentId, AgentConfig] = {
            "orchestrator": AgentConfig(
                agent_id="orchestrator",
                model=settings.model_orchestrator,
                temperature=0.6,
                max_tokens=2048,
                description="Coordinates multi-agent investigation workflows",
                tags=["coordination", "planning", "routing"],
            ),
            "graph": AgentConfig(
                agent_id="graph",
                model=settings.model_graph,
                temperature=0.4,
                max_tokens=1536,
                description="Analyzes service dependency graphs and topology",
                tags=["graph", "dependencies", "topology"],
            ),
            "incident": AgentConfig(
                agent_id="incident",
                model=settings.model_incident,
                temperature=0.5,
                max_tokens=2048,
                description="Investigates incident timelines and root causes",
                tags=["incidents", "RCA", "timeline"],
            ),
            "risk": AgentConfig(
                agent_id="risk",
                model=settings.model_risk,
                temperature=0.3,
                max_tokens=1024,
                description="Assesses deployment risk and blast radius",
                tags=["risk", "blast-radius", "SLO"],
            ),
            "embedding": AgentConfig(
                agent_id="embedding",
                model=settings.model_embedding,
                temperature=0.0,
                max_tokens=0,
                description="Text embedding pipeline for semantic search",
                tags=["embeddings", "semantic-search"],
            ),
        }

    def get_config(self, agent_id: AgentId) -> AgentConfig:
        """Return AgentConfig for *agent_id*, raising KeyError if unknown."""
        if agent_id not in self._registry:
            raise KeyError(f"Unknown agent '{agent_id}'. Valid agents: {list(self._registry)}")
        return self._registry[agent_id]

    def get_model(self, agent_id: AgentId) -> str:
        return self.get_config(agent_id).model

    def all_configs(self) -> list[AgentConfig]:
        return list(self._registry.values())

    def all_models(self) -> list[str]:
        """Unique model names (embedding model has no inference parameters)."""
        return list({cfg.model for cfg in self._registry.values()})

    def inference_models(self) -> list[str]:
        """Models used for chat inference (excludes embedding-only model)."""
        return [
            cfg.model
            for cfg in self._registry.values()
            if cfg.agent_id != "embedding"
        ]
