'use client'

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import {
  Loader2, Send, Sparkles, ChevronDown, ChevronRight,
  AlertTriangle, FileText, MessageSquare, GitCommit, Ticket,
  CheckCircle2, XCircle, Clock, Zap, Network, Shield, Activity,
  Square, Plus,
} from 'lucide-react'

// ── Types ────────────────────────────────────────────────────────────────────

type AgentStep = {
  agent: string
  status: 'started' | 'completed' | 'error'
  summary: string
  timestamp: string
  node?: string
}

type ServiceRisk    = { name: string; risk_level: string; reason: string }
type TimelineEntry  = { timestamp: string; event: string; type: string; service: string | null }

type InvestigationReportData = {
  query: string
  risk_level: string
  summary: string
  synthesis: string
  graph_analysis: string
  incident_analysis: string
  risk_analysis: string
  affected_services: ServiceRisk[]
  timeline: TimelineEntry[]
  evidence: EvidenceItem[]
  recommendations: string[]
  sources: Array<{ id: string; source: string; rrf_score: number; collection?: string }>
}

type Message = {
  role: 'user' | 'assistant'
  content: string
  evidence?: EvidenceItem[]
  rootCause?: string
  report?: InvestigationReportData
  steps?: AgentStep[]
}

export type InvestigationChatMessage = Message

interface EvidenceItem {
  type: 'incident' | 'commit' | 'slack' | 'jira' | 'deployment' | 'service'
  id: string
  title: string
  snippet?: string
}

interface InvestigationChatProps {
  sessionId: string
  messages: Message[]
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>
  sessionContext: string
  setSessionContext: React.Dispatch<React.SetStateAction<string>>
  busy: boolean
  setBusy: React.Dispatch<React.SetStateAction<boolean>>
  abortRef: React.MutableRefObject<AbortController | null>
  onStartNewSession: () => void
  onHighlightServices?: (serviceNames: string[]) => void
  onQueryStart?: () => void
  focusedIncidentId?: string | null
}

// ── Minimal inline markdown renderer ──────────────────────────────────────────

function renderInline(text: string): React.ReactNode {
  const parts: React.ReactNode[] = []
  const regex = /(\*\*(.+?)\*\*|\*(.+?)\*|`([^`]+?)`)/g
  let last = 0, match: RegExpExecArray | null
  while ((match = regex.exec(text)) !== null) {
    if (match.index > last) parts.push(text.slice(last, match.index))
    if (match[0].startsWith('**'))
      parts.push(<strong key={match.index} className="font-semibold text-foreground">{match[2]}</strong>)
    else if (match[0].startsWith('*'))
      parts.push(<em key={match.index}>{match[3]}</em>)
    else
      parts.push(<code key={match.index} className="px-1 py-0.5 rounded bg-muted/60 font-mono text-[11px] text-cyan-300">{match[4]}</code>)
    last = match.index + match[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts.length === 0 ? text : parts
}

function MarkdownContent({ text }: { text: string }) {
  const lines = text.split('\n')
  const elems: React.ReactNode[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (/^#{1,3} /.test(line)) {
      const lvl = (line.match(/^(#+)/)?.[1].length ?? 1)
      elems.push(<p key={i} className={`font-semibold text-foreground ${lvl === 1 ? 'text-sm mt-2' : 'text-xs mt-1.5'}`}>{renderInline(line.replace(/^#+\s/, ''))}</p>)
    } else if (/^[-*] /.test(line)) {
      elems.push(<div key={i} className="flex gap-1.5 items-start"><span className="text-cyan-400 shrink-0 mt-0.5">•</span><span>{renderInline(line.slice(2))}</span></div>)
    } else if (/^\d+\.\s/.test(line)) {
      const num = line.match(/^(\d+)/)?.[1]
      elems.push(<div key={i} className="flex gap-1.5 items-start"><span className="text-cyan-400 shrink-0 font-mono text-[10px] mt-0.5">{num}.</span><span>{renderInline(line.replace(/^\d+\.\s/, ''))}</span></div>)
    } else if (line.startsWith('```')) {
      const codeLines: string[] = []; i++
      while (i < lines.length && !lines[i].startsWith('```')) { codeLines.push(lines[i]); i++ }
      elems.push(<pre key={i} className="mt-1 mb-1 rounded bg-muted/40 px-2 py-1.5 text-[10px] font-mono overflow-x-auto whitespace-pre-wrap">{codeLines.join('\n')}</pre>)
    } else if (/^-{3,}$/.test(line.trim())) {
      elems.push(<hr key={i} className="my-1 border-border/40" />)
    } else if (line.trim() === '') {
      elems.push(<div key={i} className="h-1" />)
    } else {
      elems.push(<p key={i} className="leading-relaxed">{renderInline(line)}</p>)
    }
    i++
  }
  return <div className="space-y-0.5 text-sm">{elems}</div>
}

// ── Constants ────────────────────────────────────────────────────────────────

const AGENT_ICONS: Record<string, React.ReactNode> = {
  context_agent:  <Sparkles className="h-3 w-3" />,
  orchestrator:   <Sparkles className="h-3 w-3" />,
  graph_agent:    <Network className="h-3 w-3" />,
  incident_agent: <Activity className="h-3 w-3" />,
  risk_agent:     <Shield className="h-3 w-3" />,
  retrieve:       <Zap className="h-3 w-3" />,
  synthesize:     <Sparkles className="h-3 w-3" />,
  query_analyzer: <Sparkles className="h-3 w-3" />,
}

const EVIDENCE_ICONS: Record<string, React.ReactNode> = {
  incident: <AlertTriangle className="h-3 w-3" />,
  commit: <GitCommit className="h-3 w-3" />,
  slack: <MessageSquare className="h-3 w-3" />,
  jira: <Ticket className="h-3 w-3" />,
  deployment: <FileText className="h-3 w-3" />,
  service: <Sparkles className="h-3 w-3" />,
}

const EVIDENCE_COLORS: Record<string, string> = {
  incident: 'text-red-400 border-red-500/30 bg-red-500/10',
  commit: 'text-green-400 border-green-500/30 bg-green-500/10',
  slack: 'text-indigo-400 border-indigo-500/30 bg-indigo-500/10',
  jira: 'text-amber-400 border-amber-500/30 bg-amber-500/10',
  deployment: 'text-blue-400 border-blue-500/30 bg-blue-500/10',
  service: 'text-cyan-400 border-cyan-500/30 bg-cyan-500/10',
}

const STARTER_QUESTIONS = [
  'What caused the LiDAR inference latency spike?',
  'Which services are most at risk from recent deployments?',
  'Summarize INC-001 root cause and timeline',
  'Who owns the edge-inference-service?',
]

function EvidencePanel({ items }: { items: EvidenceItem[] }) {
  const [open, setOpen] = useState(false)
  if (!items || items.length === 0) return null
  return (
    <div className="mt-2 border border-border/40 rounded-md overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground hover:bg-muted/30 transition-colors"
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        <span>{items.length} evidence reference{items.length !== 1 ? 's' : ''}</span>
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-1.5">
          {items.map((ev, i) => (
            <div
              key={i}
              className={`flex items-start gap-2 text-xs px-2 py-1.5 rounded border ${EVIDENCE_COLORS[ev.type] ?? ''}`}
            >
              <span className="mt-0.5 shrink-0">{EVIDENCE_ICONS[ev.type]}</span>
              <div className="min-w-0">
                <span className="font-mono font-medium">{ev.id}</span>
                {' — '}
                <span className="text-muted-foreground">{ev.title}</span>
                {ev.snippet && (
                  <p className="mt-1 text-muted-foreground/80 truncate">{ev.snippet}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function RootCausePanel({ text }: { text: string }) {
  return (
    <div className="mt-2 rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2">
      <div className="flex items-center gap-1.5 mb-1 text-xs font-medium text-amber-400">
        <AlertTriangle className="h-3 w-3" />
        Root Cause
      </div>
      <p className="text-xs text-muted-foreground leading-relaxed">{text}</p>
    </div>
  )
}

// ── Agent pipeline live progress ──────────────────────────────────────────────

function AgentPipeline({ steps, busy }: { steps: AgentStep[]; busy?: boolean }) {
  if (!steps || steps.length === 0) return null

  // Show only steps that have started. The last one is "active" while busy.
  const lastIdx = steps.length - 1

  return (
    <div className="mt-2 w-full min-w-0 self-stretch rounded-md border border-border/40 bg-card/40 p-3 space-y-1.5">
      <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">Agent Pipeline</p>
      {steps.map((step, i) => {
        const isLast   = i === lastIdx
        const isActive = busy && isLast && step.status !== 'completed' && step.status !== 'error'
        const label    = step.agent.replace('_agent', '').replace('_', ' ')
        return (
          <div key={i} className="flex items-start gap-2">
            <span className={`mt-0.5 ${
              step.status === 'completed' ? 'text-green-400'
              : step.status === 'error'   ? 'text-red-400'
              : isActive                  ? 'text-cyan-400'
              : 'text-muted-foreground/60'
            }`}>
              {isActive
                ? <Loader2 className="h-3 w-3 animate-spin" />
                : (AGENT_ICONS[step.agent] ?? <Clock className="h-3 w-3" />)}
            </span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className={`text-xs font-medium capitalize ${
                  step.status === 'completed' ? 'text-green-400'
                  : step.status === 'error'   ? 'text-red-400'
                  : isActive                  ? 'text-cyan-300'
                  : 'text-muted-foreground'
                }`}>{label}</span>
                {step.status === 'completed' && <CheckCircle2 className="h-3 w-3 text-green-400" />}
                {step.status === 'error'     && <XCircle className="h-3 w-3 text-red-400" />}
              </div>
              {step.summary && (
                <p className="mt-0.5 min-w-0 break-words text-[10px] text-muted-foreground/70 whitespace-normal">{step.summary}</p>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Investigation report card ─────────────────────────────────────────────────

function InvestigationReportCard({ report }: { report: InvestigationReportData }) {
  const hasTimeline = report.timeline?.length > 0
  const text = report.synthesis || report.summary || ''

  return (
    <div className="mt-2 rounded-lg border border-border/60 overflow-hidden bg-card/60 text-xs">
      {/* Response text */}
      {text && (
        <div className="px-3 py-3 text-sm text-foreground leading-relaxed">
          <MarkdownContent text={text} />
        </div>
      )}

      {/* Timeline — shown only when present */}
      {hasTimeline && (
        <div className="border-t border-border/30 px-3 py-2.5">
          <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">Timeline</p>
          <div className="space-y-1.5">
            {report.timeline.map((entry, i) => (
              <div key={i} className="flex flex-col gap-0.5 sm:flex-row sm:gap-2 sm:items-start">
                <span className="min-w-0 font-mono text-[10px] text-muted-foreground/60 break-all sm:mt-0.5">
                  {entry.timestamp}
                </span>
                <span className="min-w-0 text-xs text-muted-foreground">
                  {entry.event}
                  {entry.service && (
                    <span className="ml-1 font-mono text-cyan-400/80 text-[10px]">({entry.service})</span>
                  )}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function MessageBubble({ msg, isLive }: { msg: Message; isLive?: boolean }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`flex w-full min-w-0 ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      <div className={`min-w-0 max-w-[92%] ${isUser ? 'items-end' : 'items-start'} flex flex-col gap-2`}>
        <div className={`flex items-center gap-1.5 px-1 ${isUser ? 'text-cyan-200/80' : 'text-cyan-400'}`}>
          {isUser ? (
            <span className="h-1.5 w-1.5 rounded-full bg-cyan-300/70" />
          ) : (
            <Sparkles className="h-3 w-3" />
          )}
          <span className="text-[11px] font-medium">{isUser ? 'You' : 'NexusIQ'}</span>
        </div>
        {msg.content && (
          <div className={`min-w-0 max-w-full break-words rounded-2xl px-3 py-2.5 text-sm leading-relaxed shadow-sm ${
            isUser
              ? 'bg-cyan-500/18 border border-cyan-500/30 text-foreground'
              : 'bg-card/85 border border-border/60 text-foreground'
          }`}>
            {isUser ? msg.content : <MarkdownContent text={msg.content} />}
          </div>
        )}
        {msg.steps  && msg.steps.length > 0 && <AgentPipeline steps={msg.steps} busy={isLive} />}
        {msg.report && <InvestigationReportCard report={msg.report} />}
        {msg.rootCause && <RootCausePanel text={msg.rootCause} />}
        {msg.evidence && !msg.report && <EvidencePanel items={msg.evidence} />}
      </div>
    </div>
  )
}

export default function InvestigationChat({
  sessionId,
  messages,
  setMessages,
  sessionContext,
  setSessionContext,
  busy,
  setBusy,
  abortRef,
  onStartNewSession,
  onHighlightServices,
  onQueryStart,
  focusedIncidentId,
}: InvestigationChatProps) {
  const [input, setInput] = useState('')
  const endRef = useRef<HTMLDivElement>(null)
  const [stickToBottom, setStickToBottom] = useState(true)
  const viewportRef = useRef<HTMLDivElement>(null)
  const activeSessionRef = useRef(sessionId)
  const hasSessionContext = sessionContext.trim().length > 0

  useEffect(() => {
    activeSessionRef.current = sessionId
  }, [sessionId])

  useEffect(() => {
    if (!stickToBottom) return
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, busy, stickToBottom])

  const handleViewportScroll = () => {
    const el = viewportRef.current
    if (!el) return
    setStickToBottom((el.scrollHeight - el.clientHeight - el.scrollTop) < 40)
  }

  const canSend = useMemo(() => !!input.trim() && !busy, [input, busy])

  // ── Investigation workflow (LangGraph multi-agent) ─────────────────────────

  const sendInvestigation = useCallback(async (
    q: string,
    historySnapshot: Message[],
    sessionIdSnapshot: string,
    sessionContextSnapshot: string,
  ) => {
    const stepsIdx = historySnapshot.length   // index of the assistant bubble we'll update
    setMessages(prev => [...prev, { role: 'assistant', content: '', steps: [] }])

    const updateAssistantMessage = (updater: (current: Message) => Message) => {
      setMessages(prev => {
        if (activeSessionRef.current !== sessionIdSnapshot) {
          return prev
        }
        const next = [...prev]
        const current = next[stepsIdx] ?? { role: 'assistant', content: '', steps: [] }
        next[stepsIdx] = updater(current)
        return next
      })
    }

    const serializedHistory = historySnapshot
      .map((m): { role: 'user' | 'assistant'; content: string } | null => {
        const text = m.content ||
          (m.report ? (m.report.summary || m.report.synthesis || '').slice(0, 400) : '')
        return text ? { role: m.role, content: text.slice(0, 400) } : null
      })
      .filter((turn): turn is { role: 'user' | 'assistant'; content: string } => Boolean(turn))

    const historyWindow = sessionContextSnapshot
      ? serializedHistory.slice(-8)
      : serializedHistory.slice(-40)

    const controller = new AbortController()
    abortRef.current = controller

    let res: Response
    try {
      res = await fetch('/api/investigate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          query: q,
          history: historyWindow,
          sessionContext: sessionContextSnapshot,
        }),
      })
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        setMessages(prev => {
          if (activeSessionRef.current !== sessionIdSnapshot) {
            return prev
          }
          const next = [...prev]
          const current = next[stepsIdx] ?? { role: 'assistant', content: '', steps: [] }
          next[stepsIdx] = { ...current, role: 'assistant', content: '_(stopped)_', steps: current.steps ?? [] }
          return next
        })
        return
      }
      throw err
    }
    if (!res.ok || !res.body) throw new Error(`Investigation backend error: HTTP ${res.status}`)

    const reader  = res.body.getReader()
    const decoder = new TextDecoder()
    let lineBuf = '', currentEvent = ''
    const liveSteps: AgentStep[] = []

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      lineBuf += decoder.decode(value, { stream: true })
      const lines = lineBuf.split('\n'); lineBuf = lines.pop() ?? ''
      for (const line of lines) {
        if (line.startsWith('event: ')) { currentEvent = line.slice(7).trim() }
        else if (line.startsWith('data: ')) {
          try {
            const payload = JSON.parse(line.slice(6))
            if (currentEvent === 'investigation-signal') {
              // Show investigation mode in step list
              const step: AgentStep = {
                agent: 'orchestrator',
                status: 'completed',
                summary: payload.message ?? `Evidence: ${payload.decision} (${payload.depth} mode)`,
                timestamp: new Date().toISOString(),
                node: 'evaluate',
              }
              const idx = liveSteps.findIndex(s => s.node === 'evaluate')
              if (idx >= 0) liveSteps[idx] = step; else liveSteps.push(step)
              updateAssistantMessage(current => ({ ...current, role: 'assistant', steps: [...liveSteps] }))
            }
            if (currentEvent === 'step-update') {
              const step: AgentStep = { agent: payload.agent, status: payload.status, summary: payload.summary, timestamp: payload.timestamp, node: payload.node }
              const idx = liveSteps.findIndex(s => s.agent === step.agent)
              if (idx >= 0) liveSteps[idx] = step; else liveSteps.push(step)
              updateAssistantMessage(current => ({ ...current, role: 'assistant', steps: [...liveSteps] }))
            }
            if (currentEvent === 'investigation-complete' && payload.report) {
              const report: InvestigationReportData = payload.report
              if (onHighlightServices && report.affected_services?.length)
                onHighlightServices(report.affected_services.map(s => s.name))
              updateAssistantMessage(current => ({ ...current, role: 'assistant', steps: [...liveSteps], report }))
            }
            if (currentEvent === 'session-context-updated') {
              const nextContext = typeof payload.conversation_context === 'string'
                ? payload.conversation_context
                : ''
              if (activeSessionRef.current === sessionIdSnapshot) {
                setSessionContext(nextContext)
              }
            }
            if (currentEvent === 'error') throw new Error(payload.message ?? 'Investigation failed')
          } catch (e) { if (currentEvent === 'error') throw e }
        } else if (line === '') { currentEvent = '' }
      }
    }
  }, [abortRef, onHighlightServices, setMessages, setSessionContext])

  const send = async (overrideInput?: string) => {
    const q = (overrideInput ?? input).trim()
    if (!sessionId || !q || busy) return
    setInput('')
    onQueryStart?.()                             // clear graph highlights
    if (onHighlightServices) onHighlightServices([]) // clear previous service highlights
    // Build the next messages array and pass it as snapshot so sendInvestigation
    // doesn't need to capture the messages closure (avoids stale-state bugs).
    const next = [...messages, { role: 'user' as const, content: q }]
    setMessages(next)
    setBusy(true)
    try {
      await sendInvestigation(q, next, sessionId, sessionContext)
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') return
      console.error('[InvestigationChat]', err)
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'Investigation failed. Check the backend is running and try again.',
      }])
    } finally {
      abortRef.current = null
      setBusy(false)
    }
  }

  const stop = () => {
    abortRef.current?.abort()
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="h-full min-w-0 flex flex-col relative overflow-hidden bg-gradient-to-b from-background via-background to-card/20">

      {/* Header */}
      <div className="border-b border-border/60 bg-background/85 px-3 py-3 shrink-0 backdrop-blur-sm">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-cyan-400" />
              <span className="text-sm font-semibold text-cyan-400">AI Investigation</span>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="rounded-full border border-cyan-500/25 bg-cyan-500/10 px-2 py-0.5 text-[11px] text-cyan-200/90">
                Live session
              </span>
              <span className="rounded-full border border-border/60 bg-card/70 px-2 py-0.5 text-[11px] text-muted-foreground">
                {hasSessionContext ? 'Context retained' : 'Fresh session'}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <button
              onClick={onStartNewSession}
              title="New chat session"
              className="flex shrink-0 items-center gap-1 rounded-md border border-cyan-400/30 px-2 py-1 text-[11px] text-cyan-400/80 transition-colors hover:border-cyan-400/70 hover:bg-cyan-400/5 hover:text-cyan-300"
            >
              <Plus className="h-2.5 w-2.5" />
              New Chat
            </button>
          </div>
        </div>
        {focusedIncidentId && (
          <div className="mt-2 flex items-center gap-1.5 rounded-md border border-amber-500/30 bg-amber-500/10 px-2.5 py-1.5 text-xs text-amber-300">
            <AlertTriangle className="h-3 w-3" />
            Investigating: {focusedIncidentId}
          </div>
        )}
      </div>

      {/* Messages */}
      <div
        ref={viewportRef}
        onScroll={handleViewportScroll}
        className="flex-1 min-h-0 min-w-0 overflow-x-hidden overflow-y-auto"
      >
        <div className="flex min-h-full w-full min-w-0 flex-col px-3 py-4">
          {messages.length === 0 && (
            <div className="my-auto rounded-2xl border border-border/60 bg-card/65 p-4 shadow-sm">
              <div className="text-center py-2">
                <Sparkles className="mx-auto mb-3 h-8 w-8 text-cyan-400/50" />
                <p className="text-sm font-medium text-foreground">
                  Ask anything about incidents, services, or operational risks
                </p>
                <p className="mt-1 text-xs text-muted-foreground/70">
                  Graph · Incident · Risk agents run in parallel
                </p>
              </div>
              <div className="mt-4">
                <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground/70">
                  Suggested investigations
                </p>
                <div className="grid gap-2">
                {STARTER_QUESTIONS.map((q, i) => (
                  <button
                    key={i}
                    onClick={() => send(q)}
                    className="rounded-xl border border-border/50 bg-background/70 px-3 py-2.5 text-left text-xs text-muted-foreground transition-all hover:border-cyan-500/30 hover:bg-card hover:text-foreground"
                  >
                    {q}
                  </button>
                ))}
                </div>
              </div>
            </div>
          )}
          {messages.length > 0 && (
            <div className="space-y-1">
              {messages.map((msg, i) => (
                <MessageBubble key={i} msg={msg} isLive={busy && i === messages.length - 1} />
              ))}
              {busy && (
                <div className="mb-3 inline-flex max-w-full flex-wrap items-center gap-2 rounded-full border border-border/60 bg-card/70 px-3 py-1.5 text-xs text-muted-foreground/80 shadow-sm">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  <span>Investigation pipeline running…</span>
                </div>
              )}
            </div>
          )}
          <div ref={endRef} className="h-1 shrink-0" />
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-border/60 bg-background/90 p-3 shrink-0 backdrop-blur-sm">
        <div className="w-full min-w-0 rounded-2xl border border-border/60 bg-card/70 p-3 shadow-sm">
          <div className="flex items-end gap-2">
          <Textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Investigate an incident, service, or pattern..."
            className="min-h-[72px] max-h-[160px] resize-none border-0 bg-transparent px-0 py-0 text-sm shadow-none focus-visible:border-transparent focus-visible:ring-0"
            disabled={busy}
          />
          {busy ? (
            <Button
              onClick={stop}
              size="icon"
              variant="ghost"
              className="h-11 w-11 shrink-0 self-end rounded-xl border border-red-500/30 text-red-400 hover:bg-red-500/10 hover:text-red-300"
              title="Stop investigation"
            >
              <Square className="h-4 w-4 fill-current" />
            </Button>
          ) : (
            <Button
              onClick={() => send()}
              disabled={!canSend}
              size="icon"
              className="h-11 w-11 shrink-0 self-end rounded-xl bg-cyan-600 hover:bg-cyan-500"
            >
              <Send className="h-4 w-4" />
            </Button>
          )}
        </div>
          <p className="mt-2 text-xs text-muted-foreground">
            Shift+Enter for new line · Enter to send
          </p>
        </div>
      </div>
    </div>
  )
}
