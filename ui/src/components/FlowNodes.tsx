import { Handle, Position, type NodeProps } from '@xyflow/react'
import { createContext, memo, useContext } from 'react'
import type { FlowNodeData, GroupData } from '../scene'
import { PIPE } from '../scene'

export interface Actions {
  toggle: (instKey: string, nodeId: number, targets: string[], open: boolean) => void
  setRun: (instKey: string, run: number) => void
  openFn: (fn: string) => void
}
export const ActionsCtx = createContext<Actions>({ toggle: () => {}, setRun: () => {}, openFn: () => {} })

export const KIND: Record<string, { chip: string; cat: string }> = {
  trigger: { chip: 'REQUEST', cat: 'trigger' },
  middleware: { chip: 'MIDDLEWARE', cat: 'call' },
  mwlib: { chip: 'LIB', cat: 'muted' },
  dependency: { chip: 'DEPENDS', cat: 'call' },
  handler: { chip: 'ENDPOINT', cat: 'call' },
  response: { chip: 'RESPONSE', cat: 'ret' },
  start: { chip: 'INÍCIO', cat: 'trigger' },
  end: { chip: 'FIM', cat: 'muted' },
  step: { chip: 'CÓDIGO', cat: 'step' },
  call: { chip: 'CHAMADA', cat: 'call' },
  if: { chip: 'IF', cat: 'ctrl' },
  loop: { chip: 'LOOP', cat: 'ctrl' },
  match: { chip: 'MATCH', cat: 'ctrl' },
  case: { chip: 'CASE', cat: 'ctrl' },
  try: { chip: 'TRY', cat: 'err' },
  except: { chip: 'EXCEPT', cat: 'err' },
  finally: { chip: 'FINALLY', cat: 'err' },
  with: { chip: 'WITH', cat: 'step' },
  return: { chip: 'RETURN', cat: 'ret' },
  raise: { chip: 'RAISE', cat: 'err' },
  break: { chip: 'BREAK', cat: 'ctrl' },
  continue: { chip: 'CONTINUE', cat: 'ctrl' },
}

function short(fn: string) {
  return fn.split('::').pop() ?? fn
}

export const FlowNodeView = memo(function FlowNodeView({ data, selected }: NodeProps) {
  const d = data as FlowNodeData
  const actions = useContext(ActionsCtx)
  const meta = KIND[d.node.kind] ?? { chip: d.node.kind.toUpperCase(), cat: 'step' }
  const open = d.targets.length > 0 && d.targets.every((t) => d.openTargets.includes(t))
  const ext = d.libs.length > 0 && meta.cat !== 'ctrl'
  return (
    <div
      className={`fnode cat-${ext && d.node.kind === 'call' ? 'io' : meta.cat} st-${d.state} ${selected ? 'sel' : ''} k-${d.node.kind}`}
      title={d.node.label}
    >
      <Handle type="target" position={Position.Top} id="t" className="h" />
      <Handle type="target" position={Position.Left} id="l" className="h" />
      <div className="fn-chip">{meta.chip}</div>
      <div className="fn-label">{d.node.label}</div>
      <div className="fn-badges">
        {d.libs.slice(0, 2).map((l) => (
          <span key={l} className="lib">
            {l}
          </span>
        ))}
        {d.raised && <span className="raised" title="exceção levantada aqui">!</span>}
        {d.count > 1 && <span className="count">×{d.count}</span>}
      </div>
      {d.targets.length > 0 && (
        <button
          className={`exp ${open ? 'open' : ''}`}
          title={open ? 'recolher' : 'expandir: ' + d.targets.map(short).join(', ')}
          onClick={(e) => {
            e.stopPropagation()
            actions.toggle(d.instKey, d.node.id, d.targets, !open)
          }}
        >
          {open ? '−' : '+'}
        </button>
      )}
      <Handle type="source" position={Position.Bottom} id="b" className="h" />
      <Handle type="source" position={Position.Right} id="r" className="h" />
    </div>
  )
})

export const FnGroupView = memo(function FnGroupView({ data }: NodeProps) {
  const { inst, flow } = data as GroupData
  const actions = useContext(ActionsCtx)
  const isPipe = flow.id === PIPE
  const fr = inst.frame
  const dur = fr && fr.end_us != null ? (fr.end_us - fr.start_us) / 1000 : null
  return (
    <div className={`fgroup ${isPipe ? 'pipe' : ''} ${fr?.exception ? 'gerr' : ''} ${inst.frame || isPipe ? '' : 'gstatic'}`}>
      <div className="ghead">
        <div className="gtitle">
          {isPipe ? (
            <span className="gname">Pipeline da requisição</span>
          ) : (
            <span className="gname" onDoubleClick={() => actions.openFn(flow.id)} title="duplo clique: abrir sozinho">
              {flow.is_async && <span className="async">async</span>}
              {flow.qualname}
            </span>
          )}
          {!isPipe && (
            <span className="gfile">
              {flow.file}:{flow.line}
            </span>
          )}
        </div>
        <div className="gmeta">
          {inst.ov?.stale && <span className="warn" title="o código mudou desde esta execução">código mudou</span>}
          {fr?.exception && <span className="errb">{fr.exception.type}</span>}
          {dur != null && <span className="dur">{dur < 1 ? dur.toFixed(2) : dur.toFixed(1)} ms</span>}
          {inst.frames.length > 1 && (
            <span className="runs" onClick={(e) => e.stopPropagation()}>
              <button disabled={inst.run <= 0} onClick={() => actions.setRun(inst.key, inst.run - 1)}>
                ‹
              </button>
              {inst.run + 1}/{inst.frames.length}
              <button disabled={inst.run >= inst.frames.length - 1} onClick={() => actions.setRun(inst.key, inst.run + 1)}>
                ›
              </button>
            </span>
          )}
        </div>
      </div>
    </div>
  )
})

export const nodeTypes = { flowNode: FlowNodeView, fnGroup: FnGroupView }
