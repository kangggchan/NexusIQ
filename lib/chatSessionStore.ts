/**
 * Chat Session Store
 *
 * Each investigation chat session gets a unique ID.
 * Messages are persisted to localStorage keyed by session ID.
 * A session index (list of session metadata) is kept separately.
 *
 * Storage layout:
 *   localStorage["nexusiq:sessions"]          → SessionMeta[]  (index)
 *   localStorage["nexusiq:session:<id>"]      → Message[]      (messages)
 *   sessionStorage["nexusiq:active-session"]  → string         (current session ID)
 */

export type SessionMessage = {
  role: 'user' | 'assistant'
  content: string
  steps?: unknown[]
  report?: unknown
  rootCause?: string
  evidence?: unknown[]
}

export type SessionMeta = {
  id: string
  title: string          // first user message (truncated)
  createdAt: string      // ISO timestamp
  updatedAt: string      // ISO timestamp
  messageCount: number
}

const INDEX_KEY   = 'nexusiq:sessions'
const SESSION_PREFIX = 'nexusiq:session:'
const ACTIVE_KEY  = 'nexusiq:active-session'
const MAX_SESSIONS = 50

function safe<T>(fn: () => T, fallback: T): T {
  try { return fn() } catch { return fallback }
}

// ── Session index ─────────────────────────────────────────────────────────────

export function getAllSessions(): SessionMeta[] {
  return safe(() => {
    const raw = localStorage.getItem(INDEX_KEY)
    return raw ? (JSON.parse(raw) as SessionMeta[]) : []
  }, [])
}

function saveIndex(sessions: SessionMeta[]) {
  safe(() => localStorage.setItem(INDEX_KEY, JSON.stringify(sessions)), undefined)
}

// ── Active session ────────────────────────────────────────────────────────────

export function getActiveSessionId(): string | null {
  return safe(() => sessionStorage.getItem(ACTIVE_KEY), null)
}

export function setActiveSessionId(id: string) {
  safe(() => sessionStorage.setItem(ACTIVE_KEY, id), undefined)
}

// ── CRUD ──────────────────────────────────────────────────────────────────────

export function createSession(): SessionMeta {
  const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  const now = new Date().toISOString()
  const meta: SessionMeta = {
    id,
    title: 'New investigation',
    createdAt: now,
    updatedAt: now,
    messageCount: 0,
  }
  const all = getAllSessions()
  // Trim oldest if over limit
  const trimmed = [meta, ...all].slice(0, MAX_SESSIONS)
  saveIndex(trimmed)
  setActiveSessionId(id)
  return meta
}

export function getSessionMessages(id: string): SessionMessage[] {
  return safe(() => {
    const raw = localStorage.getItem(`${SESSION_PREFIX}${id}`)
    return raw ? (JSON.parse(raw) as SessionMessage[]) : []
  }, [])
}

export function saveSessionMessages(id: string, messages: SessionMessage[]) {
  safe(() => {
    localStorage.setItem(`${SESSION_PREFIX}${id}`, JSON.stringify(messages))
    // Update index metadata
    const all = getAllSessions()
    const idx = all.findIndex(s => s.id === id)
    if (idx >= 0) {
      const firstUser = messages.find(m => m.role === 'user')
      all[idx] = {
        ...all[idx],
        title: firstUser ? truncate(firstUser.content, 60) : all[idx].title,
        updatedAt: new Date().toISOString(),
        messageCount: messages.length,
      }
      saveIndex(all)
    }
  }, undefined)
}

export function deleteSession(id: string) {
  safe(() => {
    localStorage.removeItem(`${SESSION_PREFIX}${id}`)
    const all = getAllSessions().filter(s => s.id !== id)
    saveIndex(all)
    if (getActiveSessionId() === id) {
      sessionStorage.removeItem(ACTIVE_KEY)
    }
  }, undefined)
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function truncate(text: string, max: number): string {
  return text.length <= max ? text : text.slice(0, max - 1) + '…'
}

export function formatSessionDate(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  if (diffMins < 1)  return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  const diffHours = Math.floor(diffMins / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  const diffDays = Math.floor(diffHours / 24)
  if (diffDays < 7) return `${diffDays}d ago`
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}
