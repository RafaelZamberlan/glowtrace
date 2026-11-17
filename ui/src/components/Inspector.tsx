import { useContext } from 'react'
import { childFramesOf, fmtUs, frameDurUs, isBranchNode, passesFor } from '../insight'
import type { Placed } from '../scene'
import { PIPE } from '../scene'
import type { Execution, FlowNode, FnFlow, Frame, Meta } from '../types'
import { ComparePanel } from './ComparePanel'
import { ConditionCard } from './ConditionCard'
import { DataView } from './DataView'
import { ActionsCtx, KIND } from './FlowNodes'
import { FunctionPanel } from './FunctionPanel'
import { JsonView } from './JsonView'
import { RequestPanel, ResponsePanel, bodyTitle, emptyBody } from './RequestPanel'

export type Selection = { instKey: string; nodeId: number } | { special: 'request' | 'response' | 'compare' }

function snippet(flow: FnFlow, n: FlowNode): string {
  if (!flow.source || !n.line) return ''
  const lines = flow.source.split('\n')
  const a = Math.max(0, n.line - flow.source_start)
  const b = Math.min(lines.length, n.end_line - flow.source_start + 1)
  // compound statements (if/for/try...) show only their header line(s)
  const own = n.own ? Math.min(b, n.own[1] - flow.source_start + 1) : b
  const slice = lines.slice(a, Math.max(a + 1, isBranchNode(n) || ['try', 'with', 'except'].includes(n.kind) ? own : b))
  const indent = Math.min(...slice.filter((l) => l.trim()).map((l) => l.length - l.trimStart().length))
  return slice.map((l) => l.slice(Number.isFinite(indent) ? indent : 0)).join('\n')
}

/** External libraries called on visited nodes of the execution (shown before a replay). */
export function observedLibs(placed: Placed[]): string[] {
  const libs = new Set<string>()
  for (const p of placed) {
    if (!p.inst.frame || !p.inst.ov) continue
    for (const n of p.flow.nodes) {
      if (!(p.inst.ov.visits?.[String(n.id)] ?? 0)) continue
      n.calls?.forEach((c) => c.kind === 'external' && c.lib && libs.add(c.lib))
    }
  }
  return [...libs].sort()
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
          <div className="io-h">{frame.exception ? 'Exceção ✗' : 'Saída ✓'}</div>
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
      <div className="io-foot">duração: {fmtUs(frameDurUs(frame))}</div>
    </div>
  )
}

export function Inspector({
  sel,
  placed,
  exec,
  meta,
  flows,
  onClose,
  onOpenExec,
}: {
  sel: Selection
  placed: Placed[]
  exec: Execution | null
  meta: Meta | null
  flows: Map<string, FnFlow>
  onClose: () => void
  onOpenExec: (id: string) => void
}) {
  const actions = useContext(ActionsCtx)
  if ('special' in sel) {
    if (!exec) return null
    if (sel.special === 'compare') return <ComparePanel key={exec.id} exec={exec} flows={flows} onOpenExec={onOpenExec} onClose={onClose} />
    return sel.special === 'request' ? (
      <RequestPanel exec={exec} meta={meta} libs={observedLibs(placed)} onOpenExec={onOpenExec} onClose={onClose} />
    ) : (
      <ResponsePanel exec={exec} onClose={onClose} />
    )
  }

  const p = placed.find((x) => x.inst.key === sel.instKey)
  if (!p) return null
  const { inst, flow } = p
  const node = flow.nodes[sel.nodeId]
  if (!node) return null
  const isPipe = flow.id === PIPE

  // the start node is the function itself: wide Entrada | Código | Saída panel
  if (!isPipe && node.kind === 'start') return <FunctionPanel key={inst.key} p={p} exec={exec} onClose={onClose} />
  // the request trigger is the request panel (re-send, copy as...)
  if (isPipe && node.kind === 'trigger' && exec)
    return <RequestPanel exec={exec} meta={meta} libs={observedLibs(placed)} onOpenExec={onOpenExec} onClose={onClose} />

  const meta_ = KIND[node.kind] ?? { chip: node.kind, cat: 'step' }
  const frame = inst.frame
  const code = isPipe ? '' : snippet(flow, node)
  const passes = frame ? passesFor(frame, flow, node.id) : []
  const childFrames = exec && frame ? childFramesOf(exec, frame, node.id) : []
  const pipeFrames =
    exec && isPipe && node.calls?.[0]?.target ? exec.frames.filter((f) => f.parent === null && f.fn === node.calls![0].target) : []
  const branch = isBranchNode(node) && !isPipe
  const start = flow.nodes.find((n) => n.kind === 'start')?.id

  return (
    <aside className="inspector">
      <div className="ins-head">
        <div>
          <div className={`fn-chip cat-${meta_.cat}`}>{meta_.chip}</div>
          <div className="ins-title">{node.label}</div>
          {!isPipe && (
            <div className="ins-sub">
              <span className="linkish" onClick={() => start !== undefined && actions.select(inst.key, start)} title="abrir o painel da função">
                {flow.qualname}
              </span>{' '}
              · {flow.file}:{node.line || flow.line}
            </div>
          )}
        </div>
        <button className="x" onClick={onClose} title="fechar (Esc)">
          ×
        </button>
      </div>

      {branch && frame ? (
        <Section title={node.kind === 'loop' ? 'Laço' : 'Condição'}>
          <ConditionCard key={`${inst.key}#${node.id}#${frame.id}`} node={node} flow={flow} frame={frame} code={code} />
        </Section>
      ) : (
        code && (
          <Section title="Código">
            <pre className="code">{code}</pre>
          </Section>
        )
      )}

      {/* request pipeline */}
      {isPipe && exec && node.kind === 'response' && (
        <Section title={bodyTitle(`Resposta · status ${exec.status ?? '—'}`, exec.response.body_source)}>
          <DataView value={exec.response.body ?? undefined} role="body" root="body" empty={emptyBody(exec.response.headers)} />
        </Section>
      )}
      {pipeFrames.map((f, i) => (
        <Section key={f.id} title={pipeFrames.length > 1 ? `Execução ${i + 1}` : 'Execução'}>
          <FrameIO frame={f} />
        </Section>
      ))}

      {frame && (node.kind === 'end' || node.kind === 'return') && (passes.length > 0 || node.kind === 'end') && inst.ov?.error_node !== node.id && (
        <Section title={frame.exception ? 'Exceção da função ✗' : 'Saída da função ✓'}>
          {frame.exception ? (
            <div className="exc">
              <b>{frame.exception.type}</b>: {frame.exception.message}
            </div>
          ) : (
            <DataView value={frame.return} role="return" root="" empty="null" />
          )}
        </Section>
      )}
      {frame && inst.ov?.error_node === node.id && frame.exception && (
        <Section title="Parou aqui">
          <div className="exc big">
            <b>{frame.exception.type}</b>
            {frame.exception.status_code ? ` (HTTP ${frame.exception.status_code})` : ''}
            <div>{frame.exception.message}</div>
            {frame.exception.detail !== undefined && <DataView value={frame.exception.detail} role="detail" root="detail" />}
          </div>
        </Section>
      )}

      {childFrames.length > 0 && (
        <Section title={childFrames.length > 1 ? `Chamadas (${childFrames.length})` : 'Chamada'}>
          {childFrames.slice(0, 30).map((f, i) => (
            <div key={f.id} className="io-wrap">
              <FrameIO frame={f} title={`${f.fn.split('::').pop()}${childFrames.length > 1 ? ` #${i + 1}` : ''}`} />
              <button className="link" onClick={() => actions.openCall(inst.key, node.id, f.fn, childFrames.filter((x) => x.fn === f.fn).indexOf(f))}>
                abrir {f.fn.split('::').pop()} →
              </button>
            </div>
          ))}
        </Section>
      )}

      {frame && passes.length > 0 && !branch && node.kind !== 'end' && (
        <Section title={passes.length > 1 ? `Executou ${passes.length} vezes` : 'Executou 1 vez'}>
          {passes.length === 1 && passes[0].after && !passes[0].before ? (
            <DataView value={passes[0].after} role="vars" root="" />
          ) : (
            passes.slice(0, 60).map((v) => (
              <div key={v.pos} className="visit">
                <div className="visit-h">
                  <span>#{v.index + 1}</span>
                  <span className="t">+{fmtUs(v.t)}</span>
                </div>
                {v.before && (
                  <div className="kv">
                    <span className="kvh">valores</span>
                    <JsonView value={v.before} />
                  </div>
                )}
                {v.after && (
                  <div className="kv">
                    <span className="kvh">resultado</span>
                    <JsonView value={v.after} />
                  </div>
                )}
              </div>
            ))
          )}
          {passes.length > 60 && <div className="muted">… +{passes.length - 60} vezes</div>}
          {passes.length > 0 && !passes.some((x) => x.before || x.after) && <div className="muted">sem valores capturados neste nó</div>}
        </Section>
      )}
      {frame && passes.length === 0 && !['start', 'end'].includes(node.kind) && !isPipe && (
        <div className="muted pad">Este nó não foi executado nesta requisição.</div>
      )}
      {frame?.raised
        ?.filter((r) => r.line >= node.line && r.line <= node.end_line)
        .map((r, i) => (
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
