import dagre from '@dagrejs/dagre'
import type { Edge as RFEdge, Node as RFNode } from '@xyflow/react'
import type { Execution, FlowNode, FnFlow, Frame, FrameOverlay, MiddlewareInfo, RouteInfo } from './types'

export const PIPE = '__pipeline__'

// ---------------------------------------------------------------------------
// pipeline pseudo-flow: request -> middlewares -> dependencies -> handler -> response

export function pipelineFlow(route: RouteInfo, middlewares: MiddlewareInfo[]): FnFlow {
  const nodes: FlowNode[] = []
  const add = (kind: string, label: string, target?: string | null) => {
    nodes.push({
      id: nodes.length,
      kind,
      label,
      line: 0,
      end_line: 0,
      calls: target ? [{ expr: label, kind: 'user', target, line: 0 }] : [],
    })
  }
  add('trigger', `${route.methods.join(' | ') || route.kind.toUpperCase()} ${route.path}`)
  for (const m of middlewares) add(m.fn ? 'middleware' : 'mwlib', m.name, m.fn)
  for (const d of route.dependencies ?? []) add('dependency', 'Depends(' + d.fn.split('::').pop() + ')', d.fn)
  add('handler', route.handler ? route.handler.split('::').pop()! : route.handler_desc || 'endpoint', route.handler)
  add('response', 'resposta')
  const edges = nodes.slice(1).map((n, i) => ({ source: i, target: n.id, kind: 'next' }))
  return {
    id: PIPE,
    qualname: route.id,
    file: route.file ?? '',
    line: route.line ?? 0,
    end_line: 0,
    is_async: false,
    params: [],
    source: '',
    source_start: 0,
    source_hash: '',
    nodes,
    edges,
  }
}

// ---------------------------------------------------------------------------
// instances: one box per (function, call site); executions bind frames to them

export interface Inst {
  key: string
  fn: string
  depth: number
  parent: Inst | null
  parentNode: number | null
  frames: Frame[]
  run: number
  frame: Frame | null
  ov: FrameOverlay | null
  executed: boolean
}

export interface SceneInput {
  rootFn: string
  flows: Map<string, FnFlow>
  toggled: Map<string, boolean>
  exec: Execution | null
  runSel: Map<string, number>
  defaultOpen: Set<string>
}

function defaultRun(frames: Frame[]): number {
  const err = frames.findIndex((f) => f.exception)
  return err >= 0 ? err : 0
}

export function buildInstances(inp: SceneInput): Inst[] {
  const { rootFn, flows, toggled, exec, runSel, defaultOpen } = inp
  const ovById = new Map<number, FrameOverlay>()
  exec?.overlay?.frames.forEach((o) => ovById.set(o.id, o))
  const root: Inst = { key: 'r', fn: rootFn, depth: 0, parent: null, parentNode: null, frames: [], run: 0, frame: null, ov: null, executed: !!exec }
  if (exec && rootFn !== PIPE) {
    const tops = exec.frames.filter((f) => f.fn === rootFn)
    if (tops.length) {
      root.frames = tops
      root.run = runSel.get('r') ?? defaultRun(tops)
      root.frame = tops[root.run] ?? null
      root.ov = root.frame ? ovById.get(root.frame.id) ?? null : null
    }
  }
  const out: Inst[] = []
  const queue: Inst[] = [root]
  let guard = 0
  while (queue.length && guard++ < 400) {
    const inst = queue.shift()!
    out.push(inst)
    const flow = flows.get(inst.fn)
    if (!flow) continue
    const children = new Map<string, { node: number; fn: string; frames: Frame[] }>()
    const keyOf = (node: number, fn: string) => `${inst.key}/${node}:${fn}`
    if (exec) {
      let cands: Frame[] = []
      if (inst.fn === PIPE) cands = exec.frames.filter((f) => f.parent === null)
      else if (inst.frame) cands = exec.frames.filter((f) => f.parent === inst.frame!.id)
      for (const f of cands) {
        let node: number
        if (inst.fn === PIPE) {
          const hit = flow.nodes.find((n) => n.calls?.some((c) => c.target === f.fn))
          node = hit ? hit.id : flow.nodes.findIndex((n) => n.kind === 'handler')
        } else {
          node = ovById.get(f.id)?.call_node ?? 0
        }
        const k = keyOf(node, f.fn)
        const entry = children.get(k) ?? { node, fn: f.fn, frames: [] }
        entry.frames.push(f)
        children.set(k, entry)
      }
    }
    for (const n of flow.nodes) {
      for (const c of n.calls ?? []) {
        if (c.kind !== 'user' || !c.target) continue
        const k = keyOf(n.id, c.target)
        if (!children.has(k)) children.set(k, { node: n.id, fn: c.target, frames: [] })
      }
    }
    const sorted = [...children.entries()].sort((a, b) => a[1].node - b[1].node)
    for (const [k, ch] of sorted) {
      const executed = ch.frames.length > 0
      const open = toggled.has(k) ? toggled.get(k)! : executed || defaultOpen.has(k)
      if (!open) continue
      if (isAncestorFn(inst, ch.fn) && !executed) continue // avoid infinite static recursion
      const run = Math.min(runSel.get(k) ?? defaultRun(ch.frames), Math.max(0, ch.frames.length - 1))
      const frame = ch.frames[run] ?? null
      queue.push({
        key: k,
        fn: ch.fn,
        depth: inst.depth + 1,
        parent: inst,
        parentNode: ch.node,
        frames: ch.frames,
        run,
        frame,
        ov: frame ? ovById.get(frame.id) ?? null : null,
        executed,
      })
    }
  }
  return out
}

function isAncestorFn(inst: Inst | null, fn: string): boolean {
  for (let i = inst; i; i = i.parent) if (i.fn === fn) return true
  return false
}

/** Which child call sites of a node exist / are open (for the +/- button). */
export function callTargets(n: FlowNode, observed: Frame[] = []): string[] {
  const t = new Set<string>()
  n.calls?.forEach((c) => c.kind === 'user' && c.target && t.add(c.target))
  observed.forEach((f) => t.add(f.fn))
  return [...t]
}

// ---------------------------------------------------------------------------
// layout

export const NODE_W = 270
const NODE_H = 46
const SMALL = new Set(['break', 'continue', 'end', 'finally'])
const HEADER = 50
const PAD = 22
const GAP_X = 150
const GAP_Y = 46

export interface Box {
  x: number
  y: number
  w: number
  h: number
}
export interface FlowLayout {
  w: number
  h: number
  pos: Map<number, Box>
}

const layoutCache = new Map<string, FlowLayout>()

export function nodeSize(n: FlowNode): { w: number; h: number } {
  if (SMALL.has(n.kind)) return { w: 150, h: 34 }
  if (n.kind === 'start' || n.kind === 'trigger') return { w: NODE_W, h: 54 }
  return { w: NODE_W, h: NODE_H }
}

export function layoutFlow(flow: FnFlow): FlowLayout {
  const key = flow.id + '@' + flow.source_hash + '@' + flow.qualname + '@' + flow.nodes.length
  const hit = layoutCache.get(key)
  if (hit) return hit
  const g = new dagre.graphlib.Graph({ multigraph: true })
  g.setGraph({ rankdir: 'TB', nodesep: 34, ranksep: 34, edgesep: 14, marginx: 0, marginy: 0 })
  g.setDefaultEdgeLabel(() => ({}))
  for (const n of flow.nodes) {
    const s = nodeSize(n)
    g.setNode(String(n.id), { width: s.w, height: s.h })
  }
  flow.edges.forEach((e, i) => {
    const labelled = !!e.label && e.kind !== 'next'
    g.setEdge(String(e.source), String(e.target), labelled ? { width: 34, height: 14, labelpos: 'c', weight: e.kind === 'loop' ? 0 : 1 } : { weight: e.kind === 'loop' ? 0 : 1 }, 'e' + i)
  })
  dagre.layout(g)
  const pos = new Map<number, Box>()
  let w = 0
  let h = 0
  for (const n of flow.nodes) {
    const d = g.node(String(n.id)) as unknown as { x: number; y: number; width: number; height: number }
    const box = { x: d.x - d.width / 2 + PAD, y: d.y - d.height / 2 + HEADER, w: d.width, h: d.height }
    pos.set(n.id, box)
    w = Math.max(w, box.x + box.w)
    h = Math.max(h, box.y + box.h)
  }
  const res = { w: Math.max(w + PAD, 320), h: h + PAD, pos }
  layoutCache.set(key, res)
  return res
}

export interface Placed {
  inst: Inst
  flow: FnFlow
  layout: FlowLayout
  x: number
  y: number
}

export function place(insts: Inst[], flows: Map<string, FnFlow>): Placed[] {
  const items = insts
    .map((inst) => ({ inst, flow: flows.get(inst.fn) }))
    .filter((x): x is { inst: Inst; flow: FnFlow } => !!x.flow)
    .map(({ inst, flow }) => ({ inst, flow, layout: layoutFlow(flow), x: 0, y: 0 }))
  const maxW: number[] = []
  for (const p of items) maxW[p.inst.depth] = Math.max(maxW[p.inst.depth] ?? 0, p.layout.w)
  const colX: number[] = [0]
  for (let d = 1; d < maxW.length; d++) colX[d] = colX[d - 1] + (maxW[d - 1] ?? 0) + GAP_X
  const skyline: number[] = []
  const byKey = new Map<string, Placed>()
  for (const p of items) {
    const d = p.inst.depth
    let desired = 0
    if (p.inst.parent) {
      const par = byKey.get(p.inst.parent.key)
      const box = par?.layout.pos.get(p.inst.parentNode ?? 0)
      if (par && box) desired = par.y + box.y - HEADER + 6
    }
    p.x = colX[d] ?? 0
    p.y = Math.max(desired, skyline[d] ?? -Infinity)
    skyline[d] = p.y + p.layout.h + GAP_Y
    byKey.set(p.inst.key, p)
  }
  return items
}

// ---------------------------------------------------------------------------
// React Flow elements

export type NodeState = 'normal' | 'visited' | 'dim' | 'error' | 'static'

export interface FlowNodeData extends Record<string, unknown> {
  instKey: string
  node: FlowNode
  state: NodeState
  count: number
  targets: string[]
  openTargets: string[]
  isRoot: boolean
  libs: string[]
  raised: boolean
}

export interface GroupData extends Record<string, unknown> {
  inst: Inst
  flow: FnFlow
}

export function pipelineOverlay(flow: FnFlow, exec: Execution): FrameOverlay {
  const visits: Record<string, number> = { '0': 1 }
  const edges: Record<string, number> = {}
  const tops = exec.frames.filter((f) => f.parent === null)
  let errorNode: number | undefined
  for (const n of flow.nodes) {
    const t = n.calls?.[0]?.target
    if (!t) continue
    const fr = tops.filter((f) => f.fn === t)
    if (fr.length) {
      visits[String(n.id)] = fr.length
      if (fr.some((f) => f.exception) && errorNode === undefined) errorNode = n.id
    }
  }
  const resp = flow.nodes.length - 1
  visits[String(resp)] = 1
  // library middlewares are always traversed
  flow.nodes.forEach((n) => {
    if (n.kind === 'mwlib') visits[String(n.id)] = 1
  })
  flow.edges.forEach((e, i) => {
    if (visits[String(e.source)] && visits[String(e.target)]) edges[String(i)] = 1
  })
  return { id: -1, visits, edges, error_node: errorNode }
}

export function toElements(
  placed: Placed[],
  exec: Execution | null,
  selected: string | null,
): { nodes: RFNode[]; edges: RFEdge[] } {
  const nodes: RFNode[] = []
  const edges: RFEdge[] = []
  const openByNode = new Map<string, string[]>()
  for (const p of placed) {
    if (p.inst.parent) {
      const k = p.inst.parent.key + '#' + p.inst.parentNode
      openByNode.set(k, [...(openByNode.get(k) ?? []), p.inst.fn])
    }
  }
  for (const p of placed) {
    const { inst, flow, layout } = p
    let ov = inst.ov
    if (exec && inst.fn === PIPE) ov = pipelineOverlay(flow, exec)
    const hasRun = !!exec && (inst.fn === PIPE || !!inst.frame)
    nodes.push({
      id: inst.key,
      type: 'fnGroup',
      position: { x: p.x, y: p.y },
      data: { inst, flow } satisfies GroupData,
      style: { width: layout.w, height: layout.h },
      width: layout.w,
      height: layout.h,
      draggable: false,
      selectable: false,
      zIndex: 0,
    })
    const childFrames = exec && inst.frame ? exec.frames.filter((f) => f.parent === inst.frame!.id) : []
    for (const n of flow.nodes) {
      const box = layout.pos.get(n.id)!
      const count = ov?.visits?.[String(n.id)] ?? 0
      let state: NodeState = 'normal'
      if (exec) {
        if (!hasRun) state = 'static'
        else if (ov?.error_node === n.id) state = 'error'
        else state = count > 0 ? 'visited' : 'dim'
      }
      const observed = inst.fn === PIPE ? [] : childFrames.filter((f) => (ov && exec?.overlay?.frames.find((o) => o.id === f.id)?.call_node) === n.id)
      const id = inst.key + '#' + n.id
      const libs = [...new Set((n.calls ?? []).filter((c) => c.kind === 'external' && c.lib).map((c) => c.lib!))]
      const raised = !!inst.frame?.raised?.some((r) => r.line >= n.line && r.line <= n.end_line) && n.line > 0
      nodes.push({
        id,
        type: 'flowNode',
        parentId: inst.key,
        position: { x: box.x, y: box.y },
        width: box.w,
        height: box.h,
        data: {
          instKey: inst.key,
          node: n,
          state,
          count,
          targets: callTargets(n, observed),
          openTargets: openByNode.get(id) ?? [],
          isRoot: inst.parent === null,
          libs,
          raised,
        } satisfies FlowNodeData,
        draggable: false,
        selected: selected === id,
        zIndex: 1,
      })
    }
    flow.edges.forEach((e, i) => {
      const c = ov?.edges?.[String(i)] ?? 0
      const visited = hasRun && c > 0
      const cls = ['k-' + e.kind, exec ? (visited ? 'ev' : hasRun ? 'ed' : 'es') : '']
      edges.push({
        id: `${inst.key}#e${i}`,
        source: `${inst.key}#${e.source}`,
        target: `${inst.key}#${e.target}`,
        sourceHandle: 'b',
        targetHandle: 't',
        type: e.kind === 'loop' ? 'default' : 'smoothstep',
        label: visited && c > 1 ? `${e.label ? e.label + ' ' : ''}×${c}` : e.label || undefined,
        className: cls.join(' '),
        animated: visited,
        zIndex: 1,
      })
    })
    if (inst.parent) {
      const executed = inst.executed
      edges.push({
        id: `call:${inst.key}`,
        source: `${inst.parent.key}#${inst.parentNode}`,
        target: `${inst.key}#0`,
        sourceHandle: 'r',
        targetHandle: 'l',
        type: 'default',
        className: 'k-call ' + (exec ? (executed ? 'ev' : 'es') : ''),
        animated: !!exec && executed,
        label: inst.frames.length > 1 ? `${inst.frames.length} chamadas` : undefined,
        zIndex: 2,
      })
    }
  }
  return { nodes, edges }
}
