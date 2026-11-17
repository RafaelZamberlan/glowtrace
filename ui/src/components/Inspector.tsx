import type { Execution, FlowNode, FnFlow, Frame } from '../types'
import type { Placed } from '../scene'
import { PIPE } from '../scene'
import { JsonView } from './JsonView'
import { KIND } from './FlowNodes'

export type Selection = { instKey: string; nodeId: number } | { special: 'request' | 'response' }

function fmtMs(us: number | null | undefined) {
  if (us == null) return '—'
  const ms = us / 1000
  return ms < 1 ? ms.toFixed(2) + ' ms' : ms.toFixed(1) + ' ms'
}

function snippet(flow: FnFlow, n: FlowNode): string {
  if (!flow.source || !n.line) return ''
  const lines = flow.source.split('\n')
  const a = Math.max(0, n.line - flow.source_start)
  const b = Math.min(lines.length, n.end_line - flow.source_start + 1)
  const slice = lines.slice(a, Math.max(a + 1, b))
  const indent = Math.min(...slice.filter((l) => l.trim()).map((l) => l.length - l.trimStart().length))
  return slice.map((l) => l.slice(Number.isFinite(indent) ? indent : 0)).join('\n')
}

function branchOf(flow: FnFlow, node: number, next: number | undefined): string | null {
  if (next === undefined) return null
  const e = flow.edges.find((x) => x.source === node && x.target === next)
  if (e) return e.label || e.kind
  return null
}

/** "sem corpo" only when the request/response really had none; otherwise say the backend did not capture it. */
function emptyBody(headers: Record<string, string> | undefined): string {
  const len = Number(headers?.['content-length'] ?? 0)
  const chunked = (headers?.['transfer-encoding'] ?? '').includes('chunked')
  return len > 0 || chunked ? 'corpo não capturado por este backend (veja os argumentos/retorno do endpoint)' : 'sem corpo'
}

function bodyTitle(base: string, source?: string): string {
  return source ? `${base} · via ${source}` : base
}

function FrameIO({ frame, title }: { frame: Frame; title?: string }) {
  return (
    <div className="io">
      {title && <div className="io-title">{title}</div>}
      <div className="io-grid">
        <div>
          <div className="io-h">Entrada</div>
          <JsonView value={frame.args} />
        </div>
        <div>
          <div className="io-h">{frame.exception ? 'Exceção' : 'Saída'}</div>
          {frame.exception ? (
            <div className="exc">
              <b>{frame.exception.type}</b>
              {frame.exception.status_code ? ` (${frame.exception.status_code})` : ''}: {frame.exception.message}
              {frame.exception.detail !== undefined && <JsonView value={frame.exception.detail} />}
            </div>
          ) : (
            <JsonView value={frame.return} />
          )}
        </div>
      </div>
      <div className="io-foot">duração: {fmtMs(frame.end_us != null ? frame.end_us - frame.start_us : null)}</div>
    </div>
  )
}

export function Inspector({
  sel,
  placed,
  exec,
  onClose,
}: {
  sel: Selection
  placed: Placed[]
  exec: Execution | null
  onClose: () => void
}) {
  if ('special' in sel) {
    if (!exec) return null
    const isReq = sel.special === 'request'
    return (
      <aside className="inspector">
        <div className="ins-head">
          <div>
            <div className={`fn-chip cat-${isReq ? 'trigger' : 'ret'}`}>{isReq ? 'REQUEST' : 'RESPONSE'}</div>
            <div className="ins-title">
              {exec.method} {exec.path}
            </div>
          </div>
          <button className="x" onClick={onClose}>
            ×
          </button>
        </div>
        {isReq ? (
          <>
            <Section title={bodyTitle('Body', exec.request.body_source)}>
              <JsonView value={exec.request.body ?? undefined} empty={emptyBody(exec.request.headers)} />
            </Section>
            <Section title="Query / path">
              <JsonView value={{ query: exec.request.query, path: exec.request.path_params }} />
            </Section>
            <Section title="Headers">
              <JsonView value={exec.request.headers} />
            </Section>
          </>
        ) : (
          <>
            <Section title={bodyTitle(`Status ${exec.status ?? '—'} · ${exec.duration_ms.toFixed(1)} ms`, exec.response.body_source)}>
              <JsonView value={exec.response.body ?? undefined} empty={emptyBody(exec.response.headers)} />
            </Section>
            <Section title="Headers">
              <JsonView value={exec.response.headers} />
            </Section>
          </>
        )}
      </aside>
    )
  }

  const p = placed.find((x) => x.inst.key === sel.instKey)
  if (!p) return null
  const { inst, flow } = p
  const node = flow.nodes[sel.nodeId]
  if (!node) return null
  const meta = KIND[node.kind] ?? { chip: node.kind, cat: 'step' }
  const frame = inst.frame
  const isPipe = flow.id === PIPE
  const code = isPipe ? '' : snippet(flow, node)
  const visits = frame ? frame.path.map((pp, i) => ({ pos: i, t: pp[1], node: pp[0] })).filter((v) => v.node === node.id) : []
  const childFrames =
    exec && frame
      ? exec.frames.filter((f) => f.parent === frame.id && exec.overlay?.frames.find((o) => o.id === f.id)?.call_node === node.id)
      : []
  const pipeFrames =
    exec && isPipe && node.calls?.[0]?.target ? exec.frames.filter((f) => f.parent === null && f.fn === node.calls![0].target) : []

  return (
    <aside className="inspector">
      <div className="ins-head">
        <div>
          <div className={`fn-chip cat-${meta.cat}`}>{meta.chip}</div>
          <div className="ins-title">{node.label}</div>
          {!isPipe && (
            <div className="ins-sub">
              {flow.qualname} · {flow.file}:{node.line || flow.line}
            </div>
          )}
        </div>
        <button className="x" onClick={onClose}>
          ×
        </button>
      </div>

      {code && (
        <Section title="Código">
          <pre className="code">{code}</pre>
        </Section>
      )}
      {node.kind === 'start' && flow.doc && (
        <Section title="Docstring">
          <pre className="code doc">{flow.doc}</pre>
        </Section>
      )}

      {/* execution data */}
      {isPipe && exec && node.kind === 'trigger' && (
        <Section title="Requisição recebida">
          <JsonView value={{ body: exec.request.body, query: exec.request.query, path: exec.request.path_params }} />
        </Section>
      )}
      {isPipe && exec && node.kind === 'response' && (
        <Section title={bodyTitle(`Resposta · status ${exec.status ?? '—'}`, exec.response.body_source)}>
          <JsonView value={exec.response.body ?? undefined} empty={emptyBody(exec.response.headers)} />
        </Section>
      )}
      {pipeFrames.map((f, i) => (
        <Section key={f.id} title={pipeFrames.length > 1 ? `Execução ${i + 1}` : 'Execução'}>
          <FrameIO frame={f} />
        </Section>
      ))}

      {frame && node.kind === 'start' && (
        <Section title="Entrada da função">
          <JsonView value={frame.args} />
        </Section>
      )}
      {frame && (node.kind === 'end' || node.kind === 'return') && visits.length + (node.kind === 'end' ? 1 : 0) > 0 && (
        <Section title={frame.exception ? 'Exceção' : 'Saída da função'}>
          {frame.exception ? (
            <div className="exc">
              <b>{frame.exception.type}</b>: {frame.exception.message}
            </div>
          ) : (
            <JsonView value={frame.return} />
          )}
        </Section>
      )}
      {frame && inst.ov?.error_node === node.id && frame.exception && (
        <Section title="Parou aqui">
          <div className="exc big">
            <b>{frame.exception.type}</b>
            {frame.exception.status_code ? ` (HTTP ${frame.exception.status_code})` : ''}
            <div>{frame.exception.message}</div>
            {frame.exception.detail !== undefined && <JsonView value={frame.exception.detail} />}
          </div>
        </Section>
      )}

      {childFrames.length > 0 && (
        <Section title={childFrames.length > 1 ? `Chamadas (${childFrames.length})` : 'Chamada'}>
          {childFrames.slice(0, 30).map((f, i) => (
            <FrameIO key={f.id} frame={f} title={`${f.fn.split('::').pop()}${childFrames.length > 1 ? ` #${i + 1}` : ''}`} />
          ))}
        </Section>
      )}

      {frame && visits.length > 0 && node.kind !== 'start' && (
        <Section title={visits.length > 1 ? `Passagens (${visits.length})` : 'Passagem'}>
          {visits.slice(0, 60).map((v, i) => {
            const before = frame.values.find((x) => x[0] === v.pos && x[2] === 'before')?.[1]
            const after = frame.values.find((x) => x[0] === v.pos && x[2] === 'after')?.[1]
            const next = frame.path[v.pos + 1]?.[0]
            const br = ['if', 'loop', 'match', 'case'].includes(node.kind) ? branchOf(flow, node.id, next) : null
            return (
              <div key={v.pos} className="visit">
                <div className="visit-h">
                  <span>#{i + 1}</span>
                  <span className="t">+{fmtMs(v.t)}</span>
                  {br && <span className={`br br-${br}`}>→ {br}</span>}
                </div>
                {before && (
                  <div className="kv">
                    <span className="kvh">valores</span>
                    <JsonView value={before} />
                  </div>
                )}
                {after && (
                  <div className="kv">
                    <span className="kvh">resultado</span>
                    <JsonView value={after} />
                  </div>
                )}
              </div>
            )
          })}
          {visits.length > 60 && <div className="muted">… +{visits.length - 60} passagens</div>}
        </Section>
      )}
      {frame && visits.length === 0 && !['start', 'end'].includes(node.kind) && !isPipe && (
        <div className="muted pad">Este nó não foi executado nesta requisição.</div>
      )}
      {frame?.raised?.filter((r) => r.line >= node.line && r.line <= node.end_line).map((r, i) => (
        <Section key={i} title="Exceção levantada aqui">
          <div className="exc">
            <b>{r.type}</b>: {r.message}
          </div>
        </Section>
      ))}

      {(node.calls?.length ?? 0) > 0 && (
        <Section title="Chamadas no código">
          <ul className="calls">
            {node.calls!.map((c, i) => (
              <li key={i}>
                <code>{c.expr}</code>
                <span className={`ck ck-${c.kind}`}>{c.kind === 'external' ? c.lib : c.kind}</span>
                {c.awaited && <span className="ck">await</span>}
              </li>
            ))}
          </ul>
        </Section>
      )}
      {!frame && !isPipe && exec && <div className="muted pad">Função não executada nesta requisição (visão estática).</div>}
    </aside>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="sec">
      <div className="sec-t">{title}</div>
      {children}
    </section>
  )
}
