'use client'

import React, { useEffect, useState } from 'react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { Button } from '@/components/ui/button'
import {
  X, Server, User, AlertTriangle, GitBranch,
  Globe, Database, Layers, ChevronRight, Users, Boxes
} from 'lucide-react'
import { Node3D, Link3D } from '@/lib/forceSimulation'

interface ServiceData {
  service_id: string
  name: string
  description: string
  team: string
  owner_employee_id: string
  apis: Array<{ name: string; protocol: string; purpose: string }>
  dependencies: string[]
  databases: string[]
  deployment_targets: string[]
}

interface EmployeeData {
  employee_id: string
  name: string
  role: string
  specialization: string
  team: string
  email: string
  owned_services: string[]
  years_of_experience: number
}

interface IncidentRef {
  incident_id: string
  title: string
  severity: string
  started_at: string
  status: string
}

interface ServiceInspectorProps {
  selectedNode: Node3D | null
  connectedLinks: Link3D[]
  onClose: () => void
  onNodeSelect: (node: Node3D) => void
  onInvestigate?: (query: string) => void
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex gap-2 py-1">
      <span className="text-xs text-muted-foreground w-28 shrink-0">{label}</span>
      <span className="text-xs text-foreground flex-1 min-w-0">{value}</span>
    </div>
  )
}

function TagList({ items, colorClass }: { items: string[]; colorClass?: string }) {
  if (!items || items.length === 0) return <span className="text-xs text-muted-foreground">—</span>
  return (
    <div className="flex flex-wrap gap-1">
      {items.map((item, i) => (
        <span key={i} className={`text-xs px-1.5 py-0.5 rounded border ${colorClass ?? 'bg-muted/30 border-border/40 text-muted-foreground'}`}>
          {item}
        </span>
      ))}
    </div>
  )
}

export default function ServiceInspector({
  selectedNode,
  connectedLinks,
  onClose,
  onNodeSelect,
  onInvestigate,
}: ServiceInspectorProps) {
  const [serviceData, setServiceData] = useState<ServiceData | null>(null)
  const [employeeData, setEmployeeData] = useState<EmployeeData | null>(null)
  const [incidents, setIncidents] = useState<IncidentRef[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!selectedNode) {
      setServiceData(null)
      setEmployeeData(null)
      setIncidents([])
      return
    }

    const loadNodeData = async () => {
      setLoading(true)
      setServiceData(null)
      setEmployeeData(null)
      setIncidents([])

      try {
        if (selectedNode.type === 'SERVICE') {
          // Load services and find match by id or name
          const [svcRes, incRes] = await Promise.all([
            fetch('/api/nexusiq/graph', { cache: 'no-store' }),
            fetch('/api/nexusiq/incidents', { cache: 'no-store' }),
          ])

          // Load from services.json via the graph API data
          const svcGraphData = svcRes.ok ? null : null // we don't have direct services endpoint

          // Fetch services directly
          const svcRaw = await fetch('/api/data/services.json').catch(() => null)

          // Fallback: use node data
          if (incRes.ok) {
            const allIncidents: Array<Record<string, unknown>> = await incRes.json()
            const nodeTitle = selectedNode.title
            const nodeId = selectedNode.id
            const related = allIncidents.filter(inc => {
              const affected = Array.isArray(inc.affected_services)
                ? (inc.affected_services as string[])
                : []
              return affected.includes(nodeTitle) || affected.includes(nodeId)
            })
            setIncidents(related.map(inc => ({
              incident_id: String(inc.incident_id),
              title: String(inc.title),
              severity: String(inc.severity ?? ''),
              started_at: String(inc.started_at ?? ''),
              status: inc.ended_at ? 'resolved' : 'active',
            })))
          }
        } else if (selectedNode.type === 'EMPLOYEE') {
          const incRes = await fetch('/api/nexusiq/incidents', { cache: 'no-store' })
          if (incRes.ok) {
            // Incidents don't directly reference employees, skip
          }
        }
      } catch (err) {
        console.error('[ServiceInspector] load error', err)
      } finally {
        setLoading(false)
      }
    }

    loadNodeData()
  }, [selectedNode])

  if (!selectedNode) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center space-y-2">
          <Boxes className="h-8 w-8 text-muted-foreground/30 mx-auto" />
          <p className="text-xs text-muted-foreground">Click a node to inspect</p>
        </div>
      </div>
    )
  }

  const isService = selectedNode.type === 'SERVICE'
  const isEmployee = selectedNode.type === 'EMPLOYEE'
  const iconColor = isService ? 'text-cyan-400' : isEmployee ? 'text-purple-400' : 'text-muted-foreground'

  const outboundLinks = connectedLinks.filter(l => l.source.id === selectedNode.id)
  const inboundLinks = connectedLinks.filter(l => l.target.id === selectedNode.id)

  const sevColors: Record<string, string> = {
    'SEV-1': 'bg-red-600/20 text-red-300 border-red-500/40',
    'SEV-2': 'bg-orange-600/20 text-orange-300 border-orange-500/40',
    'SEV-3': 'bg-yellow-600/20 text-yellow-300 border-yellow-500/40',
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="p-3 border-b shrink-0">
        <div className="flex items-center gap-2">
          <div className={iconColor}>
            {isService ? <Server className="h-4 w-4" /> : <User className="h-4 w-4" />}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold truncate">{selectedNode.title}</p>
            <p className="text-xs text-muted-foreground">{selectedNode.type}</p>
          </div>
          <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0" onClick={onClose}>
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>

        {/* Investigate button */}
        {onInvestigate && (
          <Button
            variant="outline"
            size="sm"
            className="mt-2 w-full h-7 text-xs border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/10"
            onClick={() => onInvestigate(`Investigate ${selectedNode.title}: recent incidents, deployments, and risks`)}
          >
            <AlertTriangle className="h-3 w-3 mr-1" />
            Investigate with AI
          </Button>
        )}
      </div>

      <ScrollArea className="flex-1 min-h-0">
        <div className="p-3 space-y-4">
          {/* Node description */}
          {selectedNode.description && (
            <div>
              <p className="text-xs text-muted-foreground leading-relaxed">{selectedNode.description}</p>
            </div>
          )}

          <Separator className="opacity-30" />

          {/* Graph connections */}
          <div>
            <p className="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
              <GitBranch className="h-3.5 w-3.5" />
              Connections ({connectedLinks.length})
            </p>
            <div className="space-y-1.5">
              {outboundLinks.slice(0, 8).map(link => (
                <button
                  key={link.id}
                  className="w-full flex items-center gap-2 text-xs p-1.5 rounded hover:bg-muted/20 transition-colors text-left"
                  onClick={() => onNodeSelect(link.target)}
                >
                  <ChevronRight className="h-3 w-3 text-cyan-400 shrink-0" />
                  <span className="text-cyan-400/70 font-mono shrink-0">
                    {link.description}
                  </span>
                  <span className="text-foreground truncate">{link.target.title}</span>
                  <span className="ml-auto text-muted-foreground text-xs">{link.target.type}</span>
                </button>
              ))}
              {inboundLinks.slice(0, 8).map(link => (
                <button
                  key={link.id}
                  className="w-full flex items-center gap-2 text-xs p-1.5 rounded hover:bg-muted/20 transition-colors text-left"
                  onClick={() => onNodeSelect(link.source)}
                >
                  <ChevronRight className="h-3 w-3 text-purple-400 shrink-0 rotate-180" />
                  <span className="text-purple-400/70 font-mono shrink-0 truncate">
                    {link.description}
                  </span>
                  <span className="text-foreground truncate">{link.source.title}</span>
                  <span className="ml-auto text-muted-foreground text-xs">{link.source.type}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Incidents */}
          {incidents.length > 0 && (
            <>
              <Separator className="opacity-30" />
              <div>
                <p className="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
                  <AlertTriangle className="h-3.5 w-3.5 text-red-400" />
                  Related Incidents ({incidents.length})
                </p>
                <div className="space-y-1.5">
                  {incidents.map(inc => (
                    <div key={inc.incident_id} className="rounded border border-red-500/20 bg-red-500/5 px-2 py-1.5">
                      <div className="flex items-center gap-1.5 mb-0.5">
                        <span className={`text-xs px-1 py-0.5 rounded border ${sevColors[inc.severity] ?? 'text-muted-foreground border-border'}`}>
                          {inc.severity}
                        </span>
                        <span className="text-xs font-mono text-muted-foreground">{inc.incident_id}</span>
                        <span className={`text-xs ml-auto ${inc.status === 'resolved' ? 'text-green-400' : 'text-red-400'}`}>
                          {inc.status}
                        </span>
                      </div>
                      <p className="text-xs leading-snug">{inc.title}</p>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          {/* Node metadata */}
          <Separator className="opacity-30" />
          <div>
            <p className="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
              <Layers className="h-3.5 w-3.5" />
              Node Metadata
            </p>
            <InfoRow label="ID" value={<span className="font-mono text-xs">{selectedNode.id}</span>} />
            <InfoRow label="Type" value={selectedNode.type} />
            <InfoRow label="Connections" value={String(connectedLinks.length)} />
            <InfoRow label="Community" value={selectedNode.community?.title ?? '—'} />
          </div>
        </div>
      </ScrollArea>
    </div>
  )
}
