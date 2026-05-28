import { NextResponse } from 'next/server'
import path from 'node:path'
import fs from 'node:fs/promises'

const BACKEND   = process.env.OLLAMA_BACKEND_URL ?? 'http://localhost:8000'
const DATA_DIR  = path.join(process.cwd(), 'data', 'nexusiq_dataset')

async function readJson<T>(filename: string): Promise<T> {
  const raw = await fs.readFile(path.join(DATA_DIR, filename), 'utf-8')
  return JSON.parse(raw) as T
}

export async function GET() {
  // ── Primary: live Neo4j data via FastAPI ──────────────────────────────────
  try {
    const res = await fetch(`${BACKEND}/graph/visualization`, {
      next: { revalidate: 60 },   // cache for 60 s to avoid hammering Neo4j
    })
    if (res.ok) {
      const data = await res.json()
      // Attach empty communities/reports so the visualizer stays happy
      return NextResponse.json({
        entities:         data.entities        ?? [],
        relationships:    data.relationships   ?? [],
        communities:      data.communities     ?? [],
        communityReports: data.communityReports ?? [],
      })
    }
    console.warn('[nexusiq/graph] Neo4j backend returned', res.status, '— falling back to JSON')
  } catch (err) {
    console.warn('[nexusiq/graph] Neo4j backend unreachable — falling back to JSON:', err)
  }

  // ── Fallback: static JSON files (used when backend is down) ───────────────
  try {
    const [servicesData, employeeData, relationshipsData, incidentsData] = await Promise.all([
      readJson<{ services: Array<Record<string, unknown>> }>('services.json'),
      readJson<{ employees: Array<Record<string, unknown>> }>('employee_db.json'),
      readJson<{ relationships: Array<Record<string, unknown>> }>('graph_relationships.json'),
      readJson<{ incidents: Array<Record<string, unknown>> }>('incidents.json'),
    ])

    // Build entities: services + employees
    const entities: Record<string, unknown>[] = []
    const entityIdMap = new Map<string, number>() // for human_readable_id
    let hrid = 0

    for (const svc of servicesData.services) {
      const id = String(svc.service_id)
      entityIdMap.set(id, hrid)
      const deps = Array.isArray(svc.dependencies) ? (svc.dependencies as string[]) : []
      entities.push({
        id,
        human_readable_id: String(hrid++),
        title: String(svc.name ?? id),
        type: 'SERVICE',
        description: String(svc.description ?? ''),
        text_unit_ids: [],
        frequency: deps.length + 1,
        degree: deps.length + 1,
      })
    }

    for (const emp of employeeData.employees) {
      const id = String(emp.employee_id)
      entityIdMap.set(id, hrid)
      const owned = Array.isArray(emp.owned_services) ? (emp.owned_services as string[]) : []
      entities.push({
        id,
        human_readable_id: String(hrid++),
        title: String(emp.name ?? id),
        type: 'EMPLOYEE',
        description: `${String(emp.role ?? '')} — ${String(emp.specialization ?? '')}`,
        text_unit_ids: [],
        frequency: owned.length + 1,
        degree: owned.length + 1,
      })
    }

    // Build relationships from graph_relationships.json
    const relationships: Record<string, unknown>[] = []
    let relId = 0

    for (const rel of relationshipsData.relationships) {
      const from = String(rel.from)
      const to = String(rel.to)
      const type = String(rel.type)

      // Map IDs: service names may not match IDs directly — normalise to service_id
      const resolvedFrom = from
      const resolvedTo = to

      const weight = type === 'SERVICE_DEPENDS_ON' ? 3 : 2

      relationships.push({
        id: String(relId),
        human_readable_id: String(relId++),
        source: resolvedFrom,
        target: resolvedTo,
        description: type.replace(/_/g, ' ').toLowerCase(),
        weight,
        combined_degree: weight,
        text_unit_ids: [],
      })
    }

    // Add INCIDENT_AFFECTS_SERVICE edges
    for (const inc of incidentsData.incidents) {
      const affected = Array.isArray(inc.affected_services) ? (inc.affected_services as string[]) : []
      for (const svcName of affected) {
        // Find the service entity whose title matches
        const svcEntity = entities.find(e => String(e.title) === svcName && e.type === 'SERVICE')
        if (!svcEntity) continue
        relationships.push({
          id: String(relId),
          human_readable_id: String(relId++),
          source: String(inc.incident_id),
          target: String(svcEntity.id),
          description: `incident affects service`,
          weight: 1,
          combined_degree: 1,
          text_unit_ids: [],
        })
      }
    }

    // Single flat community grouping by team
    const teamMap = new Map<string, string[]>()
    for (const emp of employeeData.employees) {
      const team = String(emp.team ?? 'Unassigned')
      if (!teamMap.has(team)) teamMap.set(team, [])
      const owned = Array.isArray(emp.owned_services) ? (emp.owned_services as string[]) : []
      teamMap.get(team)!.push(String(emp.employee_id), ...owned)
    }

    const communities: Record<string, unknown>[] = []
    let commId = 0
    for (const [team, memberIds] of teamMap.entries()) {
      const memberEntities = entities
        .filter(e => memberIds.includes(String(e.id)))
        .map(e => String(e.id))
      communities.push({
        id: String(commId),
        human_readable_id: commId,
        community: String(commId),
        level: 0,
        parent: undefined,
        children: [],
        title: team,
        entity_ids: memberEntities,
        relationship_ids: [],
        text_unit_ids: [],
        period: '2026',
        size: memberEntities.length,
      })
      commId++
    }

    return NextResponse.json({ entities, relationships, communities, communityReports: [] })
  } catch (err) {
    console.error('[nexusiq/graph]', err)
    return NextResponse.json({ error: 'Failed to build graph data' }, { status: 500 })
  }
}
