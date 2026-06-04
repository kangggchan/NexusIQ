import { NextResponse } from 'next/server'

const BACKEND = process.env.BACKEND_URL ?? 'http://backend-service'

export async function GET() {
  try {
    const res = await fetch(`${BACKEND}/graph/visualization`, {
      next: { revalidate: 60 },
    })
    if (!res.ok) {
      throw new Error(`Backend returned ${res.status}`)
    }
    const data = await res.json()
    // Attach empty communities/reports so the visualizer stays happy
    return NextResponse.json({
      entities: data.entities ?? [],
      relationships: data.relationships ?? [],
      communities: data.communities ?? [],
      communityReports: data.communityReports ?? [],
    })
  } catch (err) {
    console.error('[nexusiq/graph]', err)
    return NextResponse.json({ error: 'Failed to load graph data from backend' }, { status: 500 })
  }
}
