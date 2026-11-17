export type CallKind = 'user' | 'external' | 'stdlib' | 'builtin' | 'unresolved'

export interface CallInfo {
  expr: string
  kind: CallKind
  target?: string
  lib?: string
  awaited?: boolean
  line: number
}

export interface FlowNode {
  id: number
  kind: string
  label: string
  line: number
  end_line: number
  own?: [number, number] | null
  parent?: number
  calls?: CallInfo[]
  watch?: string[]
  assigns?: string[]
  try_parent?: number
  loop_parent?: number
}

export interface FlowEdge {
  source: number
  target: number
  kind: string
  label?: string
}

export interface FnFlow {
  id: string
  qualname: string
  file: string
  line: number
  end_line: number
  is_async: boolean
  params: string[]
  doc?: string | null
  source: string
  source_start: number
  source_hash: string
  nodes: FlowNode[]
  edges: FlowEdge[]
  observed_calls?: string[]
}

export interface RouteInfo {
  id: string
  kind: 'http' | 'websocket' | 'mount'
  methods: string[]
  path: string
  name?: string | null
  summary?: string | null
  tags?: string[]
  handler?: string | null
  handler_desc?: string | null
  dependencies?: { fn: string; desc: string }[]
  file?: string | null
  line?: number | null
  is_async?: boolean | null
}

export interface MiddlewareInfo {
  name: string
  fn: string | null
  kind: 'user' | 'library'
}

export interface Meta {
  title: string
  version: string
  mode: string
  backend: string | null
  python?: string
  runtime?: string
  prefix: string
  sample_rate: number
  route_count: number
  /** POST /api/replay is enabled (GLOWTRACE_REPLAY=1, development only) */
  replay_enabled?: boolean
  /** how much of each value is kept (GLOWTRACE_MAX_DEPTH / _ITEMS / _VALUES / _STR) */
  capture?: CaptureLimits
}

export interface CaptureLimits {
  max_depth: number
  max_items: number
  max_values: number
  max_str: number
}

export interface ExecError {
  type: string
  message: string
  escaped?: boolean
  status_code?: number
  frame?: number
}

export interface ExecSummary {
  id: string
  trace_id: string
  started_at: number
  method: string
  path: string
  route_id: string | null
  status: number | null
  duration_ms: number
  error: ExecError | null
  frame_count: number
  /** "replay" when created by POST /api/replay */
  mode?: 'recorded' | 'replay'
  replay_of?: string | null
  /** a few request values that tell executions apart ("cliente=ana · itens[2]") */
  hint?: string | null
  /** why a 4xx/5xx was refused ({"detail": ...}) */
  detail?: string | null
}

export type ValueSnap = [number, Record<string, unknown>, 'before' | 'after']

export interface Frame {
  id: number
  parent: number | null
  fn: string
  call_line: number | null
  args: Record<string, unknown>
  start_us: number
  end_us: number | null
  path: [number, number][]
  values: ValueSnap[]
  return?: unknown
  exception?: { type: string; message: string; line: number; detail?: unknown; status_code?: number }
  raised?: { line: number; type: string; message: string }[]
  hash?: string
  incomplete?: boolean
  truncated?: boolean
}

export interface FrameOverlay {
  id: number
  visits?: Record<string, number>
  edges?: Record<string, number>
  error_node?: number
  call_node?: number
  stale?: boolean
  missing?: boolean
  jumps?: [number, number][]
}

export interface Execution extends ExecSummary {
  truncated?: boolean
  backend?: string
  request: { headers: Record<string, string>; query: unknown; path_params: unknown; body: unknown; body_source?: string }
  response: { headers: Record<string, string>; body: unknown; body_source?: string }
  frames: Frame[]
  overlay?: { frames: FrameOverlay[] }
  replay_edits?: string[]
}

export interface ReplaySpec {
  method: string
  path: string
  query?: string
  headers?: Record<string, string>
  body?: unknown
  replay_of?: string | null
  edits?: string[]
}

export interface ReplayResult {
  status: number
  execution_id: string | null
  recorded: boolean
  error: string | null
  response_size: number
  response_preview: string
}

export interface MapData {
  routes: RouteInfo[]
  middlewares: MiddlewareInfo[]
  functions: {
    id: string
    qualname: string
    file: string
    line: number
    is_async: boolean
    nodes: number
    branches: number
    external: string[]
    observed_only?: boolean
  }[]
  edges: { source: string; target: string; static: boolean; observed: number }[]
}
