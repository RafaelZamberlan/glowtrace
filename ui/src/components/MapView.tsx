import dagre from '@dagrejs/dagre'
import { Background, Controls, Handle, MiniMap, Position, ReactFlow, useReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react'
import { memo, useEffect, useMemo, useState } from 'react'
import type { MapData } from '../types'

interface MapNodeData extends Record<string, unknown> {
  kind: 'route' | 'fn'
  title: string
  sub: string
  methods?: string[]
  branches?: number
  external?: string[]
  observedOnly?: boolean
  hot?: boolean
}

const MapNode = memo(function MapNode({ data }: NodeProps) {
  const d = data as MapNodeData
  return (
    <div className={`mnode mk-${d.kind} ${d.observedOnly ? 'obs' : ''} ${d.hot ? 'hot' : ''}`}>
      <Handle type="target" position={Position.Left} className="h" />
      <div className="mtitle">
        {d.methods?.map((m) => (
          <span key={m} className={`mchip m-${m.toLowerCase()}`}>
            {m}
          </span>
        ))}
        <span className="mt">{d.title}</span>
      </div>
      <div className="msub">
        {d.sub}
        {!!d.branches && <span className="mb">{d.branches} {d.branches === 1 ? 'decisão' : 'decisões'}</span>}
        {d.external?.slice(0, 3).map((l) => (
          <span key={l} className="lib">
            {l}
          </span>
        ))}
      </div>
      <Handle type="source" position={Position.Right} className="h" />
    </div>
  )
})

const mapTypes = { mapNode: MapNode }

export function MapView({ data, onOpenRoute, onOpenFn }: { data: MapData; onOpenRoute: (id: string) => void; onOpenFn: (fn: string) => void }) {
  const [q, setQ] = useState('')
  const { nodes, edges } = useMemo(() => {
    const ql = q.trim().toLowerCase()
    const g = new dagre.graphlib.Graph()
    g.setGraph({ rankdir: 'LR', nodesep: 10, ranksep: 90 })
    g.setDefaultEdgeLabel(() => ({}))
    const nodes: Node[] = []
    const edges: Edge[] = []
    const keepFn = new Set<string>()
    const routes = data.routes.filter((r) => r.handler && (!ql || r.path.toLowerCase().includes(ql) || r.handler.toLowerCase().includes(ql)))
    const adj = new Map<string, string[]>()
    data.edges.forEach((e) => adj.set(e.source, [...(adj.get(e.source) ?? []), e.target]))
    const stack: string[] = []
    routes.forEach((r) => {
      stack.push(r.handler!)
      r.dependencies?.forEach((d) => stack.push(d.fn))
    })
    data.middlewares.forEach((m) => m.fn && !ql && stack.push(m.fn))
    while (stack.length) {
      const f = stack.pop()!
      if (keepFn.has(f)) continue
      keepFn.add(f)
      adj.get(f)?.forEach((t) => stack.push(t))
    }
    if (ql) data.functions.forEach((f) => f.qualname.toLowerCase().includes(ql) && keepFn.add(f.id))
    for (const r of routes) {
      const id = 'route:' + r.id
      g.setNode(id, { width: 250, height: 46 })
      nodes.push({ id, type: 'mapNode', position: { x: 0, y: 0 }, data: { kind: 'route', title: r.path, sub: r.handler!.split('::').pop()!, methods: r.methods } satisfies MapNodeData })
      const targets = [...(r.dependencies ?? []).map((d) => d.fn), r.handler!]
      targets.forEach((t, i) => {
        g.setEdge(id, t)
        edges.push({ id: `${id}->${t}#${i}`, source: id, target: t, className: 'k-route' })
      })
    }
    const fnById = new Map(data.functions.map((f) => [f.id, f]))
    for (const fid of keepFn) {
      const f = fnById.get(fid)
      if (!f) continue
      g.setNode(fid, { width: 250, height: 46 })
      nodes.push({
        id: fid,
        type: 'mapNode',
        position: { x: 0, y: 0 },
        data: {
          kind: 'fn',
          title: f.qualname,
          sub: `${f.file}:${f.line}`,
          branches: f.branches,
          external: f.external,
          observedOnly: f.observed_only,
          hot: !!ql && f.qualname.toLowerCase().includes(ql),
        } satisfies MapNodeData,
      })
    }
    for (const e of data.edges) {
      if (!keepFn.has(e.source) || !keepFn.has(e.target) || !fnById.has(e.source) || !fnById.has(e.target)) continue
      g.setEdge(e.source, e.target)
      edges.push({
        id: `${e.source}->${e.target}`,
        source: e.source,
        target: e.target,
        className: e.static ? (e.observed ? 'k-static ev' : 'k-static') : 'k-observed',
        label: e.observed ? `${e.observed}×` : undefined,
      })
    }
    dagre.layout(g)
    for (const n of nodes) {
      const d = g.node(n.id) as unknown as { x: number; y: number } | undefined
      if (d) n.position = { x: d.x - 125, y: d.y - 23 }
    }
    return { nodes, edges: edges.filter((e) => g.hasNode(e.source) && g.hasNode(e.target)) }
  }, [data, q])

  const rf = useReactFlow()
  useEffect(() => {
    const t = setTimeout(() => rf.fitView({ padding: 0.08, duration: 300, maxZoom: 1.1 }), 120)
    return () => clearTimeout(t)
  }, [nodes, rf])

  return (
    <div className="mapwrap">
      <div className="maptools">
        <input className="search" placeholder="Filtrar mapa (rota ou função)…" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="muted">
          {data.routes.length} rotas · {data.functions.length} funções · {data.edges.length} chamadas
        </span>
        <span className="legend">
          <i className="lg-static" /> estática <i className="lg-observed" /> só observada em execução
        </span>
      </div>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={mapTypes}
        fitView
        minZoom={0.05}
        nodesDraggable={false}
        nodesConnectable={false}
        onNodeClick={(_, n) => (n.id.startsWith('route:') ? onOpenRoute(n.id.slice(6)) : onOpenFn(n.id))}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={24} size={1} />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable />
      </ReactFlow>
    </div>
  )
}
