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


# ── Incidents endpoint (all incidents for UI) ───────────────────────────────────

@router.get("/incidents")
async def get_all_incidents():
    """Return all incidents from Neo4j for the incidents panel."""
    cypher = """
        MATCH (i:Incident)
        RETURN
            i.incident_id AS incident_id,
            i.title AS title,
            i.severity AS severity,
            i.started_at AS started_at,
            i.ended_at AS ended_at,
            i.root_cause AS root_cause,
            i.mitigation_steps AS mitigation_steps,
            [(i)-[:AFFECTS]->(s:Service) | s.name] AS affected_services
        ORDER BY i.started_at DESC
    """
    try:
        async with get_session() as session:
            result = await session.run(cypher)
            incidents = []
            async for record in result:
                incidents.append({
                    "incident_id": record["incident_id"],
                    "title": record["title"],
                    "severity": record["severity"],
                    "started_at": record["started_at"],
                    "ended_at": record["ended_at"],
                    "root_cause": record["root_cause"],
                    "mitigation_steps": record["mitigation_steps"],
                    "affected_services": record["affected_services"],
                })
            return {"incidents": incidents}
    except Exception as exc:
        log.error("[graph/incidents] Neo4j error: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc))


# ── Context documents endpoint ───────────────────────────────────────────────────

@router.get("/context")
async def get_context_documents(
    doc_type: str = Query(default=None, description="Filter by type: slack, meeting, technical, jira, commit"),
    query: str = Query(default="", description="Text search query")
):
    """
    Return context documents from ChromaDB (semantic) + Neo4j (relationships).
    ChromaDB provides the actual document content with semantic search.
    Neo4j provides relationship context.
    """
    from retrieval.retrieval.chroma_retriever import ChromaRetriever
    from retrieval.schema.chroma_schema import COLLECTIONS
    
    try:
        documents = []
        
        # Map frontend doc_type to ChromaDB collection keys
        type_to_collection = {
            "slack": "slack",
            "meeting": "meeting_notes",
            "technical": "tech_docs",
            "jira": "jira",
            "commit": "commits",
        }
        
        # Determine which collections to query
        target_collections = []
        if doc_type and doc_type in type_to_collection:
            target_collections = [type_to_collection[doc_type]]
        else:
            target_collections = list(COLLECTIONS.keys())
        
        # Use ChromaDB for semantic search
        chroma = ChromaRetriever()
        if query:
            # Semantic search with query
            vector_results = await chroma.search(
                query=query,
                collections=target_collections,
                top_k=20
            )
            
            # Convert VectorResults to frontend format
            for vr in vector_results:
                doc = _convert_chroma_result(vr)
                if doc:
                    documents.append(doc)
        else:
            # No query - get recent documents from ChromaDB
            for col_key in target_collections:
                col_def = COLLECTIONS.get(col_key)
                if not col_def:
                    continue
                
                try:
                    from retrieval.vector.chroma_client import get_or_create_collection
                    collection = await get_or_create_collection(col_def.name)
                    # Get recent documents (no embedding needed for simple retrieval)
                    response = await collection.get(
                        limit=20,
                        include=["documents", "metadatas"]
                    )
                    
                    ids = response.get("ids", [])
                    docs = response.get("documents", [])
                    metas = response.get("metadatas", [])
                    
                    for doc_id, doc_text, meta in zip(ids, docs, metas):
                        converted = _convert_chroma_raw(col_key, doc_id, doc_text, meta)
                        if converted:
                            documents.append(converted)
                except Exception as exc:
                    log.warning("Failed to get documents from %s: %s", col_key, exc)
        
        # Sort by timestamp descending (if available)
        documents.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return documents

    except Exception as exc:
        log.error("[graph/context] Error: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc))


def _convert_chroma_result(vr) -> dict | None:
    """Convert ChromaDB VectorResult to frontend ContextDocument format."""
    collection = vr.collection
    metadata = vr.metadata
    
    # Map collection names to frontend types
    type_map = {
        "nexusiq-slack": "slack",
        "nexusiq-meeting-notes": "meeting",
        "nexusiq-tech-docs": "technical",
        "nexusiq-jira": "jira",
        "nexusiq-commits": "commit",
        "nexusiq-incidents": "incident",
        "nexusiq-deployments": "deployment",
    }
    
    doc_type = type_map.get(collection, "unknown")
    
    try:
        if doc_type == "slack":
            return {
                "id": metadata.get("message_id", vr.id),
                "type": "slack",
                "title": f"{metadata.get('author', 'Unknown')} in {metadata.get('channel', 'unknown')}",
                "content": vr.document,
                "timestamp": metadata.get("timestamp", ""),
                "author": metadata.get("author", ""),
                "channel": metadata.get("channel", ""),
                "tags": [],
                "metadata": {
                    "employee_id": metadata.get("employee_id", ""),
                },
            }
        elif doc_type == "meeting":
            return {
                "id": metadata.get("note_id", vr.id),
                "type": "meeting",
                "title": metadata.get("title", "Meeting Note"),
                "content": vr.document[:1200],
                "timestamp": "",
                "tags": [],
                "metadata": {"filename": metadata.get("filename", "")},
            }
        elif doc_type == "technical":
            return {
                "id": metadata.get("doc_id", vr.id),
                "type": "technical",
                "title": metadata.get("title", "Technical Document"),
                "content": vr.document[:1200],
                "timestamp": "",
                "tags": [],
                "metadata": {"filename": metadata.get("filename", "")},
            }
        elif doc_type == "jira":
            return {
                "id": metadata.get("ticket_id", vr.id),
                "type": "jira",
                "title": f"[{metadata.get('ticket_id', vr.id)}] Ticket",
                "content": vr.document,
                "timestamp": metadata.get("created_at", ""),
                "author": metadata.get("assignee", ""),
                "tags": metadata.get("related_services", []),
                "metadata": {
                    "status": metadata.get("status", ""),
                    "priority": metadata.get("priority", ""),
                    "type": metadata.get("type", ""),
                    "assignee": metadata.get("assignee", ""),
                },
            }
        elif doc_type == "commit":
            return {
                "id": metadata.get("commit_id", vr.id),
                "type": "commit",
                "title": "Commit",
                "content": vr.document,
                "timestamp": metadata.get("timestamp", ""),
                "author": metadata.get("author", ""),
                "tags": metadata.get("services_modified", []),
                "metadata": {
                    "branch": metadata.get("branch", ""),
                    "jira_ticket_ids": metadata.get("jira_tickets", []),
                },
            }
        return None
    except Exception:
        return None


def _convert_chroma_raw(col_key: str, doc_id: str, doc_text: str, meta: dict) -> dict | None:
    """Convert raw ChromaDB result to frontend format."""
    type_map = {
        "slack": "slack",
        "meeting_notes": "meeting",
        "tech_docs": "technical",
        "jira": "jira",
        "commits": "commit",
        "incidents": "incident",
        "deployments": "deployment",
    }
    
    doc_type = type_map.get(col_key, "unknown")
    
    try:
        if doc_type == "slack":
            return {
                "id": meta.get("message_id", doc_id),
                "type": "slack",
                "title": f"{meta.get('author', 'Unknown')} in {meta.get('channel', 'unknown')}",
                "content": doc_text,
                "timestamp": meta.get("timestamp", ""),
                "author": meta.get("author", ""),
                "channel": meta.get("channel", ""),
                "tags": [],
                "metadata": {"employee_id": meta.get("employee_id", "")},
            }
        elif doc_type == "meeting":
            return {
                "id": meta.get("note_id", doc_id),
                "type": "meeting",
                "title": meta.get("title", "Meeting Note"),
                "content": doc_text[:1200],
                "timestamp": "",
                "tags": [],
                "metadata": {"filename": meta.get("filename", "")},
            }
        elif doc_type == "technical":
            return {
                "id": meta.get("doc_id", doc_id),
                "type": "technical",
                "title": meta.get("title", "Technical Document"),
                "content": doc_text[:1200],
                "timestamp": "",
                "tags": [],
                "metadata": {"filename": meta.get("filename", "")},
            }
        elif doc_type == "jira":
            return {
                "id": meta.get("ticket_id", doc_id),
                "type": "jira",
                "title": f"[{meta.get('ticket_id', doc_id)}] Ticket",
                "content": doc_text,
                "timestamp": meta.get("created_at", ""),
                "author": meta.get("assignee", ""),
                "tags": meta.get("related_services", []),
                "metadata": {
                    "status": meta.get("status", ""),
                    "priority": meta.get("priority", ""),
                    "type": meta.get("type", ""),
                    "assignee": meta.get("assignee", ""),
                },
            }
        elif doc_type == "commit":
            return {
                "id": meta.get("commit_id", doc_id),
                "type": "commit",
                "title": "Commit",
                "content": doc_text,
                "timestamp": meta.get("timestamp", ""),
                "author": meta.get("author", ""),
                "tags": meta.get("services_modified", []),
                "metadata": {
                    "branch": meta.get("branch", ""),
                    "jira_ticket_ids": meta.get("jira_tickets", []),
                },
            }
        return None
    except Exception:
        return None


# ── Timeline events endpoint ───────────────────────────────────────────────────

@router.get("/timeline")
async def get_timeline_events():
    """
    Return timeline events using hybrid approach:
    - Neo4j for relationships and timestamps
    - ChromaDB for semantic content (descriptions, messages, etc.)
    """
    from retrieval.retrieval.chroma_retriever import ChromaRetriever
    from retrieval.vector.chroma_client import get_or_create_collection
    from retrieval.schema.chroma_schema import COLLECTIONS
    
    try:
        events = []
        
        # Get timeline structure from Neo4j (relationships, timestamps)
        async with get_session() as session:
            # Incidents
            incident_cypher = """
                MATCH (i:Incident)
                OPTIONAL MATCH (i)-[:AFFECTS]->(s:Service)
                RETURN
                    i.incident_id AS id,
                    'incident' AS type,
                    i.started_at AS timestamp,
                    i.title AS title,
                    i.severity AS severity,
                    [s.name] AS affected_services,
                    i.ended_at AS ended_at
                ORDER BY i.started_at DESC
            """
            result = await session.run(incident_cypher)
            async for record in result:
                events.append({
                    "id": record["id"],
                    "type": "incident",
                    "timestamp": record["timestamp"],
                    "title": record["title"],
                    "description": "",  # Will fetch from ChromaDB
                    "severity": record["severity"],
                    "service": ", ".join(record["affected_services"]),
                    "status": "resolved" if record["ended_at"] else "active",
                    "metadata": {
                        "ended_at": record["ended_at"],
                        "affected_services": record["affected_services"],
                    },
                })

            # Deployments
            deployment_cypher = """
                MATCH (d:Deployment)-[:DEPLOYS]->(s:Service)
                OPTIONAL MATCH (d)-[:DEPLOYED_BY]->(e:Employee)
                RETURN
                    d.deployment_id AS id,
                    'deployment' AS type,
                    d.timestamp AS timestamp,
                    d.service AS service,
                    d.version AS version,
                    e.employee_id AS author,
                    d.status AS status,
                    d.environment AS environment,
                    d.target AS target,
                    d.rollback_of AS rollback_of,
                    d.source_commit_id AS source_commit_id
                ORDER BY d.timestamp DESC
                LIMIT 50
            """
            result = await session.run(deployment_cypher)
            async for record in result:
                events.append({
                    "id": record["id"],
                    "type": "deployment",
                    "timestamp": record["timestamp"],
                    "title": f"Deploy {record['service']} {record['version']}".strip(),
                    "description": "",  # Will fetch from ChromaDB
                    "service": record["service"],
                    "author": record["author"],
                    "status": record["status"],
                    "metadata": {
                        "environment": record["environment"],
                        "target": record["target"],
                        "rollback_of": record["rollback_of"],
                        "source_commit_id": record["source_commit_id"],
                    },
                })

            # Commits
            commit_cypher = """
                MATCH (c:Commit)
                OPTIONAL MATCH (c)-[:MODIFIES]->(s:Service)
                OPTIONAL MATCH (c)-[:AUTHORED_BY]->(e:Employee)
                RETURN
                    c.commit_id AS id,
                    'commit' AS type,
                    c.timestamp AS timestamp,
                    c.message AS title,
                    [s.name] AS services_modified,
                    e.name AS author,
                    c.branch AS branch,
                    [(c)-[:REFERENCES]->(t:JiraTicket) | t.ticket_id] AS jira_ticket_ids,
                    c.files_touched AS files_touched,
                    c.pull_request AS pull_request
                ORDER BY c.timestamp DESC
                LIMIT 50
            """
            result = await session.run(commit_cypher)
            async for record in result:
                pr = record["pull_request"]
                events.append({
                    "id": record["id"],
                    "type": "commit",
                    "timestamp": record["timestamp"],
                    "title": record["title"],
                    "description": "",  # Will fetch from ChromaDB
                    "service": ", ".join(record["services_modified"]),
                    "author": record["author"],
                    "status": "merged" if pr and pr.get("merged") else "open",
                    "metadata": {
                        "branch": record["branch"],
                        "jira_ticket_ids": record["jira_ticket_ids"],
                        "files_touched": record["files_touched"],
                        "pull_request": pr,
                    },
                })

            # Jira tickets
            jira_cypher = """
                MATCH (t:JiraTicket)
                OPTIONAL MATCH (t)-[:RELATES_TO]->(s:Service)
                OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(e:Employee)
                RETURN
                    t.ticket_id AS id,
                    'jira' AS type,
                    t.created_at AS timestamp,
                    t.summary AS title,
                    [s.name] AS related_services,
                    e.employee_id AS author,
                    t.status AS status,
                    t.priority AS severity,
                    t.type AS ticket_type,
                    e.employee_id AS assignee_employee_id,
                    [(t)-[:LINKED_TO]->(c:Commit) | c.commit_id] AS linked_commits
                ORDER BY t.created_at DESC
                LIMIT 30
            """
            result = await session.run(jira_cypher)
            async for record in result:
                events.append({
                    "id": record["id"],
                    "type": "jira",
                    "timestamp": record["timestamp"],
                    "title": f"[{record['id']}] {record['title']}",
                    "description": "",  # Will fetch from ChromaDB
                    "service": ", ".join(record["related_services"]),
                    "author": record["author"],
                    "status": record["status"],
                    "severity": record["severity"],
                    "metadata": {
                        "type": record["ticket_type"],
                        "assignee_employee_id": record["assignee_employee_id"],
                        "linked_commits": record["linked_commits"],
                    },
                })

        # Enrich with semantic content from ChromaDB
        chroma = ChromaRetriever()
        
        # Group events by type for batch ChromaDB queries
        incidents = [e for e in events if e["type"] == "incident"]
        commits = [e for e in events if e["type"] == "commit"]
        jira = [e for e in events if e["type"] == "jira"]
        deployments = [e for e in events if e["type"] == "deployment"]
        
        # Fetch incident descriptions from ChromaDB
        if incidents:
            try:
                collection = await get_or_create_collection(COLLECTIONS["incidents"].name)
                incident_ids = [e["id"] for e in incidents]
                response = await collection.get(
                    ids=incident_ids,
                    include=["documents"]
                )
                docs_map = dict(zip(response.get("ids", []), response.get("documents", [])))
                for e in incidents:
                    if e["id"] in docs_map:
                        e["description"] = docs_map[e["id"]]
            except Exception as exc:
                log.warning("Failed to fetch incident content from ChromaDB: %s", exc)
        
        # Fetch commit content from ChromaDB
        if commits:
            try:
                collection = await get_or_create_collection(COLLECTIONS["commits"].name)
                commit_ids = [e["id"] for e in commits]
                response = await collection.get(
                    ids=commit_ids,
                    include=["documents"]
                )
                docs_map = dict(zip(response.get("ids", []), response.get("documents", [])))
                for e in commits:
                    if e["id"] in docs_map:
                        e["description"] = docs_map[e["id"]]
            except Exception as exc:
                log.warning("Failed to fetch commit content from ChromaDB: %s", exc)
        
        # Fetch jira content from ChromaDB
        if jira:
            try:
                collection = await get_or_create_collection(COLLECTIONS["jira"].name)
                jira_ids = [e["id"] for e in jira]
                response = await collection.get(
                    ids=jira_ids,
                    include=["documents"]
                )
                docs_map = dict(zip(response.get("ids", []), response.get("documents", [])))
                for e in jira:
                    if e["id"] in docs_map:
                        e["description"] = docs_map[e["id"]]
            except Exception as exc:
                log.warning("Failed to fetch jira content from ChromaDB: %s", exc)
        
        # Fetch deployment content from ChromaDB
        if deployments:
            try:
                collection = await get_or_create_collection(COLLECTIONS["deployments"].name)
                deployment_ids = [e["id"] for e in deployments]
                response = await collection.get(
                    ids=deployment_ids,
                    include=["documents"]
                )
                docs_map = dict(zip(response.get("ids", []), response.get("documents", [])))
                for e in deployments:
                    if e["id"] in docs_map:
                        e["description"] = docs_map[e["id"]]
            except Exception as exc:
                log.warning("Failed to fetch deployment content from ChromaDB: %s", exc)

        # Sort all events by timestamp descending
        events.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return events

    except Exception as exc:
        log.error("[graph/timeline] Error: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc))
