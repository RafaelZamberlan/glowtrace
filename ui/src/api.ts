import type { ExecSummary, Execution, FnFlow, MapData, Meta, MiddlewareInfo, ReplayResult, ReplaySpec, RouteInfo } from './types'

// When served by the Python package the UI lives at <prefix>/ (e.g. /_glowtrace/).
export const BASE = import.meta.env.DEV
  ? '/_glowtrace'
  : window.location.pathname.replace(/index\.html$/, '').replace(/\/$/, '')

async function get<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, { credentials: 'same-origin', ...init })
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* ignore */
    }
    throw new Error(`${res.status}: ${detail}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  meta: () => get<Meta>('/api/meta'),
  routes: () => get<{ routes: RouteInfo[]; middlewares: MiddlewareInfo[] }>('/api/routes'),
  fn: (id: string) => get<FnFlow>('/api/function?id=' + encodeURIComponent(id)),
  map: () => get<MapData>('/api/map'),
  executions: (route?: string | null, status?: string | null, limit = 150) => {
    const q = new URLSearchParams({ limit: String(limit) })
    if (route) q.set('route', route)
    if (status) q.set('status', status)
    return get<{ executions: ExecSummary[] }>('/api/executions?' + q)
  },
  execution: (id: string) => get<Execution>('/api/executions/' + encodeURIComponent(id)),
  clear: () => get<{ deleted: number }>('/api/executions', { method: 'DELETE' }),
  replay: async (spec: ReplaySpec): Promise<ReplayResult> => {
    const res = await fetch(BASE + '/api/replay', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(spec),
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new ReplayFailure(res.status, data.detail ?? res.statusText, data.fields ?? [])
    return data as ReplayResult
  },
}

export class ReplayFailure extends Error {
  constructor(
    public status: number,
    detail: string,
    public fields: string[],
  ) {
    super(detail)
  }
}
