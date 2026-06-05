"""
Parameterized Cypher query library.
All queries return lists of dicts for easy serialization.
"""
from __future__ import annotations

from neo4j import AsyncSession


# ── Schema setup ──────────────────────────────────────────────────────────────

async def create_constraints(session: AsyncSession) -> None:
    """Create uniqueness constraints for all node types."""
    from retrieval.schema.neo4j_schema import CONSTRAINTS
    for label, prop in CONSTRAINTS:
        cypher = (
            f"CREATE CONSTRAINT {label.lower()}_{prop}_unique IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
        )
        await session.run(cypher)


# ── Service queries ───────────────────────────────────────────────────────────

async def get_service_by_name(session: AsyncSession, name: str) -> dict | None:
    result = await session.run(
        "MATCH (s:Service) WHERE toLower(s.name) = toLower($name) RETURN s",
        name=name,
    )
    record = await result.single()
    return dict(record["s"]) if record else None


async def get_service_dependencies(session: AsyncSession, service_name: str, depth: int = 2) -> list[dict]:
    """Return direct + transitive dependencies up to *depth* hops."""
    result = await session.run(
        """
        MATCH path = (s:Service {name: $name})-[:DEPENDS_ON*1..$depth]->(dep:Service)
        RETURN
          dep.service_id  AS dep_id,
          dep.name        AS dep_name,
          dep.team        AS dep_team,
          dep.status      AS dep_status,
          length(path)    AS hops
        ORDER BY hops
        """,
        name=service_name,
        depth=depth,
    )
    return [dict(r) async for r in result]


async def get_service_dependents(session: AsyncSession, service_name: str, depth: int = 2) -> list[dict]:
    """Return services that depend ON this service (blast radius)."""
    result = await session.run(
        """
        MATCH path = (upstream:Service)-[:DEPENDS_ON*1..$depth]->(s:Service {name: $name})
        RETURN
          upstream.service_id AS dep_id,
          upstream.name       AS dep_name,
          upstream.team       AS dep_team,
          upstream.status     AS dep_status,
          length(path)        AS hops
        ORDER BY hops
        """,
        name=service_name,
        depth=depth,
    )
    return [dict(r) async for r in result]


async def get_service_owners(session: AsyncSession, service_name: str) -> list[dict]:
    result = await session.run(
        """
        MATCH (s:Service {name: $name})-[:OWNED_BY]->(e:Employee)
        RETURN e.employee_id AS id, e.name AS name, e.role AS role, e.team AS team, e.email AS email
        """,
        name=service_name,
    )
    return [dict(r) async for r in result]


# ── Incident queries ──────────────────────────────────────────────────────────

async def get_incident_by_id(session: AsyncSession, incident_id: str) -> dict | None:
    result = await session.run(
        "MATCH (i:Incident {incident_id: $id}) RETURN i",
        id=incident_id,
    )
    record = await result.single()
    return dict(record["i"]) if record else None


async def get_incident_full_context(session: AsyncSession, incident_id: str) -> dict:
    """
    Full incident investigation context:
    - affected services + their dependencies
    - deployments in the ±24h window around the incident
    - commits in the same window
    """
    result = await session.run(
        """
        MATCH (i:Incident {incident_id: $id})
        OPTIONAL MATCH (i)-[:AFFECTS]->(s:Service)
        OPTIONAL MATCH (s)-[:DEPENDS_ON]->(dep:Service)
        OPTIONAL MATCH (d:Deployment)-[:DEPLOYS]->(s)
          WHERE d.timestamp >= i.started_at
            AND d.timestamp <= i.ended_at
        OPTIONAL MATCH (c:Commit)-[:MODIFIES]->(s)
          WHERE c.timestamp >= i.started_at
            AND c.timestamp <= i.ended_at
        OPTIONAL MATCH (s)-[:OWNED_BY]->(e:Employee)
        RETURN
          i AS incident,
          collect(DISTINCT {id: s.service_id, name: s.name, team: s.team})
            AS affected_services,
          collect(DISTINCT {id: dep.service_id, name: dep.name})
            AS dependencies,
          collect(DISTINCT {id: d.deployment_id, service: d.service,
                            version: d.version, status: d.status, ts: d.timestamp})
            AS deployments,
          collect(DISTINCT {id: c.commit_id, msg: c.message, author: c.author_name, ts: c.timestamp})
            AS commits,
          collect(DISTINCT {id: e.employee_id, name: e.name, role: e.role})
            AS owners
        """,
        id=incident_id,
    )
    record = await result.single()
    if not record:
        return {}
    return {
        "incident": dict(record["incident"]),
        "affected_services": record["affected_services"],
        "dependencies": record["dependencies"],
        "deployments": record["deployments"],
        "commits": record["commits"],
        "owners": record["owners"],
    }


async def get_incidents_for_service(session: AsyncSession, service_name: str) -> list[dict]:
    result = await session.run(
        """
        MATCH (i:Incident)-[:AFFECTS]->(s:Service {name: $name})
        RETURN i.incident_id AS id, i.title AS title, i.severity AS severity,
               i.started_at AS started_at, i.ended_at AS ended_at
        ORDER BY i.started_at DESC
        """,
        name=service_name,
    )
    return [dict(r) async for r in result]


# ── Deployment queries ────────────────────────────────────────────────────────

async def get_recent_deployments(session: AsyncSession, service_name: str, limit: int = 5) -> list[dict]:
    result = await session.run(
        """
        MATCH (d:Deployment)-[:DEPLOYS]->(s:Service {name: $name})
        OPTIONAL MATCH (d)-[:DEPLOYED_BY]->(e:Employee)
        RETURN d.deployment_id AS id, d.service AS service, d.version AS version,
               d.environment AS env, d.status AS status, d.timestamp AS ts,
               e.name AS deployed_by
        ORDER BY d.timestamp DESC LIMIT $limit
        """,
        name=service_name,
        limit=limit,
    )
    return [dict(r) async for r in result]


async def get_deployment_context(session: AsyncSession, deployment_ref: str) -> dict | None:
    result = await session.run(
        """
        MATCH (d:Deployment)
        WHERE toUpper(d.deployment_id) = toUpper($ref)
        OPTIONAL MATCH (d)-[:DEPLOYED_BY]->(e:Employee)
        OPTIONAL MATCH (d)-[:DEPLOYS]->(s:Service)
        OPTIONAL MATCH (c:Commit {commit_id: d.commit_id})
        RETURN
            d.deployment_id AS id,
            coalesce(s.name, d.service) AS service,
            d.version AS version,
            d.environment AS env,
            d.status AS status,
            d.timestamp AS ts,
            d.notes AS notes,
            d.commit_id AS commit_id,
            c.short_id AS commit_short_id,
            coalesce(e.name, e.employee_id) AS deployed_by
        LIMIT 1
        """,
        ref=deployment_ref,
    )
    record = await result.single()
    if not record:
        return None
    return {
        "id": record["id"],
        "service": record["service"],
        "version": record["version"],
        "env": record["env"],
        "status": record["status"],
        "ts": record["ts"],
        "notes": record["notes"],
        "commit_id": record["commit_id"],
        "commit_short_id": record["commit_short_id"],
        "deployed_by": record["deployed_by"],
    }


# ── Commit / Jira queries ─────────────────────────────────────────────────────

async def get_commits_for_service(session: AsyncSession, service_name: str, limit: int = 10) -> list[dict]:
    result = await session.run(
        """
        MATCH (c:Commit)-[:MODIFIES]->(s:Service {name: $name})
        OPTIONAL MATCH (c)-[:AUTHORED_BY]->(e:Employee)
        RETURN c.commit_id AS id, c.message AS message, c.timestamp AS ts,
               e.name AS author
        ORDER BY c.timestamp DESC LIMIT $limit
        """,
        name=service_name,
        limit=limit,
    )
    return [dict(r) async for r in result]


async def get_commit_context(session: AsyncSession, commit_ref: str) -> dict | None:
    result = await session.run(
        """
        MATCH (c:Commit)
        WHERE toString(c.commit_id) = $ref
           OR toLower(coalesce(c.commit_id, '')) = toLower($ref)
           OR toLower(coalesce(c.short_id, '')) = toLower($ref)
        OPTIONAL MATCH (c)-[:MODIFIES]->(s:Service)
        OPTIONAL MATCH (c)-[:AUTHORED_BY]->(e:Employee)
        OPTIONAL MATCH (c)-[:REFERENCES]->(t:JiraTicket)
        RETURN
            c.commit_id AS id,
            c.short_id AS short_id,
            c.message AS message,
            c.timestamp AS ts,
            c.branch AS branch,
            coalesce(e.name, c.author_name) AS author,
            collect(DISTINCT s.name) AS services,
            collect(DISTINCT t.ticket_id) AS jira_ticket_ids
        LIMIT 1
        """,
        ref=commit_ref,
    )
    record = await result.single()
    if not record:
        return None
    return {
        "id": record["id"],
        "short_id": record["short_id"],
        "message": record["message"],
        "ts": record["ts"],
        "branch": record["branch"],
        "author": record["author"],
        "services": [svc for svc in record["services"] if svc],
        "jira_ticket_ids": [ticket for ticket in record["jira_ticket_ids"] if ticket],
    }


async def get_jira_tickets_for_service(session: AsyncSession, service_name: str) -> list[dict]:
    result = await session.run(
        """
        MATCH (t:JiraTicket)-[:RELATES_TO]->(s:Service {name: $name})
        RETURN t.ticket_id AS id, t.summary AS summary, t.type AS type,
               t.priority AS priority, t.status AS status
        ORDER BY t.created_at DESC
        """,
        name=service_name,
    )
    return [dict(r) async for r in result]


# ── Employee queries ──────────────────────────────────────────────────────────

async def get_employee_services(session: AsyncSession, employee_id: str) -> list[dict]:
    result = await session.run(
        """
        MATCH (e:Employee)
        WHERE toUpper(e.employee_id) = toUpper($id)
           OR toLower(e.name) = toLower($id)
        OPTIONAL MATCH (e)<-[:OWNED_BY]-(s:Service)
        RETURN s.service_id AS id, s.name AS name, s.status AS status, s.team AS team
        """,
        id=employee_id,
    )
    return [dict(r) async for r in result if r.get("name")]


async def get_employee_profile(session: AsyncSession, employee_ref: str) -> dict | None:
    result = await session.run(
        """
        MATCH (e:Employee)
        WHERE toUpper(e.employee_id) = toUpper($ref)
           OR toLower(e.name) = toLower($ref)
        OPTIONAL MATCH (e)<-[:OWNED_BY]-(s:Service)
        RETURN
            e.employee_id AS employee_id,
            e.name AS name,
            e.role AS role,
            e.team AS team,
            e.email AS email,
            collect(DISTINCT {
                id: s.service_id,
                name: s.name,
                status: s.status,
                team: s.team
            }) AS services
        LIMIT 1
        """,
        ref=employee_ref,
    )
    record = await result.single()
    if not record:
        return None
    return {
        "employee_id": record["employee_id"],
        "name": record["name"],
        "role": record["role"],
        "team": record["team"],
        "email": record["email"],
        "services": [svc for svc in record["services"] if svc.get("name")],
    }


# ── Generic entity lookup ─────────────────────────────────────────────────────

async def get_entity_neighbors(
    session: AsyncSession,
    entity_id: str,
    label: str,
    id_prop: str,
    max_depth: int = 2,
) -> list[dict]:
    """Generic 1-hop neighbor lookup for any node type."""
    result = await session.run(
        f"""
        MATCH (n:{label} {{{id_prop}: $id}})-[r]-(neighbor)
        RETURN type(r) AS rel_type, labels(neighbor) AS neighbor_labels,
               neighbor AS neighbor_props
        LIMIT 50
        """,
        id=entity_id,
    )
    rows = []
    async for rec in result:
        rows.append({
            "rel_type": rec["rel_type"],
            "neighbor_labels": rec["neighbor_labels"],
            "neighbor": dict(rec["neighbor_props"]),
        })
    return rows
