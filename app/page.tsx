'use client';

import React, { useState, useMemo, useEffect, useCallback, useRef } from 'react';
import { Input } from '@/components/ui/input';
import { X, Search, Activity, Zap, AlertTriangle, ChevronLeft, ChevronRight } from 'lucide-react';
import { type ImperativePanelHandle } from 'react-resizable-panels';
import GraphVisualizer from '@/components/GraphVisualizer';
import InvestigationChat, { type InvestigationChatMessage } from '@/components/nexusiq/InvestigationChat';
import SessionHistoryPanel from '@/components/nexusiq/SessionHistoryPanel';
import IncidentTimeline from '@/components/nexusiq/IncidentTimeline';
import ContextExplorer from '@/components/nexusiq/ContextExplorer';
import ServiceInspector from '@/components/nexusiq/ServiceInspector';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from '@/components/ui/resizable';
import { type Entity, type Relationship, type Community, type GraphData } from '../lib/graphData';
import { ForceSimulation3D, GraphLayout, Node3D, defaultForceConfig } from '../lib/forceSimulation';
import {
  type SessionMeta,
  createSession,
  deleteSession,
  getActiveSessionId,
  getAllSessions,
  getSessionContext,
  getSessionMessages,
  saveSessionContext,
  saveSessionMessages,
  setActiveSessionId,
} from '@/lib/chatSessionStore';

export default function Home() {
  // ─── Graph state ────────────────────────────────────────────────────────
  const [layout, setLayout] = useState<GraphLayout | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error] = useState<string | null>(null);
  const [status, setStatus] = useState<string>('Loading NexusIQ data...');
  const [selectedNode, setSelectedNode] = useState<Node3D | null>(null);
  const [hoveredNode, setHoveredNode] = useState<Node3D | null>(null);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [selectedEntityTypes] = useState<Set<string>>(new Set());
  const [minRelationshipWeight] = useState<number>(1);
  const [showAllRelationships, setShowAllRelationships] = useState<boolean>(true);

  // ─── NexusIQ UI state ───────────────────────────────────────────────────
  const [leftTab, setLeftTab] = useState<'chat' | 'history'>('chat');
  const [rightTab, setRightTab] = useState<'timeline' | 'context' | 'inspector'>('timeline');
  const [highlightedServiceNames, setHighlightedServiceNames] = useState<string[]>([]);
  const [focusedIncidentId, setFocusedIncidentId] = useState<string | null>(null);
  const [contextQuery, setContextQuery] = useState<string>('');
  const [nodeCount, setNodeCount] = useState<number>(0);
  const [sessionId, setSessionId] = useState<string>('');
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [messages, setMessages] = useState<InvestigationChatMessage[]>([]);
  const [sessionContext, setSessionContext] = useState<string>('');
  const [sessionStoreHydrated, setSessionStoreHydrated] = useState(false);
  const [busy, setBusy] = useState(false);
  const [isRightPanelCollapsed, setRightPanelCollapsed] = useState(false);

  const searchInputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const rightPanelRef = useRef<ImperativePanelHandle | null>(null);

  // ─── Load NexusIQ graph data ─────────────────────────────────────────────
  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true);
        setStatus('Fetching service dependency data...');

        const res = await fetch('/api/nexusiq/graph', { cache: 'no-store' });
        if (!res.ok) throw new Error(`Graph API ${res.status}`);

        const raw = await res.json() as {
          entities: Entity[];
          relationships: Relationship[];
          communities: Community[];
          communityReports: [];
        };

        setStatus('Computing 3D force layout...');
        const graphData: GraphData = {
          entities: raw.entities,
          relationships: raw.relationships,
          communities: raw.communities,
          communityReports: raw.communityReports,
        };

        setNodeCount(raw.entities.length);

        const sim = new ForceSimulation3D(defaultForceConfig);
        const computed = await sim.generateLayout(graphData);

        setLayout(computed);
        setStatus('');
        setLoading(false);
      } catch (err) {
        console.error('[NexusIQ graph]', err);
        setStatus('Failed to load graph. Check /api/nexusiq/graph.');
        setLoading(false);
      }
    };
    load();
  }, []);

  useEffect(() => {
    const active = getActiveSessionId();
    const id = active ?? createSession().id;
    setSessionId(id);
    setSessions(getAllSessions());
    setMessages((getSessionMessages(id) as InvestigationChatMessage[]) ?? []);
    setSessionContext(getSessionContext(id));
    setSessionStoreHydrated(true);
  }, []);

  useEffect(() => {
    if (!sessionStoreHydrated || !sessionId) return;
    saveSessionMessages(sessionId, messages as Parameters<typeof saveSessionMessages>[1]);
    setSessions(getAllSessions());
  }, [messages, sessionId, sessionStoreHydrated]);

  useEffect(() => {
    if (!sessionStoreHydrated || !sessionId) return;
    saveSessionContext(sessionId, sessionContext);
  }, [sessionContext, sessionId, sessionStoreHydrated]);

  // ─── Keyboard shortcuts ──────────────────────────────────────────────────
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelectedNode(null);
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  // ─── Auto-switch to inspector on node select ─────────────────────────────
  useEffect(() => {
    if (selectedNode) setRightTab('inspector');
  }, [selectedNode]);

  // ─── Derived: highlighted node IDs from service names ────────────────────
  const ragHighlightedNodeIds = useMemo(() => {
    if (!layout || highlightedServiceNames.length === 0) return new Set<string>();
    const names = new Set(highlightedServiceNames.filter(Boolean).map(s => s.toLowerCase()));
    const ids = layout.nodes
      .filter(n => n.title != null && names.has(n.title.toLowerCase()))
      .map(n => n.id);
    return new Set(ids);
  }, [layout, highlightedServiceNames]);

  // ─── Derived: filtered layout ────────────────────────────────────────────
  const filteredLayout = useMemo(() => {
    if (!layout) return null;
    let nodes = layout.nodes;
    let links = layout.links;

    if (selectedEntityTypes.size > 0) {
      nodes = nodes.filter(n => selectedEntityTypes.has(n.type));
    }

    const visibleIds = new Set(nodes.map(n => n.id));
    links = links.filter(l =>
      l.weight >= minRelationshipWeight &&
      visibleIds.has(l.source.id) &&
      visibleIds.has(l.target.id)
    );

    return { nodes, links, communities: layout.communities };
  }, [layout, selectedEntityTypes, minRelationshipWeight]);

  // ─── Derived: connected node IDs for selected node (after filteredLayout) ───
  const connectedNodeIds = useMemo(() => {
    if (!selectedNode || !filteredLayout) return new Set<string>()
    const neighborIds = new Set<string>()

    filteredLayout.links.forEach(link => {
      const sourceId = link.source.id
      const targetId = link.target.id
      if (sourceId !== selectedNode.id && targetId !== selectedNode.id) return
      neighborIds.add(sourceId === selectedNode.id ? targetId : sourceId)
    })

    return neighborIds
  }, [selectedNode, filteredLayout])

  // Only highlight connected neighbours when a node is selected; no persistent highlights otherwise
  const activeHighlightedNodeIds = useMemo(() => {
    if (selectedNode) return connectedNodeIds
    return ragHighlightedNodeIds
  }, [selectedNode, connectedNodeIds, ragHighlightedNodeIds])

  // ─── Connected links for inspector ───────────────────────────────────────
  const connectedLinks = useMemo(() => {
    if (!selectedNode || !filteredLayout) return [];
    return filteredLayout.links.filter(
      l => l.source.id === selectedNode.id || l.target.id === selectedNode.id
    );
  }, [selectedNode, filteredLayout]);

  // ─── Handlers ────────────────────────────────────────────────────────────
  const handleHighlightServices = useCallback((names: string[]) => {
    setHighlightedServiceNames(names);
  }, []);

  const handleSelectIncident = useCallback((id: string) => {
    setFocusedIncidentId(id);
    setContextQuery(id);
    setLeftTab('chat');
  }, []);

  const handleHighlightService = useCallback((names: string[]) => {
    setHighlightedServiceNames(names);
  }, []);

  const handleInvestigate = useCallback((query: string) => {
    setLeftTab('chat');
    // The chat panel will pick up the query via the starter question mechanism
    // We dispatch a custom event that InvestigationChat can listen to
    window.dispatchEvent(new CustomEvent('nexusiq:investigate', { detail: { query } }));
  }, []);

  const toggleRightPanel = useCallback(() => {
    const panel = rightPanelRef.current;
    if (!panel) return;

    if (panel.isCollapsed()) {
      panel.expand();
      return;
    }

    panel.collapse();
  }, []);

  const startNewSession = useCallback((openChat = true) => {
    if (busy) {
      abortRef.current?.abort();
      setBusy(false);
    }
    const meta = createSession();
    setSessionId(meta.id);
    setMessages([]);
    setSessionContext('');
    setSessions(getAllSessions());
    setHighlightedServiceNames([]);
    setFocusedIncidentId(null);
    if (openChat) {
      setLeftTab('chat');
    }
  }, [busy]);

  const switchSession = useCallback((id: string, openChat = true) => {
    if (id === sessionId) {
      if (openChat) {
        setLeftTab('chat');
      }
      return;
    }
    if (busy) {
      abortRef.current?.abort();
      setBusy(false);
    }
    setActiveSessionId(id);
    setSessionId(id);
    setMessages((getSessionMessages(id) as InvestigationChatMessage[]) ?? []);
    setSessionContext(getSessionContext(id));
    setSessions(getAllSessions());
    setHighlightedServiceNames([]);
    setFocusedIncidentId(null);
    if (openChat) {
      setLeftTab('chat');
    }
  }, [busy, sessionId]);

  const removeSession = useCallback((id: string) => {
    deleteSession(id);
    const remaining = getAllSessions();
    setSessions(remaining);
    setHighlightedServiceNames([]);
    setFocusedIncidentId(null);

    if (id !== sessionId) {
      return;
    }

    if (remaining.length > 0) {
      switchSession(remaining[0].id, false);
      return;
    }

    startNewSession(false);
  }, [sessionId, startNewSession, switchSession]);

  const visibleCommunities = useMemo(() => layout?.communities ?? [], [layout]);

  return (
    <div className="w-screen h-screen bg-background overflow-hidden flex flex-col">

      {/* ── NexusIQ Header ───────────────────────────────────────────────── */}
      <header className="h-12 border-b shrink-0 flex items-center px-4 gap-4 bg-background/95 backdrop-blur-sm z-50">
        {/* Logo + name */}
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-md bg-cyan-500/20 border border-cyan-500/40 flex items-center justify-center">
            <Zap className="h-4 w-4 text-cyan-400" />
          </div>
          <div className="flex items-baseline gap-1.5">
            <span className="font-bold text-base tracking-tight text-foreground">NexusIQ</span>
            <span className="text-xs text-muted-foreground hidden sm:block">
              Enterprise Operational Intelligence
            </span>
          </div>
        </div>

        <div className="w-px h-5 bg-border/50 hidden md:block" />

        {/* Stats */}
        {!loading && (
          <div className="hidden md:flex items-center gap-3 text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-cyan-400" />
              {nodeCount} nodes
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-purple-400" />
              NovaDrive AI
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
              Live
            </span>
          </div>
        )}

        {/* Spacer */}
        <div className="flex-1" />

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            ref={searchInputRef}
            placeholder="Search nodes..."
            value={searchTerm}
            onChange={e => setSearchTerm(e.target.value)}
            className="w-48 h-8 pl-8 pr-8 text-xs bg-card/60 border-border/50"
          />
          {searchTerm && (
            <button
              onClick={() => setSearchTerm('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>

        {/* Incident count badge */}
        <Badge variant="outline" className="hidden lg:flex items-center gap-1 text-xs border-red-500/30 text-red-400 bg-red-500/5">
          <AlertTriangle className="h-3 w-3" />
          18 incidents
        </Badge>

        <Badge variant="outline" className="hidden lg:flex items-center gap-1 text-xs border-green-500/30 text-green-400 bg-green-500/5">
          <Activity className="h-3 w-3" />
          54 deployments
        </Badge>
      </header>

      {/* ── Main 3-column layout ─────────────────────────────────────────── */}
      <ResizablePanelGroup direction="horizontal" className="flex-1 min-h-0 overflow-hidden">

        {/* ── LEFT PANEL: Investigation Chat + History ── */}
        <ResizablePanel defaultSize={25} minSize={10} maxSize={45}>
          <div className="h-full min-w-0 border-r flex flex-col z-40">
          <div className="p-2 border-b shrink-0">
            <Tabs value={leftTab} onValueChange={v => setLeftTab(v as 'chat' | 'history')} className="w-full">
              <TabsList className="grid grid-cols-2 w-full h-8">
                <TabsTrigger value="chat" className="text-xs">Investigation</TabsTrigger>
                <TabsTrigger value="history" className="text-xs">History</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
          <div className="flex-1 min-h-0 min-w-0 relative">
            {/* Always mounted so SSE streams survive tab switches */}
            <div className={leftTab === 'chat' ? 'h-full min-w-0' : 'hidden'}>
              <InvestigationChat
                sessionId={sessionId}
                messages={messages}
                setMessages={setMessages}
                sessionContext={sessionContext}
                setSessionContext={setSessionContext}
                busy={busy}
                setBusy={setBusy}
                abortRef={abortRef}
                onStartNewSession={() => startNewSession(true)}
                onHighlightServices={handleHighlightServices}
                onQueryStart={() => setHighlightedServiceNames([])}
                focusedIncidentId={focusedIncidentId}
              />
            </div>
            {leftTab === 'history' && (
              <SessionHistoryPanel
                sessions={sessions}
                activeSessionId={sessionId}
                onSelectSession={id => switchSession(id, true)}
                onStartNewSession={() => startNewSession(true)}
                onDeleteSession={removeSession}
              />
            )}
          </div>
          </div>

        </ResizablePanel>

        <ResizableHandle withHandle />

        {/* ── CENTER: 3D Service Dependency Graph ── */}
        <ResizablePanel defaultSize={50} minSize={25}>
          <div className="h-full min-w-0 relative z-0">
          <GraphVisualizer
            layout={filteredLayout}
            loading={loading}
            error={error}
            status={status}
            onRetry={() => window.location.reload()}
            selectedEntityTypes={selectedEntityTypes}
            minRelationshipWeight={minRelationshipWeight}
            showCommunityBoundaries={true}
            visibleCommunities={visibleCommunities}
            communityMode="all"
            selectedLevel={null}
            onNodeSelect={setSelectedNode}
            selectedNode={selectedNode}
            ragHighlightedNodeIds={activeHighlightedNodeIds}
            searchTerm={searchTerm}
            onNodeHover={setHoveredNode}
            hoveredNode={hoveredNode}
            showAllRelationships={showAllRelationships}
          />

          {isRightPanelCollapsed && (
            <button
              onClick={toggleRightPanel}
              className="absolute top-4 right-4 z-20 flex items-center gap-1.5 rounded-md border border-border/60 bg-background/85 px-3 py-1.5 text-xs text-muted-foreground shadow-sm backdrop-blur-sm transition-colors hover:border-cyan-500/40 hover:text-foreground"
              title="Open right sidebar"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
              <span>Open panel</span>
            </button>
          )}

          {/* Graph legend overlay */}
          <div className="absolute bottom-4 left-4 z-10 flex items-center gap-3 bg-background/80 backdrop-blur-sm border border-border/40 rounded-md px-3 py-2">
            <span className="text-xs text-muted-foreground font-medium">Legend</span>
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-[#00bcd4]" />
              <span className="text-xs text-muted-foreground">Service</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-[#a855f7]" />
              <span className="text-xs text-muted-foreground">Employee</span>
            </div>
          </div>

          <div className="absolute bottom-4 right-4 z-10 flex items-center gap-2 bg-background/80 backdrop-blur-sm border border-border/40 rounded-md px-3 py-2">
            <span className="text-xs text-muted-foreground">Show all relationships</span>
            <Switch
              checked={showAllRelationships}
              onCheckedChange={setShowAllRelationships}
              aria-label="Toggle all relationships visibility"
            />
          </div>
          </div>

        </ResizablePanel>

        <ResizableHandle withHandle={!isRightPanelCollapsed} disabled={isRightPanelCollapsed} className={isRightPanelCollapsed ? 'pointer-events-none opacity-0' : undefined} />

        {/* ── RIGHT PANEL: Timeline + Context + Inspector ── */}
        <ResizablePanel
          ref={rightPanelRef}
          defaultSize={25}
          minSize={15}
          maxSize={45}
          collapsible
          collapsedSize={0}
          onCollapse={() => setRightPanelCollapsed(true)}
          onExpand={() => setRightPanelCollapsed(false)}
        >
          <div className="h-full min-w-0 border-l flex flex-col z-40 overflow-hidden">
          <div className="p-2 border-b shrink-0">
            <div className="flex items-center gap-2">
              <Tabs value={rightTab} onValueChange={v => setRightTab(v as 'timeline' | 'context' | 'inspector')} className="min-w-0 flex-1">
              <TabsList className="grid grid-cols-3 w-full h-8">
                <TabsTrigger value="timeline" className="text-xs">Timeline</TabsTrigger>
                <TabsTrigger value="context" className="text-xs">Context</TabsTrigger>
                <TabsTrigger value="inspector" className="text-xs">Inspector</TabsTrigger>
              </TabsList>
            </Tabs>
              <button
                onClick={toggleRightPanel}
                className="shrink-0 rounded-md border border-border/60 p-1.5 text-muted-foreground transition-colors hover:border-cyan-500/40 hover:text-foreground"
                title="Hide right sidebar"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
          <div className="flex-1 min-h-0 min-w-0">
            {rightTab === 'timeline' && (
              <IncidentTimeline
                onSelectIncident={handleSelectIncident}
                onHighlightService={handleHighlightService}
              />
            )}
            {rightTab === 'context' && (
              <ContextExplorer highlightQuery={contextQuery} />
            )}
            {rightTab === 'inspector' && (
              <ServiceInspector
                selectedNode={selectedNode}
                connectedLinks={connectedLinks}
                onClose={() => setSelectedNode(null)}
                onNodeSelect={setSelectedNode}
                onInvestigate={handleInvestigate}
              />
            )}
          </div>
          </div>

        </ResizablePanel>

      </ResizablePanelGroup>

    </div>
  );
}
