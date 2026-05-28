'use client'

import React, { useCallback, useEffect, useState } from 'react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  MessageSquare, Ticket, GitCommit, FileText, BookOpen,
  Search, RefreshCw, ChevronRight, ChevronDown, ExternalLink
} from 'lucide-react'
import { Button } from '@/components/ui/button'

interface ContextDocument {
  id: string
  type: 'slack' | 'jira' | 'commit' | 'meeting' | 'technical'
  title: string
  content: string
  timestamp?: string
  author?: string
  channel?: string
  tags?: string[]
  metadata?: Record<string, unknown>
}

const TYPE_CONFIG = {
  slack: {
    icon: <MessageSquare className="h-3.5 w-3.5" />,
    label: 'Slack',
    color: 'text-indigo-400',
    badge: 'bg-indigo-500/15 text-indigo-400 border-indigo-500/30',
    border: 'border-indigo-500/20',
    bg: 'bg-indigo-500/5',
  },
  jira: {
    icon: <Ticket className="h-3.5 w-3.5" />,
    label: 'Jira',
    color: 'text-amber-400',
    badge: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
    border: 'border-amber-500/20',
    bg: 'bg-amber-500/5',
  },
  commit: {
    icon: <GitCommit className="h-3.5 w-3.5" />,
    label: 'Commit',
    color: 'text-green-400',
    badge: 'bg-green-500/15 text-green-400 border-green-500/30',
    border: 'border-green-500/20',
    bg: 'bg-green-500/5',
  },
  meeting: {
    icon: <BookOpen className="h-3.5 w-3.5" />,
    label: 'Meeting',
    color: 'text-purple-400',
    badge: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
    border: 'border-purple-500/20',
    bg: 'bg-purple-500/5',
  },
  technical: {
    icon: <FileText className="h-3.5 w-3.5" />,
    label: 'Technical',
    color: 'text-cyan-400',
    badge: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30',
    border: 'border-cyan-500/20',
    bg: 'bg-cyan-500/5',
  },
}

const FILTER_TABS = [
  { key: 'all', label: 'All' },
  { key: 'slack', label: 'Slack' },
  { key: 'jira', label: 'Jira' },
  { key: 'commit', label: 'Commits' },
  { key: 'meeting', label: 'Meetings' },
  { key: 'technical', label: 'Docs' },
] as const

type FilterKey = typeof FILTER_TABS[number]['key']

function formatTimestamp(ts?: string) {
  if (!ts) return ''
  try {
    return new Date(ts).toLocaleDateString('en-US', {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
    })
  } catch {
    return ts
  }
}

function DocCard({ doc }: { doc: ContextDocument }) {
  const [expanded, setExpanded] = useState(false)
  const cfg = TYPE_CONFIG[doc.type]

  return (
    <div
      className={`rounded-md border ${cfg.border} ${cfg.bg} cursor-pointer hover:brightness-110 transition-all mb-2`}
      onClick={() => setExpanded(e => !e)}
    >
      <div className="px-3 py-2">
        <div className="flex items-start gap-2">
          <div className={`mt-0.5 shrink-0 ${cfg.color}`}>{cfg.icon}</div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 mb-1 flex-wrap">
              <span className={`text-xs px-1.5 py-0.5 rounded border ${cfg.badge}`}>
                {cfg.label}
              </span>
              {doc.channel && (
                <span className="text-xs text-muted-foreground">{doc.channel}</span>
              )}
              {doc.timestamp && (
                <span className="text-xs text-muted-foreground ml-auto">
                  {formatTimestamp(doc.timestamp)}
                </span>
              )}
            </div>
            <p className="text-xs font-medium leading-snug line-clamp-2">{doc.title}</p>
            {doc.author && (
              <p className="text-xs text-muted-foreground mt-0.5">{doc.author}</p>
            )}
          </div>
          <div className="shrink-0 mt-0.5">
            {expanded
              ? <ChevronDown className="h-3 w-3 text-muted-foreground" />
              : <ChevronRight className="h-3 w-3 text-muted-foreground" />
            }
          </div>
        </div>

        {!expanded && doc.content && (
          <p className="text-xs text-muted-foreground mt-1.5 ml-5 line-clamp-2 leading-relaxed">
            {doc.content}
          </p>
        )}

        {expanded && (
          <div className="mt-2 ml-5 space-y-2">
            <div className="text-xs text-muted-foreground bg-background/20 rounded p-2 leading-relaxed whitespace-pre-wrap max-h-40 overflow-y-auto">
              {doc.content}
            </div>
            {doc.tags && doc.tags.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {doc.tags.slice(0, 5).map((tag, i) => (
                  <span
                    key={i}
                    className="text-xs px-1.5 py-0.5 rounded bg-card/50 border border-border/40 text-muted-foreground"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

interface ContextExplorerProps {
  highlightQuery?: string
}

export default function ContextExplorer({ highlightQuery }: ContextExplorerProps) {
  const [docs, setDocs] = useState<ContextDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<FilterKey>('all')
  const [search, setSearch] = useState(highlightQuery ?? '')

  const load = useCallback(async (type?: string, q?: string) => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (type && type !== 'all') params.set('type', type)
      if (q) params.set('q', q)
      const res = await fetch(`/api/nexusiq/context?${params.toString()}`, { cache: 'no-store' })
      if (res.ok) setDocs(await res.json())
    } catch (err) {
      console.error('[ContextExplorer]', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(filter === 'all' ? undefined : filter, search || undefined)
  }, [load, filter, search])

  useEffect(() => {
    if (highlightQuery) setSearch(highlightQuery)
  }, [highlightQuery])

  const docsByType = filter === 'all'
    ? docs
    : docs.filter(d => d.type === filter)

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="p-3 border-b shrink-0 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileText className="h-4 w-4 text-purple-400" />
            <span className="text-sm font-semibold text-purple-400">Context Explorer</span>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={() => load(filter === 'all' ? undefined : filter, search || undefined)}
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
            placeholder="Search documents..."
            className="pl-7 h-7 text-xs bg-card/50 border-border/40"
          />
        </div>

        {/* Type tabs */}
        <div className="flex gap-1 flex-wrap">
          {FILTER_TABS.map(tab => {
            const cfg = tab.key !== 'all' ? TYPE_CONFIG[tab.key as keyof typeof TYPE_CONFIG] : null
            return (
              <button
                key={tab.key}
                onClick={() => setFilter(tab.key)}
                className={`px-2 py-0.5 text-xs rounded transition-colors border ${
                  filter === tab.key
                    ? cfg
                      ? cfg.badge
                      : 'bg-foreground/10 border-foreground/20 text-foreground'
                    : 'border-transparent text-muted-foreground hover:text-foreground'
                }`}
              >
                {tab.label}
              </button>
            )
          })}
        </div>
      </div>

      {/* Count */}
      <div className="px-3 py-1.5 border-b shrink-0">
        <span className="text-xs text-muted-foreground">
          {loading ? 'Loading...' : `${docsByType.length} documents`}
        </span>
      </div>

      {/* Documents */}
      <ScrollArea className="flex-1 min-h-0">
        <div className="p-3">
          {!loading && docsByType.length === 0 && (
            <div className="text-xs text-muted-foreground text-center py-8">
              No documents found
            </div>
          )}
          {docsByType.map(doc => (
            <DocCard key={`${doc.type}-${doc.id}`} doc={doc} />
          ))}
        </div>
      </ScrollArea>
    </div>
  )
}
