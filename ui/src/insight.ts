// Read an execution: passes per node, branch taken, value summaries, node status
// lines, executed source lines. Shared by the canvas (status line) and the panels.
import type { Execution, FlowNode, FnFlow, Frame, FrameOverlay } from './types'

export const MASK_RE = /\[(REDACTED|CPF|CNPJ|CARD|JWT)\]/

/** err = crashed (5xx / exception that escaped); rej = the API refused the request (4xx). */
export function severity(e: { status: number | null; error: { escaped?: boolean } | null }): 'ok' | 'rej' | 'err' {
  const s = e.status ?? 0
  if (s >= 500 || e.error?.escaped) return 'err'
  if (s >= 400) return 'rej'
  return e.error ? 'err' : 'ok'
}

export function fmtUs(us: number | null | undefined): string {
  if (us == null) return '—'
  return fmtMs(us / 1000)
}

export function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return '—'
  if (ms < 1) return `${ms.toFixed(2)} ms`
  if (ms < 1000) return `${ms < 10 ? ms.toFixed(1) : Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`
}

export function frameDurUs(f: Frame | null | undefined): number | null {
  return f && f.end_us != null ? f.end_us - f.start_us : null
}

/** One-word-ish summary of a captured value: 239.6, "ana", dict(3), list[5], Pedido, null. */
export function summarize(v: unknown, max = 18): string {
  if (v === null || v === undefined) return 'null' // same word the JSON views use, for every language
  if (typeof v === 'string') {
    if (MASK_RE.test(v) || /^<.*>$/.test(v)) return v.length > max ? v.slice(0, max - 1) + '…' : v
    const s = v.length > max - 2 ? v.slice(0, max - 3) + '…' : v
    return `"${s}"`
  }
  if (typeof v === 'number' || typeof v === 'boolean') {
    const s = String(v)
    return s.length > max ? s.slice(0, max - 1) + '…' : s
  }
  if (Array.isArray(v)) return `list[${v.length}]`
  if (typeof v === 'object') {
    const o = v as Record<string, unknown>
    if (typeof o.__type__ === 'string') return o.__type__
    return `dict(${Object.keys(o).length})`
  }
  return String(v)
}

/** A text field that holds JSON ('{"id": ...}'): the parsed object/list, or undefined. */
export function jsonInText(v: unknown): object | undefined {
  if (typeof v !== 'string' || v.length < 2 || v.length > 200_000) return undefined
  const t = v.trim()
  if (!((t.startsWith('{') && t.endsWith('}')) || (t.startsWith('[') && t.endsWith(']')))) return undefined
  try {
    const p = JSON.parse(t)
    return p && typeof p === 'object' ? p : undefined
  } catch {
    return undefined
  }
}

export function typeName(v: unknown): string {
  if (v === null || v === undefined) return 'null'
  if (typeof v === 'string') {
    if (MASK_RE.test(v)) return 'redigido'
    // "<LinkedHashMap>", "<ciclo No>", "<LazyProxy Owner>": the type of the value that was not opened
    const m = /^<(?:ciclo |LazyProxy )?([A-Za-z_$][\w$.]*)[^<>]*>$/.exec(v)
    return m ? m[1] : 'str'
  }
  if (typeof v === 'number') return Number.isInteger(v) ? 'int' : 'float'
  if (typeof v === 'boolean') return 'bool'
  if (Array.isArray(v)) return `list[${v.length}]`
  if (typeof v === 'object') {
    const o = v as Record<string, unknown>
    return typeof o.__type__ === 'string' ? o.__type__ : 'dict'
  }
  return typeof v
}

export const BRANCH_TRUE = new Set(['sim', 'true', 'cada', 'casou'])

/** Words shown to people for a branch label (the graph keeps the short ones). */
export function branchName(label: string | null | undefined): string {
  if (!label) return '—'
  if (label === 'cada') return 'repete'
  if (label === 'fim' || label === 'exit') return 'saída'
  return label
}
export const BRANCH_FALSE = new Set(['não', 'false', 'fim', 'exit', 'nenhum'])

/** Label of the edge taken from `node` to the next visited node (sim/não/cada/fim/<case>). */
export function branchOf(flow: FnFlow, node: number, next: number | undefined): string | null {
  if (next === undefined) return null
  // an `if` without `else` leaves through an unlabeled edge (next / loop back): that is its "não"
  const name = (e: { label?: string; kind: string }) => e.label || (flow.nodes[node]?.kind === 'if' ? 'não' : e.kind)
  const e = flow.edges.find((x) => x.source === node && x.target === next)
  if (e) return name(e)
  // the next visited node may be further away (silent nodes in between): follow single edges
  const outs = flow.edges.filter((x) => x.source === node)
  for (const o of outs) {
    let cur = o.target
    for (let i = 0; i < 4; i++) {
      if (cur === next) return name(o)
      const n = flow.nodes[cur]
      if (!n || !['finally', 'try', 'end'].includes(n.kind)) break
      const nx = flow.edges.filter((x) => x.source === cur)
      if (nx.length !== 1) break
      cur = nx[0].target
    }
  }
  return null
}

export interface Pass {
  index: number // 0-based visit number of this node
  pos: number // position in frame.path
  t: number // µs since request start
  before?: Record<string, unknown>
  after?: Record<string, unknown>
  branch: string | null
}

export function passesFor(frame: Frame, flow: FnFlow, nodeId: number): Pass[] {
  const out: Pass[] = []
  const path = frame.path ?? []
  const values = frame.values ?? []
  path.forEach(([nid, t], pos) => {
    if (nid !== nodeId) return
    const before = values.find((x) => x[0] === pos && x[2] === 'before')?.[1]
    const after = values.find((x) => x[0] === pos && x[2] === 'after')?.[1]
    out.push({ index: out.length, pos, t, before, after, branch: branchOf(flow, nodeId, path[pos + 1]?.[0]) })
  })
  return out
}

export function isBranchNode(n: FlowNode): boolean {
  return ['if', 'loop', 'match', 'case'].includes(n.kind)
}

export function branchCounts(passes: Pass[]): [string, number][] {
  const m = new Map<string, number>()
  for (const p of passes) if (p.branch) m.set(p.branch, (m.get(p.branch) ?? 0) + 1)
  return [...m.entries()]
}

export function childFramesOf(exec: Execution, frame: Frame, nodeId: number): Frame[] {
  const ov = new Map((exec.overlay?.frames ?? []).map((o) => [o.id, o]))
  return exec.frames.filter((f) => f.parent === frame.id && ov.get(f.id)?.call_node === nodeId)
}

export interface Status {
  text: string
  tone: 'ok' | 'err' | 'warn' | 'muted'
}

/** Short status line under a node (≤ ~22 chars), Node-RED style. */
export function nodeStatus(n: FlowNode, flow: FnFlow, frame: Frame | null, ov: FrameOverlay | null, exec: Execution | null): Status | null {
  if (!exec || !frame || !ov) return null
  const count = ov.visits?.[String(n.id)] ?? 0
  if (ov.error_node === n.id && frame.exception) return { text: frame.exception.type, tone: 'err' }
  if (count === 0) return null
  switch (n.kind) {
    case 'start': {
      const d = frameDurUs(frame)
      return d == null ? { text: 'em andamento', tone: 'warn' } : { text: fmtUs(d), tone: frame.exception ? 'err' : 'ok' }
    }
    case 'end':
      return frame.exception ? null : { text: 'concluiu', tone: 'ok' }
    case 'if':
    case 'match':
    case 'case': {
      const counts = branchCounts(passesFor(frame, flow, n.id))
      if (!counts.length) return { text: `${count}×`, tone: 'ok' }
      if (counts.length === 1 && counts[0][1] === 1) return { text: `→ ${counts[0][0]}`, tone: 'ok' }
      return { text: counts.map(([b, c]) => `${b} ${c}`).join(' · '), tone: 'ok' }
    }
    case 'loop': {
      const counts = branchCounts(passesFor(frame, flow, n.id))
      const iters = counts.filter(([b]) => BRANCH_TRUE.has(b)).reduce((a, [, c]) => a + c, 0)
      return { text: `${iters} ${iters === 1 ? 'iteração' : 'iterações'}`, tone: 'ok' }
    }
    case 'call': {
      const kids = childFramesOf(exec, frame, n.id)
      if (kids.length) {
        const bad = kids.find((k) => k.exception)
        if (bad) return { text: bad.exception!.type, tone: 'err' }
        const total = kids.reduce((a, k) => a + (frameDurUs(k) ?? 0), 0)
        return { text: `${fmtUs(total)}${kids.length > 1 ? ` · ${kids.length}×` : ''}`, tone: 'ok' }
      }
      return assigned(frame, flow, n.id)
    }
    case 'return':
      return frame.exception ? { text: 'executou', tone: 'ok' } : { text: `→ ${summarize(frame.return)}`, tone: 'ok' }
    case 'raise': {
      const r = frame.raised?.find((x) => x.line >= n.line && x.line <= n.end_line)
      return { text: `levantou ${r?.type ?? 'exceção'}`, tone: 'warn' }
    }
    case 'except': {
      const r = frame.raised?.[frame.raised.length - 1]
      return { text: r ? `pegou ${r.type}` : 'tratou exceção', tone: 'warn' }
    }
    case 'try':
    case 'finally':
    case 'with':
      return null
    default:
      return assigned(frame, flow, n.id)
  }
}

function assigned(frame: Frame, flow: FnFlow, nodeId: number): Status | null {
  const p = passesFor(frame, flow, nodeId)
  const last = [...p].reverse().find((x) => x.after && Object.keys(x.after).length)
  if (!last?.after) return null
  const [k, v] = Object.entries(last.after)[0]
  return { text: `${k} = ${summarize(v, 12)}`, tone: 'ok' }
}

/** Static subtitle (no execution selected). */
export function staticSubtitle(n: FlowNode, flow: FnFlow): string | null {
  if (n.kind === 'start' && flow.doc) return flow.doc.split('\n')[0].slice(0, 40)
  if (n.kind === 'call' || n.kind === 'return' || n.kind === 'with') {
    const user = n.calls?.find((c) => c.kind === 'user' && c.target)
    if (user) return `→ ${user.target!.split('::').pop()}`
    const ext = n.calls?.find((c) => c.kind === 'external' && c.lib)
    if (ext) return `lib ${ext.lib}`
  }
  if (n.kind === 'step' && n.assigns?.length) return `define ${n.assigns.slice(0, 3).join(', ')}`
  return null
}

/** Source lines owned by visited nodes, with visit counts; and the error line. */
export function executedLines(flow: FnFlow, frame: Frame | null, ov: FrameOverlay | null): { lines: Map<number, number>; errorLine: number | null } {
  const lines = new Map<number, number>()
  if (!frame || !ov) return { lines, errorLine: null }
  for (const n of flow.nodes) {
    const c = ov.visits?.[String(n.id)] ?? 0
    const r = n.own ?? (n.line && n.kind !== 'end' ? [n.line, n.line] : null)
    if (!c || !r) continue
    for (let l = r[0]; l <= r[1]; l++) lines.set(l, Math.max(lines.get(l) ?? 0, c))
  }
  return { lines, errorLine: frame.exception?.line ?? null }
}
