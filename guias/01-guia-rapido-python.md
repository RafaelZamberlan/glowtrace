# Glowtrace — guia rápido (Python / FastAPI / Starlette)

Em 5 minutos: mapa visual de todas as rotas da sua API (estilo n8n) + gravação de cada requisição
mostrando por onde ela passou (funções, `if/else`, loops, `try/except`, valores e o ponto do erro).

> Você **usa** a lib; não precisa (nem deve) mexer no código-fonte dela.

---

## 1. Requisitos

- Python **3.10+** (3.12+ recomendado: tracing com `sys.monitoring`, custo menor)
- App **FastAPI** ou **Starlette** (qualquer versão do FastAPI de 0.95 em diante)

## 2. Instalar (no ambiente virtual do SEU projeto)

```bash
pip install "https://github.com/RafaelZamberlan/glowtrace/releases/download/v0.3.1/glowtrace-0.3.1-py3-none-any.whl"
# ou com uv:
uv pip install "https://github.com/RafaelZamberlan/glowtrace/releases/download/v0.3.1/glowtrace-0.3.1-py3-none-any.whl"
```

O pacote se chama `glowtrace` e é importado como `glowtrace`.

Única dependência: `starlette` (que o FastAPI já traz). A interface web vem dentro do pacote (funciona offline).

## 3. Aplicar — escolha UMA forma

### A) Sem mudar nenhuma linha do projeto (recomendado para testar)

Troque o comando que sobe o servidor, prefixando com `python -m glowtrace run`:

```bash
# antes:  uvicorn app.main:app --reload --port 8000
python -m glowtrace run uvicorn app.main:app --port 8000

# também funciona chamando o Python explicitamente:
python -m glowtrace run python -m uvicorn app.main:app --port 8000
```

Rode **a partir da raiz do projeto** (o Glowtrace considera "código do app" tudo que está abaixo da pasta
atual — ver `GLOWTRACE_ROOTS` abaixo).

### B) Uma linha no código, ligada só quando você quiser (para deixar no projeto)

No arquivo onde o `app` é criado, **depois** de todos os `include_router` / `add_middleware`:

```python
import os

if os.getenv("GLOWTRACE_ENABLED") == "1":
    from glowtrace import Glowtrace

    Glowtrace(app)
```

e suba com `GLOWTRACE_ENABLED=1` (PowerShell: `$env:GLOWTRACE_ENABLED="1"`). Sem a variável, nada muda.

Se o app é criado por uma *factory* (`def create_app(): ...`), coloque o bloco dentro dela, logo antes do `return app`.

### C) Na suíte de testes (grava cada requisição que os testes fazem)

```bash
GLOWTRACE_EXPOSE_HEADER=0 GLOWTRACE_STORE=memory GLOWTRACE_SELFCHECK=1 pytest -p glowtrace.pytest_plugin
```

Ao final o pytest imprime algo como
`glowtrace: 3 apps instrumented, 412 executions stored, 0 internal errors` e
`glowtrace selfcheck: 1840 frames, 0 unexplained transitions ...`.
Os testes devem passar exatamente como sem o plugin (o Glowtrace é transparente).

## 4. Ver

1. Abra **http://127.0.0.1:8000/_glowtrace/** (mesma porta da API).
2. Aba **Rotas** → clique numa rota: pipeline (request → middlewares → `Depends` → endpoint) e o fluxo da
   função; clique em **+** num nó de chamada para entrar na função chamada.
3. Faça requisições à API (curl, navegador, Swagger, front-end). Cada resposta gravada traz o header
   `x-glowtrace-execution: <id>`.
4. Aba **Execuções** → clique numa execução: o caminho real aceso, nós não executados apagados, o nó do
   erro em vermelho (botão **ir ao erro**). Clique num nó para ver entrada/saída/valores.
5. **Mapa da API** (topo): visão de todas as funções e chamadas; use o filtro.
6. **ao vivo** (topo direito): segue a requisição mais recente automaticamente.

## 5. Configuração (variáveis de ambiente)

| Variável | Padrão | Para quê |
|---|---|---|
| `GLOWTRACE_MODE` | `trace` | `graph` = só mapa (custo zero), `trace` = mapa + gravação, `off` |
| `GLOWTRACE_ROOTS` | pasta atual | pasta(s) do código do app (separe com `;` no Windows, `:` no Linux) |
| `GLOWTRACE_SAMPLE` | `1.0` | fração de requisições gravadas (ex.: `0.05`) |
| `GLOWTRACE_TOKEN` | — | exige token para abrir `/_glowtrace` fora do localhost |
| `GLOWTRACE_ALLOW_REMOTE` | `0` | `1` libera acesso remoto sem token (não use fora de dev) |
| `GLOWTRACE_STORE` / `GLOWTRACE_DB` | `sqlite` / `.glowtrace/glowtrace.db` | onde guardar execuções (`memory` = só RAM) |
| `GLOWTRACE_EXPOSE_HEADER` | `1` | `0` não adiciona o header `x-glowtrace-execution` |
| `GLOWTRACE_ENABLED` | — | `0` desliga tudo |
| `GLOWTRACE_REPLAY` | `0` | `1` libera **Reenviar / Editar e reenviar** na UI (só em desenvolvimento) |
| `GLOWTRACE_MAX_DEPTH` | `8` | níveis de objetos aninhados abertos (até 200) |
| `GLOWTRACE_MAX_ITEMS` | `25` | itens de lista / campos de objeto mostrados |
| `GLOWTRACE_MAX_VALUES` | `400` | valores lidos por captura, somando todos os níveis |
| `GLOWTRACE_MAX_STR` | `400` | caracteres guardados de cada texto |

Header por requisição: `X-Glowtrace-Trace: 1` força gravar (útil com amostragem baixa), `0` não grava.

**Reenviar uma requisição** (com `GLOWTRACE_REPLAY=1`): abra a execução → **Requisição** → *Reenviar* ou
*Editar e reenviar* (método, caminho, query, headers, corpo). O código roda de verdade (banco, e-mails,
chamadas externas); valores redigidos na gravação (tokens, senhas, CPF) precisam ser digitados de novo.
A requisição reenviada chega com o header `X-Glowtrace-Replay`; para pular efeitos colaterais:

```python
import glowtrace

if not glowtrace.is_replay():
    enviar_email(pedido)
```

*Copiar como* (cURL, HTTPie, Python requests, fetch) funciona sempre, mesmo sem `GLOWTRACE_REPLAY`.

## 6. Segurança (leia antes de usar com dados reais)

- `/_glowtrace` só responde para **localhost** por padrão. Em Docker/WSL/proxy o acesso vem de outro IP
  → defina `GLOWTRACE_TOKEN` e abra `http://host:porta/_glowtrace/?token=<valor>` uma vez (vira cookie).
- Valores capturados passam por redação **antes** de gravar: senhas, tokens, cookies, `Authorization`,
  CPF/CNPJ (com dígito verificador), cartões, JWT; e-mails são mascarados. Mesmo assim, trate o banco
  `.glowtrace/` como dado sensível: **adicione `.glowtrace/` ao `.gitignore` do projeto**.
- Em produção: `GLOWTRACE_MODE=graph`, ou `trace` com `GLOWTRACE_SAMPLE` baixo + `GLOWTRACE_TOKEN`.

## 7. Problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| `/_glowtrace` dá **403** | acesso não-localhost (Docker, WSL, outra máquina) | `GLOWTRACE_TOKEN=...` e `?token=` na URL |
| `/_glowtrace` dá **404** | Glowtrace não foi instalado no app | confira forma A/B; no B, `GLOWTRACE_ENABLED=1` |
| Rotas aparecem mas **sem funções** / execuções com 0 funções | `GLOWTRACE_ROOTS` não aponta para o código | rode da raiz do projeto ou `GLOWTRACE_ROOTS=<pasta do código>` |
| Requisição sem header `x-glowtrace-execution` | `GLOWTRACE_MODE=graph`, amostragem, rota ignorada (`/docs`, `/openapi.json`), `OPTIONS` | ajuste modo/amostragem ou mande `X-Glowtrace-Trace: 1` |
| Debugger do VS Code/PyCharm parou de funcionar (Python 3.10/3.11) | os dois usam `sys.settrace` | use Python 3.12+ ou rode sem debugger |
| `ModuleNotFoundError: glowtrace` no modo A | wheel instalado em outro ambiente | instale no mesmo venv que roda o servidor |
| Vários workers (`gunicorn -w 4`) | cada processo grava separado | use o SQLite padrão, que todos compartilham pelo arquivo (ainda não validado sob carga) |

Ainda **não** suportado: Flask, Django, WebSockets como fluxo, chamadas entre serviços ligadas numa
mesma execução (cada serviço mostra a sua).

## 8. Conferir que está tudo certo

```bash
# baixe o script: https://github.com/RafaelZamberlan/glowtrace/releases/latest/download/verificar_glowtrace.py
python verificar_glowtrace.py http://127.0.0.1:8000 --min-executions 1
```

## 9. Remover

Forma A: volte ao comando antigo. Forma B: apague o bloco (ou só não defina `GLOWTRACE_ENABLED`).
Depois `pip uninstall glowtrace` e apague a pasta `.glowtrace/`.
