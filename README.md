# EasyAPI

**Veja sua API como um fluxo (estilo n8n) e assista cada requisição atravessá-lo.**

Uma linha no seu app FastAPI e você ganha, em `/_easyapi`:

- **Mapa da API**: cada rota → middlewares → dependências → endpoint → cada função chamada, com
  `if/elif/else`, `for/while`, `try/except/finally`, `with`, `match/case`, `return`, `raise`, e as
  integrações externas detectadas (httpx, requests, pymongo, sqlalchemy…).
- **Execuções gravadas**: para cada requisição, o caminho real aceso sobre o mapa — qual ramo cada `if`
  tomou (e com quais valores), quantas voltas cada loop deu, a entrada/saída de cada função, e o nó
  exato onde uma exceção parou o fluxo.

```python
from fastapi import FastAPI
from easyapi import EasyAPI

app = FastAPI()
# ... suas rotas ...
EasyAPI(app)   # abra http://127.0.0.1:8000/_easyapi/
```

Ou **sem mudar nenhuma linha** do projeto:

```bash
python -m easyapi run uvicorn main:app        # qualquer servidor ASGI
pytest -p easyapi.pytest_plugin               # grava cada requisição da sua suíte de testes
```

Sem decorators, sem mudar o código das funções, sem LLM: análise estática do código + `sys.monitoring`
(Python 3.12+) ou `sys.settrace` (3.10/3.11), escopado por requisição via `ContextVar`.

**Compatibilidade testada**: Python 3.10 → 3.15 (inclusive 3.14 free-threaded) × FastAPI 0.95 → 0.162
(Pydantic v1 e v2) — 84/84. Suítes oficiais do **FastAPI** (4.750 testes), **Mealie** (3.703) e
**full-stack-fastapi-template** rodam idênticas com o EasyAPI gravando tudo. Ver
[docs/COMPATIBILIDADE.md](docs/COMPATIBILIDADE.md).

### Java / Spring Boot

```bash
java -javaagent:easyapi-agent.jar=packages=com.minhaempresa.app;sources=src/main/java -jar app.jar
# UI em http://127.0.0.1:7070/_easyapi/
```

Mesmo mapa, mesma UI, mesmo contrato ([docs/IR.md](docs/IR.md)). Validado no **spring-petclinic-rest**
(37 rotas, 721 funções; 427 frames gravados, 0 transições sem explicação). Ver [java/README.md](java/README.md).

## Por que existe

A pesquisa ([reports/](reports/)) não encontrou nenhuma ferramenta que junte as três coisas:
grafo estático **com desvios** + overlay **por requisição** + canvas tipo n8n plugável. AppMap grava
chamadas mas não `if`/loops (e é MIT + Commons Clause); APMs (Datadog, Sentry, Dynatrace…) param no
nível de span/função; projetos recentes cobrem só metade.

## Recursos

| | |
|---|---|
| Descoberta de rotas | `APIRoute`, routers incluídos (inclusive o formato lazy do FastAPI ≥ 0.16x), `Mount`, `Depends` recursivo, middlewares de usuário |
| Grafo por função | AST → nós legíveis; chamadas resolvidas com os **objetos vivos** do app (`__globals__`, anotações, `with X() as y`), sem efeitos colaterais (`inspect.getattr_static`) |
| Runtime | middleware ASGI externo a tudo; `ContextVar` isola requisições concorrentes; endpoints `def` (threadpool) e `async def`; tasks filhas |
| Valores | captura sem chamar `__repr__`/properties (nada de lazy-load de ORM), limites de profundidade/itens/tamanho, 5 passagens por nó em loops |
| Privacidade | redação no processo: chaves sensíveis (senha, token, cookie, cpf, cnpj, cartão…), CPF/CNPJ com dígito verificador, cartão (Luhn), JWT, Bearer, e-mail mascarado; headers sensíveis |
| Acesso | `/_easyapi` só via loopback por padrão; `EASYAPI_TOKEN` (header/cookie) ou `auth=callback` para acesso remoto |
| Armazenamento | SQLite (thread escritora, retenção por quantidade + idade) ou memória |
| Produção | `mode="graph"` (custo zero), amostragem `sample_rate`, `X-EasyAPI-Trace: 1` força gravar uma requisição, tracer ligado só enquanto há requisição gravada |
| UI | React + React Flow + dagre, embutida no pacote (funciona offline/air-gapped), tema claro/escuro, "ao vivo", ir ao erro, mapa da API filtrável |

## Configuração

```python
EasyAPI(
    app,
    mode="trace",            # "graph" | "trace" | "off"         (EASYAPI_MODE)
    sample_rate=1.0,         # fração de requisições gravadas     (EASYAPI_SAMPLE)
    roots=["."],             # o que é "código do usuário"       (EASYAPI_ROOTS)
    store="sqlite",          # "sqlite" | "memory" | Store        (EASYAPI_STORE / EASYAPI_DB)
    max_executions=500, retention_seconds=7*24*3600,
    token=None,              # exige token fora do loopback       (EASYAPI_TOKEN)
    allow_remote=False,      # (EASYAPI_ALLOW_REMOTE)
    trace_paths=None, ignore_paths=("/docs", "/openapi.json", ...),
    capture=CaptureConfig(redact_keys=("matricula",), allow_keys=("token_count",)),
    limits=Limits(max_frames=3000, max_values_per_node=5),
)
```

`EASYAPI_ENABLED=0` desliga tudo sem mudar código.

## Desempenho (medido)

Endpoint de **pior caso** (100% CPU, loops de ~50 iterações com desvios, ~500 nós visitados por requisição),
Windows, in-process ([benchmarks/](python/benchmarks/bench_overhead.py)):

| Python / backend | sem EasyAPI | `graph` | `trace`, requisição não amostrada | `trace`, requisição gravada |
|---|---|---|---|---|
| 3.13 / sys.monitoring | 0,40 ms | 0,44 ms | 0,43 ms | 2,1 ms |
| 3.11 / sys.settrace | 0,68 ms | 0,65 ms | 0,69 ms | 2,4 ms |

Em endpoints com I/O (o caso comum) a diferença some no ruído. Recomendação para produção:
`mode="graph"` + `sample_rate` baixo + `X-EasyAPI-Trace: 1` sob demanda.

## Validado em projeto real

uma aplicação interna real com dois serviços (132 rotas, 746 funções, 8.548 nós, 1.930 desvios; e 28 rotas, 79 funções) em
branch isolado — ver [docs/VALIDACAO.md](docs/VALIDACAO.md). Mapa completo do apir em 0,77 s.

## Desenvolvimento

```bash
cd python && uv venv --python 3.13 .venv3.13 && VIRTUAL_ENV=.venv3.13 uv pip install -e ".[dev]"
.venv3.13/Scripts/python -m pytest          # 32 testes
python scripts/matrix.py --jobs 6           # matriz Python x FastAPI
python scripts/fuzz_flow.py <diretórios>    # fuzz do construtor de grafo
cd ../ui && npm install && npm run build    # gera python/src/easyapi/_ui
cd ../python && uvicorn examples.loja.app:app --reload   # demo: http://127.0.0.1:8000/_easyapi/
```

Estrutura: `python/` (lib), `java/` (agente Java/Spring), `ui/` (React, agnóstica de linguagem — contrato em
[docs/IR.md](docs/IR.md)), `docs/` (plano, validação, compatibilidade), `reports/` + `research_notes/` (pesquisa).

## Roadmap

Ver [docs/PLANO.md](docs/PLANO.md): exportação OTLP (spans `code.*`), propagação de `traceparent`
entre serviços (ligar execuções apir → authapi), Flask/Django/Litestar, Java (agent + JavaParser),
Node/TS (AsyncLocalStorage + SWC), i18n (EN).

## Licença

Apache-2.0.
