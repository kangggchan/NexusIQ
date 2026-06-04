import { NextRequest, NextResponse } from 'next/server'

const BACKEND = process.env.BACKEND_URL ?? 'http://backend-service'

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

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url)
    const filter = searchParams.get('type') // 'slack'|'meeting'|'technical'|'jira'|'commit'|null
    const query = searchParams.get('q') ?? ''

    const url = new URL(`${BACKEND}/graph/context`)
    if (filter) url.searchParams.set('doc_type', filter)
    if (query) url.searchParams.set('query', query)

    const res = await fetch(url.toString(), {
      next: { revalidate: 60 },
    })
    if (!res.ok) {
      throw new Error(`Backend returned ${res.status}`)
    }
    const docs: ContextDocument[] = await res.json()
    return NextResponse.json(docs)
  } catch (err) {
    console.error('[nexusiq/context]', err)
    return NextResponse.json({ error: 'Failed to load context documents from backend' }, { status: 500 })
  }
}
