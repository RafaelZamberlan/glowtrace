# Glowtrace — contrato de dados (Graph IR + execuções)

Qualquer backend de linguagem (Python hoje, Java/Node depois) expõe **as mesmas rotas HTTP** sob
`<prefix>` (padrão `/_glowtrace`) e a mesma UI estática. A UI é agnóstica de linguagem.

## Rotas HTTP

| Rota | Resposta |
|---|---|
| `GET <prefix>/` | `index.html` da UI (assets em `<prefix>/assets/*`) |
| `GET <prefix>/api/meta` | `Meta` |
| `GET <prefix>/api/routes` | `{routes: Route[], middlewares: Middleware[]}` |
| `GET <prefix>/api/function?id=<fn_id>` | `FunctionFlow` (+ `observed_calls: fn_id[]`) |
| `GET <prefix>/api/map` | `{routes, middlewares, functions: MapFn[], edges: MapEdge[]}` |
| `GET <prefix>/api/executions?route=&status=error\|ok&limit=` | `{executions: ExecSummary[]}` (mais recente primeiro) |
| `DELETE <prefix>/api/executions` | `{deleted: n}` |
| `GET <prefix>/api/executions/<id>` | `Execution` (campo `overlay` **opcional**: a UI calcula se ausente) |

Acesso: por padrão só loopback; com token configurado, header `X-Glowtrace-Token`, cookie
`glowtrace_token` ou `?token=` (que grava o cookie).

## Tipos

```ts
Meta = { title, version, mode: "trace"|"graph"|"off", backend: string|null,
         runtime: string /* "python 3.13.1", "java 17.0.18" */, python?: string,
         prefix, sample_rate: number, route_count: number, internal_errors: number }

Route = { id /* "GET /owners/{id}" — métodos unidos por "|" */, kind: "http"|"websocket"|"mount",
          methods: string[], path, name?, summary?, tags: string[],
          handler: fn_id|null, handler_desc?: string,
          dependencies: {fn: fn_id, desc: string}[],   // Depends (Python) / interceptors (Java)
          file?: string, line?: number, is_async?: boolean }

Middleware = { name, fn: fn_id|null, kind: "user"|"library" }   // em ordem: mais externo primeiro

fn_id = "<arquivo relativo com />::<qualname>"   // ex. "src/services/auth.py::AuthService.login"
                                                 // Java: "src/main/java/a/b/OwnerController.java::OwnerController.findOwner"

FunctionFlow = {
  id: fn_id, qualname, file /* relativo */, line, end_line, is_async: boolean, params: string[],
  doc?: string|null, source: string /* texto da função */, source_start: number /* linha da 1ª linha de source */,
  source_hash: string,
  nodes: Node[],   // nodes[0].kind == "start", último nó kind == "end"; id == índice no array
  edges: Edge[],
  observed_calls?: fn_id[]
}

Node = { id: number, kind: NodeKind, label: string /* código curto, <= 90 chars */,
         line: number, end_line: number,
         own?: [number, number] /* linhas observáveis em runtime; ausente em start/end/finally */,
         calls?: Call[], watch?: string[] /* variáveis lidas: capturadas ao visitar */,
         assigns?: string[] /* variáveis escritas: capturadas depois */,
         try_parent?: number /* nó try que envolve */, loop_parent?: number }

NodeKind = "start" | "end" | "step" | "call" | "if" | "loop" | "match" | "case" | "try" | "except"
         | "finally" | "with" | "return" | "raise" | "break" | "continue"
         // Java: switch→match, case/default→case, catch→except, throw→raise,
         //       try-with-resources/synchronized→with, for/foreach/while/do→loop

Call = { expr: string, kind: "user"|"external"|"stdlib"|"builtin"|"unresolved",
         target?: fn_id /* se user */, lib?: string /* se external */, awaited?: boolean, line: number }

Edge = { source: number, target: number,
         kind: "next"|"true"|"false"|"loop"|"exit"|"exception"|"case"|"return"|"break",
         label?: "sim"|"não"|"cada"|"fim"|"erro"|"nenhum"|<padrão do case> }
```

Regras do grafo:
- passos simples consecutivos sem chamada interessante viram **um** nó `step` (máx. 8 statements);
- statement com chamada a código do usuário / I/O externo / `await` vira nó `call`;
- `if`: aresta `true` (label "sim") para o 1º nó do corpo, `false` ("não") para o `else`/`elif` ou para o que vem depois;
- loops: `true` ("cada") para o corpo, `loop` do fim do corpo de volta à cabeça, `exit` ("fim") para depois;
- `try`: aresta `exception` ("erro") do `try` para cada `except`; `raise` dentro do try liga aos handlers;
- todo `return` liga ao nó `end` com aresta `return`.

**Mapeamento runtime→nó por linha**: cada nó "possui" linhas (cabeçalho de estruturas de controle:
da linha do statement até a linha antes do 1º statement do corpo; statements simples: todas as suas
linhas). A tabela `linha → nó` é usada pelo recorder: ao executar uma linha cujo nó difere do último
registrado no frame, acrescenta `[nó, t_us]` em `path`.

```ts
ExecSummary = { id, trace_id, started_at /* epoch s */, method, path, route_id: string|null,
                status: number|null, duration_ms: number, error: ExecError|null, frame_count: number }

ExecError = { type, message, escaped: boolean /* saiu do app */, status_code?: number, frame?: number }

Execution = ExecSummary & {
  truncated: boolean, backend: string,
  request:  { headers: {[k]: string}, query: object, path_params: object, body: any },
  response: { headers: {[k]: string}, body: any },
  frames: Frame[],
  overlay?: { frames: FrameOverlay[] }    // opcional
}

Frame = { id: number /* índice */, parent: number|null, fn: fn_id, call_line: number|null /* linha no pai */,
          args: {[name]: Value}, start_us: number, end_us: number|null /* relativos ao início da req */,
          path: [nodeIdx, t_us][],
          values: [pathPos, {[name]: Value}, "before"|"after"][],
          return?: Value, exception?: {type, message, line, detail?, status_code?},
          raised?: {line, type, message}[], hash?: source_hash, incomplete?: true, truncated?: true }

Value = JSON  // objetos: {"__type__": "Classe", campo: valor...}; truncamentos com "…"; segredos "[REDACTED]"/"[CPF]"/"[JWT]"...

FrameOverlay = { id, visits: {[nodeIdx]: count}, edges: {[edgeIdx]: count}, error_node?: number,
                 call_node?: number /* nó do pai que fez a chamada */, stale?: boolean, jumps?: [a,b][] }
```

## Privacidade (obrigatório em todo backend)

Redigir **no processo**, antes de armazenar: chaves sensíveis (password, senha, secret, token, apikey,
authorization, cookie, credential, cpf, cnpj, cartao, cvv, pin, session…), valores (JWT, Bearer, CPF/CNPJ
com DV válido, cartão com Luhn, e-mail mascarado), headers (authorization, cookie, set-cookie, x-api-key).
Nunca chamar `toString`/`__repr__`/getters arbitrários para capturar objetos — usar campos.
