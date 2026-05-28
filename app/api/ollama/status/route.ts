/**
 * GET /api/ollama/status
 *
 * Proxies to the FastAPI backend's health + models/status endpoints,
 * returning a combined status object the frontend AgentActivity component
 * can poll to show real model availability.
 */
import { NextResponse } from 'next/server'

const BACKEND_URL = process.env.OLLAMA_BACKEND_URL ?? 'http://localhost:8000'

export async function GET() {
  try {
    const [healthRes, modelsRes] = await Promise.all([
      fetch(`${BACKEND_URL}/health/ollama`, {
        signal: AbortSignal.timeout(5000),
      }),
      fetch(`${BACKEND_URL}/models/status`, {
        signal: AbortSignal.timeout(5000),
      }),
    ])

    const health = healthRes.ok ? await healthRes.json() : { status: 'error' }
    const models = modelsRes.ok ? await modelsRes.json() : { models: [], available_count: 0 }

    return NextResponse.json({ health, models })
  } catch (err) {
    return NextResponse.json(
      {
        health: { status: 'error', message: String(err) },
        models: { models: [], available_count: 0 },
      },
      { status: 503 },
    )
  }
}
