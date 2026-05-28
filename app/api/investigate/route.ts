import { NextRequest } from "next/server";

const BACKEND = process.env.OLLAMA_BACKEND_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const body = await req.json();

  if (!body.query?.trim()) {
    return new Response(JSON.stringify({ error: "query is required" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND}/investigation/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: body.query, history: body.history ?? [] }),
    });
  } catch {
    return new Response(
      JSON.stringify({ error: "Investigation backend unreachable" }),
      { status: 503, headers: { "Content-Type": "application/json" } }
    );
  }

  if (!upstream.ok || !upstream.body) {
    const text = await upstream.text().catch(() => "");
    return new Response(
      JSON.stringify({ error: `Backend error ${upstream.status}`, detail: text }),
      { status: upstream.status, headers: { "Content-Type": "application/json" } }
    );
  }

  // Proxy the SSE stream directly to the client
  return new Response(upstream.body, {
    headers: {
      "Content-Type":     "text/event-stream",
      "Cache-Control":    "no-cache",
      "X-Accel-Buffering": "no",
      "Connection":       "keep-alive",
    },
  });
}
