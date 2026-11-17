// Request panel: what came in, "copy as" (cURL / HTTPie / requests / fetch) and
// re-send / edit-and-re-send through POST /api/replay (development only).
import { useEffect, useMemo, useState } from 'react'
import { ReplayFailure, api } from '../api'
import { MASK_RE } from '../insight'
import type { Execution, Meta } from '../types'
import { DataView } from './DataView'

const MUTATING = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])
const SKIP_HEADERS = new Set(['host', 'content-length', 'connection', 'accept-encoding', 'transfer-encoding', 'keep-alive', 'upgrade'])
const MASK_G = /\[(REDACTED|CPF|CNPJ|CARD|JWT)\]/g

/** "sem corpo" only when the request really had none; otherwise say the backend did not capture it. */
export function emptyBody(headers: Record<string, string> | undefined): string {
  const len = Number(headers?.['content-length'] ?? 0)
  const chunked = (headers?.['transfer-encoding'] ?? '').includes('chunked')
  return len > 0 || chunked ? 'corpo não capturado por este backend (veja os argumentos/retorno do endpoint)' : 'sem corpo'
}

export function bodyTitle(base: string, source?: string): string {
  return source ? `${base} · via ${source}` : base
}

function sendHeaders(exec: Execution): [string, string][] {
  return Object.entries(exec.request.headers ?? {}).filter(([k]) => !SKIP_HEADERS.has(k) && !k.startsWith('x-glowtrace-'))
}

function queryString(q: unknown): string {
  if (!q || typeof q !== 'object') return ''
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(q as Record<string, unknown>)) sp.append(k, typeof v === 'string' ? v : JSON.stringify(v))
  return sp.toString()
}

function bodyText(body: unknown): string {
  if (body === undefined || body === null) return ''
  return typeof body === 'string' ? body : JSON.stringify(body, null, 2)
}

function baseUrl(exec: Execution): string {
  const host = exec.request.headers?.host
  if (!host) return window.location.origin
  const proto = host === window.location.host ? window.location.protocol : 'http:'
  return `${proto}//${host}`
}

/** Masked values become explicit placeholders: the originals were never stored. */
function fill(s: string, name: string): string {
  return s.replace(MASK_G, () => `<PREENCHA_${name.toUpperCase().replace(/[^A-Z0-9]+/g, '_')}>`)
}

const sq = (s: string) => `'${s.replace(/'/g, `'\\''`)}'`

function toPy(v: unknown, ind = 0): string {
  const pad = '    '.repeat(ind + 1)
  const end = '    '.repeat(ind)
  if (v === null || v === undefined) return 'None'
  if (v === true) return 'True'
  if (v === false) return 'False'
  if (typeof v === 'number') return String(v)
  if (typeof v === 'string') return JSON.stringify(v)
  if (Array.isArray(v)) return v.length ? `[\n${v.map((x) => pad + toPy(x, ind + 1)).join(',\n')},\n${end}]` : '[]'
  const e = Object.entries(v as object)
  return e.length ? `{\n${e.map(([k, x]) => `${pad}${JSON.stringify(k)}: ${toPy(x, ind + 1)}`).join(',\n')},\n${end}}` : '{}'
}

type CopyKind = 'curl' | 'httpie' | 'requests' | 'fetch' | 'powershell'

/** JSON with every non-ASCII character as \uXXXX: survives any terminal encoding
 * (Git Bash / cmd / PowerShell 5 on Windows mangle "boné" otherwise). Non-JSON text is kept. */
function asciiJson(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text)).replace(/[\u007f-￿]/g, (c) => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0'))
  } catch {
    return text
  }
}

const psq = (s: string) => `'${s.replace(/'/g, "''")}'`
// headers PowerShell 5.1 refuses in -Headers (set through parameters or by the runtime)
const PS_SKIP = new Set(['user-agent', 'content-type', 'accept', 'connection', 'host', 'content-length', 'expect', 'referer', 'date', 'range', 'if-modified-since', 'transfer-encoding'])

export function copyAs(kind: CopyKind, exec: Execution): string {
  const qs = queryString(exec.request.query)
  const url = fill(baseUrl(exec) + exec.path + (qs ? '?' + qs : ''), 'query')
  const hs = sendHeaders(exec).map(([k, v]) => [k, fill(v, k)] as const)
  const raw = exec.request.body
  const text = raw === undefined || raw === null ? '' : fill(typeof raw === 'string' ? raw : JSON.stringify(raw), 'body')
  const m = exec.method
  if (kind === 'curl') {
    const parts = [`curl -X ${m} ${sq(url)}`, ...hs.map(([k, v]) => `-H ${sq(`${k}: ${v}`)}`)]
    if (text) parts.push(`--data-raw ${sq(asciiJson(text))}`)
    return parts.join(' \\\n  ')
  }
  if (kind === 'httpie') {
    const parts = [`http${text ? ` --raw ${sq(asciiJson(text))}` : ''} ${m} ${sq(url)}`, ...hs.map(([k, v]) => sq(`${k}:${v}`))]
    return parts.join(' \\\n  ')
  }
  if (kind === 'powershell') {
    const ctype = hs.find(([k]) => k === 'content-type')?.[1] ?? (text ? 'application/json' : '')
    const lines = ['$headers = @{', ...hs.filter(([k]) => !PS_SKIP.has(k)).map(([k, v]) => `  ${psq(k)} = ${psq(v)}`), '}']
    const args = [`-Method ${m}`, `-Uri ${psq(url)}`, '-Headers $headers']
    if (text) {
      lines.push(`$body = ${psq(asciiJson(text))}`)
      args.push(`-ContentType ${psq(ctype.includes('charset') ? ctype : ctype + '; charset=utf-8')}`, '-Body $body')
    }
    lines.push(`Invoke-RestMethod ${args.join(' ')}`)
    return lines.join('\n') + '\n'
  }
  const hobj = Object.fromEntries(hs)
  if (kind === 'requests') {
    let bodyArg = ''
    if (text) {
      try {
        bodyArg = `    json=${toPy(JSON.parse(text), 1)},\n`
      } catch {
        bodyArg = `    data=${JSON.stringify(text)},\n`
      }
    }
    return `import requests\n\nr = requests.request(\n    ${JSON.stringify(m)},\n    ${JSON.stringify(url)},\n    headers=${toPy(hobj, 1)},\n${bodyArg})\nprint(r.status_code, r.text)\n`
  }
  let bodyArg = ''
  if (text) {
    try {
      bodyArg = `  body: JSON.stringify(${JSON.stringify(JSON.parse(text), null, 2).replace(/\n/g, '\n  ')}),\n`
    } catch {
      bodyArg = `  body: ${JSON.stringify(text)},\n`
    }
  }
  return `const res = await fetch(${JSON.stringify(url)}, {\n  method: ${JSON.stringify(m)},\n  headers: ${JSON.stringify(hobj, null, 2).replace(/\n/g, '\n  ')},\n${bodyArg}})\nconsole.log(res.status, await res.text())\n`
}

export function RequestPanel({
  exec,
  meta,
  libs,
  onOpenExec,
  onClose,
}: {
  exec: Execution
  meta: Meta | null
  libs: string[]
  onOpenExec: (id: string) => void
  onClose: () => void
}) {
  const [copyOpen, setCopyOpen] = useState(false)
  const [copied, setCopied] = useState<string | null>(null)
  const [editor, setEditor] = useState<null | 'edit' | 'confirm'>(null)
  const enabled = !!meta?.replay_enabled
  const off = 'Reenvio desabilitado. Habilite com GLOWTRACE_REPLAY=1 (somente em desenvolvimento).'

  const [busy, setBusy] = useState(false)
  const [fail, setFail] = useState<string | null>(null)

  // same request again: GET-like goes straight away; side effects ask first; redacted values open the editor
  const quick = async () => {
    setFail(null)
    if (hasMask(exec)) return setEditor('edit')
    if (MUTATING.has(exec.method)) return setEditor('confirm')
    setBusy(true)
    try {
      const r = await api.replay({
        method: exec.method,
        path: exec.path,
        query: queryString(exec.request.query),
        headers: Object.fromEntries(sendHeaders(exec)),
        body: bodyText(exec.request.body) || undefined,
        replay_of: exec.id,
        edits: [],
      })
      if (r.execution_id) onOpenExec(r.execution_id)
      else setFail(`resposta ${r.status}, mas a execução não foi gravada (amostragem / rota excluída)`)
    } catch (e) {
      setFail(String((e as Error).message ?? e))
    } finally {
      setBusy(false)
    }
  }

  const doCopy = async (k: CopyKind) => {
    try {
      await navigator.clipboard.writeText(copyAs(k, exec))
      setCopied(k)
      setTimeout(() => setCopied(null), 1500)
    } catch {
      setCopied('erro')
    }
    setCopyOpen(false)
  }

  return (
    <aside className="inspector">
      <div className="ins-head">
        <div>
          <div className="fn-chip cat-trigger">REQUEST</div>
          <div className="ins-title">
            {exec.method} {exec.path}
          </div>
          {exec.mode === 'replay' && (
            <div className="ins-sub">
              <span className="replay-chip" onClick={() => exec.replay_of && exec.replay_of !== 'manual' && onOpenExec(exec.replay_of)}>
                ↻ replay de #{(exec.replay_of ?? 'manual').slice(0, 8)}
              </span>
              {(exec.replay_edits?.length ?? 0) > 0 && <span className="muted"> · editado: {exec.replay_edits!.join(', ')}</span>}
            </div>
          )}
        </div>
        <button className="x" onClick={onClose} title="fechar (Esc)">
          ×
        </button>
      </div>

      <div className="req-actions">
        <button className="primary" disabled={!enabled || busy} title={enabled ? 'reenviar a mesma requisição' : off} onClick={quick}>
          {busy ? 'enviando…' : '↻ Reenviar'}
        </button>
        <button disabled={!enabled} title={enabled ? 'editar método, caminho, query, headers e corpo antes de reenviar' : off} onClick={() => setEditor('edit')}>
          ✎ Editar e reenviar
        </button>
        <span className="copy-as">
          <button onClick={() => setCopyOpen(!copyOpen)}>Copiar como ▾</button>
          {copyOpen && (
            <div className="menu">
              <button onClick={() => doCopy('curl')}>cURL</button>
              <button onClick={() => doCopy('httpie')}>HTTPie</button>
              <button onClick={() => doCopy('requests')}>Python requests</button>
              <button onClick={() => doCopy('fetch')}>JavaScript fetch</button>
              <button onClick={() => doCopy('powershell')}>PowerShell</button>
            </div>
          )}
        </span>
        {copied && <span className="dv-copied">{copied === 'erro' ? 'não foi possível copiar' : 'copiado'}</span>}
      </div>
      {fail && <div className="exc pad-x">{fail}</div>}
      {!enabled && <div className="hint">Reenviar fica disponível com <code>GLOWTRACE_REPLAY=1</code> (somente em desenvolvimento). Copiar como funciona sempre.</div>}
      {hasMask(exec) && <div className="hint">Valores redigidos (senhas, tokens, CPF…) não foram gravados; ao copiar ou reenviar, preencha os campos marcados.</div>}

      <Section title={bodyTitle('Body', exec.request.body_source)}>
        <DataView value={exec.request.body ?? undefined} role="body" root="body" empty={emptyBody(exec.request.headers)} />
      </Section>
      <Section title="Query">
        <DataView value={exec.request.query} role="query" root="query" empty="sem query" />
      </Section>
      <Section title="Parâmetros de caminho">
        <DataView value={exec.request.path_params} role="query" root="path" empty="nenhum" />
      </Section>
      <Section title="Headers">
        <DataView value={exec.request.headers} role="headers" root="headers" />
      </Section>

      {editor && <ReplayEditor exec={exec} libs={libs} start={editor} onClose={() => setEditor(null)} onOpenExec={onOpenExec} />}
    </aside>
  )
}

export function ResponsePanel({ exec, onClose }: { exec: Execution; onClose: () => void }) {
  return (
    <aside className="inspector">
      <div className="ins-head">
        <div>
          <div className="fn-chip cat-ret">RESPONSE</div>
          <div className="ins-title">
            {exec.method} {exec.path}
          </div>
        </div>
        <button className="x" onClick={onClose} title="fechar (Esc)">
          ×
        </button>
      </div>
      <Section title={bodyTitle(`Status ${exec.status ?? '—'} · ${exec.duration_ms.toFixed(1)} ms`, exec.response.body_source)}>
        <DataView value={exec.response.body ?? undefined} role="body" root="body" empty={emptyBody(exec.response.headers)} />
      </Section>
      <Section title="Headers">
        <DataView value={exec.response.headers} role="headers" root="headers" />
      </Section>
    </aside>
  )
}

function hasMask(exec: Execution): boolean {
  const r = exec.request
  return MASK_RE.test(JSON.stringify([r.body ?? null, r.query ?? null, sendHeaders(exec)]))
}

function maskedPaths(v: unknown, path: string, out: string[]) {
  if (typeof v === 'string') {
    if (MASK_RE.test(v)) out.push(path)
  } else if (Array.isArray(v)) v.forEach((x, i) => maskedPaths(x, `${path}[${i}]`, out))
  else if (v && typeof v === 'object') for (const [k, x] of Object.entries(v)) maskedPaths(x, `${path}.${k}`, out)
}

function parseHeaders(text: string): [string, string][] {
  return text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => {
      const i = l.indexOf(':')
      return i < 0 ? ([l.toLowerCase(), ''] as [string, string]) : ([l.slice(0, i).trim().toLowerCase(), l.slice(i + 1).trim()] as [string, string])
    })
}

function ReplayEditor({
  exec,
  libs,
  start,
  onClose,
  onOpenExec,
}: {
  exec: Execution
  libs: string[]
  start: 'edit' | 'confirm'
  onClose: () => void
  onOpenExec: (id: string) => void
}) {
  const orig = useMemo(
    () => ({
      method: exec.method,
      path: exec.path,
      query: queryString(exec.request.query),
      headers: sendHeaders(exec).map(([k, v]) => `${k}: ${v}`).join('\n'),
      body: bodyText(exec.request.body),
    }),
    [exec],
  )
  const [method, setMethod] = useState(orig.method)
  const [path, setPath] = useState(orig.path)
  const [query, setQuery] = useState(orig.query)
  const [headers, setHeaders] = useState(orig.headers)
  const [body, setBody] = useState(orig.body)
  const [step, setStep] = useState<'edit' | 'confirm'>(start === 'confirm' && MUTATING.has(exec.method) ? 'confirm' : 'edit')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<{ msg: string; fields: string[] } | null>(null)
  const [result, setResult] = useState<{ status: number; preview: string } | null>(null)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !busy && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [busy, onClose])

  const hdrs = parseHeaders(headers)
  const ctype = hdrs.find(([k]) => k === 'content-type')?.[1] ?? (body.trim() ? 'application/json' : '')
  let parsed: unknown = undefined
  let jsonErr: string | null = null
  if (body.trim() && ctype.includes('json')) {
    try {
      parsed = JSON.parse(body)
    } catch (e) {
      jsonErr = String((e as Error).message)
    }
  }
  const masked: string[] = []
  hdrs.forEach(([k, v]) => MASK_RE.test(v) && masked.push(`headers.${k}`))
  if (MASK_RE.test(query)) masked.push('query')
  if (parsed !== undefined) maskedPaths(parsed, 'body', masked)
  else if (MASK_RE.test(body)) masked.push('body')

  const edits = (() => {
    const e: string[] = []
    if (method !== orig.method) e.push('method')
    if (path !== orig.path) e.push('path')
    if (query !== orig.query) e.push('query')
    const a = new Map(parseHeaders(orig.headers))
    const b = new Map(hdrs)
    for (const k of new Set([...a.keys(), ...b.keys()])) if (a.get(k) !== b.get(k)) e.push(`headers.${k}`)
    if (body !== orig.body) {
      let done = false
      try {
        const o = JSON.parse(orig.body || 'null')
        if (o && typeof o === 'object' && !Array.isArray(o) && parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          const po = parsed as Record<string, unknown>
          for (const k of new Set([...Object.keys(o), ...Object.keys(po)])) if (JSON.stringify(o[k]) !== JSON.stringify(po[k])) e.push(`body.${k}`)
          done = true
        }
      } catch {
        /* not JSON */
      }
      if (!done) e.push('body')
    }
    return e
  })()

  const blocked = masked.length > 0 || !!jsonErr || !path.startsWith('/')

  async function send() {
    setBusy(true)
    setErr(null)
    try {
      const r = await api.replay({
        method,
        path,
        query,
        headers: Object.fromEntries(hdrs),
        body: body.trim() ? body : undefined,
        replay_of: exec.id,
        edits,
      })
      if (r.execution_id) {
        onClose()
        onOpenExec(r.execution_id)
      } else setResult({ status: r.status, preview: r.response_preview })
    } catch (e) {
      if (e instanceof ReplayFailure) setErr({ msg: e.message, fields: e.fields })
      else setErr({ msg: String((e as Error).message ?? e), fields: [] })
      setStep('edit')
    } finally {
      setBusy(false)
    }
  }

  const next = () => (MUTATING.has(method) && step === 'edit' ? setStep('confirm') : send())

  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="modal" role="dialog" aria-label="Editar e reenviar">
        <div className="modal-h">
          <b>{step === 'confirm' ? 'Confirmar reenvio' : 'Editar e reenviar'}</b>
          <span className="muted"> · baseado em #{exec.id.slice(0, 8)}</span>
          <button className="x" onClick={onClose} disabled={busy}>
            ×
          </button>
        </div>

        {step === 'edit' && (
          <div className="modal-b">
            <div className="re-line">
              <select value={method} onChange={(e) => setMethod(e.target.value)}>
                {['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'].map((m) => (
                  <option key={m}>{m}</option>
                ))}
              </select>
              <input className="re-path" value={path} onChange={(e) => setPath(e.target.value)} spellCheck={false} />
            </div>
            <label>
              Query <span className="muted">(a=1&amp;b=2)</span>
              <input value={query} onChange={(e) => setQuery(e.target.value)} spellCheck={false} />
            </label>
            <label>
              Headers <span className="muted">(um por linha: Nome: valor)</span>
              <textarea rows={Math.min(8, Math.max(3, hdrs.length + 1))} value={headers} onChange={(e) => setHeaders(e.target.value)} spellCheck={false} />
            </label>
            <label>
              Corpo {ctype && <span className="muted">({ctype})</span>}
              <textarea rows={10} value={body} onChange={(e) => setBody(e.target.value)} spellCheck={false} className={jsonErr ? 'bad' : ''} />
            </label>
            {jsonErr && <div className="exc">JSON inválido: {jsonErr}</div>}
            {masked.length > 0 && (
              <div className="masked">
                <b>Preencha antes de enviar</b> — estes valores foram redigidos na gravação e não existem mais:
                <div className="chips">
                  {masked.map((m) => (
                    <span key={m} className="mchip">
                      {m}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {edits.length > 0 && <div className="muted">alterado: {edits.join(', ')}</div>}
            {err && (
              <div className="exc">
                {err.msg}
                {err.fields.length > 0 && <div>campos: {err.fields.join(', ')}</div>}
              </div>
            )}
            {result && (
              <div className="hint">
                Resposta {result.status} (esta requisição não foi gravada — verifique a amostragem / rotas excluídas)
                <pre className="code">{result.preview.slice(0, 2000)}</pre>
              </div>
            )}
          </div>
        )}

        {step === 'confirm' && (
          <div className="modal-b">
            <div className="warnbox">
              <div>
                <b>
                  {method} {path}
                </b>{' '}
                vai rodar <b>de verdade</b> dentro da API: gravações no banco, e-mails, filas e chamadas externas acontecem de novo.
              </div>
              {libs.length > 0 && (
                <div>
                  Bibliotecas de I/O usadas na execução original: <b>{libs.join(', ')}</b>
                </div>
              )}
              <div className="muted">
                A requisição leva o header <code>X-Glowtrace-Replay</code>; o código pode checar <code>glowtrace.is_replay()</code> para pular efeitos colaterais.
              </div>
            </div>
            {edits.length > 0 && <div className="muted">alterado: {edits.join(', ')}</div>}
          </div>
        )}

        <div className="modal-f">
          {step === 'confirm' && start === 'edit' && (
            <button onClick={() => setStep('edit')} disabled={busy}>
              ← voltar
            </button>
          )}
          {step === 'confirm' && start === 'confirm' && (
            <button onClick={() => setStep('edit')} disabled={busy}>
              editar antes
            </button>
          )}
          <span className="grow" />
          <button onClick={onClose} disabled={busy}>
            cancelar
          </button>
          <button className={step === 'confirm' ? 'danger' : 'primary'} disabled={busy || blocked} onClick={step === 'confirm' ? send : next}>
            {busy ? 'enviando…' : step === 'confirm' ? 'Reenviar mesmo assim' : MUTATING.has(method) ? 'Continuar' : 'Reenviar'}
          </button>
        </div>
      </div>
    </div>
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
