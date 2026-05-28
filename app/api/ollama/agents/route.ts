/**
 * POST /api/ollama/agents
 *
 * Proxy for single-agent inference.
 *
 * Request body:
 *   {
 *     agent_id: "orchestrator" | "graph" | "incident" | "risk",
 *     messages: [{ role, content }, ...],
 *     context?: string,
 *     stream?: boolean   (default: true)
 *   }
 *
 * When stream=true (default), returns SSE.
 * When stream=false, returns JSON { agent_id, model, content }.
 */
import { NextRequest } from 'next/server'

const BACKEND_URL = process.env.OLLAMA_BACKEND_URL ?? 'http://localhost:8000'

export const dynamic = 'force-dynamic'

const VALID_AGENTS = ['orchestrator', 'graph', 'incident', 'risk'] as const
type AgentId = (typeof VALID_AGENTS)[number]

export async function POST(req: NextRequest) {
  let body: Record<string, unknown>
  try {
    body = await req.json()
  } catch {
    return new Response('Invalid JSON body', { status: 400 })
  }

  const agentId = String(body.agent_id ?? 'orchestrator') as AgentId
  if (!VALID_AGENTS.includes(agentId)) {
    return new Response(
      JSON.stringify({ error: `Unknown agent '${agentId}'. Valid: ${VALID_AGENTS.join(', ')}` }),
      { status: 400, headers: { 'Content-Type': 'application/json' } },
    )
  }

  if (!Array.isArray(body.messages) || body.messages.length === 0) {
    return new Response('Missing "messages" array', { status: 400 })
  }

  const streaming = body.stream !== false // default true
  const endpoint = streaming
    ? `/agents/${agentId}/stream`
    : `/agents/${agentId}/invoke`

  const backendPayload = {
    messages: body.messages,
    context: body.context ?? '',
  }

  let backendRes: Response
  try {
    backendRes = await fetch(`${BACKEND_URL}${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(backendPayload),
      // @ts-expect-error – Node fetch duplex
      duplex: 'half',
    })
  } catch (err) {
    const message = `Ollama backend unreachable: ${String(err)}`
    if (streaming) {
      const errEvent = `event: error\ndata: ${JSON.stringify({ message })}\n\n`
      return new Response(errEvent, {
        status: 503,
        headers: { 'Content-Type': 'text/event-stream' },
      })
    }
    return new Response(JSON.stringify({ error: message }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  if (!backendRes.ok) {
    const text = await backendRes.text()
    if (streaming) {
      const errEvent = `event: error\ndata: ${JSON.stringify({ message: text })}\n\n`
      return new Response(errEvent, {
        status: backendRes.status,
        headers: { 'Content-Type': 'text/event-stream' },
      })
    }
    return new Response(text, {
      status: backendRes.status,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  if (streaming) {
    return new Response(backendRes.body, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
      },
    })
  }

  // Non-streaming: return JSON directly
  const data = await backendRes.json()
  return new Response(JSON.stringify(data), {
    headers: { 'Content-Type': 'application/json' },
  })
}


/**
 * GET /api/ollama/agents
 * List all available agents.
 */
export async function GET() {
  try {
    const res = await fetch(`${BACKEND_URL}/agents`, {
      signal: AbortSignal.timeout(5000),
    })
    const data = res.ok ? await res.json() : { agents: [] }
    return new Response(JSON.stringify(data), {
      headers: { 'Content-Type': 'application/json' },
    })
  } catch (err) {
    return new Response(JSON.stringify({ agents: [], error: String(err) }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    })
  }
}
