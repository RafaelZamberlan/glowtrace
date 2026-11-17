// Compare a replay with its original execution: request changes, response changes,
// and where the code took a different path (branches, calls, exceptions).
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { branchCounts, branchName, fmtMs, isBranchNode, passesFor, summarize } from '../insight'
import type { Execution, FnFlow } from '../types'

function leaves(v: unknown, path: string, out: Map<string, unknown>) {
  if (Array.isArray(v)) {
    if (!v.length) out.set(path, v)
    v.forEach((x, i) => leaves(x, `${path}[${i}]`, out))
  } else if (v && typeof v === 'object') {
    const e = Object.entries(v as object).filter(([k]) => k !== '__type__')
    if (!e.length) out.set(path, v)
    for (const [k, x] of e) leaves(x, path ? `${path}.${k}` : k, out)
  } else out.set(path, v)
}

interface Change {
  path: string
  a: unknown
  b: unknown
  kind: 'changed' | 'added' | 'removed'
}

function diff(a: unknown, b: unknown, root: string): Change[] {
  const ma = new Map<string, unknown>()
  const mb = new Map<string, unknown>()
  leaves(a ?? null, root, ma)
  leaves(b ?? null, root, mb)
  const out: Change[] = []
  for (const [k, v] of ma) {
    if (!mb.has(k)) out.push({ path: k, a: v, b: undefined, kind: 'removed' })
    else if (JSON.stringify(v) !== JSON.stringify(mb.get(k))) out.push({ path: k, a: v, b: mb.get(k), kind: 'changed' })
  }
  for (const [k, v] of mb) if (!ma.has(k)) out.push({ path: k, a: undefined, b: v, kind: 'added' })
  return out
}

const short = (fn: string) => fn.split('::').pop() ?? fn

interface PathDiff {
  fn: string
  text: string
  a: string
  b: string
  /** flip = took another branch; count = same branches, different number of times */
  kind: 'flip' | 'count' | 'call' | 'exc'
}

function pathDiffs(a: Execution, b: Execution, flows: Map<string, FnFlow>): PathDiff[] {
  const out: PathDiff[] = []
  const fnsA = new Set(a.frames.map((f) => f.fn))
  const fnsB = new Set(b.frames.map((f) => f.fn))
  for (const fn of fnsA) if (!fnsB.has(fn)) out.push({ fn, text: `${short(fn)} não foi chamada no reenvio`, a: 'chamada', b: '—', kind: 'call' })
  for (const fn of fnsB) if (!fnsA.has(fn)) out.push({ fn, text: `${short(fn)} só foi chamada no reenvio`, a: '—', b: 'chamada', kind: 'call' })
  for (const fn of fnsA) {
    if (!fnsB.has(fn)) continue
    const fa = a.frames.filter((f) => f.fn === fn)
    const fb = b.frames.filter((f) => f.fn === fn)
    const ea = fa.find((f) => f.exception)?.exception?.type ?? null
    const eb = fb.find((f) => f.exception)?.exception?.type ?? null
    if (ea !== eb) out.push({ fn, text: `${short(fn)}: exceção`, a: ea ?? 'nenhuma', b: eb ?? 'nenhuma', kind: 'exc' })
    if (fa.length !== fb.length) out.push({ fn, text: `${short(fn)}: número de chamadas`, a: String(fa.length), b: String(fb.length), kind: 'count' })
    const flow = flows.get(fn)
    if (!flow) continue
    for (const n of flow.nodes) {
      if (!isBranchNode(n)) continue
      const ca = branchCounts(fa.flatMap((f) => passesFor(f, flow, n.id)))
      const cb = branchCounts(fb.flatMap((f) => passesFor(f, flow, n.id)))
      const fmt = (c: [string, number][]) => (c.length ? c.map(([k, v]) => `${branchName(k)} ${v}`).join(' · ') : 'não avaliada')
      if (fmt(ca) === fmt(cb)) continue
      const same = ca.map(([k]) => k).sort().join() === cb.map(([k]) => k).sort().join()
      out.push({ fn, text: `${short(fn)} · ${n.label}`, a: fmt(ca), b: fmt(cb), kind: same ? 'count' : 'flip' })
    }
  }
  return out
}

export function ComparePanel({
  exec,
  flows,
  onOpenExec,
  onClose,
}: {
  exec: Execution
  flows: Map<string, FnFlow>
  onOpenExec: (id: string) => void
  onClose: () => void
}) {
  const origId = exec.replay_of && exec.replay_of !== 'manual' ? exec.replay_of : null
  const [orig, setOrig] = useState<Execution | null>(null)
  const [fail, setFail] = useState<string | null>(null)
  const [fl, setFl] = useState(flows)

  useEffect(() => {
    if (!origId) return
    api
      .execution(origId)
      .then(setOrig)
      .catch(() => setFail('A execução original não está mais gravada (limpa ou removida pela retenção).'))
  }, [origId])

  useEffect(() => {
    if (!orig) return
    const need = [...new Set([...orig.frames, ...exec.frames].map((f) => f.fn))].filter((f) => !fl.has(f))
    if (!need.length) return
    Promise.all(need.map((f) => api.fn(f).then((x) => [f, x] as const).catch(() => null))).then((res) =>
      setFl((prev) => {
        const m = new Map(prev)
        res.forEach((r) => r && m.set(r[0], r[1]))
        return m
      }),
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orig, exec])

  const reqChanges = useMemo(
    () => (orig ? [...diff(orig.request.body, exec.request.body, 'body'), ...diff(orig.request.query, exec.request.query, 'query')] : []),
    [orig, exec],
  )
  const respChanges = useMemo(() => (orig ? diff(orig.response.body, exec.response.body, 'resposta') : []), [orig, exec])
  const paths = useMemo(() => (orig ? pathDiffs(orig, exec, fl) : []), [orig, exec, fl])

  return (
    <aside className="inspector mid">
      <div className="ins-head">
        <div>
          <div className="fn-chip cat-ctrl">COMPARAR</div>
          <div className="ins-title">original × reenvio</div>
          <div className="ins-sub">
            {origId && (
              <span className="linkish" onClick={() => onOpenExec(origId)}>
                abrir original #{origId.slice(0, 8)}
              </span>
            )}
          </div>
        </div>
        <button className="x" onClick={onClose} title="fechar (Esc)">
          ×
        </button>
      </div>
      {!origId && <div className="muted pad">Este reenvio não aponta para uma execução original.</div>}
      {fail && <div className="exc pad-x">{fail}</div>}
      {origId && !orig && !fail && <div className="muted pad">carregando o original…</div>}
      {orig && (
        <>
          <section className="sec">
            <table className="cmp-t">
              <thead>
                <tr>
                  <th />
                  <th>original</th>
                  <th>reenvio</th>
                </tr>
              </thead>
              <tbody>
                <Row k="status" a={orig.status ?? '—'} b={exec.status ?? '—'} />
                <Row k="duração" a={fmtMs(orig.duration_ms)} b={fmtMs(exec.duration_ms)} plain />
                <Row k="funções" a={orig.frame_count} b={exec.frame_count} />
                <Row k="erro" a={orig.error ? orig.error.type : 'nenhum'} b={exec.error ? exec.error.type : 'nenhum'} />
              </tbody>
            </table>
          </section>
          <Changes title="O que você mudou na requisição" items={reqChanges} empty="nada no corpo nem na query (veja headers)" note={exec.replay_edits?.length ? `editado: ${exec.replay_edits.join(', ')}` : undefined} />
          <section className="sec">
            <div className="sec-t">Onde o código seguiu outro caminho ({paths.filter((d) => d.kind !== 'count').length})</div>
            {paths.filter((d) => d.kind !== 'count').length === 0 && <div className="muted">mesmas decisões nas duas execuções</div>}
            {paths
              .filter((d) => d.kind !== 'count')
              .slice(0, 60)
              .map((d, i) => (
                <PathRow key={i} d={d} />
              ))}
            {paths.some((d) => d.kind === 'count') && (
              <details className="cmp-more">
                <summary>mesmo caminho, mas outra quantidade de vezes ({paths.filter((d) => d.kind === 'count').length})</summary>
                {paths
                  .filter((d) => d.kind === 'count')
                  .slice(0, 60)
                  .map((d, i) => (
                    <PathRow key={i} d={d} />
                  ))}
              </details>
            )}
          </section>
          <Changes title="O que mudou na resposta" items={respChanges} empty="resposta idêntica" />
        </>
      )}
    </aside>
  )
}

function PathRow({ d }: { d: PathDiff }) {
  return (
    <div className={`cmp-row k-${d.kind}`}>
      <div className="cmp-k">{d.text}</div>
      <div className="cmp-v">
        <span className="cmp-a">{d.a}</span> → <span className="cmp-b">{d.b}</span>
      </div>
    </div>
  )
}

function Row({ k, a, b, plain }: { k: string; a: string | number; b: string | number; plain?: boolean }) {
  const changed = !plain && String(a) !== String(b)
  return (
    <tr className={changed ? 'chg' : ''}>
      <th>{k}</th>
      <td>{a}</td>
      <td>{b}</td>
    </tr>
  )
}

function Changes({ title, items, empty, note }: { title: string; items: Change[]; empty: string; note?: string }) {
  return (
    <section className="sec">
      <div className="sec-t">
        {title} ({items.length})
      </div>
      {note && <div className="muted">{note}</div>}
      {items.length === 0 && <div className="muted">{empty}</div>}
      {items.slice(0, 80).map((c) => (
        <div key={c.path} className={`cmp-row ${c.kind}`}>
          <div className="cmp-k">{c.path}</div>
          <div className="cmp-v">
            {c.kind === 'added' ? (
              <span className="cmp-b">+ {summarize(c.b, 40)}</span>
            ) : c.kind === 'removed' ? (
              <span className="cmp-a">− {summarize(c.a, 40)}</span>
            ) : (
              <>
                <span className="cmp-a">{summarize(c.a, 40)}</span> → <span className="cmp-b">{summarize(c.b, 40)}</span>
              </>
            )}
          </div>
        </div>
      ))}
      {items.length > 80 && <div className="muted">… +{items.length - 80}</div>}
    </section>
  )
}
