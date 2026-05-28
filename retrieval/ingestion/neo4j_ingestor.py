"""
Neo4j ingestion pipeline.
Loads all NexusIQ synthetic dataset files → Neo4j graph.

Run with::

    python -m retrieval.ingestion.run_ingestion --target neo4j
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from retrieval.config import DATASET_DIR
from retrieval.graph.neo4j_client import get_session
from retrieval.graph.cypher_queries import create_constraints
from retrieval.schema.neo4j_schema import NodeLabel, RelType

log = logging.getLogger(__name__)


def _load(filename: str) -> dict:
    path = DATASET_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


async def ingest_all() -> dict[str, int]:
    """
    Run the full Neo4j ingestion in dependency order:
    1. Services  2. Employees  3. Incidents
    4. Deployments  5. Commits  6. Jira  7. Slack
    8. Relationships (edges)
    """
    counts: dict[str, int] = {}
    async with get_session() as session:
        log.info("Creating schema constraints…")
        await create_constraints(session)

        counts["services"]    = await _ingest_services(session)
        counts["employees"]   = await _ingest_employees(session)
        counts["incidents"]   = await _ingest_incidents(session)
        counts["deployments"] = await _ingest_deployments(session)
        counts["commits"]     = await _ingest_commits(session)
        counts["jira"]        = await _ingest_jira(session)
        counts["slack"]       = await _ingest_slack(session)
        counts["tech_docs"]   = await _ingest_tech_docs(session)
        counts["meetings"]    = await _ingest_meeting_notes(session)
        counts["edges"]       = await _ingest_relationships(session)

    log.info("Neo4j ingestion complete: %s", counts)
    return counts


# ── Node ingestors ────────────────────────────────────────────────────────────

async def _ingest_services(session) -> int:
    data = _load("services.json")
    services = data.get("services", [])
    for svc in services:
        await session.run(
            """
            MERGE (s:Service {service_id: $id})
            SET s.name        = $name,
                s.project     = $project,
                s.team        = $team,
                s.description = $description,
                s.status      = $status
            """,
            id=svc["service_id"],
            name=svc.get("name", ""),
            project=svc.get("project", ""),
            team=svc.get("team", ""),
            description=svc.get("description", ""),
            status=svc.get("status", "unknown"),
        )
    log.info("  ✓ %d services", len(services))
    return len(services)


async def _ingest_employees(session) -> int:
    data = _load("employee_db.json")
    employees = data.get("employees", [])
    for emp in employees:
        await session.run(
            """
            MERGE (e:Employee {employee_id: $id})
            SET e.name  = $name,
                e.role  = $role,
                e.team  = $team,
                e.email = $email
            """,
            id=emp["employee_id"],
            name=emp.get("name", ""),
            role=emp.get("role", ""),
            team=emp.get("team", ""),
            email=emp.get("email", ""),
        )
    log.info("  ✓ %d employees", len(employees))
    return len(employees)


async def _ingest_incidents(session) -> int:
    data = _load("incidents.json")
    incidents = data.get("incidents", [])
    for inc in incidents:
        # Flatten timeline for storage
        timeline_text = " | ".join(
            f"{e['timestamp']}: {e['event']}"
            for e in inc.get("timeline", [])
        )
        await session.run(
            """
            MERGE (i:Incident {incident_id: $id})
            SET i.title           = $title,
                i.severity        = $severity,
                i.started_at      = $started_at,
                i.ended_at        = $ended_at,
                i.timeline        = $timeline,
                i.root_cause      = $root_cause,
                i.affected_services_raw = $affected
            """,
            id=inc["incident_id"],
            title=inc.get("title", ""),
            severity=inc.get("severity", ""),
            started_at=inc.get("started_at", ""),
            ended_at=inc.get("ended_at", ""),
            timeline=timeline_text,
            root_cause=inc.get("root_cause", ""),
            affected=json.dumps(inc.get("affected_services", [])),
        )
        # Incident → Service (AFFECTS)
        for svc_name in inc.get("affected_services", []):
            await session.run(
                """
                MATCH (i:Incident {incident_id: $inc_id})
                MATCH (s:Service {name: $svc_name})
                MERGE (i)-[:AFFECTS]->(s)
                """,
                inc_id=inc["incident_id"],
                svc_name=svc_name,
            )
    log.info("  ✓ %d incidents", len(incidents))
    return len(incidents)


async def _ingest_deployments(session) -> int:
    data = _load("deployment_logs.json")
    deployments = data.get("deployments", [])
    for dep in deployments:
        await session.run(
            """
            MERGE (d:Deployment {deployment_id: $id})
            SET d.service     = $service,
                d.version     = $version,
                d.environment = $env,
                d.status      = $status,
                d.timestamp   = $ts,
                d.notes       = $notes,
                d.commit_id   = $commit_id
            """,
            id=dep["deployment_id"],
            service=dep.get("service", ""),
            version=dep.get("service_version", ""),
            env=dep.get("environment", ""),
            status=dep.get("status", ""),
            ts=dep.get("timestamp", ""),
            notes=dep.get("notes", ""),
            commit_id=dep.get("source_commit_id", ""),
        )
        # Deployment → Service
        if dep.get("service"):
            await session.run(
                """
                MATCH (d:Deployment {deployment_id: $dep_id})
                MATCH (s:Service {name: $svc})
                MERGE (d)-[:DEPLOYS]->(s)
                """,
                dep_id=dep["deployment_id"],
                svc=dep["service"],
            )
        # Deployment → Employee
        if dep.get("initiated_by_employee_id"):
            await session.run(
                """
                MATCH (d:Deployment {deployment_id: $dep_id})
                MATCH (e:Employee {employee_id: $emp_id})
                MERGE (d)-[:DEPLOYED_BY]->(e)
                """,
                dep_id=dep["deployment_id"],
                emp_id=dep["initiated_by_employee_id"],
            )
    log.info("  ✓ %d deployments", len(deployments))
    return len(deployments)


async def _ingest_commits(session) -> int:
    data = _load("github_commits.json")
    commits = data.get("commits", [])
    for commit in commits:
        await session.run(
            """
            MERGE (c:Commit {commit_id: $id})
            SET c.short_id    = $short_id,
                c.message     = $message,
                c.author_name = $author,
                c.timestamp   = $ts,
                c.branch      = $branch
            """,
            id=commit["commit_id"],
            short_id=commit.get("short_commit_id", ""),
            message=commit.get("message", ""),
            author=commit.get("author_name", ""),
            ts=commit.get("timestamp", ""),
            branch=commit.get("branch", ""),
        )
        # Commit → Service
        for svc_name in commit.get("services_modified", []):
            await session.run(
                """
                MATCH (c:Commit {commit_id: $cid})
                MATCH (s:Service {name: $svc})
                MERGE (c)-[:MODIFIES]->(s)
                """,
                cid=commit["commit_id"],
                svc=svc_name,
            )
        # Commit → Employee
        if commit.get("author_employee_id"):
            await session.run(
                """
                MATCH (c:Commit {commit_id: $cid})
                MATCH (e:Employee {employee_id: $eid})
                MERGE (c)-[:AUTHORED_BY]->(e)
                """,
                cid=commit["commit_id"],
                eid=commit["author_employee_id"],
            )
        # Commit → JiraTicket
        for jira_id in commit.get("jira_ticket_ids", []):
            await session.run(
                """
                MATCH (c:Commit {commit_id: $cid})
                MERGE (t:JiraTicket {ticket_id: $tid})
                MERGE (c)-[:LINKED_TO]->(t)
                """,
                cid=commit["commit_id"],
                tid=jira_id,
            )
    log.info("  ✓ %d commits", len(commits))
    return len(commits)


async def _ingest_jira(session) -> int:
    data = _load("jira_tickets.json")
    tickets = data.get("tickets", [])
    for ticket in tickets:
        await session.run(
            """
            MERGE (t:JiraTicket {ticket_id: $id})
            SET t.summary    = $summary,
                t.description = $desc,
                t.type       = $type,
                t.priority   = $priority,
                t.status     = $status,
                t.project    = $project,
                t.created_at = $created
            """,
            id=ticket["ticket_id"],
            summary=ticket.get("summary", ""),
            desc=ticket.get("description", ""),
            type=ticket.get("type", ""),
            priority=ticket.get("priority", ""),
            status=ticket.get("status", ""),
            project=ticket.get("project", ""),
            created=ticket.get("created_at", ""),
        )
        # Jira → Service
        for svc_name in ticket.get("related_services", []):
            await session.run(
                """
                MATCH (t:JiraTicket {ticket_id: $tid})
                MATCH (s:Service {name: $svc})
                MERGE (t)-[:RELATES_TO]->(s)
                """,
                tid=ticket["ticket_id"],
                svc=svc_name,
            )
        # Jira → Employee (assignee)
        if ticket.get("assignee_employee_id"):
            await session.run(
                """
                MATCH (t:JiraTicket {ticket_id: $tid})
                MATCH (e:Employee {employee_id: $eid})
                MERGE (t)-[:ASSIGNED_TO]->(e)
                """,
                tid=ticket["ticket_id"],
                eid=ticket["assignee_employee_id"],
            )
    log.info("  ✓ %d Jira tickets", len(tickets))
    return len(tickets)


async def _ingest_slack(session) -> int:
    slack_dir = DATASET_DIR / "slack_logs"
    total = 0
    for json_file in slack_dir.glob("*.json"):
        data = json.loads(json_file.read_text(encoding="utf-8"))
        channel = data.get("channel", json_file.stem)
        messages = data.get("messages", [])
        for msg in messages:
            msg_id = f"{channel}_{msg.get('timestamp', total)}"
            await session.run(
                """
                MERGE (m:SlackMessage {message_id: $id})
                SET m.channel   = $channel,
                    m.author    = $author,
                    m.content   = $content,
                    m.timestamp = $ts
                """,
                id=msg_id,
                channel=channel,
                author=msg.get("author", ""),
                content=msg.get("content", msg.get("message", "")),
                ts=msg.get("timestamp", ""),
            )
            total += 1
    log.info("  ✓ %d Slack messages", total)
    return total


async def _ingest_tech_docs(session) -> int:
    docs_dir = DATASET_DIR / "technical_documents"
    total = 0
    for md_file in sorted(docs_dir.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        title = _extract_md_title(content, md_file.stem)
        doc_id = f"TDOC-{md_file.stem}"
        await session.run(
            """
            MERGE (d:TechDoc {doc_id: $id})
            SET d.title    = $title,
                d.filename = $filename,
                d.content_preview = $preview
            """,
            id=doc_id,
            title=title,
            filename=md_file.name,
            preview=content[:500],
        )
        total += 1
    log.info("  ✓ %d tech docs", total)
    return total


async def _ingest_meeting_notes(session) -> int:
    notes_dir = DATASET_DIR / "meeting_notes"
    total = 0
    for md_file in sorted(notes_dir.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        title = _extract_md_title(content, md_file.stem)
        note_id = f"MTG-{md_file.stem}"
        await session.run(
            """
            MERGE (n:MeetingNote {note_id: $id})
            SET n.title    = $title,
                n.filename = $filename,
                n.content_preview = $preview
            """,
            id=note_id,
            title=title,
            filename=md_file.name,
            preview=content[:500],
        )
        total += 1
    log.info("  ✓ %d meeting notes", total)
    return total


# ── Relationship ingestor ─────────────────────────────────────────────────────

async def _ingest_relationships(session) -> int:
    """Process graph_relationships.json for EMPLOYEE_OWNS_SERVICE and SERVICE_DEPENDS_ON."""
    data = _load("graph_relationships.json")
    rels = data.get("relationships", [])
    count = 0
    for rel in rels:
        rel_type = rel.get("type")
        from_id = rel.get("from", "")
        to_id = rel.get("to", "")

        if rel_type == "EMPLOYEE_OWNS_SERVICE":
            await session.run(
                """
                MATCH (s:Service {name: $svc})
                MATCH (e:Employee {employee_id: $emp})
                MERGE (s)-[:OWNED_BY]->(e)
                """,
                svc=to_id,
                emp=from_id,
            )
            count += 1
        elif rel_type == "SERVICE_DEPENDS_ON":
            await session.run(
                """
                MATCH (a:Service {name: $from})
                MATCH (b:Service {name: $to})
                MERGE (a)-[:DEPENDS_ON]->(b)
                """,
                from_=from_id,
                to=to_id,
            )
            count += 1
    log.info("  ✓ %d graph relationships", count)
    return count


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_md_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback.replace("-", " ").replace("_", " ").title()
