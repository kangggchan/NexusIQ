"""
Entity detector — extracts NexusIQ entity references from free-text queries.
Loads known service and employee names at startup for fuzzy name matching.
"""
from __future__ import annotations

import json
import re
import logging
from dataclasses import dataclass, field
from pathlib import Path

from retrieval.config import DATASET_DIR

log = logging.getLogger(__name__)


@dataclass
class DetectedEntities:
    incidents:    list[str] = field(default_factory=list)   # INC-xxx
    services:     list[str] = field(default_factory=list)   # service names
    employees:    list[str] = field(default_factory=list)   # EMP-xxx
    jira_tickets: list[str] = field(default_factory=list)   # LID-xxx / ADAS-xxx
    deployments:  list[str] = field(default_factory=list)   # DEP-xxx
    commits:      list[str] = field(default_factory=list)   # short SHA or full SHA

    def is_empty(self) -> bool:
        return not any([
            self.incidents, self.services, self.employees,
            self.jira_tickets, self.deployments, self.commits,
        ])

    def to_dict(self) -> dict:
        return {
            "incidents": self.incidents,
            "services": self.services,
            "employees": self.employees,
            "jira_tickets": self.jira_tickets,
            "deployments": self.deployments,
            "commits": self.commits,
        }


# ── Compiled regex patterns ───────────────────────────────────────────────────

_RE_INCIDENT   = re.compile(r"\bINC-\d+\b", re.IGNORECASE)
_RE_EMPLOYEE   = re.compile(r"\bEMP-\d{3}\b", re.IGNORECASE)
_RE_JIRA       = re.compile(r"\b(?:LID|ADAS)-\d+\b", re.IGNORECASE)
_RE_DEPLOYMENT = re.compile(r"\bDEP-\d+\b", re.IGNORECASE)
_RE_SERVICE_ID = re.compile(r"\bSVC-[A-Z0-9-]+\b", re.IGNORECASE)
# Git commit: 7-8 hex chars (short SHA) or 40 hex chars (full SHA)
_RE_COMMIT_SHA = re.compile(r"\b[0-9a-f]{40}\b|\b[0-9a-f]{7,8}\b", re.IGNORECASE)


class EntityDetector:
    """
    Stateful detector — loads known entity names from dataset on init
    so it can match service names mentioned naturally in queries.
    """

    def __init__(self) -> None:
        self._service_names: list[str] = []
        self._service_lower: list[str] = []
        self._employee_names: list[str] = []
        self._employee_lower: list[str] = []
        self._loaded = False

    def load(self) -> None:
        """Load entity catalogs from dataset files (call once at startup)."""
        if self._loaded:
            return
        try:
            svc_data = json.loads((DATASET_DIR / "services.json").read_text())
            self._service_names = [s["name"] for s in svc_data.get("services", [])]
            self._service_lower = [n.lower() for n in self._service_names]

            emp_data = json.loads((DATASET_DIR / "employee_db.json").read_text())
            self._employee_names = [e["name"] for e in emp_data.get("employees", [])]
            self._employee_lower = [n.lower() for n in self._employee_names]

            self._loaded = True
            log.info(
                "EntityDetector loaded: %d services, %d employees",
                len(self._service_names),
                len(self._employee_names),
            )
        except Exception as exc:
            log.warning("EntityDetector could not load catalog: %s", exc)

    def detect(self, query: str) -> DetectedEntities:
        """Extract all entity references from *query*."""
        entities = DetectedEntities()
        query_lower = query.lower()

        # Pattern-based extraction
        entities.incidents    = _unique(_RE_INCIDENT.findall(query))
        entities.employees    = _unique(_RE_EMPLOYEE.findall(query))
        entities.jira_tickets = _unique(_RE_JIRA.findall(query))
        entities.deployments  = _unique(_RE_DEPLOYMENT.findall(query))

        # Service IDs + name matching
        svc_ids = _unique(_RE_SERVICE_ID.findall(query))
        svc_by_name = [
            self._service_names[i]
            for i, name in enumerate(self._service_lower)
            if name in query_lower
        ]
        entities.services = _unique(svc_ids + svc_by_name)

        # Commit SHAs (avoid matching plain numbers; require hex pattern)
        commit_candidates = _RE_COMMIT_SHA.findall(query)
        # Filter out pure decimal strings that happen to match 7-8 digits
        entities.commits = _unique([
            c for c in commit_candidates if not c.isdigit()
        ])

        return entities


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.upper()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


# ── Module-level singleton ────────────────────────────────────────────────────

_detector: EntityDetector | None = None


def get_detector() -> EntityDetector:
    global _detector
    if _detector is None:
        _detector = EntityDetector()
        _detector.load()
    return _detector
