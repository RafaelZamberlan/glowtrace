# Glowtrace — roteiro para um agente aplicar a lib num projeto

Este roteiro é para um agente de IA (ou pessoa) que vai **aplicar** o Glowtrace numa API existente e
provar que funciona. Leia junto com `01-guia-rapido-python.md` (ou `02-guia-rapido-java.md`).

## Regras (obrigatórias)

1. **Não modifique o código-fonte do Glowtrace** (github.com/RafaelZamberlan/glowtrace).
   Você é usuário da lib: instale o pacote pronto da Release e use. Se encontrar um bug ou limitação da
   lib, **não contorne editando a lib**: registre no relatório (passos para reproduzir, saída, versão).
2. **Projeto alvo: trabalhe isolado.** Se for repositório git, crie um branch novo (ex.: `feat/glowtrace`)
   — se houver alterações não commitadas na pasta, use `git worktree add ../<pasta>-glowtrace -b feat/glowtrace`
   para não mexer no trabalho em andamento. Nunca faça push. Não faça commit sem autorização do usuário.
3. **Prefira não mudar o código do projeto**: use a forma A (`python -m glowtrace run ...`) ou o
   `JAVA_TOOL_OPTIONS`. Só use a forma B (bloco opt-in com `GLOWTRACE_ENABLED=1`) se a A não for possível,
   e mantenha a mudança mínima e desligada por padrão.
4. **Nada de bancos/serviços compartilhados ou de produção.** Antes de subir o app, leia os nomes das
   variáveis de conexão (`.env`, `settings`, `docker-compose`) **sem imprimir valores secretos**.
   Aponte tudo para serviços locais descartáveis (ex.: `docker run postgres` em `127.0.0.1`) ou para
   endereços mortos (`127.0.0.1:9`) — o app ainda sobe e os caminhos de erro também são ótimos de visualizar.
   Atenção: `python-dotenv` **não** sobrescreve variáveis já definidas — defina as suas antes de subir.
5. Instale dependências num ambiente virtual **fora** do repositório ou numa pasta já ignorada pelo git;
   adicione `.glowtrace/` (banco das execuções) ao `.gitignore` se for criar arquivos no projeto.
6. Não envie dados do projeto para serviços externos.

## Passo a passo

### 1. Reconhecimento (sem alterar nada)
- Linguagem/framework: FastAPI/Starlette (Python) ou Spring Boot MVC (Java)? Flask/Django **não** são suportados — pare e reporte.
- Onde o objeto `app` é criado (`app = FastAPI(...)`), se há *factory* (`create_app()`), quantos routers.
- Versão do Python/JDK exigida (pyproject, Dockerfile, `.python-version`, `pom.xml`).
- Como o projeto sobe (README, Dockerfile, Makefile, docker-compose) e de quais serviços depende.
- Se há suíte de testes (pytest / JUnit) e como roda.

### 2. Ambiente
- Python: crie o venv com a versão certa, instale as dependências do projeto e depois
  `pip install "https://github.com/RafaelZamberlan/glowtrace/releases/download/v0.3.2/glowtrace-0.3.2-py3-none-any.whl"`.
- Java: baixe https://github.com/RafaelZamberlan/glowtrace/releases/latest/download/glowtrace-agent.jar (ou o kit https://github.com/RafaelZamberlan/glowtrace/releases/latest/download/glowtrace-java-kit.zip); não precisa compilar a lib.

### 3. Aplicar e subir
- Python, forma A (a partir da raiz do código, para `GLOWTRACE_ROOTS` ficar certo):
  `python -m glowtrace run uvicorn <modulo>:app --port <porta>`
  Se o código do app não estiver abaixo da pasta atual: `GLOWTRACE_ROOTS=<pasta do código>`.
- Java: `JAVA_TOOL_OPTIONS="-javaagent:<dist>/glowtrace-agent.jar=packages=<pacote raiz>;sources=<src/main/java>;port=7070"`.

### 4. Gerar tráfego variado
Faça requisições que passem por caminhos diferentes: sucesso, validação (4xx), não encontrado (404),
sem autenticação (401/403), erro interno (500, se existir), rotas com loops/listas. Se a API exige login,
use credenciais de teste que você mesmo criar no ambiente local (nunca credenciais reais).

### 5. Verificar
```bash
# baixe: https://github.com/RafaelZamberlan/glowtrace/releases/latest/download/verificar_glowtrace.py
python verificar_glowtrace.py http://127.0.0.1:<porta> --min-executions 1
# Java: a interface fica na porta do agente (padrão 7070)
```
Precisa terminar com `RESULTADO: OK`. Se houver um navegador disponível, abra a UI
(`/_glowtrace/`), abra uma execução com erro e use **ir ao erro**; tire screenshots.

### 6. Testes do projeto (se existirem) — prova de transparência
Python: rode a suíte **duas vezes** e compare teste a teste (ex.: `--junitxml`):
```bash
pytest --junitxml=sem.xml
GLOWTRACE_ROOTS=<código> GLOWTRACE_EXPOSE_HEADER=0 GLOWTRACE_STORE=memory GLOWTRACE_SELFCHECK=1 \
  pytest -p glowtrace.pytest_plugin --junitxml=com.xml
```
Esperado: mesmos testes passando/falhando nas duas rodadas, `0 internal errors` e
`0 unexplained transitions` no resumo do Glowtrace. Falhas que já existiam sem o Glowtrace não contam.

### 7. Relatório final (formato)

```
## Projeto
- caminho / branch / framework e versões / como subiu
## Aplicação
- forma usada (A/B/Java) e exatamente o que mudou no projeto (diff, se houver)
- variáveis de ambiente usadas (sem valores secretos) e como isolou bancos/serviços
## Resultado
- saída do verificar_glowtrace.py
- rotas mapeadas X/Y, funções no mapa, execuções gravadas (amostras: status, rota, nº de funções, erro)
- testes: sem Glowtrace vs com Glowtrace (passaram/falharam), regressões, selfcheck
- screenshots (se houver)
## Problemas encontrados
- bugs/limitações da lib com passos para reproduzir (sem ter editado a lib)
- dificuldades do guia (o que estava confuso ou faltando)
```

## Limitações conhecidas (não tente "corrigir")
- Flask/Django/WebSocket como fluxo: não suportado.
- Chamadas entre serviços (A chama B) aparecem como execuções separadas, uma em cada serviço.
- `if x: return y` numa única linha: o ramo tomado pode não ser distinguível.
- Java: sem variáveis locais nem corpo de request; só Spring MVC (sem WebFlux/`@Async`).
- Python 3.10/3.11 usam `sys.settrace`: conflita com debugger ativo.
