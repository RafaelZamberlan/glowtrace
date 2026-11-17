import { useMemo, useState } from 'react'
import type { ExecSummary, RouteInfo } from '../types'

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

export function RoutesList({
  routes,
  selected,
  onSelect,
  counts,
}: {
  routes: RouteInfo[]
  selected: string | null
  onSelect: (id: string) => void
  counts: Map<string, { n: number; err: number }>
}) {
  const [q, setQ] = useState('')
  const groups = useMemo(() => {
    const ql = q.trim().toLowerCase()
    const m = new Map<string, RouteInfo[]>()
    for (const r of routes) {
      if (ql && !(r.path.toLowerCase().includes(ql) || (r.handler ?? '').toLowerCase().includes(ql) || r.methods.join(' ').toLowerCase().includes(ql)))
        continue
      const k = groupKey(r)
      m.set(k, [...(m.get(k) ?? []), r])
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [routes, q])
  return (
    <div className="list">
      <input className="search" placeholder="Buscar rota, método ou função…" value={q} onChange={(e) => setQ(e.target.value)} />
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
                  <span className={`rcount ${c.err ? 'has-err' : ''}`} title={`${c.n} execuções, ${c.err} com erro`}>
                    {c.n}
                  </span>
                )}
              </div>
            )
          })}
        </div>
      ))}
      {groups.length === 0 && <div className="muted pad">Nenhuma rota.</div>}
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
  return (
    <div className="list">
      {items.map((e) => (
        <div key={e.id} className={`row exec ${selected === e.id ? 'on' : ''}`} onClick={() => onSelect(e.id)}>
          <StatusChip s={e.status} err={!!e.error} />
          <MethodChip m={e.method} />
          <span className="rpath" title={e.path}>
            {e.path}
          </span>
          <span className="edur">{e.duration_ms < 10 ? e.duration_ms.toFixed(1) : Math.round(e.duration_ms)}ms</span>
          <span className="eago">{ago(e.started_at)}</span>
          {e.error && (
            <div className="eerr" title={e.error.message}>
              {e.error.type}: {e.error.message}
            </div>
          )}
        </div>
      ))}
      {items.length === 0 && (
        <div className="muted pad">
          Nenhuma execução ainda. Faça uma requisição à API (ou envie o header <code>X-Glowtrace-Trace: 1</code> se a amostragem estiver baixa).
        </div>
      )}
    </div>
  )
}
