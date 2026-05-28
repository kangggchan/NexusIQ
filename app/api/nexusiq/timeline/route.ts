import { NextResponse } from 'next/server'
import path from 'node:path'
import fs from 'node:fs/promises'

const DATA_DIR = path.join(process.cwd(), 'data', 'nexusiq_dataset')

async function readJson<T>(filename: string): Promise<T> {
  const raw = await fs.readFile(path.join(DATA_DIR, filename), 'utf-8')
  return JSON.parse(raw) as T
}

export interface TimelineEvent {
  id: string
  type: 'incident' | 'deployment' | 'commit' | 'jira' | 'slack'
  timestamp: string
  title: string
  description: string
  severity?: string
  service?: string
  author?: string
  status?: string
  url?: string
  metadata?: Record<string, unknown>
}

export async function GET() {
  try {
    const [incidentsData, deploymentsData, commitsData, jiraData] = await Promise.all([
      readJson<{ incidents: Array<Record<string, unknown>> }>('incidents.json'),
      readJson<{ deployments: Array<Record<string, unknown>> }>('deployment_logs.json'),
      readJson<{ commits: Array<Record<string, unknown>> }>('github_commits.json'),
      readJson<{ tickets: Array<Record<string, unknown>> }>('jira_tickets.json'),
    ])

    const events: TimelineEvent[] = []

    // Incidents
    for (const inc of incidentsData.incidents) {
      events.push({
        id: String(inc.incident_id),
        type: 'incident',
        timestamp: String(inc.started_at),
        title: String(inc.title),
        description: String(inc.root_cause ?? ''),
        severity: String(inc.severity ?? ''),
        service: Array.isArray(inc.affected_services)
          ? (inc.affected_services as string[]).join(', ')
          : '',
        status: inc.ended_at ? 'resolved' : 'active',
        metadata: {
          ended_at: inc.ended_at,
          affected_services: inc.affected_services,
          mitigation_steps: inc.mitigation_steps,
        },
      })
    }

    // Deployments
    for (const dep of deploymentsData.deployments) {
      events.push({
        id: String(dep.deployment_id),
        type: 'deployment',
        timestamp: String(dep.timestamp),
        title: `Deploy ${String(dep.service)} ${String(dep.service_version ?? '')}`.trim(),
        description: String(dep.notes ?? ''),
        service: String(dep.service ?? ''),
        author: String(dep.initiated_by_employee_id ?? ''),
        status: String(dep.status ?? ''),
        metadata: {
          environment: dep.environment,
          target: dep.target,
          rollback_of: dep.rollback_of,
          source_commit_id: dep.source_commit_id,
        },
      })
    }

    // Commits (sample recent 50 to keep payload manageable)
    const recentCommits = commitsData.commits.slice(0, 50)
    for (const commit of recentCommits) {
      const services = Array.isArray(commit.services_modified)
        ? (commit.services_modified as string[]).join(', ')
        : ''
      events.push({
        id: String(commit.short_commit_id ?? commit.commit_id),
        type: 'commit',
        timestamp: String(commit.timestamp),
        title: String(commit.message ?? ''),
        description: String(commit.change_notes ?? ''),
        service: services,
        author: String(commit.author_name ?? ''),
        status: (commit.pull_request as Record<string, unknown>)?.merged ? 'merged' : 'open',
        metadata: {
          branch: commit.branch,
          jira_ticket_ids: commit.jira_ticket_ids,
          files_touched: commit.files_touched,
          pull_request: commit.pull_request,
        },
      })
    }

    // Jira tickets (recent 30)
    const recentTickets = jiraData.tickets.slice(0, 30)
    for (const ticket of recentTickets) {
      events.push({
        id: String(ticket.ticket_id),
        type: 'jira',
        timestamp: String(ticket.created_at),
        title: `[${String(ticket.ticket_id)}] ${String(ticket.summary)}`,
        description: String(ticket.description ?? ''),
        service: Array.isArray(ticket.related_services)
          ? (ticket.related_services as string[]).join(', ')
          : '',
        author: String(ticket.reporter_employee_id ?? ''),
        status: String(ticket.status ?? ''),
        severity: String(ticket.priority ?? ''),
        metadata: {
          type: ticket.type,
          assignee_employee_id: ticket.assignee_employee_id,
          linked_commits: ticket.linked_commits,
        },
      })
    }

    // Sort all events by timestamp descending
    events.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())

    return NextResponse.json(events)
  } catch (err) {
    console.error('[nexusiq/timeline]', err)
    return NextResponse.json({ error: 'Failed to load timeline' }, { status: 500 })
  }
}
