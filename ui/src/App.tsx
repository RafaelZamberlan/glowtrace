import { Background, Controls, MiniMap, ReactFlow, ReactFlowProvider, useReactFlow } from '@xyflow/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
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

function writeHash(v: View, exec?: string | null) {
  let h = ''
  if (v.kind === 'route') h = 'route=' + v.route
  else if (v.kind === 'fn') h = 'fn=' + v.fn
  else if (v.kind === 'map') h = 'map'
  if (exec) h += '&exec=' + exec
  const next = '#' + encodeURIComponent(h).replace(/%3D/g, '=').replace(/%26/g, '&')
  if (window.location.hash !== next) history.replaceState(null, '', next)
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
  const rf = useReactFlow()

  // boot
  useEffect(() => {
    Promise.all([api.meta(), api.routes()])
      .then(([m, r]) => {
        setMeta(m)
        setRoutes(r.routes)
        setMws(r.middlewares)
        document.title = `Glowtrace · ${m.title}`
        const ex = new URLSearchParams(window.location.hash.slice(1).replace(/^[^&]*&?/, '')).get('exec')
        if (ex) selectExec(ex)
      })
      .catch((e) => setError(String(e.message || e)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // shared links pasted into an already-open tab only change the hash
  useEffect(() => {
    const onHash = () => {
      setView(readHash())
      const ex = new URLSearchParams(window.location.hash.slice(1).replace(/^[^&]*&?/, '')).get('exec')
      if (ex) selectExec(ex)
      else setExec(null)
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
      .executions(rid, onlyErr ? 'error' : null)
      .then((r) => setExecs(r.executions))
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
      selectExec(newest.id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [execs, live])

  const counts = useMemo(() => {
    const m = new Map<string, { n: number; err: number }>()
    for (const e of execs) {
      if (!e.route_id) continue
      const c = m.get(e.route_id) ?? { n: 0, err: 0 }
      c.n++
      if (e.error || (e.status ?? 0) >= 500) c.err++
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

  // fit view when the root/execution changes
  const fitKey = `${rootFn}|${activeExec?.id ?? ''}|${placed.length}`
  useEffect(() => {
    if (!placed.length) return
    const t = setTimeout(() => rf.fitView({ padding: 0.08, duration: 300, maxZoom: 1 }), 180)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey])

  // actions
  const actions: Actions = useMemo(
    () => ({
      toggle: (instKey, nodeId, targets, open) =>
        setToggled((prev) => {
          const m = new Map(prev)
          targets.forEach((t) => m.set(`${instKey}/${nodeId}:${t}`, open))
          return m
        }),
      setRun: (instKey, run) =>
        setRunSel((prev) => {
          const m = new Map(prev)
          m.set(instKey, run)
          return m
        }),
      openFn: (fn) => go({ kind: 'fn', fn }),
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
    writeHash(v, keepExec ? exec?.id : null)
  }

  useEffect(() => {
    if (view.kind === 'map' && !mapData) api.map().then(setMapData).catch((e) => setError(String(e.message || e)))
  }, [view.kind, mapData])

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

  function selectExec(id: string) {
    api
      .execution(id)
      .then(withOverlay)
      .then((ex) => {
        setExec(ex)
        setRunSel(new Map())
        setToggled(new Map())
        setSel(null)
        if (ex.route_id) {
          const v: View = { kind: 'route', route: ex.route_id }
          setView(v)
          writeHash(v, ex.id)
        }
      })
      .catch((e) => setError(String(e.message || e)))
  }

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
                {meta.backend && <span className="pill dim">{meta.backend}</span>}
                <span className="pill dim">{meta.runtime ?? `python ${meta.python}`}</span>
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
              <RoutesList routes={routes} selected={view.kind === 'route' ? view.route : null} onSelect={(id) => go({ kind: 'route', route: id })} counts={counts} />
            ) : (
              <>
                <div className="filters">
                  <label>
                    <input type="checkbox" checked={onlyRoute} onChange={(e) => setOnlyRoute(e.target.checked)} /> só a rota aberta
                  </label>
                  <label>
                    <input type="checkbox" checked={onlyErr} onChange={(e) => setOnlyErr(e.target.checked)} /> só erros
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
                <ExecList items={execs} selected={exec?.id ?? null} onSelect={selectExec} />
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
              <Home meta={meta} routes={routes} execs={execs} onRoute={(id) => go({ kind: 'route', route: id })} onExec={selectExec} />
            ) : (
              <>
                {activeExec && (
                  <div className="execbar">
                    <StatusChip s={activeExec.status} err={!!activeExec.error} />
                    <MethodChip m={activeExec.method} />
                    <span className="ep">{activeExec.path}</span>
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
                          const origin = activeExec.error?.frame
                          const p = placed.find((x) => x.inst.frame && x.inst.frame.id === origin) ?? placed.find((x) => x.inst.frame?.exception)
                          const node = p?.inst.ov?.error_node
                          const box = node !== undefined ? p?.layout.pos.get(node) : undefined
                          if (p && node !== undefined && box) {
                            setSel({ instKey: p.inst.key, nodeId: node })
                            rf.setCenter(p.x + box.x + box.w / 2, p.y + box.y + box.h / 2, { zoom: 1, duration: 450 })
                          }
                        }}
                      >
                        ir ao erro
                      </button>
                    )}
                    <button onClick={() => setSel({ special: 'request' })}>Requisição</button>
                    <button onClick={() => setSel({ special: 'response' })}>Resposta</button>
                    <button className="x" title="sair da execução (visão estática)" onClick={() => { setExec(null); writeHash(view) }}>
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
                    <span className="muted">visão estática · todos os caminhos possíveis · clique em + para entrar nas funções</span>
                  </div>
                )}
                {view.kind === 'fn' && !activeExec && (
                  <div className="execbar static">
                    <span className="ep">{view.fn.split('::').pop()}</span>
                    <span className="muted">{view.fn.split('::')[0]}</span>
                  </div>
                )}
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
              </>
            )}
          </main>

          {sel && view.kind !== 'map' && <Inspector sel={sel} placed={placed} exec={activeExec} onClose={() => setSel(null)} />}
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
  const errs = execs.filter((e) => e.error || (e.status ?? 0) >= 500)
  const slow = [...execs].sort((a, b) => b.duration_ms - a.duration_ms).slice(0, 5)
  return (
    <div className="home">
      <h1>{meta?.title ?? 'API'}</h1>
      <p className="muted">
        {routes.length} rotas mapeadas · {execs.length} execuções recentes · {errs.length} com erro
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
