'use client'

import React, { useEffect, useRef, useState, useCallback } from 'react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import {
  Bot, Brain, Shield, Network, Cpu,
  CheckCircle2, Circle, Loader2, ChevronRight, ChevronDown, Zap,
  Wifi, WifiOff, HelpCircle,
} from 'lucide-react'

// ── Ollama status types ───────────────────────────────────────────────────────

interface ModelStatus {
  agent_id: string
  model: string
  description: string
  pulled: boolean
}

interface OllamaStatus {
  health: { status: string }
  models: { models: ModelStatus[]; available_count: number }
}

const STATUS_POLL_INTERVAL_MS = 30_000

type AgentStatus = 'idle' | 'running' | 'done' | 'error'

interface AgentStep {
  id: string
  agent: AgentId
  label: string
  detail?: string
  status: AgentStatus
  timestamp?: number
  durationMs?: number
}

type AgentId = 'orchestrator' | 'graph' | 'incident' | 'risk'

const AGENT_CONFIG: Record<AgentId, {
  label: string
  description: string
  icon: React.ReactNode
  color: string
  badge: string
}> = {
  orchestrator: {
    label: 'Orchestrator',
    description: 'Coordinates multi-agent investigation workflow',
    icon: <Bot className="h-4 w-4" />,
    color: 'text-cyan-400',
    badge: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30',
  },
  graph: {
    label: 'Graph Agent',
    description: 'Traverses service dependency graph and entity relationships',
    icon: <Network className="h-4 w-4" />,
    color: 'text-blue-400',
    badge: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  },
  incident: {
    label: 'Incident Agent',
    description: 'Analyzes incident timelines, root causes, and mitigation',
    icon: <Brain className="h-4 w-4" />,
    color: 'text-amber-400',
    badge: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  },
  risk: {
    label: 'Risk Analyst',
    description: 'Evaluates deployment risk and service blast radius',
    icon: <Shield className="h-4 w-4" />,
    color: 'text-red-400',
    badge: 'bg-red-500/15 text-red-400 border-red-500/30',
  },
}

// Simulated agent workflows for different query patterns
const INVESTIGATION_FLOWS: AgentStep[][] = [
  [
    { id: 's1', agent: 'orchestrator', label: 'Parsing investigation query', status: 'idle' },
    { id: 's2', agent: 'orchestrator', label: 'Routing to relevant agents', status: 'idle' },
    { id: 's3', agent: 'graph', label: 'Loading service dependency graph', status: 'idle' },
    { id: 's4', agent: 'graph', label: 'Identifying affected service cluster', status: 'idle' },
    { id: 's5', agent: 'incident', label: 'Retrieving incident timeline', status: 'idle' },
    { id: 's6', agent: 'incident', label: 'Correlating commits and deployments', status: 'idle' },
    { id: 's7', agent: 'incident', label: 'Extracting root cause signals', status: 'idle' },
    { id: 's8', agent: 'risk', label: 'Evaluating blast radius', status: 'idle' },
    { id: 's9', agent: 'risk', label: 'Assessing downstream dependencies', status: 'idle' },
    { id: 's10', agent: 'orchestrator', label: 'Synthesizing investigation report', status: 'idle' },
  ],
  [
    { id: 's1', agent: 'orchestrator', label: 'Query classification: service ownership', status: 'idle' },
    { id: 's2', agent: 'graph', label: 'Looking up employee → service assignments', status: 'idle' },
    { id: 's3', agent: 'graph', label: 'Resolving service API surface', status: 'idle' },
    { id: 's4', agent: 'incident', label: 'Checking recent incident history', status: 'idle' },
    { id: 's5', agent: 'orchestrator', label: 'Compiling ownership report', status: 'idle' },
  ],
  [
    { id: 's1', agent: 'orchestrator', label: 'Initiating deployment risk assessment', status: 'idle' },
    { id: 's2', agent: 'graph', label: 'Mapping service dependency chains', status: 'idle' },
    { id: 's3', agent: 'incident', label: 'Scanning recent deployment logs', status: 'idle' },
    { id: 's4', agent: 'incident', label: 'Cross-referencing Jira activity', status: 'idle' },
    { id: 's5', agent: 'risk', label: 'Computing change risk score', status: 'idle' },
    { id: 's6', agent: 'risk', label: 'Identifying high-risk service paths', status: 'idle' },
    { id: 's7', agent: 'orchestrator', label: 'Generating risk summary', status: 'idle' },
  ],
]

function AgentCard({ agentId, steps, activeStep }: {
  agentId: AgentId
  steps: AgentStep[]
  activeStep: number
}) {
  const [expanded, setExpanded] = useState(true)
  const cfg = AGENT_CONFIG[agentId]
  const agentSteps = steps.filter(s => s.agent === agentId)
  const hasActive = agentSteps.some(s => s.status === 'running')
  const allDone = agentSteps.length > 0 && agentSteps.every(s => s.status === 'done')
  const hasAny = agentSteps.some(s => s.status !== 'idle')

  if (!hasAny) return null

  return (
    <div className={`rounded-md border mb-3 overflow-hidden ${
      hasActive ? 'border-current/30' : allDone ? 'border-green-500/20' : 'border-border/30'
    }`}
      style={{ borderColor: hasActive ? cfg.color.replace('text-', '') : undefined }}
    >
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-muted/20 transition-colors"
      >
        <span className={cfg.color}>{cfg.icon}</span>
        <span className={`text-xs font-semibold ${cfg.color}`}>{cfg.label}</span>
        {hasActive && <Loader2 className="h-3 w-3 animate-spin ml-auto text-muted-foreground" />}
        {allDone && <CheckCircle2 className="h-3 w-3 ml-auto text-green-400" />}
        {!hasActive && !allDone && (
          expanded
            ? <ChevronDown className="h-3 w-3 ml-auto text-muted-foreground" />
            : <ChevronRight className="h-3 w-3 ml-auto text-muted-foreground" />
        )}
      </button>

      {expanded && (
        <div className="px-3 pb-2 space-y-1">
          {agentSteps.map(step => (
            <div key={step.id} className="flex items-start gap-2">
              <div className="mt-0.5 shrink-0">
                {step.status === 'running' && (
                  <Loader2 className={`h-3 w-3 animate-spin ${cfg.color}`} />
                )}
                {step.status === 'done' && (
                  <CheckCircle2 className="h-3 w-3 text-green-400" />
                )}
                {step.status === 'idle' && (
                  <Circle className="h-3 w-3 text-muted-foreground/30" />
                )}
              </div>
              <div className="min-w-0 flex-1">
                <span className={`text-xs ${step.status === 'idle' ? 'text-muted-foreground/50' : 'text-foreground'}`}>
                  {step.label}
                </span>
                {step.detail && step.status !== 'idle' && (
                  <p className="text-xs text-muted-foreground mt-0.5">{step.detail}</p>
                )}
                {step.durationMs && step.status === 'done' && (
                  <span className="text-xs text-muted-foreground/60 ml-2">{step.durationMs}ms</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

interface AgentActivityProps {
  isActive?: boolean
  queryCount?: number
}

export default function AgentActivity({ isActive, queryCount = 0 }: AgentActivityProps) {
  const [steps, setSteps] = useState<AgentStep[]>([])
  const [activeStep, setActiveStep] = useState(-1)
  const [running, setRunning] = useState(false)
  const [completedRuns, setCompletedRuns] = useState(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // ── Ollama connectivity + model status ──────────────────────────────────────
  const [ollamaStatus, setOllamaStatus] = useState<OllamaStatus | null>(null)
  const [statusLoading, setStatusLoading] = useState(true)

  const fetchOllamaStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/ollama/status', { signal: AbortSignal.timeout(6000) })
      if (res.ok) setOllamaStatus(await res.json())
    } catch {
      setOllamaStatus(null)
    } finally {
      setStatusLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchOllamaStatus()
    pollRef.current = setInterval(fetchOllamaStatus, STATUS_POLL_INTERVAL_MS)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [fetchOllamaStatus])

  const ollamaOnline = ollamaStatus?.health?.status === 'ok'
  const modelMap = new Map<string, ModelStatus>(
    (ollamaStatus?.models?.models ?? []).map(m => [m.agent_id, m])
  )

  const runFlow = (flowIndex: number) => {
    const flow = INVESTIGATION_FLOWS[flowIndex % INVESTIGATION_FLOWS.length]
    const freshSteps = flow.map(s => ({ ...s, status: 'idle' as AgentStatus }))
    setSteps(freshSteps)
    setActiveStep(-1)
    setRunning(true)

    let i = 0
    const advance = () => {
      if (i >= freshSteps.length) {
        setRunning(false)
        setCompletedRuns(c => c + 1)
        setActiveStep(-1)
        return
      }
      setSteps(prev => prev.map((s, idx) => {
        if (idx < i) return { ...s, status: 'done', durationMs: 80 + Math.round(Math.random() * 200) }
        if (idx === i) return { ...s, status: 'running' }
        return s
      }))
      setActiveStep(i)
      i++
      timerRef.current = setTimeout(advance, 350 + Math.random() * 500)
    }
    advance()
  }

  // Trigger a new flow run when queryCount increases
  const prevQueryRef = useRef(queryCount)
  useEffect(() => {
    if (queryCount > prevQueryRef.current) {
      prevQueryRef.current = queryCount
      if (timerRef.current) clearTimeout(timerRef.current)
      runFlow(queryCount - 1)
    }
  }, [queryCount])

  // Cleanup on unmount
  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current)
  }, [])

  const agentIds: AgentId[] = ['orchestrator', 'graph', 'incident', 'risk']
  const hasSteps = steps.length > 0

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="p-3 border-b shrink-0">
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-2">
            <Cpu className={`h-4 w-4 ${running ? 'text-cyan-400 animate-pulse' : 'text-muted-foreground'}`} />
            <span className="text-sm font-semibold text-foreground">Agent Activity</span>
          </div>
          <div className="flex items-center gap-1.5">
            {/* Ollama connectivity badge */}
            {statusLoading ? (
              <Badge variant="outline" className="text-xs h-5 bg-muted/20 text-muted-foreground border-border/40">
                <Loader2 className="h-2.5 w-2.5 mr-1 animate-spin" />Checking
              </Badge>
            ) : ollamaOnline ? (
              <Badge variant="outline" className="text-xs h-5 bg-green-500/10 text-green-400 border-green-500/30">
                <Wifi className="h-2.5 w-2.5 mr-1" />Ollama
              </Badge>
            ) : (
              <Badge variant="outline" className="text-xs h-5 bg-red-500/10 text-red-400 border-red-500/30">
                <WifiOff className="h-2.5 w-2.5 mr-1" />Offline
              </Badge>
            )}
            {running && (
              <Badge variant="outline" className="text-xs h-5 bg-cyan-500/10 text-cyan-400 border-cyan-500/30 animate-pulse">
                Running
              </Badge>
            )}
            {!running && completedRuns > 0 && (
              <Badge variant="outline" className="text-xs h-5 bg-green-500/10 text-green-400 border-green-500/30">
                Done
              </Badge>
            )}
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          Multi-agent reasoning pipeline • {completedRuns} run{completedRuns !== 1 ? 's' : ''} completed
        </p>
      </div>

      <ScrollArea className="flex-1 min-h-0">
        <div className="p-3">
          {/* Agent status cards */}
          {agentIds.map(id => (
            <AgentCard key={id} agentId={id} steps={steps} activeStep={activeStep} />
          ))}

          {!hasSteps && (
            <div className="text-center py-12 space-y-3">
              <div className="flex justify-center gap-3">
                {agentIds.map(id => {
                  const cfg = AGENT_CONFIG[id]
                  return (
                    <div key={id} className={`${cfg.color} opacity-30`}>
                      {cfg.icon}
                    </div>
                  )
                })}
              </div>
              <div className="text-xs text-muted-foreground">
                <p className="font-medium mb-1">Agent pipeline ready</p>
                <p>Send an investigation query to activate the multi-agent workflow</p>
              </div>
            </div>
          )}

          {/* Agent legend */}
          <div className="mt-4 border border-border/30 rounded-md p-3 space-y-2">
            <p className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1.5">
              <Zap className="h-3 w-3" /> Agent Roster
            </p>
            {agentIds.map(id => {
              const cfg = AGENT_CONFIG[id]
              const ms = modelMap.get(id)
              return (
                <div key={id} className="flex items-start gap-2">
                  <span className={`mt-0.5 ${cfg.color}`}>{cfg.icon}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs font-medium">{cfg.label}</span>
                      {ollamaOnline && ms ? (
                        ms.pulled ? (
                          <span title="Model pulled">
                            <CheckCircle2 className="h-3 w-3 text-green-400 shrink-0" />
                          </span>
                        ) : (
                          <span title="Model not yet pulled">
                            <HelpCircle className="h-3 w-3 text-amber-400 shrink-0" />
                          </span>
                        )
                      ) : null}
                    </div>
                    <p className="text-xs text-muted-foreground truncate">{cfg.description}</p>
                    {ms && (
                      <p className="text-xs text-muted-foreground/50 font-mono mt-0.5 truncate">{ms.model}</p>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </ScrollArea>
    </div>
  )
}
