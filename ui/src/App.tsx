import { Background, Controls, MiniMap, ReactFlow, ReactFlowProvider, useReactFlow } from '@xyflow/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import { setCaptureLimits } from './components/DataView'
import { severity } from './insight'
import { computeOverlay } from './overlay'
import { ActionsCtx, nodeTypes, type Actions } from './components/FlowNodes'
import { Inspector, type Selection } from './components/Inspector'
import { MapView } from './components/MapView'
import { ExecList, MethodChip, RoutesList, StatusChip, ago } from './components/Sidebar'
import { PIPE, buildInstances, pipelineFlow, place, toElements } from './scene'
import type { ExecSummary, Execution, FnFlow, MapData, Meta, MiddlewareInfo, RouteInfo } from './types'

type View = { kind: 'route'; route: string } | { kind: 'fn'; fn: string } | { kind: 'map' } | { kind: 'home' }

function readHash(): View {
  const h = decodeURIComponent(window.location.hash.slice(1).split('&exec=')[0])
  if (h.startsWith('route=')) return { kind: 'route', route: h.slice(6) }
  if (h.startsWith('fn=')) return { kind: 'fn', fn: h.slice(3) }
  if (h === 'map') return { kind: 'map' }
  return { kind: 'home' }
}

/** Navigation is pushed to the browser history (Back works); internal syncs replace. */
function writeHash(v: View, exec?: string | null, mode: 'push' | 'replace' = 'push') {
  let h = ''
  if (v.kind === 'route') h = 'route=' + v.route
  else if (v.kind === 'fn') h = 'fn=' + v.fn
  else if (v.kind === 'map') h = 'map'
  if (exec) h += '&exec=' + exec
  const next = '#' + encodeURIComponent(h).replace(/%3D/g, '=').replace(/%26/g, '&')
  if (window.location.hash === next) return
  if (mode === 'push') history.pushState(null, '', next)
  else history.replaceState(null, '', next)
}

const READABLE_ZOOM = 0.6

function isFailure(e: ExecSummary): boolean {
  return !!e.error || (e.status ?? 0) >= 400
}

export default function App() {
  return (
    <ReactFlowProvider>
      <Shell />
    </ReactFlowProvider>
  )
}

function Shell() {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [routes, setRoutes] = useState<RouteInfo[]>([])
  const [mws, setMws] = useState<MiddlewareInfo[]>([])
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<View>(() => {
    const raw = window.location.hash.split('&exec=')[0]
    return raw ? readHash() : { kind: 'home' }
  })
  const [flows, setFlows] = useState<Map<string, FnFlow>>(new Map())
  const pending = useRef(new Set<string>())
  const [toggled, setToggled] = useState<Map<string, boolean>>(new Map())
  const [runSel, setRunSel] = useState<Map<string, number>>(new Map())
  const [tab, setTab] = useState<'routes' | 'execs'>('routes')
  const [execs, setExecs] = useState<ExecSummary[]>([])
  const [onlyRoute, setOnlyRoute] = useState(true)
  const [onlyErr, setOnlyErr] = useState(false)
  const [live, setLive] = useState(false)
  const [exec, setExec] = useState<Execution | null>(null)
  const [sel, setSel] = useState<Selection | null>(null)
  const [mapData, setMapData] = useState<MapData | null>(null)
  // node to bring into view once it is placed (navigation from panels, "ir ao erro")
  const [focus, setFocus] = useState<{ instKey: string; nodeId: number } | null>(null)
  const lastFocusAt = useRef(0)
  const flowsRef = useRef(flows)
  flowsRef.current = flows
  const execRef = useRef(exec)
  execRef.current = exec
  const rf = useReactFlow()

  // boot
  useEffect(() => {
    Promise.all([api.meta(), api.routes()])
      .then(([m, r]) => {
        setMeta(m)
        setCaptureLimits(m.capture)
        setRoutes(r.routes)
        setMws(r.middlewares)
        document.title = `Glowtrace · ${m.title}`
        const ex = new URLSearchParams(window.location.hash.slice(1).replace(/^[^&]*&?/, '')).get('exec')
        if (ex) selectExec(ex, { keepView: readHash().kind === 'fn', history: 'replace' })
      })
      .catch((e) => setError(String(e.message || e)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // shared links pasted into an already-open tab only change the hash
  useEffect(() => {
    // also fires on browser Back/Forward between our own history entries
    const onHash = () => {
      setView(readHash())
      setSel(null)
      setToggled(new Map())
      setRunSel(new Map())
      const ex = new URLSearchParams(window.location.hash.slice(1).replace(/^[^&]*&?/, '')).get('exec')
      if (ex) {
        if (ex !== execRef.current?.id) selectExec(ex, { keepView: true })
      } else setExec(null)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const route = view.kind === 'route' ? routes.find((r) => r.id === view.route) ?? null : null

  // executions polling
  const refreshExecs = useCallback(() => {
    const rid = onlyRoute && view.kind === 'route' ? view.route : null
    api
      .executions(rid, onlyErr ? 'fail' : null)
      // backends that don't know "fail" return everything: filter here too
      .then((r) => setExecs(onlyErr ? r.executions.filter(isFailure) : r.executions))
      .catch(() => {})
  }, [onlyRoute, onlyErr, view])
  useEffect(() => {
    refreshExecs()
    const t = setInterval(refreshExecs, live ? 1500 : 5000)
    return () => clearInterval(t)
  }, [refreshExecs, live])

  // live mode: follow newest execution of the current route
  const lastLive = useRef<string | null>(null)
  useEffect(() => {
    if (!live || !execs.length) return
    const newest = execs[0]
    if (newest.id !== lastLive.current) {
      lastLive.current = newest.id
      selectExec(newest.id, { history: 'replace' })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [execs, live])

  const counts = useMemo(() => {
    const m = new Map<string, { n: number; err: number; rej: number }>()
    for (const e of execs) {
      if (!e.route_id) continue
      const c = m.get(e.route_id) ?? { n: 0, err: 0, rej: 0 }
      c.n++
      const sv = severity(e)
      if (sv === 'err') c.err++
      else if (sv === 'rej') c.rej++
      m.set(e.route_id, c)
    }
    return m
  }, [execs])

  // scene
  const rootFn = view.kind === 'route' ? PIPE : view.kind === 'fn' ? view.fn : null
  const allFlows = useMemo(() => {
    const m = new Map(flows)
    if (route) m.set(PIPE, pipelineFlow(route, mws))
    return m
  }, [flows, route, mws])

  const defaultOpen = useMemo(() => {
    const s = new Set<string>()
    if (route && route.handler) {
      const pf = allFlows.get(PIPE)
      const h = pf?.nodes.find((n) => n.kind === 'handler')
      if (h) s.add(`r/${h.id}:${route.handler}`)
    }
    return s
  }, [route, allFlows])

  const activeExec = exec && ((view.kind === 'route' && exec.route_id === view.route) || view.kind === 'fn') ? exec : null

  const insts = useMemo(
    () => (rootFn ? buildInstances({ rootFn, flows: allFlows, toggled, exec: activeExec, runSel, defaultOpen }) : []),
    [rootFn, allFlows, toggled, activeExec, runSel, defaultOpen],
  )

  // lazy-load missing flows
  useEffect(() => {
    const need = insts.map((i) => i.fn).filter((f) => f !== PIPE && !flows.has(f) && !pending.current.has(f))
    if (!need.length) return
    need.forEach((f) => pending.current.add(f))
    Promise.all(need.map((f) => api.fn(f).then((x) => [f, x] as const).catch(() => null))).then((res) => {
      setFlows((prev) => {
        const m = new Map(prev)
        res.forEach((r) => r && m.set(r[0], r[1]))
        return m
      })
      need.forEach((f) => pending.current.delete(f))
    })
  }, [insts, flows])

  const placed = useMemo(() => place(insts, allFlows), [insts, allFlows])
  const selectedId = sel && 'instKey' in sel ? `${sel.instKey}#${sel.nodeId}` : null
  const { nodes, edges } = useMemo(() => toElements(placed, activeExec, selectedId), [placed, activeExec, selectedId])

  // first view of a route/execution: the whole graph only if it stays readable; otherwise
  // start reading at a legible zoom - at the error, or where the request enters (top-left)
  const fitKey = `${rootFn}|${activeExec?.id ?? ''}|${placed.length}`
  useEffect(() => {
    if (!placed.length) return
    if (Date.now() - lastFocusAt.current < 2000) return // navigating to a node: keep it centered
    const t = setTimeout(() => {
      const el = document.querySelector('.flowwrap') as HTMLElement | null
      const W = el?.clientWidth || 900
      const H = el?.clientHeight || 600
      let x0 = Infinity
      let y0 = Infinity
      let x1 = -Infinity
      let y1 = -Infinity
      for (const p of placed) {
        x0 = Math.min(x0, p.x)
        y0 = Math.min(y0, p.y)
        x1 = Math.max(x1, p.x + p.layout.w)
        y1 = Math.max(y1, p.y + p.layout.h)
      }
      const fit = Math.min(W / ((x1 - x0) * 1.1), H / ((y1 - y0) * 1.1))
      if (fit >= READABLE_ZOOM) {
        rf.fitView({ padding: 0.06, duration: 250, maxZoom: 1 })
        return
      }
      const err = activeExec?.error ? errorTarget() : null
      if (err) {
        const box = err.p.layout.pos.get(err.node)!
        rf.setCenter(err.p.x + box.x + box.w / 2, err.p.y + box.y + box.h / 2, { zoom: 0.9, duration: 250 })
      } else rf.setViewport({ x: -x0 * 0.85 + 28, y: -y0 * 0.85 + 20, zoom: 0.85 }, { duration: 250 })
    }, 180)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey])

  function errorTarget(): { p: (typeof placed)[number]; node: number } | null {
    const origin = activeExec?.error?.frame
    const p = placed.find((x) => x.inst.frame && x.inst.frame.id === origin) ?? placed.find((x) => x.inst.frame?.exception)
    const node = p?.inst.ov?.error_node
    return p && node !== undefined && p.layout.pos.has(node) ? { p, node } : null
  }

  // Esc closes the open panel (the replay dialog handles its own Esc)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || document.querySelector('.modal-back')) return
      const a = document.activeElement as HTMLElement | null
      if (a && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA')) return
      setSel(null)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (!focus) return
    const p = placed.find((x) => x.inst.key === focus.instKey)
    const box = p?.layout.pos.get(focus.nodeId)
    if (!p || !box) return
    lastFocusAt.current = Date.now()
    rf.setCenter(p.x + box.x + box.w / 2, p.y + box.y + box.h / 2, { zoom: Math.max(rf.getZoom(), 0.85), duration: 400 })
    setFocus(null)
  }, [focus, placed, rf])

  // actions
  const actions: Actions = useMemo(
    () => ({
      toggle: (instKey, nodeId, targets, open) => {
        setToggled((prev) => {
          const m = new Map(prev)
          targets.forEach((t) => m.set(`${instKey}/${nodeId}:${t}`, open))
          return m
        })
        lastFocusAt.current = Date.now() // keep the zoom; show the opened function instead of refitting
        if (open && targets.length) {
          const fn = targets[0]
          const start = flowsRef.current.get(fn)?.nodes.find((n) => n.kind === 'start')?.id ?? 0
          setFocus({ instKey: `${instKey}/${nodeId}:${fn}`, nodeId: start })
        }
      },
      setRun: (instKey, run) =>
        setRunSel((prev) => {
          const m = new Map(prev)
          m.set(instKey, run)
          return m
        }),
      // keep the execution when it ran this function, so its values stay visible
      openFn: (fn) => go({ kind: 'fn', fn }, !!execRef.current?.frames.some((f) => f.fn === fn)),
      select: (instKey, nodeId) => {
        lastFocusAt.current = Date.now()
        setSel({ instKey, nodeId })
        setFocus({ instKey, nodeId })
      },
      openCall: (instKey, nodeId, fn, run) => {
        const key = `${instKey}/${nodeId}:${fn}`
        const start = flowsRef.current.get(fn)?.nodes.find((n) => n.kind === 'start')?.id ?? 0
        lastFocusAt.current = Date.now()
        setToggled((prev) => new Map(prev).set(key, true))
        setRunSel((prev) => new Map(prev).set(key, run))
        setSel({ instKey: key, nodeId: start })
        setFocus({ instKey: key, nodeId: start })
      },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  function go(v: View, keepExec = false) {
    setView(v)
    setToggled(new Map())
    setRunSel(new Map())
    setSel(null)
    if (!keepExec) setExec(null)
    writeHash(v, keepExec ? execRef.current?.id : null)
  }

  const mapLoading = useRef(false)
  const needMap = useCallback(() => {
    if (mapLoading.current) return
    mapLoading.current = true
    api
      .map()
      .then(setMapData)
      .catch((e) => setError(String(e.message || e)))
      .finally(() => {
        mapLoading.current = false
      })
  }, [])
  useEffect(() => {
    if (view.kind === 'map' && !mapData) needMap()
  }, [view.kind, mapData, needMap])

  async function withOverlay(ex: Execution): Promise<Execution> {
    if (ex.overlay) return ex
    // backend did not compute it (e.g. Java agent): fetch every frame's flow and compute here
    const need = [...new Set(ex.frames.map((f) => f.fn))].filter((f) => !flows.has(f))
    const got = await Promise.all(need.map((f) => api.fn(f).then((x) => [f, x] as const).catch(() => null)))
    const all = new Map(flows)
    got.forEach((r) => r && all.set(r[0], r[1]))
    setFlows(all)
    return { ...ex, overlay: computeOverlay(ex, all) }
  }

  function selectExec(id: string, opts: { keepView?: boolean; history?: 'push' | 'replace' } = {}) {
    api
      .execution(id)
      .then(withOverlay)
      .then((ex) => {
        setExec(ex)
        setRunSel(new Map())
        setToggled(new Map())
        setSel(null)
        if (!opts.keepView && ex.route_id) {
          const v: View = { kind: 'route', route: ex.route_id }
          setView(v)
          writeHash(v, ex.id, opts.history ?? 'push')
        }
      })
      .catch((e) => setError(String(e.message || e)))
  }

  const wide = useMemo(() => {
    if (!sel || !('instKey' in sel)) return false
    const p = placed.find((x) => x.inst.key === sel.instKey)
    return !!p && p.flow.id !== PIPE && p.flow.nodes[sel.nodeId]?.kind === 'start'
  }, [sel, placed])
  const inspector = sel && view.kind !== 'map' && (
    <Inspector sel={sel} placed={placed} exec={activeExec} meta={meta} flows={allFlows} onClose={() => setSel(null)} onOpenExec={(id) => selectExec(id)} />
  )

  if (error && !meta) {
    return (
      <div className="fatal">
        <h1>Glowtrace</h1>
        <p>{error}</p>
      </div>
    )
  }

  return (
    <ActionsCtx.Provider value={actions}>
      <div className="app">
        <header className="top">
          <div className="brand" onClick={() => go({ kind: 'home' })}>
            <span className="logo">⧉</span> Glowtrace <span className="app-title">{meta?.title}</span>
          </div>
          <nav className="views">
            <button className={view.kind !== 'map' ? 'on' : ''} onClick={() => (view.kind === 'map' ? go(route ? view : { kind: 'home' }) : null)}>
              Fluxos
            </button>
            <button className={view.kind === 'map' ? 'on' : ''} onClick={() => go({ kind: 'map' })}>
              Mapa da API
            </button>
          </nav>
          <div className="topmeta">
            {meta && (
              <>
                <span className="pill">{meta.route_count} rotas</span>
                <span className={`pill mode-${meta.mode}`}>{meta.mode === 'trace' ? 'gravando execuções' : meta.mode}</span>
                <span className="pill dim" title={meta.backend ? `mecanismo de gravação: ${meta.backend}` : undefined}>
                  {meta.runtime ?? `python ${meta.python}`}
                </span>
              </>
            )}
            <label className={`live ${live ? 'on' : ''}`} title="acompanhar a execução mais recente automaticamente">
              <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
              <span className="dot" /> ao vivo
            </label>
          </div>
        </header>

        <div className="body">
          <aside className="side">
            <div className="tabs">
              <button className={tab === 'routes' ? 'on' : ''} onClick={() => setTab('routes')}>
                Rotas <span className="muted">{routes.length}</span>
              </button>
              <button className={tab === 'execs' ? 'on' : ''} onClick={() => setTab('execs')}>
                Execuções <span className="muted">{execs.length}</span>
              </button>
            </div>
            {tab === 'routes' ? (
              <RoutesList
                routes={routes}
                selected={view.kind === 'route' ? view.route : null}
                onSelect={(id) => go({ kind: 'route', route: id })}
                counts={counts}
                map={mapData}
                onNeedMap={needMap}
                onOpenFn={(fn) => actions.openFn(fn)}
              />
            ) : (
              <>
                <div className="filters">
                  <label>
                    <input type="checkbox" checked={onlyRoute} onChange={(e) => setOnlyRoute(e.target.checked)} /> só a rota aberta
                  </label>
                  <label>
                    <input type="checkbox" checked={onlyErr} onChange={(e) => setOnlyErr(e.target.checked)} /> só falhas (4xx/5xx)
                  </label>
                  <button
                    className="link"
                    onClick={() => {
                      if (confirm('Apagar todas as execuções gravadas?')) api.clear().then(refreshExecs)
                    }}
                  >
                    limpar
                  </button>
                </div>
                <ExecList items={execs} selected={exec?.id ?? null} onSelect={(id) => selectExec(id)} />
              </>
            )}
          </aside>

          <main className="canvas">
            {view.kind === 'map' ? (
              mapData ? (
                <MapView data={mapData} onOpenRoute={(id) => go({ kind: 'route', route: id })} onOpenFn={(fn) => go({ kind: 'fn', fn })} />
              ) : (
                <div className="empty">Analisando a API…</div>
              )
            ) : view.kind === 'home' ? (
              <Home meta={meta} routes={routes} execs={execs} onRoute={(id) => go({ kind: 'route', route: id })} onExec={(id) => selectExec(id)} />
            ) : (
              <>
                {activeExec && (
                  <div className="execbar">
                    <StatusChip s={activeExec.status} err={!!activeExec.error} />
                    <MethodChip m={activeExec.method} />
                    <span className="ep">{activeExec.path}</span>
                    {activeExec.mode === 'replay' && (
                      <span
                        className="replay-chip"
                        title={activeExec.replay_edits?.length ? 'editado: ' + activeExec.replay_edits.join(', ') : 'reenvio sem alterações'}
                        onClick={() => activeExec.replay_of && activeExec.replay_of !== 'manual' && selectExec(activeExec.replay_of)}
                      >
                        ↻ replay de #{(activeExec.replay_of ?? 'manual').slice(0, 8)}
                      </span>
                    )}
                    {activeExec.mode === 'replay' && activeExec.replay_of && activeExec.replay_of !== 'manual' && (
                      <button className="cmp" onClick={() => setSel({ special: 'compare' })} title="o que mudou entre o original e este reenvio">
                        comparar com original
                      </button>
                    )}
                    <span className="muted">{activeExec.duration_ms.toFixed(1)} ms · {ago(activeExec.started_at)} · {activeExec.frame_count} funções</span>
                    {activeExec.error && (
                      <span className="eb">
                        {activeExec.error.type}: {activeExec.error.message}
                      </span>
                    )}
                    <span className="grow" />
                    {activeExec.error && (
                      <button
                        className="danger"
                        onClick={() => {
                          const t = errorTarget()
                          if (t) actions.select(t.p.inst.key, t.node)
                        }}
                      >
                        ir ao erro
                      </button>
                    )}
                    <button onClick={() => setSel({ special: 'request' })}>Requisição</button>
                    <button onClick={() => setSel({ special: 'response' })}>Resposta</button>
                    <button className="x" title="sair da execução (visão estática)" onClick={() => { setExec(null); setSel(null); writeHash(view) }}>
                      ×
                    </button>
                  </div>
                )}
                {!activeExec && route && (
                  <div className="execbar static">
                    {route.methods.map((m) => (
                      <MethodChip key={m} m={m} />
                    ))}
                    <span className="ep">{route.path}</span>
                    <span className="muted">visão estática · todos os caminhos possíveis · <b>+</b> entra numa função · clique no título de uma função para ver entrada, código e saída</span>
                  </div>
                )}
                {view.kind === 'fn' && !activeExec && (
                  <div className="execbar static">
                    <span className="ep">{view.fn.split('::').pop()}</span>
                    <span className="muted">{view.fn.split('::')[0]}</span>
                  </div>
                )}
                <div className="flowwrap">
                <ReactFlow
                  nodes={nodes}
                  edges={edges}
                  nodeTypes={nodeTypes}
                  minZoom={0.05}
                  maxZoom={2}
                  nodesDraggable={false}
                  nodesConnectable={false}
                  elementsSelectable
                  onNodeClick={(_, n) => {
                    if (n.type !== 'flowNode') return
                    const [k, idx] = [n.id.slice(0, n.id.lastIndexOf('#')), Number(n.id.slice(n.id.lastIndexOf('#') + 1))]
                    setSel({ instKey: k, nodeId: idx })
                  }}
                  onPaneClick={() => setSel(null)}
                  proOptions={{ hideAttribution: true }}
                >
                  <Background gap={22} size={1} />
                  <Controls showInteractive={false} />
                  <MiniMap pannable zoomable nodeStrokeWidth={3} />
                </ReactFlow>
                {/* the function panel covers the canvas only, the execution bar stays visible */}
                {wide && inspector}
                </div>
              </>
            )}
          </main>

          {!wide && inspector}
        </div>
      </div>
    </ActionsCtx.Provider>
  )
}

function Home({
  meta,
  routes,
  execs,
  onRoute,
  onExec,
}: {
  meta: Meta | null
  routes: RouteInfo[]
  execs: ExecSummary[]
  onRoute: (id: string) => void
  onExec: (id: string) => void
}) {
  const errs = execs.filter((e) => severity(e) === 'err')
  const slow = execs.filter((e) => e.route_id).sort((a, b) => b.duration_ms - a.duration_ms).slice(0, 5)
  return (
    <div className="home">
      <h1>{meta?.title ?? 'API'}</h1>
      <p className="muted">
        {routes.length} {routes.length === 1 ? 'rota mapeada' : 'rotas mapeadas'} · {execs.length} {execs.length === 1 ? 'execução recente' : 'execuções recentes'} · {errs.length} com erro
      </p>
      <div className="cards">
        <div className="card">
          <h3>Comece por aqui</h3>
          <p>Escolha uma rota à esquerda para ver o fluxo completo: middlewares, dependências, endpoint e cada função chamada, com seus if/else, loops e try/except.</p>
          <p>Faça requisições à API e abra a aba <b>Execuções</b> para ver o caminho real que cada uma percorreu — com os valores que passaram por cada nó.</p>
        </div>
        <div className="card">
          <h3>Erros recentes</h3>
          {errs.slice(0, 6).map((e) => (
            <div key={e.id} className="row exec" onClick={() => onExec(e.id)}>
              <StatusChip s={e.status} err />
              <MethodChip m={e.method} />
              <span className="rpath">{e.path}</span>
              <span className="eago">{ago(e.started_at)}</span>
              {e.error && <div className="eerr">{e.error.type}: {e.error.message}</div>}
            </div>
          ))}
          {!errs.length && <p className="muted">Nenhum erro gravado.</p>}
        </div>
        <div className="card">
          <h3>Mais lentas</h3>
          {slow.map((e) => (
            <div key={e.id} className="row exec" onClick={() => onExec(e.id)}>
              <StatusChip s={e.status} />
              <MethodChip m={e.method} />
              <span className="rpath">{e.path}</span>
              <span className="edur">{Math.round(e.duration_ms)}ms</span>
            </div>
          ))}
          {!slow.length && <p className="muted">Sem execuções ainda.</p>}
        </div>
        <div className="card">
          <h3>Rotas</h3>
          {routes.slice(0, 8).map((r) => (
            <div key={r.id} className="row" onClick={() => onRoute(r.id)}>
              {r.methods.map((m) => (
                <MethodChip key={m} m={m} />
              ))}
              <span className="rpath">{r.path}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
