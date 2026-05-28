"""
Neo4j node and relationship type constants.
Single source of truth for all graph schema labels.
"""
from __future__ import annotations
from dataclasses import dataclass


# ── Node labels ───────────────────────────────────────────────────────────────

class NodeLabel:
    SERVICE      = "Service"
    EMPLOYEE     = "Employee"
    INCIDENT     = "Incident"
    DEPLOYMENT   = "Deployment"
    COMMIT       = "Commit"
    JIRA_TICKET  = "JiraTicket"
    SLACK_MSG    = "SlackMessage"
    TECH_DOC     = "TechDoc"
    MEETING_NOTE = "MeetingNote"


# ── Relationship types ────────────────────────────────────────────────────────

class RelType:
    # Service graph
    DEPENDS_ON     = "DEPENDS_ON"       # Service → Service
    OWNED_BY       = "OWNED_BY"         # Service → Employee

    # Incident
    AFFECTS        = "AFFECTS"          # Incident → Service
    INVESTIGATED_BY = "INVESTIGATED_BY" # Incident → Employee

    # Deployment
    DEPLOYS        = "DEPLOYS"          # Deployment → Service
    DEPLOYED_BY    = "DEPLOYED_BY"      # Deployment → Employee

    # Commit
    MODIFIES       = "MODIFIES"         # Commit → Service
    AUTHORED_BY    = "AUTHORED_BY"      # Commit → Employee
    LINKED_TO      = "LINKED_TO"        # Commit → JiraTicket

    # Jira
    RELATES_TO     = "RELATES_TO"       # JiraTicket → Service
    ASSIGNED_TO    = "ASSIGNED_TO"      # JiraTicket → Employee

    # Slack
    MENTIONS_SVC   = "MENTIONS_SERVICE" # SlackMessage → Service
    MENTIONS_INC   = "MENTIONS_INCIDENT"# SlackMessage → Incident


# ── Constraint definitions (uniqueness) ──────────────────────────────────────

CONSTRAINTS = [
    (NodeLabel.SERVICE,      "service_id"),
    (NodeLabel.EMPLOYEE,     "employee_id"),
    (NodeLabel.INCIDENT,     "incident_id"),
    (NodeLabel.DEPLOYMENT,   "deployment_id"),
    (NodeLabel.COMMIT,       "commit_id"),
    (NodeLabel.JIRA_TICKET,  "ticket_id"),
    (NodeLabel.SLACK_MSG,    "message_id"),
    (NodeLabel.TECH_DOC,     "doc_id"),
    (NodeLabel.MEETING_NOTE, "note_id"),
]
