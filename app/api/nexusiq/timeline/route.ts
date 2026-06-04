import { NextResponse } from 'next/server'

const BACKEND = process.env.BACKEND_URL ?? 'http://backend-service'

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
    const res = await fetch(`${BACKEND}/graph/timeline`, {
      next: { revalidate: 60 },
    })
    if (!res.ok) {
      throw new Error(`Backend returned ${res.status}`)
    }
    const events: TimelineEvent[] = await res.json()
    return NextResponse.json(events)
  } catch (err) {
    console.error('[nexusiq/timeline]', err)
    return NextResponse.json({ error: 'Failed to load timeline from backend' }, { status: 500 })
  }
}
