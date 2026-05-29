'use client'

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Loader2, Send, Sparkles, ChevronDown, ChevronRight,
  AlertTriangle, FileText, MessageSquare, GitCommit, Ticket,
  CheckCircle2, XCircle, Clock, Zap, Network, Shield, Activity,
  Square, Plus, History, Trash2, X,
} from 'lucide-react'
import {
  type SessionMeta,
  createSession, getActiveSessionId, setActiveSessionId,
  getAllSessions, getSessionMessages, saveSessionMessages, deleteSession,
  formatSessionDate,
} from '@/lib/chatSessionStore'

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

interface EvidenceItem {
  type: 'incident' | 'commit' | 'slack' | 'jira' | 'deployment' | 'service'
  id: string
  title: string
  snippet?: string
}

interface InvestigationChatProps {
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
    <div className="mt-2 rounded-md border border-border/40 bg-card/40 p-3 space-y-1.5">
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
                <p className="text-[10px] text-muted-foreground/70 mt-0.5 truncate">{step.summary}</p>
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
              <div key={i} className="flex gap-2 items-start">
                <span className="font-mono text-[10px] text-muted-foreground/60 shrink-0 mt-0.5 w-36 truncate">
                  {entry.timestamp}
                </span>
                <span className="text-xs text-muted-foreground">
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
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-3`}>
      <div className={`max-w-[92%] ${isUser ? 'items-end' : 'items-start'} flex flex-col`}>
        {!isUser && (
          <div className="flex items-center gap-1.5 mb-1">
            <Sparkles className="h-3 w-3 text-cyan-400" />
            <span className="text-xs font-medium text-cyan-400">NexusIQ</span>
          </div>
        )}
        {msg.content && (
          <div className={`rounded-lg px-3 py-2 text-sm leading-relaxed ${
            isUser
              ? 'bg-cyan-500/20 border border-cyan-500/30 text-foreground'
              : 'bg-card border border-border/50 text-foreground'
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

export default function InvestigationChat({ onHighlightServices, onQueryStart, focusedIncidentId }: InvestigationChatProps) {
  // ── Session state ─────────────────────────────────────────────────────────
  const [sessionId, setSessionId] = useState<string>(() => {
    if (typeof window === 'undefined') return ''
    const active = getActiveSessionId()
    if (active) return active
    return createSession().id
  })
  const [sessions, setSessions] = useState<SessionMeta[]>(() => {
    if (typeof window === 'undefined') return []
    return getAllSessions()
  })
  const [showHistory, setShowHistory] = useState(false)

  const [messages, setMessages] = useState<Message[]>(() => {
    if (typeof window === 'undefined') return []
    const active = getActiveSessionId()
    if (!active) return []
    return getSessionMessages(active) as Message[]
  })

  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const [stickToBottom, setStickToBottom] = useState(true)
  const viewportRef = useRef<HTMLDivElement>(null)

  // Persist messages to localStorage after every update
  useEffect(() => {
    if (!sessionId) return
    saveSessionMessages(sessionId, messages as Parameters<typeof saveSessionMessages>[1])
    setSessions(getAllSessions())
  }, [messages, sessionId])

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

  const sendInvestigation = useCallback(async (q: string, historySnapshot: Message[]) => {
    const stepsIdx = historySnapshot.length   // index of the assistant bubble we'll update
    setMessages(prev => [...prev, { role: 'assistant', content: '', steps: [] }])

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
          history: historySnapshot
            .map(m => {
              const text = m.content ||
                (m.report ? (m.report.summary || m.report.synthesis || '').slice(0, 400) : '')
              return text ? { role: m.role, content: text.slice(0, 400) } : null
            })
            .filter(Boolean)
            .slice(-10),
        }),
      })
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        setMessages(prev => { const u = [...prev]; u[stepsIdx] = { role: 'assistant', content: '_(stopped)_', steps: u[stepsIdx]?.steps ?? [] }; return u })
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
              setMessages(prev => { const u = [...prev]; u[stepsIdx] = { role: 'assistant', content: '', steps: [...liveSteps] }; return u })
            }
            if (currentEvent === 'step-update') {
              const step: AgentStep = { agent: payload.agent, status: payload.status, summary: payload.summary, timestamp: payload.timestamp, node: payload.node }
              const idx = liveSteps.findIndex(s => s.agent === step.agent)
              if (idx >= 0) liveSteps[idx] = step; else liveSteps.push(step)
              setMessages(prev => { const u = [...prev]; u[stepsIdx] = { role: 'assistant', content: '', steps: [...liveSteps] }; return u })
            }
            if (currentEvent === 'investigation-complete' && payload.report) {
              const report: InvestigationReportData = payload.report
              if (onHighlightServices && report.affected_services?.length)
                onHighlightServices(report.affected_services.map(s => s.name))
              setMessages(prev => { const u = [...prev]; u[stepsIdx] = { role: 'assistant', content: '', steps: liveSteps, report }; return u })
            }
            if (currentEvent === 'error') throw new Error(payload.message ?? 'Investigation failed')
          } catch (e) { if (currentEvent === 'error') throw e }
        } else if (line === '') { currentEvent = '' }
      }
    }
  }, [onHighlightServices])

  const send = async (overrideInput?: string) => {
    const q = (overrideInput ?? input).trim()
    if (!q || busy) return
    setInput('')
    onQueryStart?.()                             // clear graph highlights
    if (onHighlightServices) onHighlightServices([]) // clear previous service highlights
    // Build the next messages array and pass it as snapshot so sendInvestigation
    // doesn't need to capture the messages closure (avoids stale-state bugs).
    const next = [...messages, { role: 'user' as const, content: q }]
    setMessages(next)
    setBusy(true)
    try {
      await sendInvestigation(q, next)
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

  // ── Session management actions ─────────────────────────────────────────────

  const startNewSession = () => {
    if (busy) { abortRef.current?.abort(); setBusy(false) }
    const meta = createSession()
    setSessionId(meta.id)
    setMessages([])
    setSessions(getAllSessions())
    setShowHistory(false)
  }

  const switchSession = (id: string) => {
    if (id === sessionId) { setShowHistory(false); return }
    if (busy) { abortRef.current?.abort(); setBusy(false) }
    setActiveSessionId(id)
    setSessionId(id)
    setMessages(getSessionMessages(id) as Message[])
    setSessions(getAllSessions())
    setShowHistory(false)
  }

  const removeSession = (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    deleteSession(id)
    const remaining = getAllSessions()
    setSessions(remaining)
    if (id === sessionId) {
      if (remaining.length > 0) {
        switchSession(remaining[0].id)
      } else {
        startNewSession()
      }
    }
  }

  return (
    <div className="h-full flex flex-col relative overflow-hidden">

      {/* ── History Sidebar ───────────────────────────────────────────────── */}
      {showHistory && (
        <div className="absolute inset-0 z-20 flex flex-col bg-background border-r">
          <div className="p-3 border-b shrink-0 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <History className="h-4 w-4 text-cyan-400" />
              <span className="text-sm font-semibold text-cyan-400">Chat History</span>
            </div>
            <div className="flex items-center gap-1.5">
              <button
                onClick={startNewSession}
                title="Start new session"
                className="flex items-center gap-1 text-[10px] text-cyan-400/80 hover:text-cyan-300 transition-colors border border-cyan-400/30 rounded px-1.5 py-0.5 hover:border-cyan-400/70 hover:bg-cyan-400/5"
              >
                <Plus className="h-2.5 w-2.5" />
                New
              </button>
              <button onClick={() => setShowHistory(false)} className="text-muted-foreground hover:text-foreground transition-colors p-0.5">
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>
          <ScrollArea className="flex-1 min-h-0">
            <div className="p-2 space-y-1">
              {sessions.length === 0 && (
                <p className="text-xs text-muted-foreground text-center py-6">No saved sessions</p>
              )}
              {sessions.map(s => (
                <div
                  key={s.id}
                  onClick={() => switchSession(s.id)}
                  className={`group flex items-start justify-between gap-2 px-2 py-2 rounded-md cursor-pointer transition-colors ${
                    s.id === sessionId
                      ? 'bg-cyan-500/10 border border-cyan-500/30'
                      : 'hover:bg-card border border-transparent hover:border-border/40'
                  }`}
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium truncate text-foreground/90">{s.title}</p>
                    <p className="text-[10px] text-muted-foreground mt-0.5">
                      {formatSessionDate(s.updatedAt)} · {s.messageCount} msg{s.messageCount !== 1 ? 's' : ''}
                    </p>
                  </div>
                  <button
                    onClick={e => removeSession(e, s.id)}
                    title="Delete session"
                    className="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-red-400 shrink-0 mt-0.5"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          </ScrollArea>
        </div>
      )}

      {/* Header */}
      <div className="p-3 border-b shrink-0">
        <div className="flex items-center justify-between">

          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-cyan-400" />
            <span className="text-sm font-semibold text-cyan-400">AI Investigation</span>
          </div>
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setShowHistory(h => !h)}
              title="Chat history"
              className={`flex items-center gap-1 text-[10px] transition-colors border rounded px-1.5 py-0.5 ${
                showHistory
                  ? 'text-cyan-300 border-cyan-400/70 bg-cyan-400/10'
                  : 'text-cyan-400/80 hover:text-cyan-300 border-cyan-400/30 hover:border-cyan-400/70 hover:bg-cyan-400/5'
              }`}
            >
              <History className="h-2.5 w-2.5" />
              History
            </button>
            <button
              onClick={startNewSession}
              title="New chat session"
              className="flex items-center gap-1 text-[10px] text-cyan-400/80 hover:text-cyan-300 transition-colors border border-cyan-400/30 rounded px-1.5 py-0.5 hover:border-cyan-400/70 hover:bg-cyan-400/5"
            >
              <Plus className="h-2.5 w-2.5" />
              New Chat
            </button>
          </div>
        </div>
        {focusedIncidentId && (
          <div className="text-xs text-amber-400 flex items-center gap-1 mt-1.5">
            <AlertTriangle className="h-3 w-3" />
            Investigating: {focusedIncidentId}
          </div>
        )}
      </div>

      {/* Messages */}
      <ScrollArea className="flex-1 min-h-0">
        <div
          ref={viewportRef}
          onScroll={handleViewportScroll}
          className="p-3"
        >
          {messages.length === 0 && (
            <div className="space-y-4">
              <div className="text-center py-6">
                <Sparkles className="h-8 w-8 text-cyan-400/50 mx-auto mb-3" />
                <p className="text-sm text-muted-foreground">
                  Ask anything about incidents, services, or operational risks
                </p>
                <p className="text-xs text-muted-foreground/50 mt-1">
                  Graph · Incident · Risk agents run in parallel
                </p>
              </div>
              <div className="grid gap-2">
                {STARTER_QUESTIONS.map((q, i) => (
                  <button
                    key={i}
                    onClick={() => send(q)}
                    className="text-left text-xs px-3 py-2 rounded-md border border-border/50 bg-card/50 hover:bg-card hover:border-cyan-500/30 text-muted-foreground hover:text-foreground transition-all"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((msg, i) => (
            <MessageBubble key={i} msg={msg} isLive={busy && i === messages.length - 1} />
          ))}
          {busy && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground/60 mb-3">
              <Loader2 className="h-3 w-3 animate-spin" />
              <span>Investigation pipeline running…</span>
            </div>
          )}
          <div ref={endRef} />
        </div>
      </ScrollArea>

      {/* Input */}
      <div className="p-3 border-t shrink-0">
        <div className="flex gap-2">
          <Textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Investigate an incident, service, or pattern..."
            className="min-h-[60px] max-h-[120px] resize-none text-sm bg-card/50 border-border/50 focus:border-cyan-500/50"
            disabled={busy}
          />
          {busy ? (
            <Button
              onClick={stop}
              size="icon"
              variant="ghost"
              className="shrink-0 self-end text-red-400 hover:text-red-300 hover:bg-red-500/10 border border-red-500/30"
              title="Stop investigation"
            >
              <Square className="h-4 w-4 fill-current" />
            </Button>
          ) : (
            <Button
              onClick={() => send()}
              disabled={!canSend}
              size="icon"
              className="shrink-0 self-end bg-cyan-600 hover:bg-cyan-500"
            >
              <Send className="h-4 w-4" />
            </Button>
          )}
        </div>
        <p className="text-xs text-muted-foreground mt-1.5">
          Shift+Enter for new line · Enter to send
        </p>
      </div>
    </div>
  )
}
