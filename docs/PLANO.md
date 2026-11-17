# Glowtrace — Plano do projeto

> Veja sua API como um fluxo (estilo n8n) e assista cada requisição atravessá-lo.

Base: relatório de pesquisa em `reports/Glowtrace visualização de fluxos de API.md`
(notas em `research_notes/`).

---

## 1. Visão

Uma lib que se pluga em uma linha numa API existente:

```python
from glowtrace import Glowtrace
app = FastAPI()
Glowtrace(app)          # pronto: /_glowtrace abre o mapa + execuções
```

Ela entrega duas coisas:

| Camada | Pergunta que responde | Como |
|---|---|---|
| **Mapa (estático)** | "O que essa API *pode* fazer?" | Rotas lidas do app importado + AST de cada função → grafo legível (call / if / loop / try / return / raise), expandindo para dentro dos serviços chamados |
| **Execução (runtime)** | "O que *essa* requisição fez de verdade?" | Middleware cria um `Recorder` num `ContextVar`; o tracer grava chamadas, args, retornos, linhas-chave e exceções **só** do código do usuário **só** dentro daquela requisição |

A UI sobrepõe a execução ao mapa: caminho percorrido aceso, resto apagado,
nó do erro em vermelho, clique no nó → entrada/saída/valores da condição.

## 2. Posicionamento (resumo da pesquisa)

- **Ninguém junta as 3 coisas** (grafo estático com branches + overlay por request + canvas n8n drop-in).
- **AppMap** é o mais próximo: grava chamadas/args/returns/SQL, mas só no nível de função
  (sem if/loop), sem mapa estático, e é MIT **+ Commons Clause** (não é OSI).
- Live debuggers (Datadog, Lightrun, Dynatrace/Rookout, Sentry) não mostram branch por request.
- 2026 trouxe uma leva de projetinhos FastAPI parciais (routeflow, flowsegul, FastApi-Visualizer)
  → demanda real, janela aberta, mas vai lotar: o diferencial durável é
  **CFG estático + overlay de branch + polimento + segurança enterprise**.

## 3. Princípios

1. **Drop-in**: uma linha, zero decorators obrigatórios.
2. **Estático = possibilidades inferidas; runtime = verdade observada.** Chamadas dinâmicas
   (`handlers[tipo](x)`, `self.repo.get`) aparecem como "não resolvidas" e são preenchidas
   pelas arestas observadas em execuções.
3. **Seguro por padrão**: redação de PII/segredos *dentro do processo* (senha, token, cookie,
   CPF/CNPJ com dígito verificador, cartão com Luhn, JWT), limites de tamanho, retenção curta,
   UI só em loopback ou com token, nada carregado de CDN (air-gapped OK).
4. **Overhead controlado**: off / graph / trace; amostragem; caps por trace; circuit breaker.
5. **Determinístico**: nenhuma LLM no núcleo.
6. **Multi-linguagem pelo IR**: Python primeiro; Java (agent + JavaParser) e Node (AsyncLocalStorage +
   instrumentação SWC/Babel) consomem o mesmo Graph IR e a mesma UI.

## 4. Arquitetura

```
┌────────────────────────── processo da API ──────────────────────────┐
│ FastAPI app                                                          │
│   └─ Glowtrace(app)                                                    │
│        ├─ discover/  rotas + Depends + middlewares do app vivo       │
│        ├─ static/    AST → FlowGraph por função + resolvedor de      │
│        │             chamadas (globals vivos > imports > dinâmico)   │
│        ├─ runtime/   Recorder (ContextVar) + backend:                │
│        │               • sys.monitoring (3.12+)  ← DISABLE p/ não-user│
│        │               • sys.settrace (3.10–3.11) fallback           │
│        │             safe_repr (sem side-effects) + redact (PII)     │
│        ├─ store/     SQLite (thread escritora, retenção N/TTL)       │
│        └─ server/    /_glowtrace  (JSON API + UI estática embutida)    │
└──────────────────────────────────────────────────────────────────────┘
          │ (fase 3) OTLP: cada frame vira span com atributos code.* (estáveis)
          ▼
   Jaeger / Tempo / Datadog / Honeycomb  (correlação via W3C traceparent)
```

### 4.1 Graph IR (JSON, neutro de linguagem)

```jsonc
{
  "version": "0.1",
  "routes":   [{ "id", "methods", "path", "name", "handler": "<fn_id>", "dependencies": ["<fn_id>"], "middlewares": ["<fn_id>"] }],
  "functions": {
    "<fn_id>": {                       // fn_id = "<module>:<qualname>"
      "qualname", "module", "file", "line", "end_line", "is_async", "params": [...],
      "source_hash",                   // detecta código alterado vs execução antiga
      "nodes": [{
        "id": "<fn_id>#<ast-path>",    // estável enquanto a estrutura não muda
        "kind": "start|step|call|if|loop|try|except|finally|with|match|case|return|raise|break|continue|end",
        "label", "code", "line", "end_line", "col",
        "calls": [{ "expr", "target": "<fn_id>|null", "resolution": "live|static|unresolved" }],
        "watch": ["saldo", "limite"]   // nomes cujo valor capturamos quando o nó executa
      }],
      "edges": [{ "source", "target", "kind": "next|true|false|loop|exit|exception|return" }],
      "lines": { "<lineno>": "<node_id>" }   // índice linha → nó (mapeamento runtime)
    }
  }
}
```

### 4.2 Modelo de execução

```jsonc
{
  "id", "trace_id", "method", "path", "route_id", "status", "started_at", "duration_ms",
  "error": { "type", "message", "fn_id", "line" } | null,
  "request":  { "headers", "query", "body" },      // redigidos + truncados
  "response": { "status", "headers", "body" },
  "frames": [{
    "id", "parent", "fn_id", "call_line", "args", "return", "exception",
    "start_us", "end_us",
    "path": [[line, t_us], ...],                     // linhas-chave visitadas, em ordem (cap)
    "watches": { "<line>": [{ "name": value }] }     // valores das condições / alvo de loops
  }]
}
```

A UI converte `path` em nós/arestas percorridos via `functions[fn_id].lines`.
Loops = visitas repetidas na cabeça do loop (contador de iterações). Branch tomado
= próximo nó visitado após o `if`.

### 4.3 Decisões técnicas (com motivo)

| Decisão | Motivo |
|---|---|
| Análise com o **app importado** (globals vivos) + `ast` stdlib | resolve imports/aliases com precisão que call-graph puramente estático (PyCG ~70% recall) não alcança; a lib já roda dentro do processo |
| CFG próprio (não staticfg/py2cfg/scalpel) | os existentes estão parados e não suportam `match`, `try*`, `async with` |
| Mapeamento runtime→nó por **linha** | uniforme em 3.10–3.14 e nos dois backends; `BRANCH_LEFT/RIGHT` (3.14) entra como otimização |
| Middleware **ASGI puro**, envolvendo a pilha inteira (`build_middleware_stack`) | captura também os middlewares do usuário (ex.: `enforce_authentication` do authapi) |
| `ContextVar` com objeto Recorder mutável | anyio/`run_in_threadpool` copia o contexto → endpoints `def` síncronos também são rastreados |
| `safe_repr` sem chamar `__repr__` arbitrário | evita lazy-load de ORM / efeitos colaterais; usa `__dict__` raso, pydantic `model_dump` |
| SQLite + thread escritora | stdlib, zero infra, não bloqueia o event loop |
| UI: **React + @xyflow/react (MIT) + elkjs** (layout layered em compound nodes) | mesmo paradigma de canvas do n8n (que usa Vue Flow + dagre); ELK lida com subfluxos aninhados |
| UI pré-buildada **dentro do wheel** | funciona offline/air-gapped (lição do Swagger UI via CDN) |
| Licença **Apache-2.0**, DCO, SECURITY.md, SBOM, PyPI Trusted Publishing | permissiva + patente; adoção enterprise e caminho CNCF; evita o atrito de Commons Clause/SUL/BSL |

## 5. Segurança e LGPD

- Redação in-process antes de armazenar: chaves (password/senha/token/secret/authorization/cookie/
  api_key/client_secret/cpf/cnpj/cartao/cvv/…), padrões (CPF/CNPJ com DV, cartão Luhn, JWT, Bearer).
- Limites: profundidade, itens, tamanho de string, bytes por valor e frames por execução.
- Retenção: N execuções (padrão 500) + TTL; `glowtrace purge`.
- UI/API `/_glowtrace`: por padrão **só loopback**; fora disso exige `GLOWTRACE_TOKEN`
  ou callback `auth=`. Em produção, modo recomendado: `graph` + `trace` amostrado.
- LGPD: minimização (Art. 6 III), eliminação (Art. 16), segurança by design (Art. 46).

## 6. Roadmap

| Fase | Entrega | Status |
|---|---|---|
| **0 — Pesquisa e plano** | relatório + este plano | ✅ |
| **1 — POC Python/FastAPI** | static (rotas, Depends, middlewares, CFG, resolvedor), runtime (2 backends), redação, SQLite, `/_glowtrace` + UI React Flow, testes, validação numa API interna real (2 serviços) em branch | ✅ ver `docs/VALIDACAO.md` |
| 2 — Mapa da API | visão "call graph" da API inteira (módulos → funções), busca, arestas observadas mescladas, diff de código vs execução | parcial (mapa + filtro + arestas observadas prontos) |
| 3 — Produção | OTLP export (spans `code.*`), propagação de `traceparent` entre serviços, amostragem por rota, circuit breaker de overhead, CLI `glowtrace graph app:app`, colapso automático de execuções grandes | amostragem, header sob demanda, retenção e tracer sob demanda prontos |
| 4 — Ecossistema Python | Flask, Django/DRF, Starlette, Litestar; SQL/HTTP outbound como nós; Celery | auto-instrumentação (`python -m glowtrace run`, plugin pytest) ✅; matriz 3.10–3.15 × FastAPI 0.95–0.162 ✅ |
| 5 — Java | agent ByteBuddy (calls/args) + ASM probes (branches), JavaParser p/ Spring; mesmo IR/UI | POC ✅ (petclinic-rest); falta: locais, WebFlux/@Async, corpo de request |
| 6 — Node/TS | AsyncLocalStorage + plugin SWC/Babel; Express/NestJS | |
| 7 — Governança | Apache-2.0, DCO, Scorecard, releases assinados, docs site | |

## 7. Critérios de sucesso da Fase 1

1. `Glowtrace(app)` numa API interna real (~130 endpoints) sobe sem erro e gera o mapa de todas as rotas.
2. Uma requisição real produz execução com: middlewares → endpoint → serviços, branch tomado em cada `if`,
   iterações de loop, args/retornos redigidos, e o ponto exato da exceção quando há erro.
3. Requisições concorrentes não se misturam (async e sync/threadpool).
4. Overhead medido e documentado (modo graph ≈ 0; trace em micro-benchmark).
5. Nada da API alvo modificado fora de um branch isolado (`git worktree`).

## 8. Questões em aberto

- Nome: o projeto se chama **Glowtrace** (nome livre no PyPI, npm e Maven em 2026-11). Pacote Python
  `glowtrace` (`import glowtrace`), agente Java `io.glowtrace` / `glowtrace-agent.jar`.
- Hospedagem/organização no GitHub e governança (individual vs. empresa).
