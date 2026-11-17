import { useEffect, useMemo, useState } from 'react'
import { severity } from '../insight'
import type { ExecSummary, MapData, RouteInfo } from '../types'

export interface RouteCount {
  n: number
  /** exceptions / 5xx */
  err: number
  /** refused by the API: 4xx */
  rej: number
}

export function MethodChip({ m }: { m: string }) {
  return <span className={`mchip m-${m.toLowerCase()}`}>{m}</span>
}

export function StatusChip({ s, err }: { s: number | null; err?: boolean }) {
  const cls = s == null ? 's-unk' : s >= 500 ? 's-5' : s >= 400 ? 's-4' : s >= 300 ? 's-3' : 's-2'
  return <span className={`schip ${cls} ${err ? 'with-err' : ''}`}>{s ?? '—'}</span>
}

export function ago(ts: number) {
  const s = Math.max(0, Date.now() / 1000 - ts)
  if (s < 5) return 'agora'
  if (s < 60) return `${Math.floor(s)}s`
  if (s < 3600) return `${Math.floor(s / 60)}min`
  if (s < 86400) return `${Math.floor(s / 3600)}h`
  return `${Math.floor(s / 86400)}d`
}

function groupKey(r: RouteInfo) {
  if (r.tags && r.tags.length) return r.tags[0]
  const seg = r.path.split('/').filter(Boolean)[0]
  return seg ? '/' + seg : '/'
}

function short(fn: string) {
  return fn.split('::').pop() ?? fn
}

export function RoutesList({
  routes,
  selected,
  onSelect,
  counts,
  map,
  onNeedMap,
  onOpenFn,
}: {
  routes: RouteInfo[]
  selected: string | null
  onSelect: (id: string) => void
  counts: Map<string, RouteCount>
  /** functions + call edges (loaded on the first search) */
  map: MapData | null
  onNeedMap: () => void
  onOpenFn: (fn: string) => void
}) {
  const [q, setQ] = useState('')
  const ql = q.trim().toLowerCase()
  useEffect(() => {
    if (ql && !map) onNeedMap()
  }, [ql, map, onNeedMap])

  // every function each route can reach (handler + dependencies, following calls)
  const reach = useMemo(() => {
    const out = new Map<string, Set<string>>()
    if (!map) return out
    const adj = new Map<string, string[]>()
    for (const e of map.edges) adj.set(e.source, [...(adj.get(e.source) ?? []), e.target])
    for (const r of routes) {
      const seen = new Set<string>()
      const stack = [r.handler, ...(r.dependencies ?? []).map((d) => d.fn)].filter((x): x is string => !!x)
      while (stack.length && seen.size < 2000) {
        const f = stack.pop()!
        if (seen.has(f)) continue
        seen.add(f)
        stack.push(...(adj.get(f) ?? []))
      }
      out.set(r.id, seen)
    }
    return out
  }, [map, routes])

  const fnHits = useMemo(() => {
    if (!ql || !map) return []
    return map.functions.filter((f) => f.qualname.toLowerCase().includes(ql) || f.id.toLowerCase().includes(ql)).slice(0, 30)
  }, [ql, map])

  const groups = useMemo(() => {
    const hitIds = new Set(fnHits.map((f) => f.id))
    const m = new Map<string, RouteInfo[]>()
    for (const r of routes) {
      const direct = r.path.toLowerCase().includes(ql) || (r.handler ?? '').toLowerCase().includes(ql) || r.methods.join(' ').toLowerCase().includes(ql)
      const viaFn = [...(reach.get(r.id) ?? [])].some((f) => hitIds.has(f))
      if (ql && !direct && !viaFn) continue
      const k = groupKey(r)
      m.set(k, [...(m.get(k) ?? []), r])
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [routes, ql, fnHits, reach])

  const usedBy = (fn: string) => routes.filter((r) => reach.get(r.id)?.has(fn))

  return (
    <div className="list">
      <input className="search" placeholder="Buscar rota, método ou função…" value={q} onChange={(e) => setQ(e.target.value)} />
      {fnHits.length > 0 && (
        <div className="grp">
          <div className="grp-t">
            Funções <span className="muted">{fnHits.length}</span>
          </div>
          {fnHits.map((f) => {
            const users = usedBy(f.id)
            return (
              <div key={f.id} className="row fnrow" onClick={() => onOpenFn(f.id)} title={`${f.file}:${f.line}`}>
                <span className="fname">{short(f.id)}</span>
                <span className="muted fused">
                  {users.length ? `em ${users.map((r) => r.id).slice(0, 2).join(', ')}${users.length > 2 ? ` +${users.length - 2}` : ''}` : f.file}
                </span>
              </div>
            )
          })}
        </div>
      )}
      {ql && !map && <div className="muted pad">procurando nas funções…</div>}
      {groups.map(([g, rs]) => (
        <div key={g} className="grp">
          <div className="grp-t">
            {g} <span className="muted">{rs.length}</span>
          </div>
          {rs.map((r) => {
            const c = counts.get(r.id)
            return (
              <div
                key={r.id}
                className={`row ${selected === r.id ? 'on' : ''} ${r.handler ? '' : 'nohandler'}`}
                onClick={() => onSelect(r.id)}
                title={r.handler ?? r.handler_desc ?? ''}
              >
                <span className="mchips">
                  {(r.methods.length ? r.methods : [r.kind.toUpperCase()]).map((m) => (
                    <MethodChip key={m} m={m} />
                  ))}
                </span>
                <span className="rpath">{r.path}</span>
                {c && (
                  <span className="rcounts" title={`${c.n} ${c.n === 1 ? 'execução' : 'execuções'} · ${c.err} com erro (exceção/5xx) · ${c.rej} recusadas (4xx)`}>
                    <span className="rcount">{c.n}</span>
                    {c.err > 0 && <span className="rcount has-err">{c.err} ✗</span>}
                    {c.rej > 0 && <span className="rcount has-rej">{c.rej} 4xx</span>}
                  </span>
                )}
              </div>
            )
          })}
        </div>
      ))}
      {groups.length === 0 && fnHits.length === 0 && (map || !ql) && <div className="muted pad">Nada encontrado.</div>}
    </div>
  )
}

export function ExecList({
  items,
  selected,
  onSelect,
}: {
  items: ExecSummary[]
  selected: string | null
  onSelect: (id: string) => void
}) {
  const [q, setQ] = useState('')
  const ql = q.trim().toLowerCase()
  const shown = ql
    ? items.filter((e) =>
        [e.id, e.method, e.path, String(e.status ?? ''), e.hint ?? '', e.detail ?? '', e.error?.type ?? '', e.error?.message ?? '']
          .join(' ')
          .toLowerCase()
          .includes(ql),
      )
    : items
  return (
    <div className="list">
      <input className="search" placeholder="Buscar execução: caminho, status, valor, erro…" value={q} onChange={(e) => setQ(e.target.value)} />
      {shown.map((e) => (
        <div key={e.id} className={`row exec ${selected === e.id ? 'on' : ''}`} onClick={() => onSelect(e.id)} title={`#${e.id}`}>
          <StatusChip s={e.status} err={!!e.error} />
          <MethodChip m={e.method} />
          <span className="rpath" title={e.path}>
            {e.path}
          </span>
          {e.mode === 'replay' && (
            <span className="replay-b" title={`replay de #${e.replay_of ?? 'manual'}`}>
              ↻
            </span>
          )}
          <span className="edur">{e.duration_ms < 10 ? e.duration_ms.toFixed(1) : Math.round(e.duration_ms)}ms</span>
          <span className="eago">{ago(e.started_at)}</span>
          {e.hint && <div className="ehint">{e.hint}</div>}
          {e.error ? (
            <div className={`eerr ${severity(e) === 'rej' ? 'rej' : ''}`} title={e.error.message}>
              {e.error.type}: {e.error.message}
            </div>
          ) : (
            e.detail && (
              <div className="eerr rej" title={e.detail}>
                {e.detail}
              </div>
            )
          )}
        </div>
      ))}
      {items.length > 0 && shown.length === 0 && <div className="muted pad">Nenhuma execução com “{q}”.</div>}
      {items.length === 0 && (
        <div className="muted pad">
          Nenhuma execução ainda. Faça uma requisição à API (ou envie o header <code>X-Glowtrace-Trace: 1</code> se a amostragem estiver baixa).
        </div>
      )}
    </div>
  )
}
