// Condition card for if / elif / while / for / match / case nodes: the expression,
// the values on each evaluation, the path taken each time, grouped and filterable.
// Loops: each evaluation is either an iteration ("repete") or the exit ("saída");
// the loop variable is captured right after the header runs ("after" snapshot).
import { useMemo, useState } from 'react'
import { BRANCH_FALSE, BRANCH_TRUE, branchCounts, branchName, fmtUs, passesFor, summarize, type Pass } from '../insight'
import type { FlowNode, FnFlow, Frame } from '../types'
import { JsonView } from './JsonView'

function tone(branch: string | null): 'yes' | 'no' | 'other' {
  if (!branch) return 'other'
  if (BRANCH_TRUE.has(branch)) return 'yes'
  if (BRANCH_FALSE.has(branch)) return 'no'
  return 'other'
}

function glyph(n: FlowNode, branch: string | null): string {
  const t = tone(branch)
  if (n.kind === 'loop') return t === 'yes' ? '↻' : t === 'no' ? '■' : '·'
  return t === 'yes' ? '✓' : t === 'no' ? '✗' : '→'
}

export function ConditionCard({ node, flow, frame, code }: { node: FlowNode; flow: FnFlow; frame: Frame; code: string }) {
  const isLoop = node.kind === 'loop'
  const passes = useMemo(() => passesFor(frame, flow, node.id), [frame, flow, node.id])
  const counts = useMemo(() => branchCounts(passes), [passes])
  // values that explain each evaluation: operands before an if; the loop variable after a loop header
  const valsOf = (p: Pass) => (isLoop ? p.after ?? p.before : p.before)
  const isExit = (p: Pass) => isLoop && tone(p.branch) === 'no'
  const iterNo = useMemo(() => {
    const m = new Map<number, number>()
    let k = 0
    for (const p of passes) if (!isExit(p)) m.set(p.index, ++k)
    return m
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [passes])
  const iterations = iterNo.size
  const [filter, setFilter] = useState<string | null>(null)
  const [cur, setCur] = useState<number>(() => {
    const lastIter = [...passes].reverse().find((p) => !isExit(p))
    return (lastIter ?? passes[passes.length - 1])?.index ?? 0
  })
  const [asTable, setAsTable] = useState(false)
  const shown = filter ? passes.filter((p) => p.branch === filter) : passes
  const evaluated = passes.filter((p) => !isExit(p))
  const withValues = evaluated.filter((p) => Object.keys(valsOf(p) ?? {}).length).length
  const p: Pass | undefined = passes[cur] ?? passes[passes.length - 1]
  const operands = useMemo(() => {
    const names = new Set<string>()
    for (const x of passes) Object.keys((isLoop ? x.after ?? x.before : x.before) ?? {}).forEach((k) => names.add(k))
    return [...names].slice(0, 8)
  }, [passes, isLoop])

  const title = (x: Pass) =>
    isLoop ? (isExit(x) ? 'saída do laço' : `iteração ${iterNo.get(x.index)} de ${iterations}`) : `avaliação ${x.index + 1} de ${passes.length}`

  if (!passes.length) return <div className="muted pad">{isLoop ? 'Este laço não foi executado' : 'Esta condição não foi avaliada'} nesta execução.</div>
  return (
    <div className="cond">
      <pre className="code cond-expr">{code || node.label}</pre>

      <div className="cond-sum">
        {isLoop
          ? `${iterations} ${iterations === 1 ? 'iteração' : 'iterações'}${counts.some(([b]) => tone(b) === 'no') ? ' e depois saiu do laço' : ''}`
          : `avaliada ${passes.length} ${passes.length === 1 ? 'vez' : 'vezes'}`}
      </div>

      <div className="cond-groups">
        <button className={filter === null ? 'on' : ''} onClick={() => setFilter(null)}>
          todas · {passes.length}
        </button>
        {counts.map(([b, c]) => (
          <button key={b} className={`b-${tone(b)} ${filter === b ? 'on' : ''}`} onClick={() => setFilter(filter === b ? null : b)}>
            {branchName(b)}: {c}
          </button>
        ))}
        <span className="grow" />
        <button className={asTable ? 'on' : ''} onClick={() => setAsTable(!asTable)} title="ver todas em tabela">
          tabela
        </button>
      </div>

      {!asTable && (
        <>
          <div className="strip" role="list">
            {shown.slice(0, 200).map((x) => (
              <button
                key={x.pos}
                role="listitem"
                className={`pass b-${tone(x.branch)} ${x.index === p?.index ? 'cur' : ''} ${valsOf(x) || isExit(x) ? '' : 'novals'}`}
                title={`${title(x)} · +${fmtUs(x.t)} · ${branchName(x.branch)}${valsOf(x) || isExit(x) ? '' : ' · valores não capturados'}`}
                onClick={() => setCur(x.index)}
              >
                {glyph(node, x.branch)}
              </button>
            ))}
            {shown.length > 200 && <span className="muted">+{shown.length - 200}</span>}
          </div>
          {p && (
            <div className="cond-pass">
              <div className="visit-h">
                <span>{title(p)}</span>
                <span className="t">+{fmtUs(p.t)}</span>
                {p.branch && <span className={`br br-${p.branch}`}>→ {branchName(p.branch)}</span>}
              </div>
              {isExit(p) ? (
                <div className="muted">não havia mais itens: o código seguiu depois do laço</div>
              ) : Object.keys(valsOf(p) ?? {}).length ? (
                <div className="operands">
                  {Object.entries(valsOf(p)!).map(([k, v]) => (
                    <div key={k} className="op">
                      <span className="op-k">{k}</span>
                      <span className="op-eq">=</span>
                      <span className="op-v">
                        {Array.isArray(v) || (typeof v === 'object' && v !== null) ? <JsonView value={v} /> : summarize(v, 80)}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="muted">valores não capturados aqui (o Glowtrace guarda os valores das primeiras vezes de cada nó)</div>
              )}
              {!isLoop && p.after && Object.keys(p.after).length > 0 && (
                <div className="kv">
                  <span className="kvh">definiu</span>
                  <JsonView value={p.after} />
                </div>
              )}
            </div>
          )}
        </>
      )}

      {asTable && (
        <div className="dv-table">
          <table>
            <thead>
              <tr>
                <th>{isLoop ? 'iteração' : '#'}</th>
                <th>t</th>
                <th>caminho</th>
                {operands.map((o) => (
                  <th key={o}>{o}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.slice(0, 300).map((x) => {
                const v = isExit(x) ? undefined : valsOf(x)
                return (
                  <tr key={x.pos} className={x.index === p?.index ? 'cur' : ''} onClick={() => setCur(x.index)}>
                    <td className="idx">{isLoop ? (isExit(x) ? 'saída' : iterNo.get(x.index)) : x.index + 1}</td>
                    <td className="idx">+{fmtUs(x.t)}</td>
                    <td className={`b-${tone(x.branch)}`}>
                      {glyph(node, x.branch)} {branchName(x.branch)}
                    </td>
                    {operands.map((o) => (
                      <td key={o} className={v && o in v ? '' : 'f-absent'}>
                        {v && o in v ? summarize(v[o], 30) : '—'}
                      </td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {withValues < evaluated.length && (
        <div className="honest">
          valores capturados em {withValues} de {evaluated.length} {isLoop ? 'iterações' : 'avaliações'} · o caminho de todas foi registrado
        </div>
      )}
    </div>
  )
}
