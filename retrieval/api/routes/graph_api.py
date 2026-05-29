from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from retrieval.graph.neo4j_client import get_session
from retrieval.graph import cypher_queries as q
from retrieval.graph.graph_cache import get_graph_cache
from retrieval.schema.neo4j_schema import NodeLabel

log = logging.getLogger(__name__)
router = APIRouter(prefix="/graph", tags=["graph"])


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/service/{name}/dependencies")
async def service_dependencies(name: str, depth: int = Query(default=2, ge=1, le=5)):
    """Get transitive dependencies of a service."""
    async with get_session() as session:
        deps = await q.get_service_dependencies(session, name, depth)
    return {"service": name, "dependencies": deps}


@router.get("/service/{name}/dependents")
async def service_dependents(name: str, depth: int = Query(default=2, ge=1, le=5)):
    """Get services that depend on this service (blast radius)."""
    async with get_session() as session:
        deps = await q.get_service_dependents(session, name, depth)
    return {"service": name, "dependents": deps}


@router.get("/service/{name}/owners")
async def service_owners(name: str):
    async with get_session() as session:
        owners = await q.get_service_owners(session, name)
    return {"service": name, "owners": owners}


@router.get("/service/{name}/incidents")
async def service_incidents(name: str):
    async with get_session() as session:
        incidents = await q.get_incidents_for_service(session, name)
    return {"service": name, "incidents": incidents}


@router.get("/service/{name}/deployments")
async def service_deployments(name: str, limit: int = Query(default=5, ge=1, le=20)):
    async with get_session() as session:
        deployments = await q.get_recent_deployments(session, name, limit)
    return {"service": name, "deployments": deployments}


@router.get("/incident/{incident_id}")
async def incident_context(incident_id: str):
    """Full incident investigation context subgraph."""
    async with get_session() as session:
        ctx = await q.get_incident_full_context(session, incident_id.upper())
    if not ctx:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    return ctx


@router.get("/employee/{employee_id}/services")
async def employee_services(employee_id: str):
    async with get_session() as session:
        services = await q.get_employee_services(session, employee_id.upper())
    return {"employee_id": employee_id, "services": services}


# ── Visualization endpoint (full graph for the UI) ────────────────────────────

@router.get("/visualization")
async def graph_visualization():
    """
    Return all nodes and relationships from Neo4j formatted for the graph visualizer.

    Entity format:  { id, human_readable_id, title, type, description, degree }
    Relationship:   { id, source, target, description, weight }
    """
    cypher_nodes = """
        MATCH (n)
        RETURN
            n.id          AS id,
            labels(n)[0]  AS label,
            COALESCE(n.name, n.employee_id, n.incident_id,
                     n.deployment_id, n.commit_sha, n.ticket_id,
                     n.channel, n.id, toString(id(n))) AS title,
            COALESCE(n.description, n.summary, n.status, n.role, '') AS description
        LIMIT 500
    """
    cypher_rels = """
        MATCH (a)-[r]->(b)
        RETURN
            toString(id(r))       AS id,
            COALESCE(a.id, toString(id(a))) AS source,
            COALESCE(b.id, toString(id(b))) AS target,
            type(r)               AS rel_type,
            COALESCE(r.weight, 1) AS weight
        LIMIT 2000
    """
    try:
        async with get_session() as session:
            node_result = await session.run(cypher_nodes)
            nodes_raw   = await node_result.data()
            rel_result  = await session.run(cypher_rels)
            rels_raw    = await rel_result.data()
    except Exception as exc:
        log.error("[graph/visualization] Neo4j error: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc))

    # Degree counter
    degree: dict[str, int] = {}
    for r in rels_raw:
        degree[r["source"]] = degree.get(r["source"], 0) + 1
        degree[r["target"]] = degree.get(r["target"], 0) + 1

    entities = []
    for i, n in enumerate(nodes_raw):
        nid = str(n["id"]) if n["id"] else str(i)
        entities.append({
            "id":               nid,
            "human_readable_id": str(i),
            "title":            str(n["title"] or nid),
            "type":             str(n["label"] or "NODE"),
            "description":      str(n["description"] or ""),
            "text_unit_ids":    [],
            "frequency":        degree.get(nid, 1),
            "degree":           degree.get(nid, 1),
        })

    relationships = []
    for i, r in enumerate(rels_raw):
        relationships.append({
            "id":               str(r["id"]),
            "human_readable_id": str(i),
            "source":           str(r["source"]),
            "target":           str(r["target"]),
            "description":      r["rel_type"].replace("_", " ").lower(),
            "weight":           int(r["weight"]),
            "combined_degree":  int(r["weight"]),
            "text_unit_ids":    [],
        })

    # Populate the shared in-memory cache so the graph inspector can reuse
    # this data without issuing a second Neo4j query.
    get_graph_cache().populate(entities, relationships)

    return {"entities": entities, "relationships": relationships}
