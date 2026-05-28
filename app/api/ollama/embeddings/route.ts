/**
 * POST /api/ollama/embeddings
 * Proxy for the embedding pipeline.
 */
import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.OLLAMA_BACKEND_URL ?? 'http://localhost:8000'

export async function POST(req: NextRequest) {
  let body: Record<string, unknown>
  try {
    body = await req.json()
  } catch {
    return new Response('Invalid JSON body', { status: 400 })
  }

  if (!Array.isArray(body.texts) || body.texts.length === 0) {
    return new Response('Missing "texts" array', { status: 400 })
  }

  try {
    const res = await fetch(`${BACKEND_URL}/embeddings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ texts: body.texts }),
      signal: AbortSignal.timeout(30000),
    })

    const data = res.ok ? await res.json() : await res.text()
    if (!res.ok) {
      return NextResponse.json({ error: data }, { status: res.status })
    }
    return NextResponse.json(data)
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 503 })
  }
}
