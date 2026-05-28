'use client';

import React, { useState, useMemo, useEffect, useCallback, useRef } from 'react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { X, Search, Activity, Zap, AlertTriangle } from 'lucide-react';
import GraphVisualizer from '@/components/GraphVisualizer';
import InvestigationChat from '@/components/nexusiq/InvestigationChat';
import AgentActivity from '@/components/nexusiq/AgentActivity';
import IncidentTimeline from '@/components/nexusiq/IncidentTimeline';
import ContextExplorer from '@/components/nexusiq/ContextExplorer';
import ServiceInspector from '@/components/nexusiq/ServiceInspector';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from '@/components/ui/resizable';
import { type Entity, type Relationship, type Community, type GraphData } from '../lib/graphData';
import { ForceSimulation3D, GraphLayout, Node3D, defaultForceConfig } from '../lib/forceSimulation';

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

  // ─── NexusIQ UI state ───────────────────────────────────────────────────
  const [leftTab, setLeftTab] = useState<'chat' | 'agents'>('chat');
  const [rightTab, setRightTab] = useState<'timeline' | 'context' | 'inspector'>('timeline');
  const [highlightedServiceNames, setHighlightedServiceNames] = useState<string[]>([]);
  const [focusedIncidentId, setFocusedIncidentId] = useState<string | null>(null);
  const [contextQuery, setContextQuery] = useState<string>('');
  const [queryCount, setQueryCount] = useState<number>(0);
  const [nodeCount, setNodeCount] = useState<number>(0);

  const searchInputRef = useRef<HTMLInputElement>(null);

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
    const names = new Set(highlightedServiceNames.map(s => s.toLowerCase()));
    const ids = layout.nodes
      .filter(n => names.has(n.title.toLowerCase()))
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
    const ids = new Set<string>()
    filteredLayout.links.forEach(l => {
      if (l.source.id === selectedNode.id) ids.add(l.target.id)
      if (l.target.id === selectedNode.id) ids.add(l.source.id)
    })
    return ids
  }, [selectedNode, filteredLayout])

  // Only highlight connected neighbours when a node is selected; no persistent highlights otherwise
  const activeHighlightedNodeIds = useMemo(() => {
    if (selectedNode) return connectedNodeIds
    return new Set<string>()
  }, [selectedNode, connectedNodeIds])

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
    setQueryCount(c => c + 1); // trigger agent activity
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
    setQueryCount(c => c + 1);
  }, []);

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

        {/* ── LEFT PANEL: Investigation Chat + Agents ── */}
        <ResizablePanel defaultSize={25} minSize={15} maxSize={45}>
          <div className="h-full border-r flex flex-col z-40">
          <div className="p-2 border-b shrink-0">
            <Tabs value={leftTab} onValueChange={v => setLeftTab(v as 'chat' | 'agents')} className="w-full">
              <TabsList className="grid grid-cols-2 w-full h-8">
                <TabsTrigger value="chat" className="text-xs">Investigation</TabsTrigger>
                <TabsTrigger value="agents" className="text-xs">Agents</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
          <div className="flex-1 min-h-0">
            {leftTab === 'chat' ? (
              <InvestigationChat
                onHighlightServices={handleHighlightServices}
                onQueryStart={() => setHighlightedServiceNames([])}
                focusedIncidentId={focusedIncidentId}
              />
            ) : (
              <AgentActivity queryCount={queryCount} />
            )}
          </div>
          </div>

        </ResizablePanel>

        <ResizableHandle withHandle />

        {/* ── CENTER: 3D Service Dependency Graph ── */}
        <ResizablePanel defaultSize={50} minSize={25}>
          <div className="h-full relative z-0">
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
          />

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
          </div>

        </ResizablePanel>

        <ResizableHandle withHandle />

        {/* ── RIGHT PANEL: Timeline + Context + Inspector ── */}
        <ResizablePanel defaultSize={25} minSize={15} maxSize={45}>
          <div className="h-full border-l flex flex-col z-40">
          <div className="p-2 border-b shrink-0">
            <Tabs value={rightTab} onValueChange={v => setRightTab(v as 'timeline' | 'context' | 'inspector')} className="w-full">
              <TabsList className="grid grid-cols-3 w-full h-8">
                <TabsTrigger value="timeline" className="text-xs">Timeline</TabsTrigger>
                <TabsTrigger value="context" className="text-xs">Context</TabsTrigger>
                <TabsTrigger value="inspector" className="text-xs">Inspector</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
          <div className="flex-1 min-h-0">
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
