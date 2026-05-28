"""
ChromaDB collection definitions and metadata schemas.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CollectionDef:
    name: str
    description: str
    metadata_fields: list[str]  # expected metadata keys for filtering


# ── Collection registry ───────────────────────────────────────────────────────

COLLECTIONS: dict[str, CollectionDef] = {
    "incidents": CollectionDef(
        name="nexusiq_incidents",
        description="Incident descriptions, timelines, root causes",
        metadata_fields=["incident_id", "severity", "started_at", "ended_at",
                         "affected_services", "status"],
    ),
    "commits": CollectionDef(
        name="nexusiq_commits",
        description="Git commit messages, diffs, and service mappings",
        metadata_fields=["commit_id", "short_id", "author", "timestamp",
                         "services_modified", "jira_tickets", "branch"],
    ),
    "slack": CollectionDef(
        name="nexusiq_slack",
        description="Slack channel messages across teams",
        metadata_fields=["message_id", "channel", "author", "timestamp"],
    ),
    "jira": CollectionDef(
        name="nexusiq_jira",
        description="Jira tickets: stories, bugs, tasks",
        metadata_fields=["ticket_id", "type", "priority", "status",
                         "related_services", "assignee", "created_at"],
    ),
    "tech_docs": CollectionDef(
        name="nexusiq_tech_docs",
        description="Technical architecture and runbook documents",
        metadata_fields=["doc_id", "title", "filename"],
    ),
    "meeting_notes": CollectionDef(
        name="nexusiq_meeting_notes",
        description="Team meeting notes and decisions",
        metadata_fields=["note_id", "title", "filename", "date"],
    ),
    "deployments": CollectionDef(
        name="nexusiq_deployments",
        description="Deployment records with service, version, and status",
        metadata_fields=["deployment_id", "service", "environment",
                         "status", "timestamp", "deployed_by"],
    ),
}

ALL_COLLECTION_NAMES = [c.name for c in COLLECTIONS.values()]
