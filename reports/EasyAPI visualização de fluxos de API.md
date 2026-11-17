# Ninguém ainda sobrepõe a execução real ao fluxo

**Em novembro de 2026, nenhuma solução aberta ou comercial faz ao mesmo tempo as duas coisas que o EasyAPI propõe.** A primeira é desenhar estaticamente todos os endpoints de uma API como um fluxo de nós no estilo n8n, descendo até if/else, for/while, try/except e return/raise dentro de cada função. A segunda é gravar cada requisição real e sobrepor a esse mesmo mapa os argumentos, os retornos, o branch tomado e o ponto em que uma exceção interrompeu o fluxo, tudo como uma lib plugável. O mercado só tem fragmentos. O AppMap grava chamadas de função por requisição, inclusive em FastAPI, mas não enxerga branches e usa MIT + Commons Clause. O Kolo faz algo parecido apenas para Django e é proprietário. Uma leva de projetos FastAPI de 2026 entrega ou o runtime sem CFG ou o CFG sem runtime, e Datadog, Lightrun, Dynatrace e Hud param na fronteira do span ou da função. A lacuna pode ser fechada agora porque o `sys.monitoring` (PEP 669) do Python 3.12+ emite eventos de branch com offsets de bytecode que `co_positions()` converte em linha e coluna casáveis com nós do `ast`. O risco é de timing: quatro projetos FastAPI minúsculos surgiram em 2026, o que mostra demanda e anuncia aglomeração. O fosso, portanto, precisa somar CFG estático, overlay de branches e privacidade de nível enterprise, com redação de CPF/CNPJ na captura, aderência à LGPD e operação offline. A arquitetura recomendada parte de um núcleo Python sob Apache-2.0 com IR de grafo própria, construtor de CFG escrito em casa sobre o `ast`, descoberta de rotas por importação em subprocesso isolado, gravador `sys.monitoring` escopado por `ContextVar`, SQLite local com exportação OTLP e UI React Flow + ELK.js embutida no wheel; Java (ByteBuddy + ASM) e Node (Babel/SWC + `AsyncLocalStorage`) entram depois, reaproveitando a mesma IR.

## Fragmentos cobrem metade do problema, e nenhum une mapa, branch e canvas

### O AppMap é o concorrente mais próximo, mas para no nível da função

O **AppMap** é o produto estabelecido mais próximo da metade runtime do EasyAPI. O agente Python registra chamadas de função, requisições web, SQL, parâmetros, valores de retorno e exceções. Ele suporta **FastAPI >=0.110,<1**, Django, Flask e SQLAlchemy, e oferece gravação por requisição (`APPMAP_RECORD_REQUESTS`), gravação remota e uma gravação por teste pytest ([AppMap Python reference](https://appmap.io/docs/reference/appmap-python.html)). A mesma documentação, porém, descreve instrumentação **apenas no nível de função**: cada função ganha um evento ao ser chamada, e não há menção a branches, loops ou linhas. A visualização usa sequence diagrams, dependency maps, trace views e flame graphs ([AppMap no dev.to](https://dev.to/appmap/introducing-flame-graphs-its-getting-hot-in-here-1j9l)), não um canvas de CFG.

A licença também pesa. O LICENSE do appmap-python é MIT acrescido da **Commons Clause**, que proíbe vender o software, incluindo hospedagem e consultoria ([appmap-python LICENSE](https://raw.githubusercontent.com/getappmap/appmap-python/master/LICENSE)), embora o PyPI declare só "MIT" ([PyPI appmap](https://pypi.org/project/appmap/)). Os repositórios seguiam ativos em novembro de 2026 (appmap-python com 104 estrelas e push em 2026-11-10), mas os agentes têm pouca tração na comunidade ([GitHub getappmap](https://github.com/getappmap)). Contra o AppMap, o EasyAPI se diferencia em quatro frentes: o CFG dentro de cada função, um grafo de todos os endpoints que existe antes de qualquer requisição, o canvas no estilo n8n e uma licença de fato aprovada pela OSI.

### A observabilidade comercial se consolidou e não enxerga abaixo do span

Nenhum fornecedor de observabilidade ou live debugging mostra algo como "esta requisição tomou o `else` da linha 42". O nível mais fino que eles oferecem são spans de função adicionados à mão (o Sentry exige `functions_to_trace` ou o decorator `@sentry_sdk.trace` ([Sentry custom instrumentation](https://docs.sentry.io/platforms/python/tracing/instrumentation/custom-instrumentation))), snapshots de variáveis por linha sob demanda ou grafos de chamada agregados. O Datadog liga spans à linha de origem com o **Code Origin** e deixa transformar variáveis clicadas no IDE em atributos via Dynamic Instrumentation ([Datadog Code Origin](https://docs.datadoghq.com/tracing/code_origin/)). Seu **Exception Replay** captura variáveis locais na exceção, mas em Python fica limitado a cerca de **1 snapshot por tipo de exceção, por instância, por hora** ([Datadog Exception Replay](https://docs.datadoghq.com/error_tracking/backend/exception_replay/)). O **Hud**, anunciado em dezembro de 2025 ([Webull/PR](https://www.webull.com/news/14002963577545728)), coleta só metadados para montar um grafo de chamadas agregado, com overhead autodeclarado de **1–2%** ([Hud FAQ](https://docs.hud.io/docs/faq)).

O setor se consolidou rápido. A Dynatrace comprou a Rookout em 2023 ([Dynatrace IR](https://ir.dynatrace.com/news-events/press-releases/detail/303/dynatrace-to-acquire-rookout-to-deliver-code-debugging-in)), a Snyk absorveu a Helios em 2024 para alimentar seu ASPM ([Snyk](https://snyk.io/news/snyk-acquires-runtime-data-pioneer-helios)) e a Digma encerrou operações em novembro de 2025 ([Startup Nation Central](https://finder.startupnationcentral.org/company_page/digma)). Em fevereiro de 2026 a Dash0 comprou a Lumigo ([Dash0](https://dash0.com/blog/dash0-acquires-lumigo-to-expand-agentic-observability-across-aws-and-serverless)), e a Lightrun, que levantou **US$ 70 milhões** em 2025, se reposicionou como "AI SRE" ([Lightrun](https://lightrun.com/press/lightrun-secures-70m-series-b-to-redefine-software-resilience-and-shape-the-future-of-autonomous-application-remediation/)). Esses movimentos apontam para o mesmo lugar: **contexto de runtime para agentes de IA**. O Hud tem servidor MCP, o Multiplayer vende gravações como contexto para ferramentas de IA e o Datadog gera hipóteses de causa raiz. Por isso o formato de trace do EasyAPI deve nascer legível por máquina.

### Tracers Python e geradores estáticos resolvem pedaços isolados

O tracing em Python é maduro, mas cada ferramenta cobre só um pedaço. O **VizTracer** (Apache-2.0, 7,8 mil estrelas) registra args, retornos e exceções sem alterar código e mostra tudo numa timeline Perfetto, sem grafo de chamadas ([GitHub viztracer](https://github.com/gaogaotiantian/viztracer)). O birdseye sobrepõe ao código os valores das expressões ([GitHub birdseye](https://github.com/alexmojaki/birdseye)). O **Cyberbrain**, único a desenhar como grafo o fluxo de dados entre variáveis, está dormente desde 2021–2022 (última release 0.2.3, em 2021-10-10) e se declara impróprio para produção ([GitHub Cyberbrain](https://github.com/laike9m/Cyberbrain)). O **Kolo** captura toda chamada, retorno e variável local por requisição, mas só em Django, sob licença "© Kolo", e agora se apresenta como depurador textual para agentes de IA ([GitHub koloai/kolo](https://github.com/koloai/kolo); [PyPI kolo](https://pypi.org/project/kolo/)).

Do lado estático, o code2flow está praticamente parado desde 2023 ([PyPI code2flow](https://pypi.org/project/code2flow/)), o pyan3 é ativo mas GPL-2.0 ([GitHub pyan](https://github.com/Technologicat/pyan)), o PyCG foi arquivado ([GitHub PyCG](https://github.com/vitsalis/PyCG)) e o staticfg está dormente ([GitHub staticfg](https://github.com/coetaur0/staticfg)). PyFlowchart e a extensão CodeVisualizer geram fluxogramas por função sem qualquer noção de endpoint ([GitHub pyflowchart](https://github.com/cdfmlr/pyflowchart); [GitHub CodeVisualizer](https://github.com/DucPhamNgoc08/CodeVisualizer)). Diagramadores por IA como o GitDiagram (18,9 mil estrelas) trabalham no nível de arquitetura ([GitHub gitdiagram](https://github.com/ahmedkhaleel2004/gitdiagram)). Diante de mapas gerados por LLM, um grafo determinístico feito de AST + runtime é um diferencial que vale afirmar explicitamente.

### A onda FastAPI de 2026 prova a demanda e mostra que a janela é curta

Quatro projetos independentes surgiram em 2026, cada um atacando parte da proposta. O **routeflow** (MIT, v0.3.2) rastreia funções marcadas com `@track` e desenha um grafo de nós ao vivo em `/flow/`, mas só para funções que rodaram, sem nós de branch, sem autenticação e com buffer de 500 traces ([PyPI routeflow](https://pypi.org/project/routeflow/)). O **fastapi-watchtrace** (v0.0.2, Python 3.13+) oferece grafo por requisição e avisa que endpoints síncronos podem gerar traces incompletos ([PyPI fastapi-watchtrace](https://pypi.org/project/fastapi-watchtrace/)). O **FastApi-Visualizer** já usa `sys.monitoring` para árvores de chamada e suspensões de `await`, sem args, retornos, branches ou suporte a múltiplos workers ([GitHub FastApi-Visualizer](https://github.com/raushankumar1511/FastApi-Visualizer)). O **flowsegul** é o mais próximo da metade estática. Ele desenha um grafo arrastável por endpoint, mantém as linhas `if/for/with/try` como contexto e traça o caminho de cada `raise` até o `except`, mas não tem runtime, não tem licença e tem zero estrelas ([GitHub flowsegul](https://github.com/hackertehlike/flowsegul)).

No Node, SuriLens e NodeFlow desenham mapas de execução por requisição sem declarar granularidade de branch ([SuriLens no DEV](https://dev.to/sonisuryansh/surilens-an-open-source-real-time-backend-execution-visualizer-for-nodejs-101k)). Motia, Flyde e Node-RED têm canvas e traces por execução, mas só para código escrito no modelo deles ([Motia docs](https://motia-dev-website.vercel.app/docs/concepts/flows-and-visualization)), e por isso não são drop-in.

| Ferramenta | Grafo estático de endpoints | Branches dentro da função | Gravação por requisição | Args/retornos por nó | Canvas de nós | Drop-in FastAPI | Licença / status |
|---|---|---|---|---|---|---|---|
| AppMap | ✘ | ✘ | ✔ | ✔ | ~ | ✔ | MIT + Commons Clause; ativo |
| Kolo | ✘ | ✘ | ✔ | ✔ (+locais) | ✘ | ✘ (Django) | Proprietário; ativo |
| routeflow | ✘ | ✘ | ✔ | ~ | ✔ | ✔ (decorator) | MIT; v0.3 |
| fastapi-watchtrace | ~ | ✘ | ✔ | ? | ✔ | ✔ | MIT; v0.0.2 |
| FastApi-Visualizer | ✘ | ✘ | ✔ | ✘ | ✔ | ✔ | Sem licença |
| flowsegul | ✔ | ~ | ✘ | ~ (estático) | ✔ | ✔ | Sem licença |
| PyFlowchart / CodeVisualizer | ✘ (por função) | ✔ | ✘ | ✘ | ~ | ✘ | MIT |
| VizTracer | ✘ | ✘ | ✔ (por execução) | ✔ | ✘ (timeline) | ~ | Apache-2.0 |
| Datadog / Lightrun / Dynatrace | ✘ | ✘ (snapshots de linha) | ✔ (spans) | ~ | ✘ | ✔ | Comercial |
| Motia / Flyde / Node-RED | ✔ (modelo próprio) | ✘ | ✔ (Motia) | ~ | ✔ | ✘ (exige reescrita) | OSS |
| **EasyAPI (proposto)** | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | Apache-2.0 |

### As reclamações dos usuários já definem os requisitos mínimos

O sinal mais claro da comunidade veio do "Show HN: Nogic", uma extensão VS Code de grafo de código que recebeu 135 pontos e 53 comentários ([HN 46605675](https://news.ycombinator.com/item?id=46605675)). Os comentários apontaram desconfiança de extensões fechadas, poucos quadros por segundo e travamentos acima de 2 mil arquivos, arestas ausentes em Django e ruído em bases grandes. Os usuários pediram clusters resumidos e um servidor MCP.

A documentação das próprias ferramentas completa o quadro. Endpoints síncronos geram traces instáveis. Interfaces de debug sem autenticação precisam ser desligadas em produção ([PyPI routeflow](https://pypi.org/project/routeflow/)). O Kolo trocou a extensão VS Code por uma web app servida pelo próprio processo ([Kolo docs](https://docs.kolo.app/en/latest/)).

Disso saem os requisitos mínimos do EasyAPI. Ele precisa de licença permissiva e de um grafo escalável, com colapso e filtro por endpoint. Precisa modelar fielmente o framework (`Depends`, routers, middleware, background tasks) e entregar uma web UI antes de qualquer plugin de IDE. A redação de dados tem de ser de primeira classe, com um modo seguro para produção. E o suporte a `async def` tem de ser tão sólido quanto o suporte a `def` executado no threadpool.

Uma ressalva de método: ausência de evidência não prova ausência. LangGraph Studio, Temporal, Inngest e Windmill, que têm UIs de execução passo a passo, não foram verificados, e produtos fechados ou muito novos podem ter escapado das buscas.

## Python 3.12+ já entrega cada branch, mas atribuí-lo a uma requisição é terreno inexplorado

### O que o `sys.monitoring` oferece

Para Python, a base correta é o `sys.monitoring`, adicionado no **3.12** pela PEP 669. Ele expõe dois tipos de evento ([sys.monitoring 3.14](https://docs.python.org/3.14/library/sys.monitoring.html)). Os eventos locais podem ser ativados por code object e desativados por localização: `PY_START`, `PY_RETURN`, `PY_YIELD`, `PY_RESUME`, `CALL`, `LINE`, `JUMP` e, desde o **3.14**, `BRANCH_LEFT`/`BRANCH_RIGHT`, que substituem o agora depreciado `BRANCH`. Os eventos globais não podem ser desativados por localização: `RAISE`, `PY_UNWIND`, `EXCEPTION_HANDLED` e `RERAISE`.

As assinaturas dos callbacks entregam exatamente o que o EasyAPI precisa. `PY_RETURN` recebe `retval`. `CALL` recebe o `callable` real e o primeiro argumento, que em métodos é a instância. Eventos de branch recebem `(code, instruction_offset, destination_offset)` e eventos de exceção recebem o objeto da exceção. Os callbacks, porém, **não recebem o frame**, então capturar argumentos exige acessar o frame dentro do callback. É um custo extra, que deve ficar restrito às requisições amostradas.

Existem seis tool IDs (0–5), e a VM trata todos igualmente. O coverage.py 7.14.2 corrigiu um bug causado por presumir que `COVERAGE_ID` estaria livre ([coverage.py changelog](https://coverage.readthedocs.io/en/latest/changes.html)). A lição para o EasyAPI é procurar um ID livre e coexistir com debuggers, coverage e profilers. O ponto decisivo é que eventos e callbacks valem **por interpretador, não por thread** ([PEP 669](https://peps.python.org/pep-0669/)), de modo que todo filtro por requisição precisa acontecer dentro do próprio callback.

### Por que o 3.12 já basta para gravar branches

No 3.12 e no 3.13, desativar um evento `BRANCH` desliga a instrução de origem inteira, e a ferramenta nunca mais ouve o outro destino. Foi esse problema que motivou a reformulação do 3.14 ([Ned Batchelder](https://nedbatchelder.com/blog/202407/pushing_back_on_sysmonitoring); [discuss.python.org](https://discuss.python.org/t/updating-sys-monitoring-how-branch-events-are-disabled/59527)). O defeito prejudica ferramentas de cobertura, que querem desligar cada localização depois do primeiro acerto. Um gravador por requisição **nunca** desliga branches do código do usuário, porque a próxima requisição precisa deles. Por isso o EasyAPI pode gravar branches desde o 3.12 com `BRANCH` + `JUMP` e migrar para `BRANCH_LEFT | BRANCH_RIGHT` no 3.14+. A documentação não define qual lado é "left" e qual é "right"; garante apenas consistência durante a execução. Isso não importa, porque o destino vem no próprio evento.

O mapeamento para o fonte deve usar **localizações, não offsets**. Mark Shannon trata offsets como detalhe de implementação. `co_positions()` dá linha e coluna de início e de fim de cada instrução, e um destino sem localização própria exige avançar até a próxima instrução com localização nova ([cpython#122762](https://github.com/python/cpython/issues/122762)). As colunas são offsets em bytes UTF-8, a mesma unidade do `col_offset` do `ast`, e viram `None` sob `-X no_debug_ranges` ([Python data model](https://docs.python.org/3.14/reference/datamodel.html)), o que exige um fallback por linha. O `code.co_branches()` do 3.14 devolve tuplas `(origem, não-tomado, tomado)`, mas as fontes não dizem se é API pública documentada. Ele deve ser usado com detecção de recurso e fallback para `dis`.

| Versão do Python | Mecanismo recomendado | Branches | Observações |
|---|---|---|---|
| 3.10–3.11 | `sys.setprofile` (só chamadas e retornos) ou import hook que reescreve o AST | Só via reescrita de AST | A reescrita conflita com o hook de asserts do pytest e perde módulos importados antes |
| 3.12–3.13 | `sys.monitoring` com `BRANCH` + `JUMP` | Sim, sem usar `DISABLE` em código do usuário | A limitação de branches afeta cobertura, não gravação por requisição |
| 3.14+ | `sys.monitoring` com `BRANCH_LEFT`/`BRANCH_RIGHT` + `JUMP` | Sim | `clear_tool_id()` novo; free-threading com suporte oficial |
| 3.15 | Não pesquisado | — | Conferir o What's New antes de fechar a matriz |

### O truque que barateia a cobertura não serve ao EasyAPI

Os números de overhead publicados impressionam, mas medem outra coisa. O SlipCover, que no 3.12+ usa `sys.monitoring`, tem overhead mediano de **5%**, contra **180%** do coverage.py baseado em `settrace` ([arXiv 2305.02886](https://arxiv.org/abs/2305.02886)). O coverage.py 7.7, com branch coverage via sysmon, ficou **2,42 vezes mais rápido** que a versão anterior num benchmark pequeno ([Hugo van Kemenade](https://hackers.pub/@hugovk@mastodon.social/0195a9d7-f222-74f1-969c-a34e2ac32292/quotes)). Esses ganhos vêm de retornar `DISABLE` depois do primeiro acerto em cada localização, o que torna gratuitas as execuções seguintes ([Ned Batchelder](https://nedbatchelder.com/blog/202503/faster_branch_coverage_measurement)). A própria PEP admite que, com eventos de `LINE`, o ganho sobre `settrace` é pequeno. Admite também que o bytecode instrumentado atrapalha a especialização do interpretador e que `set_events` e `restart_events` devem ser tratados como operações lentas ([PEP 669](https://peps.python.org/pep-0669/)).

Um gravador por requisição não pode usar `DISABLE` no código do usuário. O sinal mais revelador vem do coverage.py, cujo núcleo sysmon **continua incompatível com dynamic contexts**, a atribuição da execução a cada teste ([coverage.py changelog](https://coverage.readthedocs.io/en/latest/changes.html)). Nem a ferramenta de referência resolveu, sobre `sys.monitoring`, a pergunta "a que contexto pertence este evento", e esse é o problema central do EasyAPI. **Não há benchmark publicado** de CALL/RETURN/BRANCH sempre ativos no código do usuário sob carga web, então o overhead é a principal incógnita técnica do projeto.

Existem duas estratégias, e ambas têm custo. A primeira mantém os eventos sempre armados no código do usuário e descarta requisições não amostradas com um `ContextVar.get()` no callback. Nesse caso, cada requisição não amostrada ainda paga um callback Python por chamada e por branch. A segunda arma os eventos com `set_local_events` apenas enquanto houver uma requisição amostrada em andamento. O custo em regime é zero, mas armar é lento e global, e requisições concorrentes pagam durante a janela. Nas duas, código de terceiros e da stdlib sai de graça: a decisão é tomada uma vez por code object, no `PY_START`, e devolve `DISABLE` para sempre. Um callback em C ou Rust (via PyO3), à semelhança do CTracer do coverage.py, é o passo natural depois do protótipo em Python puro.

### Escopo por requisição: `ContextVar`, threads e tarefas em segundo plano

O padrão recomendado é simples. Um middleware ASGI decide a amostragem, cria um gravador **mutável** e o publica numa `ContextVar`, que os callbacks consultam. Ao fim da requisição, o gravador segue para um exportador assíncrono. Cada tarefa asyncio roda no próprio contexto, então requisições concorrentes no mesmo event loop não se misturam.

O `anyio.to_thread.run_sync`, usado por Starlette e FastAPI para endpoints e dependências `def`, roda a função numa **cópia** do contexto e não propaga escritas de volta ([encode/starlette#1525](https://github.com/encode/starlette/pull/1525); [discuss.python.org](https://discuss.python.org/t/back-propagation-of-contextvar-changes-from-worker-threads/15928)). Como a cópia carrega a referência ao mesmo gravador, os eventos de endpoints síncronos caem no lugar certo, desde que nenhum callback chame `ContextVar.set()`. Já `threading.Thread`, `ThreadPoolExecutor` e filas como Celery exigem propagação explícita. As `BackgroundTasks` do FastAPI rodam depois da resposta e devem aparecer como um segmento filho marcado "pós-resposta". Em código assíncrono, `PY_YIELD` e `PY_RESUME` marcam cada `await`, então a pilha de chamadas do gravador precisa ser mantida por tarefa, não por thread.

Nas builds free-threaded, os callbacks rodam de fato em paralelo. O coverage.py corrigiu em 2025 uma condição de corrida com `sys.monitoring`, e o CPython registrou uma data race, detectada pelo ThreadSanitizer, ao registrar callbacks em muitas threads ([coverage.py changelog](https://coverage.readthedocs.io/en/latest/changes.html); [gh-131141](https://scriptagc.wasmer.app/https_github_com/python/cpython/issues/131141)). Como a documentação atual deixou de chamar o free-threading de experimental ([free-threading HOWTO](https://docs.python.org/3/howto/free-threading-python.html)), os sub-buffers devem ser por thread ou por tarefa e fundidos ao fim da requisição.

```python
# Esboço (não executado) do núcleo do gravador, Python 3.12+
M, E = sys.monitoring, sys.monitoring.events
TOOL = next(i for i in range(6) if M.get_tool(i) is None)   # nunca presumir COVERAGE_ID
M.use_tool_id(TOOL, "easyapi")
REC = contextvars.ContextVar("easyapi_rec", default=None)   # aponta para um Recorder mutável
BR = (E.BRANCH_LEFT | E.BRANCH_RIGHT) if hasattr(E, "BRANCH_LEFT") else E.BRANCH

def on_start(code, off):
    if not is_user_code(code):          # decisão estática, cacheada por code object
        return M.DISABLE                # zero custo daqui em diante para terceiros
    r = REC.get()
    if r is not None and not r.full:
        r.enter(code, sys._getframe(1)) # args só em requisições amostradas

def on_branch(code, src, dst):
    r = REC.get()
    if r is not None:
        r.branch(code, src, dst)        # nunca DISABLE: a próxima requisição precisa
```

### Capturar valores sem quebrar a aplicação

Capturar valores é a parte mais cara e mais perigosa da gravação. A regra é nunca chamar `__repr__`, `__str__` ou getters de objetos da aplicação no caminho quente, porque uma instância SQLAlchemy pode, por exemplo, disparar SQL de lazy loading. O serializador deve despachar pelo tipo exato, limitar profundidade, itens e tamanho de strings, ler só o estado já carregado (o `__dict__`, sem `_sa_instance_state`) e tratar o `SecretStr` do Pydantic como redigido por padrão. A serialização acontece fora do caminho quente e só para os traces que serão mantidos. Isso leva a três camadas de amostragem: só o fluxo para uma fração das requisições, fluxo com valores para uma fração menor e valores sempre para as requisições com erro.

Os fornecedores comerciais limitam o custo com cotas rígidas. Pela documentação Ruby do Datadog, vista por um espelho, o Dynamic Instrumentation permite **1 execução por segundo** em probes que capturam snapshot e **5.000 por segundo** nos demais, e desliga automaticamente o probe que passar de **0,5 s de CPU** ([dd-trace-rb docs](https://docsearch.algolia.com/mcp/docs/repo/datadog/dd-trace-rb)). A Lightrun anuncia cotas e um "dead man switch", mas não publica limites ([Lightrun datasheet](https://go.lightrun.com/hubfs/Docs/Lightrun_Datasheet.pdf)).

O plano de controle do EasyAPI deve somar várias proteções. A primeira é uma chave por endpoint, com taxa padrão zero em produção e um header de debug, avaliada antes de criar o gravador. Depois vêm limites rígidos por trace: total de eventos, profundidade e, em cada loop, só as primeiras N iterações mais um contador. A exportação usa amostragem própria, mantendo erros e requisições lentas, e passa por um ring buffer que descarta o mais antigo e por um exportador assíncrono em lote. Um disjuntor desarma o monitoramento quando a latência das requisições amostradas se afasta da linha de base das não amostradas, e um kill switch remoto permite desligar tudo. Todo callback deve ficar dentro de `try/except BaseException`. As fontes não confirmam o que acontece quando um callback do `sys.monitoring` levanta exceção, então esse comportamento precisa ser testado.

## Java e Node exigem bytecode e transformação de build, não uma API pronta

### Java: ByteBuddy para métodos, sondas ASM para branches

A JVM não tem API nativa de eventos de branch por requisição. O caminho de produção é um `-javaagent` que usa **ByteBuddy `Advice`** para entrada, saída, argumentos, retornos e exceções nos pacotes do usuário, mais sondas **ASM** nos pontos estratégicos que o JaCoCo usa. O JaCoCo mantém um `boolean[]` global por classe e insere poucas sondas, em pontos escolhidos por análise de fluxo de controle ([JaCoCo implementation](https://www.jacoco.org/jacoco/trunk/doc/implementation.html)). Esse array é compartilhado entre threads e não serve para atribuição por requisição, então no EasyAPI as sondas precisam escrever num gravador obtido via `ThreadLocal`.

A densidade de sondas tem preço. Um mantenedor do JaCoCo relatou que **2,4 vezes mais sondas** levaram o tempo de execução a **100–146%** do original ([JaCoCo Google Group](https://groups.google.com/g/jacoco/c/MztSENoOh2I/m/Chok-XdGAwAJ)). O JFR ganhou rastreio de métodos no **JDK 25** com a JEP 520, mas apenas no nível de método, e a JEP declara que não pretende manter o teto de 1% de CPU nesse modo ([JEP 520](https://openjdk.org/jeps/520)). O agente OpenTelemetry para Java já instrumenta métodos listados por configuração, sem mudar código ([OTel Java methods](https://explorer.opentelemetry.io/java-agent/instrumentation/methods)), mas sua página de performance não publica números e recomenda amostragem e instrumentação seletiva ([OTel Java agent performance](https://opentelemetry.io/docs/zero-code/java/agent/performance/)).

No Spring MVC, toda requisição passa por `DispatcherServlet.doDispatch`, o ponto natural para abrir e fechar o gravador. Saltos assíncronos (`@Async`, `CompletableFuture`) exigem embrulhar `Runnable` e `Callable`, e WebFlux exige o `Context` do Reactor. `Instrumentation.retransformClasses` permite armar e desarmar a instrumentação por classe, o equivalente Java do `set_local_events`. Como bytecode guarda linha (`LineNumberTable`) mas não coluna, o overlay em Java será por linha, com o JavaParser ligando cada linha ao `if`, `switch` ou loop correspondente.

### Node: `AsyncLocalStorage` mais instrumentação no build

No Node, o contexto por requisição vem do `AsyncLocalStorage`, que no **Node 24** passou a usar `AsyncContextFrame` por padrão ([Node.js v24.0.0](https://nodejs.org/blog/release/v24.0.0)). Num benchmark da Platformatic com Fastify, o ALS manteve **93,3%** do throughput de base. A autoinstrumentação OTel completa derrubou esse número para **18,6%**, com P99 de 104 ms, e a seletiva ficou em 35,9% ([Platformatic](https://blog.platformatic.dev/the-hidden-cost-of-context)). A lição é instrumentar só os módulos do usuário.

A cobertura de blocos do V8 insere contadores antes de cada `then` e `else`. Ela é, porém, **global ao isolate** e exige desligar o compilador otimizador para que as contagens fiquem corretas ([V8 blog](https://v8.dev/blog/javascript-code-coverage)). Serve para dev, CI ou um worker isolado que receba requisições espelhadas uma de cada vez, mas não para gravação por requisição em produção. Em produção, o caminho é um **plugin Babel/SWC no estilo istanbul**, que injeta chamadas de branch, entrada, saída e retorno gravando no recorder do `AsyncLocalStorage`. As posições voltam ao TypeScript original via source maps.

### eBPF não chega ao nível de função em linguagens interpretadas

eBPF não resolve este problema. Uprobes disparam traps em endereços nativos ([CNCF/Pixie](https://www.cncf.io/blog/2021/11/17/debugging-with-ebpf-part-1-tracing-go-function-arguments-in-prod/)), e a lógica de negócio em Python, Java e Node roda em interpretador ou JIT, sem símbolos nativos estáveis por função, muito menos por branch. O logging dinâmico do Pixie só suporta binários Go ([Pixie docs](https://docs.px.dev/tutorials/custom-data/dynamic-go-logging/)). O suporte a `perf` do Python 3.12 serve a profiling por amostragem, e os próprios core devs criticam seu custo ([discuss.python.org](https://discuss.python.org/t/the-performance-of-python-with-perf-support-is-not-great-and-is-going-to-get-a-lot-worse/25280)). eBPF serve para fronteiras de protocolo como HTTP e SQL, não para o fluxo interno.

| Linguagem | Contexto da requisição | Funções, args e retornos | Branches | Mapeamento para o fonte | Custo conhecido |
|---|---|---|---|---|---|
| Python 3.12+ | `ContextVar` (copiada pelo anyio) | `PY_START`/`PY_RETURN`/`CALL` | `BRANCH`(`_LEFT`/`_RIGHT`) + `JUMP` | `co_positions` (linha + coluna) | Sem benchmark para gravação sempre ativa |
| Java | `ThreadLocal` + executores embrulhados; Reactor `Context` | ByteBuddy `Advice` | Sondas ASM no estilo JaCoCo | `LineNumberTable` (só linha) | 2,4× mais sondas → 100–146% do tempo |
| Node | `AsyncLocalStorage` | Plugin Babel/SWC | Contadores injetados escrevendo no ALS | Source maps | ALS a 93,3%; OTel completo a 18,6% |

## O mapa estático precisa ser construído em casa sobre o `ast`

### Nenhuma biblioteca de CFG cobre o Python 3.12–3.14

Nenhuma biblioteca de CFG em Python serve como está. O staticfg não tem visitors para `try`, `with`, `match` e `async for` ([staticfg builder.py](https://github.com/coetaur0/staticfg/blob/HEAD/staticfg/builder.py)). O Scalpel trata `try` e `with`, mas não `match` nem `except*`, e está parado desde 2024 ([Scalpel](https://github.com/SMAT-Lab/Scalpel)). O python-graphs, do Google, foi arquivado ([python-graphs](https://github.com/google-research/python-graphs)). O PyFlowchart é o único que trata `match`, mas gera DSL de flowchart.js, não um grafo ([PyFlowchart](https://github.com/cdfmlr/pyflowchart)).

Um builder para 3.12–3.14 precisa lidar com `match` ([PEP 634](https://peps.python.org/pep-0634/)), `except*` ([PEP 654](https://peps.python.org/pep-0654/)), type parameters ([PEP 695](https://peps.python.org/pep-0695/)), comprehensions inlined ([PEP 709](https://peps.python.org/pep-0709/)), t-strings ([PEP 750](https://peps.python.org/pep-0750/)), `except A, B:` sem parênteses ([PEP 758](https://peps.python.org/pep-0758/)) e o aviso para `return` dentro de `finally` ([PEP 765](https://peps.python.org/pep-0765/)). A base prática é o **`ast` da stdlib** executado no próprio interpretador do projeto, que sempre conhece a sintaxe exata da versão em uso. A ele se somam **beniget/gast** (BSD-3) para cadeias def-use ([beniget](https://github.com/serge-sans-paille/beniget)) e um builder próprio para cerca de 25 tipos de statement. O LibCST (MIT/PSF, já com suporte a 3.15) só entra se for preciso editar código preservando formatação ([LibCST CHANGELOG](https://github.com/Instagram/LibCST/blob/HEAD/CHANGELOG.md)). astroid (LGPL-2.1) ([astroid](https://github.com/pylint-dev/astroid)) e pyan3 (GPL-2.0) devem ficar como plugins opcionais ou ser evitados.

### Um grafo de regiões legível, não blocos básicos de compilador

Há prior art sólida para grafos que humanos conseguem ler. A **Evaluation Order Graph** do Fraunhofer CPG liga nós executáveis do AST na ordem de execução ([EOG spec](https://fraunhofer-aisec.github.io/cpg/CPG/specs/eog)). O Joern tipa estruturas como `CONTROL_STRUCTURE` (IF, ELSE, WHILE, FOR, TRY, SWITCH...) com arestas para a condição ([Joern CPG schema](https://cpg.joern.io/)). O PyFlowchart define uma taxonomia de início, fim, operação, condição, entrada/saída e sub-rotina ([PyFlowchart ast_node.py](https://github.com/cdfmlr/pyflowchart/blob/HEAD/pyflowchart/ast_node.py)).

O EasyAPI deve construir um **grafo de regiões aninhadas e colapsáveis**. Cada statement relevante vira um nó. Atribuições simples consecutivas se fundem num nó "Code", e todo statement com chamada ganha âncora própria. `if/elif/else` vira uma condição com arestas `true`/`false`. `match` vira um switch com uma aresta por `case`. `for` e `while` viram regiões de loop com arestas `loop_body`, `loop_back`, `loop_exit` e `loop_else`.

`try` vira uma região cujas arestas de exceção partem da borda para cada handler, em vez de uma por statement, o que tornaria o grafo ilegível. O `finally` aparece uma única vez. `with` vira uma região de context manager, com um selo de "recurso" em sessões de banco. `return` e `raise` são nós terminais ligados a saídas sintéticas. `await` e `yield` são nós de suspensão, e dependências FastAPI com `yield` se dividem em setup e teardown. Comprehensions ficam dentro do nó pai, coerente com a PEP 709, que reporta seus eventos no code object do pai. Decorators viram anotações. Uma camada oculta de blocos básicos sustenta a correção e o mapeamento de runtime, mas nunca aparece na UI.

### Descoberta de rotas por importação, com fallback estático

Todos os frameworks-alvo mantêm, depois da importação, um registro de rotas completo e introspectável:

| Framework | Onde estão as rotas | Fonte |
|---|---|---|
| FastAPI | `app.routes` + uma árvore `Dependant` por rota, com params, sub-dependências recursivas, `call`, `use_cache` e `scope` | [fastapi models.py](https://github.com/fastapi/fastapi/blob/HEAD/fastapi/dependencies/models.py) |
| Starlette | `Mount.routes`, percorrível recursivamente | [starlette routing.py](https://github.com/Kludex/starlette/blob/HEAD/starlette/routing.py) |
| Flask | `url_map` + `view_functions` | [flask app.py](https://github.com/pallets/flask/blob/HEAD/src/flask/sansio/app.py) |
| Django | `get_resolver().url_patterns` | [django resolvers.py](https://github.com/django/django/blob/HEAD/django/urls/resolvers.py) |
| DRF | `EndpointEnumerator` | [DRF generators.py](https://github.com/encode/django-rest-framework/blob/HEAD/rest_framework/schemas/generators.py) |
| Litestar | `route_handler_index` | [litestar app.py](https://github.com/litestar-org/litestar/blob/HEAD/litestar/app.py) |

A importação dá prefixos exatos depois de `include_router` e `Mount`, além de árvores de dependência completas, inclusive `Annotated[..., Depends()]`. O preço é executar código do usuário, com conexões, variáveis de ambiente e efeitos colaterais. Por isso a descoberta deve rodar num **subprocesso isolado**, com ambiente simulado, timeout e sem rede. Se falhar, entra um fallback estático por padrões de decorator (`@router.get`, `include_router(prefix=...)`) que marca prefixos não resolvidos como `dynamic`.

Em FastAPI, o grafo de cada endpoint deve mostrar a cadeia de middleware, a árvore de dependências, o CFG do handler, arestas de `raise HTTPException` até o `exception_handler` correspondente, `BackgroundTasks` como arestas assíncronas e a serialização do `response_model`. Dependências com `yield` rodam em `AsyncExitStack`s aninhados ([fastapi routing.py](https://github.com/fastapi/fastapi/blob/HEAD/fastapi/routing.py)), e o teardown delas precisa aparecer depois da resposta.

### Resolução de chamadas honesta, com proveniência em cada aresta

Call graphs estáticos de Python acertam muito, mas perdem bastante. O PyCG reporta **99,2% de precisão e 69,9% de recall** ([arXiv 2103.00587](https://arxiv.org/abs/2103.00587)). O JARVIS afirma 84% mais precisão que o PyCG, mas está preso ao Python 3.8 e não tem licença ([arXiv 2305.05949](https://arxiv.org/abs/2305.05949v5); [pythonJaRvis](https://github.com/pythonJaRvis/pythonJaRvis.github.io)). Nenhum dos dois serve de dependência.

A pilha de 2026 resolve cada call site em camadas. A primeira é a resolução léxica e de imports, com beniget para locais. A segunda trata `self.metodo()` pela MRO do projeto e emite todos os overrides como candidatos, com `dispatch=dynamic`. A terceira resolve receptores tipados via LSP: pyright e basedpyright são maduros e MIT, e ty e pyrefly também implementam call hierarchy ([pyright](https://github.com/microsoft/pyright/blob/HEAD/packages/pyright-internal/src/languageService/callHierarchyProvider.ts); [ty](https://github.com/astral-sh/ruff/blob/HEAD/crates/ty_ide/src/call_hierarchy.rs); [pyrefly](https://github.com/meta/pyrefly/blob/HEAD/pyrefly/lib/lsp/non_wasm/call_hierarchy.rs)). A quarta aplica conhecimento do framework, como `Depends(f)` e `add_task(f)`. Por último, o que sobrar vira uma aresta `unresolved` para um nó "?" com o texto da chamada, em vez de ser descartado.

O runtime fecha o resto. O evento `CALL` entrega o `callable` real ([sys.monitoring 3.14](https://docs.python.org/3.14/library/sys.monitoring.html)), e assim dispatch dinâmico, `getattr` e containers de DI viram arestas `observed`. Cada aresta registra `source`, `resolver`, `confidence` e `candidates`. Ninguém publicou a acurácia de pyright, ty ou pyrefly usados como oráculo de call graph, e é essa proveniência que torna o grafo confiável.

### Uma IR neutra de linguagem, com IDs estáveis

Joern, SARIF e SCIP convergem num núcleo comum: nós tipados com código e intervalo de linha e coluna, arestas tipadas e identidade por nome qualificado ([Joern CPG schema](https://cpg.joern.io/); [SARIF 2.1.0](https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json); [scip.proto](https://github.com/scip-code/scip/blob/HEAD/scip.proto)). O SARIF tem ainda `threadFlowLocation` com `executionOrder`, `webRequest` e `webResponse`, praticamente um formato pronto para exportar o caminho de uma requisição. A IR do EasyAPI deve separar a contenção (`parent`, usada pela UI para colapsar regiões) das arestas de fluxo e registrar a proveniência em cada aresta:

```json
{ "schema": "easyapi.graph/0.1",
  "snapshot": { "id": "sha256-dos-inputs", "vcs": {"commit": "abc123", "dirty": false} },
  "nodes": [ { "id": "py:app.routers.users:get_user#/body/2/If",
               "kind": "condition", "label": "user is None", "code": "if user is None:",
               "loc": {"file": "f1", "startLine": 42, "startCol": 4, "endLine": 43, "endCol": 40},
               "parent": "py:app.routers.users:get_user", "contentHash": "sha1-subarvore" } ],
  "edges": [ { "src": "…#/body/2/If", "dst": "…#/body/2/If/body/0/Raise", "kind": "true",
               "provenance": {"source": "static", "resolver": "ast", "confidence": 1.0},
               "observed": {"count": 0} } ] }
```

Os IDs devem ser **caminhos semânticos**, isto é, nome qualificado mais caminho estrutural no AST, e não números de linha. Assim sobrevivem a edições em outras partes do arquivo, enquanto o `contentHash` detecta deriva. Cada snapshot é indexado pelo commit, e uma observação de runtime só é levada ao snapshot seguinte se o hash do nó não mudou; caso contrário, fica marcada como "stale". Em runtime, um índice de intervalos leva cada tupla de `co_positions` ao nó do AST mais interno que a contém. Num evento de branch, comparar o destino com os sucessores estáticos `true`/`false` rotula a aresta observada sem precisar saber qual lado é "left".

### Java e TypeScript: as ferramentas existem, mas o TS está em transição

Em Java, o **JavaParser** é dual LGPL/Apache e pode ser usado sob Apache-2.0 ([JavaParser LICENSE](https://github.com/javaparser/javaparser/blob/HEAD/LICENSE)). Ele cobre a descoberta por anotações Spring e o CFG no nível do fonte. SootUp (LGPL-2.1) e OPAL (BSD-2) entram só quando for preciso um call graph do programa inteiro ([SootUp](https://github.com/soot-oss/SootUp); [OPAL](https://github.com/opalj/opal/blob/HEAD/LICENSE)). Em runtime, o `MappingsEndpoint` do Actuator expõe todas as rotas ([MappingsEndpoint.java](https://github.com/spring-projects/spring-boot/blob/HEAD/module/spring-boot-actuator/src/main/java/org/springframework/boot/actuate/web/mappings/MappingsEndpoint.java)). A extração estática de OpenAPI em Spring tem prior art acadêmica no Respector e no AutoOAS ([arXiv 2410.23873](https://arxiv.org/abs/2410.23873v1)).

Em TypeScript o momento é delicado. O **TypeScript 7.0**, port em Go com GA em 8 de julho de 2026, saiu **sem compiler API**. O beta do 7.1, de 20 de outubro de 2026, restaura a API com novos entry points e promete compatibilidade em toda a linha 7.x depois de estabilizar ([InfoQ TS 7.1 beta](https://infoq.com/news/2026/11/typescript-7-1-beta)). Enquanto isso, o ts-morph segue no TS 6. A recomendação é isolar o front end TS num sidecar Node, com ts-morph no MVP e a API do 7.1 quando estiver estável. No Express 5, as rotas saem de `app.router.stack` em runtime ([express application.js](https://github.com/expressjs/express/blob/HEAD/lib/application.js)); no NestJS, dos decorators `@Controller` e `@Get` ([nest core/router](https://github.com/nestjs/nest/tree/HEAD/packages/core/router)).

Como backbone multi-linguagem, o tree-sitter (MIT) dá apenas sintaxe, e o stack-graphs, que acrescentava resolução de nomes, foi arquivado ([stack-graphs](https://github.com/github/stack-graphs)). Fraunhofer CPG (Apache-2.0, com Python via CPython embutido) e Joern (Apache-2.0, releases quase diários) são candidatos maduros, porém pesados na JVM ([cpg](https://github.com/Fraunhofer-AISEC/cpg); [Joern](https://github.com/joernio/joern)). O CodeQL fica excluído para código fechado pela licença do CLI ([CodeQL license](https://securitylab.github.com/tools/codeql/license)). O mais seguro é uma IR própria, desenhada para poder ser **importada** de um export do Joern ou do CPG no futuro.

## Em produção, o EasyAPI vira um banco de dados pessoais sob a LGPD

### OpenTelemetry: spans de função sim, branches não

A interoperabilidade com OTel é obrigatória, e os padrões estão maduros. Os atributos **`code.function.name`, `code.file.path`, `code.line.number`, `code.column.number` e `code.stacktrace` são estáveis** ([OTel semconv: code](https://opentelemetry.io/docs/specs/semconv/registry/attributes/code/)), e o `traceparent` do W3C Trace Context é Recomendação desde 2021 ([W3C Trace Context](https://www.w3.org/TR/trace-context/)). O desenho correto é **um span `INTERNAL` por função instrumentada**, filho do span de servidor do framework e marcado com `code.*`. Quando houver um SDK OTel no processo, o EasyAPI reaproveita o contexto existente; sozinho, ele lê e propaga o `traceparent`, para que o grafo aponte para o mesmo trace no APM do cliente. Num replay, a ligação com o trace original deve ser um span link.

Há uma lacuna concreta que o EasyAPI pode ocupar. O agente Java do OTel instrumenta métodos arbitrários por configuração, mas a instrumentação zero-code do Python só cobre bibliotecas conhecidas ([opentelemetry-instrumentation](https://pypi.org/project/opentelemetry-instrumentation/0.63b0/)). O `opentelemetry-instrumentation-fastapi`, por sua vez, cria um span por requisição e não captura corpos nem funções ([docs fastapi instrumentation](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html)). O EasyAPI pode preencher esse espaço como uma instrumentação compatível com OTel.

Dois movimentos de 2026 mantêm os branches fora do OTel. Primeiro, o OTel anunciou a **depreciação da Span Events API** (`AddEvent`, `RecordException`) em favor de eventos baseados em logs ([OTel blog](https://opentelemetry.io/blog/2026/deprecating-span-events/)). Além disso, os SDKs limitam spans a **128 eventos** por padrão ([OTel SDK env vars](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/)), o que truncaria loops em silêncio. Segundo, o sinal de **Profiles está em alpha** desde março de 2026, não é recomendado para produção e proíbe atributos `code.*` ([OTel Profiles alpha](https://opentelemetry.io/blog/2026/profiles-alpha)).

Branches e valores ficam, portanto, no formato nativo do EasyAPI. Para o OTel seguem a estrutura (spans, timings, tipos de exceção) e, no máximo, um resumo de branches com limite de tamanho e desligado por padrão. Payloads também ficam fora por padrão: o tamanho de valores de atributo não tem limite padrão, e o intake OTLP direto do Datadog aceita só HTTP/protobuf e rejeita requisições acima de **3,2 MB** ([Datadog OTLP intake](https://docs.datadoghq.com/opentelemetry/setup/agentless/traces)). As fontes divergem sobre se esse intake está em preview ou em GA.

### Redação na captura, com CPF e CNPJ de fábrica

Todo fornecedor maduro redige dados em camadas. O Sentry remove no servidor valores e chaves que contenham `password`, `secret`, `token`, `auth`, `bearer`, `api_key` e similares, mas **não remove IPs por padrão** ([Sentry server-side scrubbing](https://docs.sentry.io/security-legal-pii/scrubbing/server-side-scrubbing/)). O `EventScrubber` do SDK Python, por desempenho, **não é recursivo por padrão** ([Sentry Python sensitive data](https://docs.sentry.io/platforms/python/data-management/sensitive-data/)). O Datadog Dynamic Instrumentation, o análogo mais próximo do EasyAPI, redige **na infraestrutura do cliente, antes do upload**, por identificador e por tipo, e não deixa colocar probes dentro de tipos marcados como sensíveis ([Datadog DI scrubbing](https://docs.datadoghq.com/dynamic_instrumentation/sensitive-data-scrubbing/)). O **redaction processor do OTel Collector** trabalha com allowlist, **falha fechado** (lista vazia remove tudo), aceita HMAC e está em beta para traces ([redactionprocessor README](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/processor/redactionprocessor/README.md)). O **Microsoft Presidio** não tem reconhecedor brasileiro, nem CPF nem CNPJ ([Presidio supported entities](https://presidio.dataprivacystack.org/supported_entities/)), e o EasyAPI precisa trazê-los de fábrica.

O desenho seguro por padrão começa pela redação dentro do processo, no momento da captura, para que nada sem redação chegue ao disco ou à rede. A denylist de chaves junta as listas do Sentry e do Datadog a chaves brasileiras como `cpf`, `cnpj`, `rg`, `senha`, `pis`, `nis`, `cns` e `titulo_eleitor`. Detectores de valor validam dígitos verificadores de CPF e CNPJ, Luhn em cartões, JWT e telefone +55, e devem ser publicados também como reconhecedores customizados do Presidio. A redação vale ainda por tipo, incluindo `SecretStr` e modelos ORM declarados.

A varredura recursiva fica ligada por padrão, porque a escolha do Sentry serve a um rastreador de erros, não a uma ferramenta que existe para capturar payloads aninhados. Limites de captura guardam só um resumo de forma (tipo e tamanho) quando o valor estoura. Há três modos de operação: `off` (só estrutura), `redacted` (padrão) e `full` (apenas local, com faixa de aviso na UI). Para valores que precisam continuar correlacionáveis, usa-se **HMAC com chave, nunca hash simples**: um CPF tem 11 dígitos, e seu hash SHA sem chave é revertido por força bruta.

### A LGPD transforma boas práticas em obrigação

A Lei 13.709/2018 se aplica diretamente aos dados que o EasyAPI captura ([Lei 13.709/2018](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm)):

| Dispositivo | O que exige | Consequência para o EasyAPI |
|---|---|---|
| Art. 6º, III (necessidade) | Tratamento limitado ao **mínimo necessário** | Minimização e redação por padrão |
| Art. 46 | Segurança desde a concepção do produto | Privacidade embutida no desenho, não opcional |
| Art. 16 | Eliminação dos dados ao fim do tratamento | Retenção curta por padrão, com expurgo automático |
| Arts. 12 e 13 | Dado pseudonimizado religável por chave continua sendo pessoal | HMAC não equivale a anonimização |
| Art. 37 | Registro das operações de tratamento | Log de auditoria de quem viu cada trace |
| Art. 52 | Multas de até **2% do faturamento, limitadas a R$ 50 milhões por infração** | Risco financeiro direto para o controlador |

A Resolução CD/ANPD nº 15/2024 exige guardar o registro de incidentes por **pelo menos cinco anos**, mesmo os não comunicados à ANPD ([Lefosse](https://lefosse.com/noticias/alerta/client-alert-anpd-aprova-regulamento-de-comunicacao-de-incidente-de-seguranca/)). Uma fonte secundária fala em prazo de três dias úteis para a comunicação ([Contábeis](https://www.contabeis.com.br/noticias/55651/anpd-vazamento-de-dados-deve-ser-comunicado-em-ate-tres-dias/)), o que precisa ser conferido no texto final.

A consequência prática é forte. Um EasyAPI que grava payloads de produção numa distribuidora de energia ou num órgão público **torna-se ele mesmo um repositório de dados pessoais**. Precisa então de criptografia em repouso, TLS na UI, SSO via OIDC e RBAC que separe quem vê valores brutos de quem vê valores redigidos. Precisa também de log de auditoria imutável, retenção configurável e um modo totalmente offline, sem CDN e sem telemetria. As notas não trouxeram fontes sobre exigências específicas da ANEEL, do GSI/PR ou de nuvem de governo para ferramentas on-prem, e esse levantamento precisa ser feito antes de vender para esses setores.

### Armazenamento em camadas, do notebook ao data center

Não foram encontrados benchmarks que comparem motores de armazenamento para este caso, então a recomendação parte dos limites já citados:

| Camada | Uso | Formato |
|---|---|---|
| Padrão | Dev e projetos pequenos | **SQLite** (stdlib, zero dependências) em modo WAL. Uma linha por requisição e por nó; payloads em tabela separada, como JSON comprimido carregado sob demanda; TTL de expurgo e criptografia opcional |
| Intercâmbio | Tickets, CI, visualizador standalone | JSONL ou OTLP-JSON |
| Análise | Consultas agregadas | DuckDB lendo os exports, como leitor e não como armazenamento principal |
| Enterprise | APM do cliente | Exportação OTLP só da estrutura |

Uma linha de resumo (rota, status, duração, exceção, trace_id) deve ser gravada para **toda** requisição, mesmo quando a captura de payload ficou de fora da amostra. É o princípio da necessidade em prática: a lista de traces fica completa e o volume de dados sensíveis fica pequeno. O tamanho real de cada trace ainda é desconhecido e deve sair de benchmarks nas aplicações-alvo.

## Apache-2.0, DCO e um canvas React Flow embutido no wheel

### Licenças com restrição de uso custam adoção enterprise

Os precedentes de licenciamento são claros:

| Licença | Aprovada pela OSI | Precedente | Implicação para o EasyAPI |
|---|---|---|---|
| MIT | Sim | Extensão VS Code do AppMap ([GitHub getappmap](https://github.com/getappmap)) | Permissiva, mas **sem concessão de patente** |
| **Apache-2.0** | Sim | Exigida pela CNCF | Permissiva e com concessão de patente explícita ([choosealicense](https://choosealicense.com/licenses/); [CNCF](https://contribute.cncf.io/projects/lifecycle/)) |
| AGPL-3.0 | Sim | Grafana, Loki e Tempo desde 2021 | O próprio CEO admitiu a burocracia que ela cria nas empresas ([Grafana](https://grafana.com/blog/2021/04/20/qa-with-our-ceo-on-relicensing/)) |
| MIT + Commons Clause | Não | AppMap ([npm @appland/appmap](https://registry.npmjs.org/@appland/appmap/latest)) | Dispara revisão jurídica |
| Sustainable Use License | Não | n8n, que não se diz open source ([n8n docs](https://docs.n8n.io/sustainable-use-license/)) | Proíbe revenda e embarque |
| FSL | Não | Sentry, que vira Apache/MIT após dois anos ([Sentry](https://blog.sentry.io/sentry-is-now-fair-source)) | Modelo pensado para vendor com SaaS |

A recomendação é **Apache-2.0 para tudo**: agente, analisador, UI e exportadores. É permissiva o bastante para projetos pequenos e órgãos públicos, traz a concessão de patente que os departamentos jurídicos procuram e deixa aberto o caminho para a CNCF Sandbox, onde a entrada é uma issue no repositório `cncf/sandbox`, com votação do TOC e sem due diligence ([cncf/sandbox](https://github.com/cncf/sandbox)). A AGPL deve ser evitada sobretudo no agente, que roda dentro do processo da API do cliente; ali, a cláusula de uso em rede vira uma pergunta jurídica real. Se um dia houver camada comercial, com SSO, RBAC e auditoria avançados, ela deve viver em repositório separado, num modelo open-core que não contamine o núcleo. Para contribuições, o **DCO** é a escolha certa ([CERN OSPO](https://ospo.docs.cern.ch/recommendations/CLAs-and-DCOs)): é um sign-off leve, e a Apache-2.0 já licencia as contribuições recebidas com concessão de patente. Um CLA só faria sentido se a flexibilidade de relicenciar virasse requisito, e a comunidade costuma ler isso como sinal de que a licença vai mudar.

### Higiene de supply chain é o que a auditoria vai pedir

Equipes de segurança do setor elétrico e do governo vão avaliar o projeto pelos artefatos que o OpenSSF Scorecard mede em seus 20 checks ([Scorecard checks](https://github.com/ossf/scorecard/blob/main/docs/checks.md)). Assinaturas nos releases valem 8/10, e proveniência SLSA eleva a nota a 10/10. Um SBOM publicado como artefato do release atinge a nota máxima, e um SECURITY.md com canal de contato pontua. No PyPI, a **PEP 740** guarda atestações in-toto assinadas com Sigstore e ligadas ao Trusted Publishing. A action oficial de publicação da PyPA as gera por padrão; o `uv publish` sozinho não ([PEP 740](https://peps.python.org/pep-0740); [PyPI attestations](https://docs.pypi.org/attestations/)).

O checklist do primeiro dia começa pelos documentos: SECURITY.md com reporte privado de vulnerabilidades, CODE_OF_CONDUCT, GOVERNANCE.md e MAINTAINERS. No repositório, branch protection com revisão obrigatória, Dependabot ou Renovate, SAST, GitHub Actions fixadas por hash e tokens com privilégio mínimo. Na publicação, Trusted Publishing e um SBOM CycloneDX ou SPDX anexado a cada release, cobrindo também as dependências JavaScript da UI. Por fim, o badge do OpenSSF Best Practices.

### React Flow + ELK.js, com colapso por padrão

O **React Flow (`@xyflow/react`) é MIT e promete continuar MIT para sempre**; o plano Pro vende exemplos e suporte, não recursos ([reactflow.dev/pro](https://reactflow.dev/pro)). O n8n usa o irmão em Vue, o **Vue Flow** (MIT), com minimap, e faz o layout com `@dagrejs/dagre` ([n8n editor-ui package.json](https://github.com/n8n-io/n8n/blob/master/packages/frontend/editor-ui/package.json)). Seu canvas novo virou padrão para novos usuários na v1.70.0 e edita com fluidez "centenas de nós", embora dados de execução volumosos em memória ainda deixem o editor lento ([n8n community](https://community.n8n.io/t/help-us-test-the-new-n8n-canvas-beta/60070)).

Para o layout automático, o **ELK Layered** suporta portas e grafos compostos, com arestas que atravessam níveis de hierarquia ([ELK Layered](https://eclipse.dev/elk/reference/algorithms/org-eclipse-elk-layered.html)). Isso casa com as regiões aninhadas da IR e com as portas de argumento e retorno. O elkjs roda num Web Worker ([Stately: React Flow + ELK](https://prod.stately.ai/docs/packages/graph/react-flow-elk-pipeline)), e o dagre fica como fallback rápido para grafos grandes e planos. Sigma.js e o renderer WebGL do Cytoscape.js, ainda em preview, servem a uma visão panorâmica de call graphs com milhares de nós, não ao editor principal ([Cytoscape.js WebGL](https://blog.js.cytoscape.org/2025/01/13/webgl-preview/)). O JointJS fica de fora: é MPL-2.0 e guarda os recursos de escala na versão comercial ([JointJS license](https://www.jointjs.com/license)).

Nenhuma dessas bibliotecas publica limite de nós ou benchmarks. O guia de performance do React Flow recomenda memoização e o uso de `hidden` para colapsar subárvores ([React Flow performance](https://reactflow.dev/learn/advanced-use/performance)). Daí saem os padrões de UX. A visão padrão é colapsada e só com o código do projeto, escondendo frames de framework, porque ruído é o maior problema desse tipo de grafo. Loops viram um único nó com seletor de iteração, e payloads carregam sob demanda. Um inspetor lateral no estilo n8n mostra abas de Input e Output em Table, JSON e Schema ([n8n data pinning](https://docs.n8n.io/data/data-pinning/)). O caminho tomado fica destacado, e uma ação "copiar como fixture", análoga ao pinning do n8n, exporta a entrada capturada como fixture pytest.

### Zero CDN: a UI viaja dentro do pacote

O FastAPI carrega Swagger UI e ReDoc de uma CDN por padrão, e o uso offline exige servir os assets manualmente ([FastAPI custom docs assets](https://fastapi.tiangolo.com/how-to/custom-docs-ui-assets/)). É o exemplo a evitar em ambientes air-gapped. O `dagster-webserver` mostra o caminho oposto: distribui um wheel universal de ~12,1 MB e serve a própria UI ([PyPI dagster-webserver](https://pypi.org/project/dagster-webserver/1.13.6/)). O EasyAPI deve compilar a SPA com Vite no CI, incluir o `dist/` como package data e servi-lo num sub-app Starlette em `/_easyapi`. Deve oferecer ainda o comando `easyapi view trace.jsonl` e um export HTML de arquivo único para anexar a tickets. A web UI vem antes de qualquer plugin de IDE, seguindo a lição do Kolo e respondendo às queixas sobre extensões fechadas.

## Conclusão: o difícil não é rastrear, é costurar o estático ao dinâmico

A pesquisa muda o eixo do problema. Gravar chamadas, argumentos e retornos já é commodity: AppMap, VizTracer e Kolo fazem isso há anos. Desenhar fluxogramas por função também. Ninguém, porém, fez a **costura**. Ela exige IDs semânticos estáveis que sobrevivam a commits, um índice que leve cada evento do `sys.monitoring` ao nó certo de um grafo de regiões legível, e proveniência honesta em cada aresta, separando o que foi provado, inferido e observado. Esse é o ativo defensável do EasyAPI, e é ele que permite exportar para SARIF, OTel e agentes de IA via MCP, a direção para onde todo o mercado de observabilidade migra. O maior risco técnico não está no parsing. Está em atribuir eventos de branch a requisições concorrentes com overhead aceitável, um problema que nem o coverage.py resolveu sobre `sys.monitoring` e sem benchmark público. Por isso a primeira fase do projeto precisa medir, não entregar features.

Para o público-alvo brasileiro, a privacidade é o próprio produto. Concorrentes estrangeiros não trazem CPF e CNPJ, tratam redação como opcional e dependem de CDN ou SaaS. Um EasyAPI que nasce com captura redigida, retenção curta, auditoria, OIDC e operação air-gapped, sob Apache-2.0 e com higiene OpenSSF, entra em processos de compra do setor elétrico e do governo que AppMap, Kolo e os projetos FastAPI de 2026 não conseguem atender. E o mesmo `pip install` continua servindo, sem configuração, ao desenvolvedor solo. A janela está aberta, mas quatro projetos num único ano mostram que ela não vai durar.

## Arquitetura recomendada e roadmap faseado do MVP

### Visão geral dos componentes

O EasyAPI deve ser **um único código com dois modos**. No modo local, `pip install easyapi` + `easyapi.instrument(app)` liga tudo dentro do processo, com SQLite e UI em `/_easyapi`, sem configuração. No modo enterprise, os mesmos agentes enviam traces já redigidos a um servidor central com SSO, RBAC, auditoria e exportação OTLP. As duas metades, análise estática e gravação, se encontram em duas especificações versionadas, `easyapi.graph` e `easyapi.trace`, que formam o contrato estável entre linguagens.

```
+------------------------- Processo da aplicação (FastAPI) --------------------------+
|  easyapi.instrument(app)                                                           |
|   +- Middleware ASGI: amostragem por endpoint/header -> Recorder em ContextVar     |
|   +- Tool sys.monitoring: PY_START/RETURN/UNWIND, CALL, BRANCH*, JUMP, RAISE...    |
|   +- Redator: chaves, CPF/CNPJ, Luhn, JWT, SecretStr, limites -> ring buffer       |
|   +- Exportador assíncrono -> SQLite local | JSONL | OTLP (spans com code.*)       |
|   +- /_easyapi: UI React Flow + ELK.js servida do wheel, zero CDN                  |
+------------------------------------------------------------------------------------+
        ^ easyapi.graph (IR)                          | easyapi.trace (redigido)
        |                                             v
+-- easyapi analyze (subprocesso isolado) --+   +-- easyapi-server (opcional) --------+
| descoberta por importação + fallback AST  |   | agregação multi-worker/instância    |
| CFG de regiões (ast + beniget)            |   | OIDC/SSO, RBAC bruto x redigido     |
| resolução em camadas (+ LSP opcional)     |   | auditoria, retenção, cripto repouso |
| IDs estáveis, contentHash, índice posições|   | OTLP -> Collector do cliente        |
+-------------------------------------------+   +-------------------------------------+
```

| Pacote | Responsabilidade | Base técnica |
|---|---|---|
| `easyapi-spec` | JSON Schemas de `easyapi.graph/0.x` e `easyapi.trace/0.x`; exportadores SARIF `codeFlows` e OTLP | Inspirado em Joern, SARIF e SCIP |
| `easyapi` (núcleo Python) | Analisador, gravador, redator, armazenamento, servidor da UI, CLI (`analyze`, `view`, `export`) | `ast`, beniget/gast, `sys.monitoring`, SQLite, SDK OTel |
| `easyapi-ui` | Canvas, inspetor, lista de requisições, diff entre execuções | React, `@xyflow/react`, elkjs em Web Worker, dagre como fallback |
| `easyapi-server` | Coleta central, OIDC, RBAC, auditoria, retenção, expurgo | Mesmo núcleo; banco do servidor central ainda não pesquisado |
| `easyapi-agent-java` | `-javaagent` com ByteBuddy `Advice` + sondas ASM; analisador JavaParser | ByteBuddy, ASM, JavaParser (opção Apache) |
| `easyapi-node` | Plugin Babel/SWC + runtime `AsyncLocalStorage`; sidecar de análise TS | Babel, SWC, ts-morph → API do TS 7.1 |

A licença de cada dependência deve entrar na auditoria de release. As notas confirmam beniget/gast (BSD-3), React Flow (MIT), JavaParser (opção Apache), Babel e ts-morph (MIT); as demais, como elkjs, ByteBuddy, ASM e SWC, ainda precisam ser verificadas antes da primeira versão.

### Decisões de projeto que se fecham agora

O suporte a Python segue uma matriz clara. Do **3.12** em diante, o overlay é completo, com `BRANCH` no 3.12/3.13 e `BRANCH_LEFT`/`BRANCH_RIGHT` no 3.14+. Nos **3.10–3.11**, um modo degradado e documentado registra só funções, via `sys.setprofile`, e a reescrita de AST por import hook entra apenas se houver demanda real. A gravação filtra o código do usuário de forma estática, por code object, com `DISABLE` para todo o resto, e atribui cada evento à requisição de forma dinâmica, via `ContextVar`. A escolha entre manter os eventos sempre armados ou armá-los só durante requisições amostradas sai do benchmark da Fase 0, não de opinião. Valores são capturados como referências limitadas e serializados fora do caminho quente, nunca com `repr()`, e o modo `redacted` é o padrão.

Na análise, a descoberta de rotas por importação em subprocesso é sempre tentada primeiro, com fallback estático. O CFG é escrito em casa, toda aresta carrega proveniência e as arestas `unresolved` aparecem na UI em vez de sumir. No OTel, funções viram spans com `code.*`, branches e payloads ficam de fora por padrão, e o projeto publica uma configuração de referência do Collector com o redaction processor como segunda linha de defesa. Na governança, Apache-2.0, DCO e o checklist OpenSSF valem desde o primeiro commit público.

### Roadmap faseado

| Fase | Escopo | Entregáveis principais | Critério de saída |
|---|---|---|---|
| **0. Provas técnicas** | Eliminar a incógnita de overhead e validar a costura estático↔runtime | Protótipo do gravador em 3.12, 3.13 e 3.14 (inclusive free-threaded); mapeamento de branch via `co_positions` → nó do AST; protótipo do builder de CFG com as ~25 construções; benchmark num app FastAPI de referência (endpoints `async` e `def`, dependências com `yield`, `BackgroundTasks`) comparando eventos sempre armados com armar/desarmar | Overhead medido e publicado para requisições amostradas e não amostradas; suíte de testes de mapeamento sem nós órfãos; decisão documentada sobre a estratégia de armar; comportamento de exceção em callbacks testado |
| **1. MVP local para FastAPI** | O desenvolvedor vê toda a API e cada requisição, sem configuração | `easyapi.instrument(app)`; mapa estático de todos os endpoints (middleware, árvore `Depends`, CFG do handler, arestas de chamada com proveniência, exception handlers); gravação de 100% das requisições em dev; overlay do caminho tomado, ponto de parada por exceção e loops agregados com seletor de iteração; inspetor Input/Output; SQLite com TTL; redação padrão com CPF/CNPJ; UI no wheel, sem CDN; `easyapi view`; export HTML de arquivo único; Apache-2.0, DCO, SECURITY.md, Trusted Publishing com PEP 740, SBOM | Funciona sem ajustes em vários projetos FastAPI reais, incluindo os do próprio time; UI fluida num benchmark local de 500, 2.000 e 5.000 nós; nenhum asset externo carregado |
| **2. Produção segura e enterprise** | Rodar em produção no setor elétrico e no governo | Amostragem por endpoint e por header, limites por trace, amostragem na exportação, disjuntor, kill switch remoto; exportação OTLP com `code.*` e junção ao `traceparent`; `easyapi-server` com OIDC, RBAC bruto x redigido, auditoria imutável, retenção, criptografia em repouso e agregação multi-worker; reconhecedores CPF/CNPJ também para o Presidio; Collector de referência; adaptadores Flask, Django/DRF e Litestar, de baixo custo porque o gravador é o mesmo; Scorecard e badge OpenSSF | Overhead dentro de um orçamento acordado com usuários-piloto e verificado em carga; pacote de revisão de segurança (SBOM, atestações, SECURITY.md, relatório Scorecard) aceito por pelo menos um piloto; levantamento ANEEL/GSI concluído |
| **3. Java/Spring** | A mesma experiência para Spring Boot MVC | Agente ByteBuddy + ASM com `ThreadLocal` aberto no `DispatcherServlet` e executores embrulhados; descoberta via `RequestMappingHandlerMapping`/Actuator mais JavaParser estático; CFG de regiões em Java emitindo a mesma IR; overlay por linha | Overlay correto num app Spring de referência; overhead medido; WebFlux/Reactor como extensão posterior |
| **4. Node/Express/NestJS** | A mesma experiência para Node | Plugin Babel/SWC com contadores escrevendo no ALS e source maps; descoberta via `app.router.stack` (Express 5) e decorators (NestJS); sidecar TS em ts-morph, migrando para a API do TS 7.1 quando estável | Overlay correto em apps Express e NestJS de referência; throughput medido contra o baseline |
| **5. Ecossistema** | Durabilidade e distribuição | Servidor MCP e export legível por agentes; export SARIF `codeFlows`; "copiar como fixture pytest" e replay com span links; import opcional de grafos Joern/Fraunhofer CPG; overlays de IDE; candidatura à CNCF Sandbox | Comunidade de contribuidores além do time fundador; adoção por terceiros fora do círculo inicial |

### Riscos e perguntas em aberto

Quatro incógnitas podem mudar o plano e devem ser resolvidas na Fase 0 ou no início da Fase 2. A primeira é o custo real de manter CALL/RETURN/BRANCH ativos no código do usuário sob carga web, sem benchmark público. A segunda é o que acontece quando um callback do `sys.monitoring` levanta exceção, ainda não confirmado nas fontes. A terceira é o status do `co_branches()` e das mudanças do Python 3.15, que não foram pesquisadas. A quarta são as exigências regulatórias específicas da ANEEL, do GSI/PR e de nuvem de governo para ferramentas on-prem, para as quais não se encontrou fonte. Há ainda um risco de mercado: um dos projetos FastAPI de 2026 pode amadurecer, ou um fornecedor comercial pode lançar overlay de branches. A defesa é chegar primeiro com as duas coisas mais difíceis de copiar, a costura estático↔runtime bem feita e a camada de privacidade brasileira.
