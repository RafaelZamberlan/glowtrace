import { useState } from 'react'

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

function Scalar({ v }: { v: unknown }) {
  if (v === null || v === undefined) return <span className="j-null">null</span>
  if (typeof v === 'string') {
    if (v === '[REDACTED]' || /^\[(CPF|CNPJ|CARD|JWT)\]$/.test(v)) return <span className="j-red">{v}</span>
    if (/^<.*>$/.test(v))
      return (
        <span className="j-obj" title="valor não aberto pelo Glowtrace (profundidade, ciclo, framework ou proxy)">
          {v}
        </span>
      )
    return <span className="j-str">"{v}"</span>
  }
  if (typeof v === 'number') return <span className="j-num">{String(v)}</span>
  if (typeof v === 'boolean') return <span className="j-bool">{String(v)}</span>
  return <span>{String(v)}</span>
}

function Entry({ k, v, depth }: { k: string | null; v: unknown; depth: number }) {
  const complex = Array.isArray(v) || isObj(v)
  const [open, setOpen] = useState(depth < 2)
  if (!complex) {
    return (
      <div className="j-row">
        {k !== null && <span className="j-key">{k}: </span>}
        <Scalar v={v} />
      </div>
    )
  }
  const arr = Array.isArray(v)
  const entries: [string, unknown][] = arr ? (v as unknown[]).map((x, i) => [String(i), x]) : Object.entries(v as object)
  const typeName = !arr && isObj(v) && typeof v.__type__ === 'string' ? (v.__type__ as string) : null
  const shown = entries.filter(([kk]) => kk !== '__type__')
  return (
    <div className="j-row">
      <span className="j-toggle" onClick={() => setOpen(!open)}>
        {open ? '▾' : '▸'} {k !== null && <span className="j-key">{k}: </span>}
        <span className="j-meta">
          {typeName ? typeName + ' ' : ''}
          {arr ? `[${shown.length}]` : `{${shown.length}}`}
        </span>
      </span>
      {open && (
        <div className="j-children">
          {shown.map(([kk, vv]) => (
            <Entry key={kk} k={kk} v={vv} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  )
}

export function JsonView({ value, empty = '—' }: { value: unknown; empty?: string }) {
  if (value === undefined) return <div className="j-empty">{empty}</div>
  if (isObj(value) && Object.keys(value).length === 0) return <div className="j-empty">{'{}'}</div>
  return (
    <div className="json">
      <Entry k={null} v={value} depth={0} />
    </div>
  )
}
