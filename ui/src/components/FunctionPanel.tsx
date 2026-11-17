// Wide function panel: Entrada | Código (executed lines, error line, inline values,
// ×N per line) | Saída, with navigation to the caller and to the calls it made.
import { useContext, useMemo } from 'react'
import { BRANCH_TRUE, executedLines, fmtUs, frameDurUs, isBranchNode, passesFor, summarize, typeName, branchCounts } from '../insight'
import type { Placed } from '../scene'
import { PIPE } from '../scene'
import type { Execution, Frame, FrameOverlay } from '../types'
import { DataView } from './DataView'
import { ActionsCtx } from './FlowNodes'

function short(fn: string) {
  return fn.split('::').pop() ?? fn
}

export function FunctionPanel({ p, exec, onClose }: { p: Placed; exec: Execution | null; onClose: () => void }) {
  const actions = useContext(ActionsCtx)
  const { inst, flow } = p
  const frame = inst.frame
  const ov = inst.ov
  const dur = frameDurUs(frame)
  const { lines, errorLine } = useMemo(() => executedLines(flow, frame, ov), [flow, frame, ov])

  // inline values: first line of each visited node -> "x = 3" / "→ sim"
  const inline = useMemo(() => {
    const m = new Map<number, string>()
    if (!frame || !ov) return m
    for (const n of flow.nodes) {
      if (!(ov.visits?.[String(n.id)] ?? 0) || !n.line) continue
      const ps = passesFor(frame, flow, n.id)
      if (n.kind === 'loop') {
        const it = ps.filter((x) => x.branch && BRANCH_TRUE.has(x.branch)).length
        m.set(n.line, `${it} ${it === 1 ? 'iteração' : 'iterações'}`)
        continue
      }
      if (isBranchNode(n)) {
        const c = branchCounts(ps)
        if (c.length) m.set(n.line, c.length === 1 && c[0][1] === 1 ? `→ ${c[0][0]}` : c.map(([b, k]) => `${b} ${k}`).join(' · '))
        continue
      }
      const last = [...ps].reverse().find((x) => x.after && Object.keys(x.after).length)
      if (last?.after) {
        const txt = Object.entries(last.after)
          .slice(0, 2)
          .map(([k, v]) => `${k} = ${summarize(v, 24)}`)
          .join(', ')
        m.set(n.line, txt)
      }
    }
    return m
  }, [flow, frame, ov])

  // which node owns a source line (smallest range wins) - clicking a line selects it
  const ownerOf = (ln: number): number | null => {
    let best: number | null = null
    let size = Infinity
    for (const n of flow.nodes) {
      const r = n.own ?? (n.line ? [n.line, n.line] : null)
      if (!r || ln < r[0] || ln > r[1]) continue
      if (r[1] - r[0] < size) {
        size = r[1] - r[0]
        best = n.id
      }
    }
    return best
  }

  const ovById = useMemo(() => new Map<number, FrameOverlay>((exec?.overlay?.frames ?? []).map((o) => [o.id, o])), [exec])
  const kids = useMemo(() => {
    if (!exec || !frame) return []
    const seen = new Map<string, number>()
    return exec.frames
      .filter((f) => f.parent === frame.id)
      .map((f) => {
        const node = ovById.get(f.id)?.call_node ?? 0
        const k = `${node}:${f.fn}`
        const run = seen.get(k) ?? 0
        seen.set(k, run + 1)
        return { f, node, run }
      })
  }, [exec, frame, ovById])
  const staticCalls = useMemo(() => {
    if (frame) return []
    const out: { node: number; fn: string }[] = []
    for (const n of flow.nodes) for (const c of n.calls ?? []) if (c.kind === 'user' && c.target && !out.some((o) => o.fn === c.target)) out.push({ node: n.id, fn: c.target })
    return out
  }, [flow, frame])

  const start = flow.nodes.find((n) => n.kind === 'start')?.id ?? 0
  const src = flow.source ? flow.source.split('\n') : []
  const parent = inst.parent

  return (
    <aside className="inspector wide">
      <div className="ins-head">
        <div className="fp-head">
          <div className="fn-chip cat-trigger">FUNÇÃO</div>
          <div className="ins-title">
            {flow.is_async && <span className="async">async</span>} {flow.qualname}({flow.params.join(', ')})
          </div>
          <div className="ins-sub">
            {flow.file}:{flow.line}
            {inst.ov?.stale && <span className="warn"> · código mudou desde esta execução</span>}
          </div>
          <div className="fp-nav">
            {parent && inst.parentNode !== null && (
              <button onClick={() => actions.select(parent.key, inst.parentNode!)} title="ir para a linha que chamou esta função">
                ← chamador: {parent.fn === PIPE ? 'pipeline da requisição' : short(parent.fn)}
              </button>
            )}
            {inst.frames.length > 1 && (
              <span className="runs">
                <button disabled={inst.run <= 0} onClick={() => actions.setRun(inst.key, inst.run - 1)}>
                  ‹
                </button>
                chamada {inst.run + 1}/{inst.frames.length}
                <button disabled={inst.run >= inst.frames.length - 1} onClick={() => actions.setRun(inst.key, inst.run + 1)}>
                  ›
                </button>
              </span>
            )}
            {inst.key !== 'r' && (
              <button onClick={() => actions.openFn(flow.id)} title="mostrar só esta função no canvas (mantém a execução)">
                ver só esta função
              </button>
            )}
          </div>
        </div>
        <button className="x" onClick={onClose} title="fechar (Esc)">
          ×
        </button>
      </div>

      {frame && (
        <div className={`fp-result ${frame.exception ? 'bad' : 'good'}`}>
          {frame.exception ? (
            <>
              <b>EXCEÇÃO ✗</b> {frame.exception.type}
              {frame.exception.status_code ? ` (HTTP ${frame.exception.status_code})` : ''} · {fmtUs(dur)}
            </>
          ) : frame.end_us == null ? (
            <>
              <b>EM ANDAMENTO</b> · a gravação terminou antes da função
            </>
          ) : (
            <>
              <b>RETORNO ✓</b> {fmtUs(dur)} · {typeName(frame.return)}
            </>
          )}
          {frame.truncated && <span className="warn"> · passagens cortadas pelo limite</span>}
        </div>
      )}
      {!frame && exec && <div className="fp-result idle">Não executada nesta requisição · visão estática</div>}

      <div className="fp-cols">
        <section className="fp-col">
          <div className="sec-t">Entrada</div>
          {frame ? (
            <DataView value={frame.args} role="args" root="" empty="sem argumentos" />
          ) : (
            <ul className="params">
              {flow.params.length ? flow.params.map((x) => <li key={x}>{x}</li>) : <li className="muted">sem parâmetros</li>}
            </ul>
          )}
          {flow.doc && (
            <>
              <div className="sec-t">Docstring</div>
              <pre className="code doc">{flow.doc}</pre>
            </>
          )}
        </section>

        <section className="fp-col code-col">
          <div className="sec-t">
            Código {frame && <span className="muted">· {lines.size} linhas executadas</span>}
          </div>
          <div className="src">
            {src.map((text, i) => {
              const ln = flow.source_start + i
              const c = lines.get(ln) ?? 0
              const cls = errorLine === ln ? 'err' : c ? 'ran' : frame ? 'skip' : ''
              return (
                <div
                  key={ln}
                  className={`sl ${cls}`}
                  onClick={() => {
                    const n = ownerOf(ln)
                    if (n !== null) actions.select(inst.key, n)
                  }}
                >
                  <span className="sl-n">{ln}</span>
                  <span className="sl-c">{c > 1 ? `×${c}` : ''}</span>
                  <span className="sl-t">{text || ' '}</span>
                  {inline.has(ln) && <span className="sl-v">{inline.get(ln)}</span>}
                  {errorLine === ln && frame?.exception && <span className="sl-v e">✗ {frame.exception.type}</span>}
                </div>
              )
            })}
            {!src.length && <div className="muted">código-fonte indisponível</div>}
          </div>
        </section>

        <section className="fp-col">
          <div className="sec-t">Saída</div>
          {!frame && <div className="j-empty">—</div>}
          {frame?.exception && (
            <div className="exc big">
              <b>{frame.exception.type}</b>
              {frame.exception.status_code ? ` (HTTP ${frame.exception.status_code})` : ''}
              <div>{frame.exception.message}</div>
              {frame.exception.detail !== undefined && <DataView value={frame.exception.detail} role="detail" root="detail" />}
              <div className="muted">linha {frame.exception.line}</div>
            </div>
          )}
          {frame && !frame.exception && frame.end_us != null && <DataView value={frame.return} role="return" root="" empty="null" />}
          {(frame?.raised?.length ?? 0) > 0 && (
            <>
              <div className="sec-t">Exceções levantadas</div>
              {frame!.raised!.map((r, i) => (
                <div key={i} className="exc">
                  linha {r.line} · <b>{r.type}</b>: {r.message}
                </div>
              ))}
            </>
          )}

          {(kids.length > 0 || staticCalls.length > 0) && <div className="sec-t">Chamadas →</div>}
          <div className="kids">
            {kids.slice(0, 80).map(({ f, node, run }) => (
              <KidRow key={f.id} f={f} onOpen={() => actions.openCall(inst.key, node, f.fn, run)} />
            ))}
            {kids.length > 80 && <div className="muted">… +{kids.length - 80}</div>}
            {staticCalls.map((c) => (
              <div key={c.fn} className="kid static" onClick={() => actions.openCall(inst.key, c.node, c.fn, 0)}>
                <span className="kid-n">{short(c.fn)}</span>
                <span className="muted">linha {flow.nodes[c.node]?.line}</span>
              </div>
            ))}
          </div>
          <button className="link" onClick={() => actions.select(inst.key, start)}>
            ver o nó de início no canvas
          </button>
        </section>
      </div>
    </aside>
  )
}

function KidRow({ f, onOpen }: { f: Frame; onOpen: () => void }) {
  const d = frameDurUs(f)
  return (
    <div className={`kid ${f.exception ? 'bad' : ''}`} onClick={onOpen} title={f.fn}>
      <span className={`glyph ${f.exception ? 't-err' : 't-ok'}`}>{f.exception ? '✗' : '✓'}</span>
      <span className="kid-n">{short(f.fn)}</span>
      <span className="muted">{f.exception ? f.exception.type : fmtUs(d)}</span>
      <span className="muted kid-l">linha {f.call_line ?? '—'}</span>
    </div>
  )
}
