// Data panel used everywhere a value is shown: Schema (flat paths + types),
// Tabela (records / key-value) and JSON (tree). Search, copy path/value,
// null / empty / truncated / masked highlighting, guard for very large values.
import { Fragment, useMemo, useRef, useState } from 'react'
import { MASK_RE, jsonInText, summarize, typeName } from '../insight'
import type { CaptureLimits } from '../types'
import { JsonView } from './JsonView'

type View = 'schema' | 'table' | 'json'
const VIEWS: [View, string][] = [
  ['schema', 'Schema'],
  ['table', 'Tabela'],
  ['json', 'JSON'],
]
const TRUNC_RE = /…\(\+\d+/
const BIG = 1_000_000
const MAX_ROWS = 1500

function loadView(role: string): View | null {
  try {
    const v = localStorage.getItem('gt.view.' + role)
    return v === 'schema' || v === 'table' || v === 'json' ? v : null
  } catch {
    return null
  }
}
function saveView(role: string, v: View) {
  try {
    localStorage.setItem('gt.view.' + role, v)
  } catch {
    /* storage unavailable: the choice just isn't remembered */
  }
}

// "/" focuses the search of the data panel the pointer was last over.
let lastSearch: HTMLInputElement | null = null
if (typeof document !== 'undefined') {
  document.addEventListener('keydown', (e) => {
    if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return
    const a = document.activeElement as HTMLElement | null
    if (a && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA' || a.tagName === 'SELECT' || a.isContentEditable)) return
    if (lastSearch && lastSearch.isConnected) {
      e.preventDefault()
      lastSearch.focus()
    }
  })
}

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

type Flag = 'null' | 'empty' | 'trunc' | 'mask' | 'opaque'

// capture limits of the running backend (meta.capture), shown in the "cut here" hints
let LIMITS: CaptureLimits | null = null
export function setCaptureLimits(l: CaptureLimits | null | undefined) {
  LIMITS = l ?? null
}

/** "<LinkedHashMap>", "<ciclo No>", "<LazyCollection>"...: a value Glowtrace chose not to open. */
export function opaqueTip(v: unknown): string {
  if (typeof v === 'string' && v.startsWith('<ciclo '))
    return 'Este objeto aponta de volta para um objeto que já aparece acima (ciclo): o Glowtrace para aqui para não repetir.'
  return `O Glowtrace não abriu este valor. Causas possíveis: o limite de ${LIMITS?.max_depth ?? 8} níveis de profundidade (aumente com GLOWTRACE_MAX_DEPTH), ou um objeto de framework, proxy ou coleção ainda não carregada do banco, que nunca são lidos para não causar efeitos colaterais.`
}

function truncTip(v: unknown, key: string): string {
  const items = LIMITS?.max_items ?? 25
  if (key === '…') return `Cortado em ${items} campos/itens (aumente com GLOWTRACE_MAX_ITEMS).`
  if (v === '…') return `Limite de ${LIMITS?.max_values ?? 400} valores por captura atingido (aumente com GLOWTRACE_MAX_VALUES).`
  if (typeof v === 'string' && /^…\(\+\d+\)$/.test(v)) return `Lista cortada em ${items} itens (aumente com GLOWTRACE_MAX_ITEMS).`
  return `Texto cortado em ${LIMITS?.max_str ?? 400} caracteres (aumente com GLOWTRACE_MAX_STR).`
}

function flagsOf(v: unknown, key: string): Flag[] {
  const f: Flag[] = []
  if (v === null || v === undefined) f.push('null')
  else if (v === '' || (Array.isArray(v) && v.length === 0) || (isObj(v) && Object.keys(v).filter((k) => k !== '__type__').length === 0)) f.push('empty')
  if (key === '…' || v === '…' || (typeof v === 'string' && TRUNC_RE.test(v))) f.push('trunc')
  if (typeof v === 'string' && MASK_RE.test(v)) f.push('mask')
  else if (typeof v === 'string' && /^<[^<>]+>$/.test(v)) f.push('opaque')
  return f
}

const IDENT = /^[A-Za-z_$][\w$]*$/
function join(path: string, key: string, arr: boolean): string {
  if (arr) return `${path}[${key}]`
  if (IDENT.test(key)) return path ? `${path}.${key}` : key
  return `${path}[${JSON.stringify(key)}]`
}

interface Row {
  path: string
  key: string
  depth: number
  value: unknown
  leaf: boolean
  type: string
  flags: Flag[]
}

function flatten(v: unknown, root: string): { rows: Row[]; more: number } {
  const rows: Row[] = []
  let more = 0
  const walk = (val: unknown, path: string, key: string, depth: number) => {
    if (rows.length >= MAX_ROWS) {
      more++
      return
    }
    const complex = Array.isArray(val) || isObj(val)
    rows.push({ path, key, depth, value: val, leaf: !complex, type: typeName(val), flags: flagsOf(val, key) })
    if (!complex) return
    const arr = Array.isArray(val)
    const entries: [string, unknown][] = arr ? (val as unknown[]).map((x, i) => [String(i), x]) : Object.entries(val as object)
    for (const [k, x] of entries) if (k !== '__type__') walk(x, join(path, k, arr), k, depth + 1)
  }
  walk(v, root, root || '(valor)', 0)
  return { rows, more }
}

function leafText(v: unknown): string {
  if (typeof v === 'string') return v
  return JSON.stringify(v) ?? String(v)
}

async function copy(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

function download(value: unknown, name: string) {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function fmtBytes(n: number): string {
  return n > 1_000_000 ? `${(n / 1_000_000).toFixed(1)} MB` : `${Math.round(n / 1000)} KB`
}

export function DataView({
  value,
  role,
  root = '',
  empty = '—',
}: {
  value: unknown
  /** remembers the chosen view per role (args, return, body, headers...) */
  role: string
  /** path prefix used by "copiar caminho" (body, args, retorno...) */
  root?: string
  empty?: string
}) {
  const [view, setView] = useState<View>(() => loadView(role) ?? (role === 'headers' ? 'table' : 'schema'))
  const [q, setQ] = useState('')
  const [force, setForce] = useState(false)
  const [copied, setCopied] = useState<string | null>(null)
  const search = useRef<HTMLInputElement>(null)
  const size = useMemo(() => {
    try {
      return (JSON.stringify(value) ?? '').length
    } catch {
      return 0
    }
  }, [value])

  if (value === undefined) return <div className="j-empty">{empty}</div>
  const complex = Array.isArray(value) || isObj(value)
  if (!complex) {
    return (
      <div className="dv dv-scalar">
        <JsonView value={value} />
      </div>
    )
  }
  if ((Array.isArray(value) && value.length === 0) || (isObj(value) && Object.keys(value).length === 0)) {
    return <div className="j-empty">{empty !== '—' ? empty : Array.isArray(value) ? '[]' : '{}'}</div>
  }
  if (size > BIG && !force) {
    return (
      <div className="dv-big">
        Valor grande ({fmtBytes(size)}). Mostrar pode deixar a página lenta.
        <div className="dv-big-actions">
          <button onClick={() => setForce(true)}>mostrar mesmo assim</button>
          <button onClick={() => download(value, `${root || role}.json`)}>baixar .json</button>
        </div>
      </div>
    )
  }

  const pick = (v: View) => {
    setView(v)
    saveView(role, v)
  }
  const flash = (what: string) => {
    setCopied(what)
    setTimeout(() => setCopied((c) => (c === what ? null : c)), 1200)
  }

  return (
    <div
      className="dv"
      onMouseEnter={() => {
        lastSearch = search.current
      }}
    >
      <div className="dv-bar">
        <div className="seg">
          {VIEWS.map(([v, l]) => (
            <button key={v} className={view === v ? 'on' : ''} onClick={() => pick(v)}>
              {l}
            </button>
          ))}
        </div>
        <input
          ref={search}
          className="dv-q"
          placeholder="buscar  /"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              setQ('')
              ;(e.target as HTMLInputElement).blur()
            }
          }}
        />
        {copied && <span className="dv-copied">copiado: {copied}</span>}
      </div>
      {view === 'schema' && <SchemaView value={value} root={root} q={q} onCopy={flash} />}
      {view === 'table' && <TableView value={value} q={q} />}
      {view === 'json' && (q ? <RawJson value={value} q={q} /> : <JsonView value={value} />)}
    </div>
  )
}

function SchemaView({ value, root, q, onCopy }: { value: unknown; root: string; q: string; onCopy: (w: string) => void }) {
  const [openJson, setOpenJson] = useState<Set<string>>(new Set())
  const { rows, more } = useMemo(() => flatten(value, root), [value, root])
  const needle = q.trim().toLowerCase()
  const shown = needle
    ? rows.filter((r) => r.depth > 0 && (r.path.toLowerCase().includes(needle) || (r.leaf && leafText(r.value).toLowerCase().includes(needle))))
    : rows.filter((r) => r.depth > 0)
  if (!shown.length) return <div className="j-empty">{needle ? 'nada encontrado' : 'vazio'}</div>
  return (
    <div className="dv-schema">
      {shown.slice(0, 600).map((r) => (
        <Fragment key={r.path}>
        <div
          className={`sr ${r.flags.map((f) => 'f-' + f).join(' ')}`}
          style={{ paddingLeft: needle ? 6 : 6 + (r.depth - 1) * 14 }}
        >
          <span className="sr-k" title={r.path}>
            {needle ? r.path || r.key : r.key}
          </span>
          <span className="sr-t">{r.leaf && jsonInText(r.value) ? 'texto JSON' : r.type}</span>
          <span className="sr-v">{r.leaf ? summarize(r.value, 60) : ''}</span>
          {r.leaf && jsonInText(r.value) && (
            <button
              className="sr-jt"
              title="este texto contém JSON: ver como árvore"
              onClick={() =>
                setOpenJson((prev) => {
                  const n = new Set(prev)
                  if (n.has(r.path)) n.delete(r.path)
                  else n.add(r.path)
                  return n
                })
              }
            >
              {openJson.has(r.path) ? 'JSON ▾' : 'JSON ▸'}
            </button>
          )}
          {r.flags.includes('null') && <span className="sr-f">nulo</span>}
          {r.flags.includes('empty') && <span className="sr-f">vazio</span>}
          {r.flags.includes('trunc') && (
            <span className="sr-f tip" title={truncTip(r.value, r.key)}>
              cortado
            </span>
          )}
          {r.flags.includes('mask') && <span className="sr-f">redigido</span>}
          {r.flags.includes('opaque') && (
            <span className="sr-f" title={opaqueTip(r.value)}>
              não aberto
            </span>
          )}
          <span className="sr-a">
            <button
              title={`copiar caminho: ${r.path}`}
              aria-label="copiar caminho"
              onClick={async () => {
                if (await copy(r.path)) onCopy(r.path)
              }}
            >
              ⌁
            </button>
            <button
              title="copiar valor"
              aria-label="copiar valor"
              onClick={async () => {
                if (await copy(r.leaf ? leafText(r.value) : JSON.stringify(r.value, null, 2))) onCopy('valor')
              }}
            >
              ⧉
            </button>
          </span>
        </div>
        {openJson.has(r.path) && (
          <div className="sr-json" style={{ paddingLeft: needle ? 20 : 20 + (r.depth - 1) * 14 }}>
            <JsonView value={jsonInText(r.value)} />
          </div>
        )}
        </Fragment>
      ))}
      {(shown.length > 600 || more > 0) && <div className="muted dv-more">… mais itens não exibidos (use a busca ou baixe o JSON)</div>}
    </div>
  )
}

function TableView({ value, q }: { value: unknown; q: string }) {
  const needle = q.trim().toLowerCase()
  const hit = (cells: unknown[]) => !needle || cells.some((c) => leafText(c).toLowerCase().includes(needle))
  const cell = (v: unknown) => {
    const f = flagsOf(v, '')
    return (
      <td className={f.map((x) => 'f-' + x).join(' ')} title={f.includes('opaque') ? opaqueTip(v) : f.includes('trunc') ? truncTip(v, '') : undefined}>
        {Array.isArray(v) || isObj(v) ? summarize(v, 40) : leafText(v ?? null)}
      </td>
    )
  }
  // list of records → one row per item, union of keys as columns
  if (Array.isArray(value) && value.length && value.every((x) => isObj(x))) {
    const cols: string[] = []
    for (const it of value as Record<string, unknown>[]) for (const k of Object.keys(it)) if (k !== '__type__' && !cols.includes(k) && cols.length < 30) cols.push(k)
    const rows = (value as Record<string, unknown>[]).map((it, i) => ({ i, it })).filter(({ it }) => hit(cols.map((c) => it[c])))
    return (
      <div className="dv-table">
        <table>
          <thead>
            <tr>
              <th>#</th>
              {cols.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 300).map(({ i, it }) => (
              <tr key={i}>
                <td className="idx">{i}</td>
                {cols.map((c) => (
                  <Fragment key={c}>{c in it ? cell(it[c]) : <td className="f-absent">—</td>}</Fragment>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length > 300 && <div className="muted dv-more">… +{rows.length - 300} linhas</div>}
      </div>
    )
  }
  const entries: [string, unknown][] = Array.isArray(value)
    ? value.map((x, i) => [String(i), x])
    : Object.entries(value as object).filter(([k]) => k !== '__type__')
  const rows = entries.filter(([k, v]) => hit([k, v]))
  return (
    <div className="dv-table">
      <table>
        <tbody>
          {rows.slice(0, 400).map(([k, v]) => (
            <tr key={k}>
              <th className="kcol">{k}</th>
              {cell(v)}
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length && <div className="j-empty">{needle ? 'nada encontrado' : 'vazio'}</div>}
    </div>
  )
}

function RawJson({ value, q }: { value: unknown; q: string }) {
  const needle = q.toLowerCase()
  const lines = useMemo(() => (JSON.stringify(value, null, 2) ?? '').split('\n'), [value])
  return (
    <pre className="dv-raw">
      {lines.slice(0, 4000).map((l, i) => (
        <div key={i} className={l.toLowerCase().includes(needle) ? 'hit' : 'miss'}>
          {l}
        </div>
      ))}
    </pre>
  )
}
