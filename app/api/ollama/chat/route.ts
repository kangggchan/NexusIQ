/**
 * POST /api/ollama/chat
 *
 * Calls Ollama directly — no Python FastAPI backend required.
 *
 * Body:
 *   {
 *     messages:  [{ role, content }, ...]
 *     agent_id?: "orchestrator" | "graph" | "incident" | "risk"  (default: orchestrator)
 *     context?:  string   (prepended to the last user message)
 *   }
 *
 * Returns SSE stream compatible with InvestigationChat:
 *   step-start → answer-chunk (N) → step-end → done
 */
import { NextRequest } from 'next/server'

export const dynamic = 'force-dynamic'

const OLLAMA_HOST = process.env.OLLAMA_HOST ?? 'http://localhost:11434'

// ── Model assignments ─────────────────────────────────────────────────────────
const AGENT_MODELS: Record<string, string> = {
  orchestrator: process.env.MODEL_ORCHESTRATOR ?? 'llama3.1:8b',
  graph:        process.env.MODEL_GRAPH        ?? 'qwen2.5:7b',
  incident:     process.env.MODEL_INCIDENT     ?? 'llama3.1:8b',
  risk:         process.env.MODEL_RISK         ?? 'gemma3:12b',
}

// ── System prompts ────────────────────────────────────────────────────────────
const SYSTEM_PROMPTS: Record<string, string> = {
  orchestrator: `You are the NexusIQ Orchestrator — an expert SRE investigation coordinator for NovaDrive AI.
Responsibilities:
1. Understand the investigation question and decompose it into findings.
2. Synthesize evidence into a concise, actionable root-cause analysis.
3. Cite relevant services (e.g. payment-service), incident IDs (e.g. INC-001), and team members when present in context.
Output format: one-sentence summary → bullet evidence → "Recommended Actions" (numbered, max 5).`,

  graph: 'You are the NexusIQ Graph Agent — a service dependency analysis expert for NovaDrive AI.\nResponsibilities:\n1. Analyze service-to-service dependencies and critical paths.\n2. Determine blast radius when a given service fails.\n3. Identify single points of failure and over-coupled services.\nAlways name specific services, dependency types, and quantify impact.',

  incident: 'You are the NexusIQ Incident Agent — an incident timeline and root-cause specialist for NovaDrive AI.\nStructure every analysis as:\n- Timeline: key events in chronological order\n- Root Cause: primary technical cause\n- Contributing Factors: secondary issues\n- Impact: affected services and users\n- Resolution: how it was fixed (if known)',

  risk: 'You are the NexusIQ Risk Analyst — a deployment risk and reliability expert for NovaDrive AI.\nOutput:\n- Risk Score: Low / Medium / High / Critical (with justification)\n- Blast Radius: affected services and estimated user impact\n- Risk Factors: specific technical or procedural concerns\n- Mitigation: concrete steps to reduce risk',
}

type OllamaMessage = { role: string; content: string }

function sseChunk(event: string, data: unknown): string {
  return 'event: ' + event + '\ndata: ' + JSON.stringify(data) + '\n\n'
}

export async function POST(req: NextRequest) {
  let body: Record<string, unknown>
  try {
    body = await req.json()
  } catch {
    return new Response('Invalid JSON body', { status: 400 })
  }

  const agentId = String(body.agent_id ?? 'orchestrator')
  const userMessages = Array.isArray(body.messages) ? (body.messages as OllamaMessage[]) : []
  const context = String(body.context ?? '')

  if (userMessages.length === 0) {
    return new Response('Missing "messages" array', { status: 400 })
  }

  const model = AGENT_MODELS[agentId] ?? AGENT_MODELS.orchestrator
  const systemPrompt = SYSTEM_PROMPTS[agentId] ?? SYSTEM_PROMPTS.orchestrator

  // Build message list with system prompt, injecting context above last user msg
  const ollamaMessages: OllamaMessage[] = [
    { role: 'system', content: systemPrompt },
    ...userMessages,
  ]

  if (context) {
    for (let i = ollamaMessages.length - 1; i >= 0; i--) {
      if (ollamaMessages[i].role === 'user') {
        ollamaMessages[i] = {
          role: 'user',
          content: `[Context]\n${context}\n\n[Question]\n${ollamaMessages[i].content}`,
        }
        break
      }
    }
  }

  // Call Ollama streaming chat
  let ollamaRes: Response
  try {
    ollamaRes = await fetch(`${OLLAMA_HOST}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model,
        messages: ollamaMessages,
        stream: true,
        options: { temperature: 0.7, num_predict: 2048 },
      }),
    })
  } catch (err) {
    const errMsg = `Ollama unreachable at ${OLLAMA_HOST}: ${String(err)}`
    return new Response(`event: error\ndata: ${JSON.stringify({ message: errMsg })}\n\n`, {
      status: 503,
      headers: { 'Content-Type': 'text/event-stream' },
    })
  }

  if (!ollamaRes.ok || !ollamaRes.body) {
    const text = await ollamaRes.text().catch(() => ollamaRes.statusText)
    return new Response(
      `event: error\ndata: ${JSON.stringify({ message: `Ollama error ${ollamaRes.status}: ${text}` })}\n\n`,
      { status: 502, headers: { 'Content-Type': 'text/event-stream' } },
    )
  }

  // Convert Ollama NDJSON stream → SSE answer-chunk events
  const encoder = new TextEncoder()
  const readable = new ReadableStream<Uint8Array>({
    async start(controller) {
      const send = (event: string, data: unknown) =>
        controller.enqueue(encoder.encode(sseChunk(event, data)))

      send('step-start', { name: 'inference', agent: agentId, at: Date.now() })

      try {
        const reader = ollamaRes.body!.getReader()
        const decoder = new TextDecoder()
        let buf = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })
          const lines = buf.split('\n')
          buf = lines.pop() ?? ''

          for (const line of lines) {
            const trimmed = line.trim()
            if (!trimmed) continue
            try {
              const chunk = JSON.parse(trimmed)
              const text: string = chunk?.message?.content ?? ''
              if (text) send('answer-chunk', { text })
            } catch { /* skip malformed NDJSON lines */ }
          }
        }
      } catch (err) {
        send('error', { message: String(err) })
      }

      send('step-end', { name: 'inference', agent: agentId, at: Date.now() })
      send('done', { at: Date.now() })
      controller.close()
    },
  })

  return new Response(readable, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'X-Accel-Buffering': 'no',
    },
  })
}

