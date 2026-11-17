# Validação do POC numa API interna real

> Nomes de clientes, repositórios, endereços e configurações foram omitidos desta versão pública.

## 1. Ambiente e isolamento

| Item | Como |
|---|---|
| Sistema alvo | monorepo com **dois serviços FastAPI** (uma API de negócio e um serviço de autenticação) |
| Isolamento git | `git worktree` num branch novo; o branch de trabalho (com alterações locais não commitadas) **não foi tocado** |
| Mudança no código alvo | 7 linhas no fim de cada `main.py`, **opt-in** (`GLOWTRACE_ENABLED=1`); sem a variável nada muda |
| Python | 3.11 (igual à imagem Docker do projeto) → backend `sys.settrace` |
| FastAPI | API de negócio 0.135 (pinado); autenticação 0.162 (formato novo `_IncludedRouter`) |
| Rede | um script de execução força **todas** as conexões (bancos, cache, provedor de identidade, servidor de mapas, LLM, arquivos) para `127.0.0.1` em porta morta **antes** de importar o app. Os `.env` versionados do projeto apontavam para bancos compartilhados — `python-dotenv` não sobrescreve variáveis já definidas, então nunca foram usados. Nenhum banco/serviço real foi contatado. |

## 2. Mapa estático

| | serviço de autenticação | API de negócio |
|---|---|---|
| Rotas descobertas | 28 / 28 | 132 / 132 |
| Middlewares | CORS (lib) + 1 de usuário | CORS (lib) + 2 de usuário (1 classe) |
| `Depends` | 0 | 8 |
| Funções alcançáveis mapeadas | 79 | **746** |
| Arestas de chamada user→user | 82 | 1.142 |
| Nós de fluxo | 1.062 | 8.548 |
| Desvios (if / loop / try / match) | 232 | 1.930 |
| Tempo do mapa completo (frio) | 0,23 s | **0,77 s** |

Erros de análise: nenhum. A API importa o mesmo arquivo sob dois nomes de módulo; como o id de
função é baseado no **arquivo**, não houve duplicação.

## 3. Execuções reais gravadas

Com as dependências externas indisponíveis, as próprias regras das APIs produziram 400/401/502/503 —
ótimos para visualizar caminhos de erro. Exemplos (resumidos):

- **validação de token** (cookie JWT de teste): middleware de autenticação → handler → função de
  validação → chamada HTTP ao provedor de identidade → `except` → `raise HTTPException(400)`; o botão
  "ir ao erro" leva à linha exata.
- **configuração de projeto**: middleware de contexto → verificação de rota global (false) →
  normalização da chave do projeto → autenticação → chamada ao serviço de auth → `AuthenticationError`.
- **rota sem cabeçalho obrigatório**: o middleware recusa com 400 antes de chegar ao handler.

Tokens apareceram como `[JWT]` em argumentos e retornos; `cookie`/`authorization` como `[REDACTED]`.

## 4. Bugs encontrados pela validação real (todos corrigidos, com teste de regressão)

1. FastAPI ≥ 0.16x guarda routers incluídos de forma lazy (`_IncludedRouter`) → rotas sem path.
2. `return await ...` marcado como exceção no Python 3.11 (`StopIteration` do protocolo de corrotinas).
3. Tracer global custava mesmo sem gravar (3.11) → ligado só durante requisições gravadas.
4. Mesmo problema no `sys.monitoring` (3.12+) → eventos ligados sob demanda.
5. Mapa frio lento (busca de módulo por arquivo varria ~3.000 módulos) → índice em cache.

## 5. Desempenho

Pior caso (100% CPU, ~500 nós visitados): requisição gravada ≈ +1,7 ms; não gravada ≈ ruído.
Em endpoints com I/O o custo é imperceptível. Ver tabela no README.

## 6. Limitações observadas

- `if x: return y` numa única linha: o ramo tomado pode não ser distinguível (Python 3.14
  `BRANCH_LEFT/RIGHT` resolve).
- Chamadas entre os dois serviços aparecem como execuções separadas; falta propagar `traceparent`.
- `self.x.metodo()` com `self.x` atribuído no `__init__` fica "não resolvido" no mapa estático (o
  runtime mostra a chamada real).
