'use client'

import React, { useEffect, useState, useCallback } from 'react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  AlertTriangle, Rocket, GitCommit, Ticket, MessageSquare,
  RefreshCw, Search, ChevronDown, ChevronRight, Clock
} from 'lucide-react'

interface TimelineEvent {
  id: string
  type: 'incident' | 'deployment' | 'commit' | 'jira' | 'slack'
  timestamp: string
  title: string
  description: string
  severity?: string
  service?: string
  author?: string
  status?: string
  metadata?: Record<string, unknown>
}

interface IncidentTimelineProps {
  onSelectIncident?: (incidentId: string) => void
  onHighlightService?: (serviceNames: string[]) => void
}

const TYPE_CONFIG = {
  incident: {
    icon: <AlertTriangle className="h-3.5 w-3.5" />,
    label: 'Incident',
    color: 'text-red-400',
    dot: 'bg-red-500',
    border: 'border-red-500/20',
    bg: 'bg-red-500/5',
    badge: 'bg-red-500/15 text-red-400 border-red-500/30',
  },
  deployment: {
    icon: <Rocket className="h-3.5 w-3.5" />,
    label: 'Deploy',
    color: 'text-blue-400',
    dot: 'bg-blue-500',
    border: 'border-blue-500/20',
    bg: 'bg-blue-500/5',
    badge: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  },
  commit: {
    icon: <GitCommit className="h-3.5 w-3.5" />,
    label: 'Commit',
    color: 'text-green-400',
    dot: 'bg-green-500',
    border: 'border-green-500/20',
    bg: 'bg-green-500/5',
    badge: 'bg-green-500/15 text-green-400 border-green-500/30',
  },
  jira: {
    icon: <Ticket className="h-3.5 w-3.5" />,
    label: 'Jira',
    color: 'text-amber-400',
    dot: 'bg-amber-500',
    border: 'border-amber-500/20',
    bg: 'bg-amber-500/5',
    badge: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  },
  slack: {
    icon: <MessageSquare className="h-3.5 w-3.5" />,
    label: 'Slack',
    color: 'text-indigo-400',
    dot: 'bg-indigo-500',
    border: 'border-indigo-500/20',
    bg: 'bg-indigo-500/5',
    badge: 'bg-indigo-500/15 text-indigo-400 border-indigo-500/30',
  },
}

const SEVERITY_COLORS: Record<string, string> = {
  'SEV-1': 'bg-red-600/30 text-red-300 border-red-500/40',
  'SEV-2': 'bg-orange-600/20 text-orange-300 border-orange-500/40',
  'SEV-3': 'bg-yellow-600/20 text-yellow-300 border-yellow-500/40',
  'High': 'bg-orange-600/20 text-orange-300 border-orange-500/40',
  'Medium': 'bg-yellow-600/20 text-yellow-300 border-yellow-500/40',
  'Low': 'bg-green-600/20 text-green-300 border-green-500/40',
}

function formatTime(ts: string) {
  try {
    const d = new Date(ts)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch {
    return ts
  }
}

function formatDate(ts: string) {
  try {
    return new Date(ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  } catch {
    return ts
  }
}

function TimelineCard({
  event,
  onSelect,
  onHighlight,
}: {
  event: TimelineEvent
  onSelect?: (id: string) => void
  onHighlight?: (names: string[]) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const cfg = TYPE_CONFIG[event.type]

  const handleClick = () => {
    setExpanded(e => !e)
    if (event.type === 'incident' && onSelect) onSelect(event.id)
    if (event.service && onHighlight) {
      onHighlight(event.service.split(', ').filter(Boolean))
    }
  }

  return (
    <div
      className={`rounded-md border ${cfg.border} ${cfg.bg} cursor-pointer hover:brightness-110 transition-all mb-2`}
      onClick={handleClick}
    >
      <div className="px-3 py-2">
        {/* Top row */}
        <div className="flex items-start gap-2">
          <div className={`mt-0.5 shrink-0 ${cfg.color}`}>{cfg.icon}</div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap mb-0.5">
              <span className={`text-xs font-mono font-medium px-1.5 py-0.5 rounded border ${cfg.badge}`}>
                {cfg.label}
              </span>
              {event.severity && (
                <span className={`text-xs px-1.5 py-0.5 rounded border ${SEVERITY_COLORS[event.severity] ?? 'text-muted-foreground'}`}>
                  {event.severity}
                </span>
              )}
              {event.status && (
                <span className={`text-xs px-1.5 py-0.5 rounded border ${
                  event.status === 'resolved' || event.status === 'success' || event.status === 'Done'
                    ? 'bg-green-500/10 text-green-400 border-green-500/30'
                    : event.status === 'active'
                    ? 'bg-red-500/10 text-red-400 border-red-500/30'
                    : 'bg-muted/30 text-muted-foreground border-border/30'
                }`}>
                  {event.status}
                </span>
              )}
            </div>
            <p className="text-xs font-medium leading-snug line-clamp-2">{event.title}</p>
          </div>
          <div className="shrink-0">
            {expanded ? (
              <ChevronDown className="h-3 w-3 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-3 w-3 text-muted-foreground" />
            )}
          </div>
        </div>

        {/* Meta row */}
        <div className="flex items-center gap-3 mt-1.5 ml-5 text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <Clock className="h-2.5 w-2.5" />
            {formatTime(event.timestamp)}
          </span>
          {event.service && (
            <span className="truncate max-w-[140px] text-cyan-400/70">{event.service}</span>
          )}
          {event.author && (
            <span className="truncate max-w-[80px]">{event.author}</span>
          )}
        </div>

        {/* Expanded content */}
        {expanded && event.description && (
          <div className="mt-2 ml-5 text-xs text-muted-foreground bg-background/20 rounded p-2 leading-relaxed">
            {event.description}
          </div>
        )}
      </div>
    </div>
  )
}

const ALL_TYPES = ['incident', 'deployment', 'commit', 'jira'] as const
type FilterType = typeof ALL_TYPES[number] | 'all'

export default function IncidentTimeline({ onSelectIncident, onHighlightService }: IncidentTimelineProps) {
  const [events, setEvents] = useState<TimelineEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<FilterType>('all')
  const [search, setSearch] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/nexusiq/timeline', { cache: 'no-store' })
      if (res.ok) setEvents(await res.json())
    } catch (err) {
      console.error('[IncidentTimeline]', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const filtered = events.filter(ev => {
    if (filter !== 'all' && ev.type !== filter) return false
    if (search) {
      const q = search.toLowerCase()
      return (
        ev.title.toLowerCase().includes(q) ||
        (ev.service ?? '').toLowerCase().includes(q) ||
        (ev.description ?? '').toLowerCase().includes(q)
      )
    }
    return true
  })

  // Group by date
  const grouped = filtered.reduce<Record<string, TimelineEvent[]>>((acc, ev) => {
    const date = formatDate(ev.timestamp)
    if (!acc[date]) acc[date] = []
    acc[date].push(ev)
    return acc
  }, {})

  const dateKeys = Object.keys(grouped)

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="p-3 border-b shrink-0 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock className="h-4 w-4 text-blue-400" />
            <span className="text-sm font-semibold text-blue-400">Incident Timeline</span>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={load}
            disabled={loading}
          >
            <RefreshCw className={`h-3 w-3 ${loading ? 'animate-spin' : ''}`} />
          </Button>
        </div>

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
          <Input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search events..."
            className="pl-7 h-7 text-xs bg-card/50 border-border/40"
          />
        </div>

        {/* Type filters */}
        <div className="flex gap-1 flex-wrap">
          <button
            onClick={() => setFilter('all')}
            className={`px-2 py-0.5 text-xs rounded transition-colors border ${
              filter === 'all'
                ? 'bg-foreground/10 border-foreground/20 text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            All
          </button>
          {ALL_TYPES.map(t => {
            const cfg = TYPE_CONFIG[t]
            return (
              <button
                key={t}
                onClick={() => setFilter(t)}
                className={`px-2 py-0.5 text-xs rounded transition-colors border ${
                  filter === t
                    ? `${cfg.badge}`
                    : 'border-transparent text-muted-foreground hover:text-foreground'
                }`}
              >
                {cfg.label}
              </button>
            )
          })}
        </div>
      </div>

      {/* Timeline */}
      <ScrollArea className="flex-1 min-h-0">
        <div className="p-3">
          {loading && (
            <div className="text-xs text-muted-foreground text-center py-8">
              Loading timeline...
            </div>
          )}
          {!loading && filtered.length === 0 && (
            <div className="text-xs text-muted-foreground text-center py-8">
              No events match the current filter
            </div>
          )}
          {dateKeys.map(date => (
            <div key={date} className="mb-4">
              <div className="text-xs text-muted-foreground font-medium mb-2 sticky top-0 bg-background/80 backdrop-blur-sm py-1">
                {date}
                <span className="ml-2 text-muted-foreground/50">({grouped[date].length})</span>
              </div>
              {grouped[date].map(ev => (
                <TimelineCard
                  key={ev.id}
                  event={ev}
                  onSelect={onSelectIncident}
                  onHighlight={onHighlightService}
                />
              ))}
            </div>
          ))}
        </div>
      </ScrollArea>
    </div>
  )
}
