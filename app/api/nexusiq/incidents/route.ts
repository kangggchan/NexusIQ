import { NextResponse } from 'next/server'

const BACKEND = process.env.BACKEND_URL ?? 'http://backend-service'

export async function GET() {
  try {
    const res = await fetch(`${BACKEND}/graph/incidents`, {
      next: { revalidate: 60 },
    })
    if (!res.ok) {
      throw new Error(`Backend returned ${res.status}`)
    }
    const data = await res.json()
    return NextResponse.json(data.incidents ?? [])
  } catch (err) {
    console.error('[nexusiq/incidents]', err)
    return NextResponse.json({ error: 'Failed to load incidents from backend' }, { status: 500 })
  }
}
