// Client-side port of python/src/easyapi/overlay.py.
// Backends may omit `execution.overlay`; the UI then computes it from the raw
// frames (path of node indexes) and the static flows. Keep both in sync.
import type { Execution, FlowNode, FnFlow, FrameOverlay } from './types'

const SILENT = new Set(['start', 'end', 'finally'])

function ownsLines(n: FlowNode): boolean {
  return n.own !== undefined ? n.own !== null : !SILENT.has(n.kind)
}

class Graph {
  out = new Map<number, [number, number][]>()
  cache = new Map<string, number[] | null>()
  flow: FnFlow
  constructor(flow: FnFlow) {
    this.flow = flow
    flow.edges.forEach((e, i) => {
      const l = this.out.get(e.source) ?? []
      l.push([e.target, i])
      this.out.set(e.source, l)
    })
  }

  path(a: number, b: number): number[] | null {
    const k = a + ':' + b
    if (this.cache.has(k)) return this.cache.get(k)!
    const r = this.bfs(a, b, true, 8) ?? this.bfs(a, b, false, 3)
    this.cache.set(k, r)
    return r
  }

  private bfs(a: number, b: number, strict: boolean, maxDepth: number): number[] | null {
    const nodes = this.flow.nodes
    const q: [number, number[]][] = [[a, []]]
    const seen = new Set([a])
    while (q.length) {
      const [cur, edges] = q.shift()!
      if (edges.length >= maxDepth) continue
      for (const [nxt, ei] of this.out.get(cur) ?? []) {
        if (nxt === b) return [...edges, ei]
        if (seen.has(nxt)) continue
        if (strict && !SILENT.has(nodes[nxt].kind) && ownsLines(nodes[nxt])) continue
        seen.add(nxt)
        q.push([nxt, [...edges, ei]])
      }
    }
    return null
  }

  isBlockExit(a: number, b: number): boolean {
    const nodes = this.flow.nodes
    if (nodes[b].kind !== 'with') return false
    let cur = nodes[a].parent
    for (let g = 0; cur !== undefined && cur !== null && g < 64; g++) {
      if (cur === b) return true
      cur = nodes[cur].parent
    }
    return false
  }

  exceptionEdge(a: number, b: number): number | null {
    const nodes = this.flow.nodes
    const t = nodes[b]
    if (t.kind !== 'except' || t.try_parent === undefined) return null
    for (const [nxt, ei] of this.out.get(t.try_parent) ?? []) if (nxt === b) return ei
    return null
  }
}

function lineMap(flow: FnFlow): Map<number, number> {
  const m = new Map<number, number>()
  for (const n of flow.nodes) {
    const own = n.own ?? (SILENT.has(n.kind) ? null : [n.line, n.end_line])
    if (!own) continue
    for (let ln = own[0]; ln <= own[1]; ln++) if (!m.has(ln)) m.set(ln, n.id)
  }
  return m
}

export function computeOverlay(ex: Execution, flows: Map<string, FnFlow>): { frames: FrameOverlay[] } {
  const graphs = new Map<string, Graph>()
  const byId = new Map(ex.frames.map((f) => [f.id, f]))
  const out: FrameOverlay[] = []
  for (const fr of ex.frames) {
    const flow = flows.get(fr.fn)
    if (!flow) {
      out.push({ id: fr.id, missing: true })
      continue
    }
    let g = graphs.get(fr.fn)
    if (!g) graphs.set(fr.fn, (g = new Graph(flow)))
    const start = 0
    const end = flow.nodes.length - 1
    const visits: Record<string, number> = { [start]: 1 }
    const edges: Record<string, number> = {}
    const jumps: [number, number][] = []
    const bump = (o: Record<string, number>, k: number, by = 1) => (o[String(k)] = (o[String(k)] ?? 0) + by)
    let a = start
    for (const [b] of fr.path) {
      if (b >= flow.nodes.length) continue
      if (g.isBlockExit(a, b)) continue
      let p = g.path(a, b)
      bump(visits, b)
      if (!p) {
        const ei = g.exceptionEdge(a, b)
        p = ei !== null ? [ei] : null
      }
      if (!p) {
        jumps.push([a, b])
        a = b
        continue
      }
      for (const ei of p) {
        bump(edges, ei)
        const tgt = flow.edges[ei].target
        if (tgt !== b) bump(visits, tgt)
      }
      a = b
    }
    const info: FrameOverlay = { id: fr.id, visits, edges, stale: !!(fr.hash && flow.source_hash && fr.hash !== flow.source_hash) }
    if (fr.exception) info.error_node = a
    else if (!fr.incomplete) {
      const p = g.path(a, end)
      if (p)
        for (const ei of p) {
          bump(edges, ei)
          bump(visits, flow.edges[ei].target)
        }
      else bump(visits, end)
    }
    if (jumps.length) info.jumps = jumps
    const parent = fr.parent !== null ? byId.get(fr.parent) : undefined
    if (parent && fr.call_line) {
      const pflow = flows.get(parent.fn)
      if (pflow) {
        const node = lineMap(pflow).get(fr.call_line)
        if (node !== undefined) info.call_node = node
      }
    }
    out.push(info)
  }
  return { frames: out }
}
