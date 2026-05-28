import { NextRequest, NextResponse } from 'next/server'
import path from 'node:path'
import fs from 'node:fs/promises'

const DATA_DIR = path.join(process.cwd(), 'data', 'nexusiq_dataset')

export interface ContextDocument {
  id: string
  type: 'slack' | 'jira' | 'commit' | 'meeting' | 'technical'
  title: string
  content: string
  timestamp?: string
  author?: string
  channel?: string
  tags?: string[]
  metadata?: Record<string, unknown>
}

async function readJson<T>(filepath: string): Promise<T> {
  const raw = await fs.readFile(filepath, 'utf-8')
  return JSON.parse(raw) as T
}

async function loadSlackMessages(): Promise<ContextDocument[]> {
  const slackDir = path.join(DATA_DIR, 'slack_logs')
  const files = await fs.readdir(slackDir)
  const docs: ContextDocument[] = []

  for (const file of files.filter(f => f.endsWith('.json'))) {
    const data = await readJson<{ channel: string; messages: Array<Record<string, unknown>> }>(
      path.join(slackDir, file)
    )
    for (const msg of data.messages.slice(0, 20)) {
      docs.push({
        id: String(msg.message_id ?? `slack-${docs.length}`),
        type: 'slack',
        title: `${String(msg.employee_name ?? '')} in ${String(msg.channel ?? data.channel)}`,
        content: String(msg.text ?? ''),
        timestamp: String(msg.timestamp ?? ''),
        author: String(msg.employee_name ?? ''),
        channel: String(msg.channel ?? data.channel),
        tags: [
          ...((msg.referenced_tickets as string[]) ?? []),
          ...((msg.referenced_services as string[]) ?? []),
        ],
        metadata: {
          referenced_commits: msg.referenced_commits,
          referenced_incidents: msg.referenced_incidents,
          employee_id: msg.employee_id,
        },
      })
    }
  }

  return docs
}

async function loadMeetingNotes(): Promise<ContextDocument[]> {
  const meetingDir = path.join(DATA_DIR, 'meeting_notes')
  const files = await fs.readdir(meetingDir)
  const docs: ContextDocument[] = []

  for (const file of files.filter(f => f.endsWith('.md'))) {
    const content = await fs.readFile(path.join(meetingDir, file), 'utf-8')
    const dateMatch = file.match(/^(\d{4}-\d{2}-\d{2})/)
    const timestamp = dateMatch ? `${dateMatch[1]}T00:00:00Z` : ''
    // Extract first heading as title
    const titleMatch = content.match(/^#\s+(.+)/m)
    const title = titleMatch ? titleMatch[1] : file.replace('.md', '').replace(/_/g, ' ')

    docs.push({
      id: `meeting-${file}`,
      type: 'meeting',
      title,
      content: content.slice(0, 1200), // preview
      timestamp,
      tags: [],
      metadata: { filename: file },
    })
  }

  return docs
}

async function loadTechnicalDocs(): Promise<ContextDocument[]> {
  const techDir = path.join(DATA_DIR, 'technical_documents')
  const files = await fs.readdir(techDir)
  const docs: ContextDocument[] = []

  for (const file of files.filter(f => f.endsWith('.md'))) {
    const content = await fs.readFile(path.join(techDir, file), 'utf-8')
    const titleMatch = content.match(/^#\s+(.+)/m)
    const title = titleMatch ? titleMatch[1] : file.replace('.md', '').replace(/_/g, ' ')

    docs.push({
      id: `tech-${file}`,
      type: 'technical',
      title,
      content: content.slice(0, 1200),
      tags: [],
      metadata: { filename: file },
    })
  }

  return docs
}

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url)
    const filter = searchParams.get('type') // 'slack'|'meeting'|'technical'|'jira'|'commit'|null
    const query = searchParams.get('q')?.toLowerCase() ?? ''

    const [slackDocs, meetingDocs, techDocs, jiraData, commitsData] = await Promise.all([
      (!filter || filter === 'slack') ? loadSlackMessages() : Promise.resolve([]),
      (!filter || filter === 'meeting') ? loadMeetingNotes() : Promise.resolve([]),
      (!filter || filter === 'technical') ? loadTechnicalDocs() : Promise.resolve([]),
      (!filter || filter === 'jira')
        ? readJson<{ tickets: Array<Record<string, unknown>> }>(path.join(DATA_DIR, 'jira_tickets.json'))
        : Promise.resolve({ tickets: [] }),
      (!filter || filter === 'commit')
        ? readJson<{ commits: Array<Record<string, unknown>> }>(path.join(DATA_DIR, 'github_commits.json'))
        : Promise.resolve({ commits: [] }),
    ])

    let docs: ContextDocument[] = [...slackDocs, ...meetingDocs, ...techDocs]

    // Jira tickets
    for (const ticket of (jiraData.tickets ?? []).slice(0, 20)) {
      docs.push({
        id: String(ticket.ticket_id),
        type: 'jira',
        title: `[${String(ticket.ticket_id)}] ${String(ticket.summary)}`,
        content: String(ticket.description ?? ''),
        timestamp: String(ticket.created_at ?? ''),
        author: String(ticket.reporter_employee_id ?? ''),
        tags: Array.isArray(ticket.related_services) ? (ticket.related_services as string[]) : [],
        metadata: {
          status: ticket.status,
          priority: ticket.priority,
          type: ticket.type,
          assignee: ticket.assignee_employee_id,
        },
      })
    }

    // Commits
    for (const commit of (commitsData.commits ?? []).slice(0, 20)) {
      docs.push({
        id: String(commit.short_commit_id ?? commit.commit_id),
        type: 'commit',
        title: String(commit.message ?? ''),
        content: `${String(commit.change_notes ?? '')}\nFiles: ${((commit.files_touched as string[]) ?? []).join(', ')}`,
        timestamp: String(commit.timestamp ?? ''),
        author: String(commit.author_name ?? ''),
        tags: Array.isArray(commit.services_modified) ? (commit.services_modified as string[]) : [],
        metadata: {
          branch: commit.branch,
          jira_ticket_ids: commit.jira_ticket_ids,
          pull_request: commit.pull_request,
        },
      })
    }

    // Apply text filter
    if (query) {
      docs = docs.filter(d =>
        d.title.toLowerCase().includes(query) ||
        d.content.toLowerCase().includes(query) ||
        (d.tags ?? []).some(t => t.toLowerCase().includes(query))
      )
    }

    // Sort by timestamp descending
    docs.sort((a, b) => {
      const ta = a.timestamp ? new Date(a.timestamp).getTime() : 0
      const tb = b.timestamp ? new Date(b.timestamp).getTime() : 0
      return tb - ta
    })

    return NextResponse.json(docs)
  } catch (err) {
    console.error('[nexusiq/context]', err)
    return NextResponse.json({ error: 'Failed to load context documents' }, { status: 500 })
  }
}
