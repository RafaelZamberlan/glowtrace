# Compatibilidade e testes com APIs reais — 2026-11-12

## 1. Matriz Python × FastAPI (suíte do Glowtrace, 32 testes, ambientes isolados `uv`)

Script: `python/scripts/matrix.py` (também roda no CI: `.github/workflows/ci.yml`).

| Python \ FastAPI | 0.95.2 | 0.100.1 | 0.104.1 | 0.110.3 | 0.115.14 | 0.120.4 | 0.128.8 | 0.135.4 | 0.145.0 | 0.150.0 | 0.156.8 | 0.162.5 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 3.10 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 3.11 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 3.12 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 3.13 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 3.14 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 3.14t (free-threaded) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 3.15 (beta 2) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

**84/84.** Cobre Pydantic v1 (FastAPI 0.95) e v2, Starlette com stack de middleware "eager" (antigo) e
"lazy", routers incluídos clássicos e o `_IncludedRouter` lazy (FastAPI ≥ 0.16x), backends
`sys.settrace` (3.10/3.11) e `sys.monitoring` (3.12+).

## 2. Suítes de testes de projetos open source, com o Glowtrace injetado

Método: rodar a suíte do projeto **sem** e **com** `pytest -p glowtrace.pytest_plugin`
(auto-instrumentação: todo app criado ganha o Glowtrace, toda requisição é gravada) e comparar teste a
teste (JUnit XML). Qualquer teste que passa sem e falha com = bug de transparência. Em seguida,
`GLOWTRACE_SELFCHECK=1` reconstrói o overlay de cada execução gravada e conta transições que o grafo
estático não explica.

| Projeto | Escopo | Sem Glowtrace | Com Glowtrace | Regressões | Gravado | Transições sem explicação |
|---|---|---|---|---|---|---|
| **FastAPI 0.162.5** (suíte oficial, `filterwarnings=error`) | ~1.700 apps de tutorial/teste: deps com yield, background tasks, websockets, sub-apps, segurança, uploads, streaming, SSE | 4.750 ✓ / 22 skip | 4.750 ✓ / 22 skip | **0** | 1.743 apps, 4.635 execuções, 16.596 frames | **0** |
| **Mealie** (Python 3.14, FastAPI 0.162.2, SQLAlchemy) | 291 rotas, 1.985 `Depends` | 3.703 ✓ / 103 ✗* | 3.703 ✓ / 103 ✗* | **0** | 162.837 frames (integração) | **0** |
| **full-stack-fastapi-template** (Python 3.14, FastAPI 0.141, SQLModel + Postgres em Docker) | API de usuários/itens/login | 56 ✓ / 2 ✗* | 56 ✓ / 2 ✗* | **0** | 58 execuções, 255 frames | **0** |
| **API interna real** (2 serviços, ver `VALIDACAO.md`) | 132 + 28 rotas | — | — | — | execuções reais | — |

\* falhas pré-existentes e idênticas nas duas rodadas (ambiente Windows: encoding cp1252 ao ler
templates, `python-ldap` sem wheel, testes que dependem de rede/IA).

Tempo da suíte: FastAPI 45 s → 60 s (8 workers), Mealie 74 s → 113 s, gravando **todas** as
requisições (em uso normal com amostragem o custo é perto de zero — ver README).

Mapa estático do Mealie: 291 rotas, 614 funções, 4.562 nós, 793 desvios — rotas em 0,68 s, mapa em 0,17 s.

## 3. Java / Spring Boot (javaagent)

Agente em `java/glowtrace-agent` (Byte Buddy + JavaParser, ambos Apache-2.0, realocados no jar): mesmo
contrato `docs/IR.md`, mesma UI (o overlay é calculado no navegador). Uso:
`java -javaagent:glowtrace-agent.jar=packages=<pacote>;sources=<src/main/java> -jar app.jar`.

| App | Estático | Runtime | Verificação independente (overlay da UI em TS sobre os frames Java) |
|---|---|---|---|
| **spring-petclinic-rest** 4.0.2 (Spring Boot, JPA/H2, interfaces geradas por OpenAPI, MapStruct) | 37/37 rotas (inclusive mapeamentos herdados de interfaces geradas), 721 funções, 3.134 nós, ~1 s | listagens, busca, 404, POST válido/ inválido, PUT, DELETE — 0 erros internos | **15 execuções, 427 frames, 0 sem fluxo, 0 transições sem explicação** |
| demo-loja (Spring Boot 3, espelho do demo Python) | todas as rotas | sucesso, validação 4xx, 404, 500, pagamento recusado (try/catch) | caminhos corretos (ramo `else` ausente quando o `if` executa) |

Overhead medido pelo agente: ~+0,8 ms em `/owners/1` e ~+3 ms em `/owners` (129 frames) gravando;
requisições não gravadas sem diferença mensurável.

Limitações conhecidas do agente Java: não captura variáveis locais (`values` vazio — args, retornos e
exceções sim); só Spring MVC / servlet (WebFlux e `@Async` não); corpo de request/response não capturado;
`javax.servlet` e containers além do Tomcat não testados.

## 4. Fuzz do construtor de grafo

`python/scripts/fuzz_flow.py` constrói o grafo de **toda função** de um conjunto de árvores de código e
verifica invariantes (start/end, arestas válidas, toda linha de statement mapeada a um nó):

- stdlib do Python 3.14 + FastAPI (código, docs_src, tests) + Mealie + uma API interna
- **2.504 arquivos, 25.763 funções, 174.226 nós, ~3.000 funções/s — 0 violações, 0 crashes**

## 5. Bugs encontrados por estes testes (todos corrigidos, com teste de regressão)

| Achado | Onde apareceu | Correção |
|---|---|---|
| Exceção não tratada reportada como `ExceptionGroup` | FastAPI 0.95 / Starlette 0.27 + anyio 4 | desembrulhar grupos de uma exceção |
| Stack de middleware "eager" (Starlette antigo) ficava `None` | FastAPI 0.95 | reconstruir a stack na hora |
| Frames duplicados em `await` no Python 3.10 | matriz py3.10 | retorno real só quando o opcode em `f_lasti` é `RETURN_*` (3.10 estaciona `f_lasti` no `LOAD_CONST` antes de `YIELD_FROM`) |
| Saída de `with` contada como salto | suíte do FastAPI (107 casos) | nós ganham `parent` estrutural; revisita do cabeçalho do `with` = saída do bloco |
| `raise` / `except` que não casa indo para `finally` sem aresta | suíte do FastAPI | arestas de exceção para o `finally` e entre handlers |
| Auto-instrumentação não pegava `FastAPI` (sobrescreve `build_middleware_stack`) | teste do modo auto | interceptar `Starlette.__call__` |
| Recursão infinita: o app interno `/_glowtrace` se auto-instrumentava | `python -m glowtrace run` | app interno marcado e ignorado |
| CLI usava o `python` do PATH em vez do venv | `python -m glowtrace run` | resolver pelo interpretador atual |
| Link colado com a aba já aberta não abria a execução (só o hash muda) | UI servida pelo agente Java | escutar `hashchange` |
| **Java: `ClassFormatError: bad offset for Uninitialized`** em `new X(a, cond ? b : c)` — a sonda de linha ficava entre o rótulo e o `NEW`, e os stack map frames copiados apontavam para ela | API Java real de terceiro (Spring Boot 3.5 / Java 21), reportado por outro agente | sonda emitida logo **depois** do `NEW`; regressão em `demo-loja` (`/diagnostico`) e teste de estresse `java/scripts/stress-instrumentacao.sh`: com o jar antigo o próprio carregador do Spring Boot quebra; com a correção **11.345 classes** (Spring, Jackson, Hibernate, Tomcat, H2, Swagger) instrumentadas, **0 erros**; suíte do petclinic-rest 256/256 com e sem agente |

## 6. Como reproduzir

```bash
cd python
python scripts/matrix.py --jobs 6                     # matriz completa
python scripts/fuzz_flow.py <dirs...>                 # fuzz do grafo
# suíte de terceiros com Glowtrace:
GLOWTRACE_ROOTS=<código do projeto> GLOWTRACE_EXPOSE_HEADER=0 GLOWTRACE_STORE=memory GLOWTRACE_SELFCHECK=1 \
  pytest -p glowtrace.pytest_plugin
# qualquer servidor, sem mudar código:
python -m glowtrace run uvicorn main:app
```
