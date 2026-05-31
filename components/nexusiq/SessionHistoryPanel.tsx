'use client'

import React, { useState } from 'react'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { History, Plus, Trash2 } from 'lucide-react'
import { type SessionMeta, formatSessionDate } from '@/lib/chatSessionStore'

interface SessionHistoryPanelProps {
  sessions: SessionMeta[]
  activeSessionId: string
  onSelectSession: (id: string) => void
  onStartNewSession: () => void
  onDeleteSession: (id: string) => void
}

export default function SessionHistoryPanel({
  sessions,
  activeSessionId,
  onSelectSession,
  onStartNewSession,
  onDeleteSession,
}: SessionHistoryPanelProps) {
  const [pendingDeleteSession, setPendingDeleteSession] = useState<SessionMeta | null>(null)

  return (
    <div className="h-full flex flex-col">
      <div className="p-3 border-b shrink-0 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <History className="h-4 w-4 text-cyan-400 shrink-0" />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-cyan-400 truncate">Chat History</p>
            <p className="text-[10px] text-muted-foreground">Local sessions and compact context</p>
          </div>
        </div>
        <button
          onClick={onStartNewSession}
          title="Start new session"
          className="flex items-center gap-1 text-[10px] text-cyan-400/80 hover:text-cyan-300 transition-colors border border-cyan-400/30 rounded px-1.5 py-0.5 hover:border-cyan-400/70 hover:bg-cyan-400/5 shrink-0"
        >
          <Plus className="h-2.5 w-2.5" />
          New
        </button>
      </div>

      <ScrollArea className="flex-1 min-h-0">
        <div className="p-2 space-y-1.5">
          {sessions.length === 0 && (
            <div className="text-center py-8 px-3">
              <p className="text-xs text-muted-foreground">No saved sessions</p>
            </div>
          )}

          {sessions.map(session => (
            <div
              key={session.id}
              onClick={() => onSelectSession(session.id)}
              className={`group flex items-start justify-between gap-2 px-2.5 py-2.5 rounded-md cursor-pointer transition-colors ${
                session.id === activeSessionId
                  ? 'bg-cyan-500/10 border border-cyan-500/30'
                  : 'hover:bg-card border border-transparent hover:border-border/40'
              }`}
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 min-w-0">
                  <p className="text-xs font-medium truncate text-foreground/90">{session.title}</p>
                  {session.id === activeSessionId && (
                    <span className="text-[9px] uppercase tracking-wide text-cyan-300 border border-cyan-400/40 bg-cyan-400/10 rounded px-1.5 py-0.5 shrink-0">
                      Active
                    </span>
                  )}
                </div>
                <p className="text-[10px] text-muted-foreground mt-0.5">
                  {formatSessionDate(session.updatedAt)} · {session.messageCount} msg{session.messageCount !== 1 ? 's' : ''}
                </p>
              </div>
              <button
                onClick={event => {
                  event.stopPropagation()
                  setPendingDeleteSession(session)
                }}
                title="Delete session"
                className="text-muted-foreground/70 hover:text-red-400 shrink-0 mt-0.5 rounded p-1 hover:bg-red-500/10 transition-colors"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      </ScrollArea>

      <AlertDialog open={pendingDeleteSession !== null} onOpenChange={open => { if (!open) setPendingDeleteSession(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete chat session?</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingDeleteSession
                ? `This will permanently remove "${pendingDeleteSession.title}" and its compacted session context from local storage.`
                : 'This will permanently remove the selected session.'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-red-600 hover:bg-red-500 focus-visible:ring-red-400"
              onClick={() => {
                if (pendingDeleteSession) {
                  onDeleteSession(pendingDeleteSession.id)
                }
              }}
            >
              Delete session
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}