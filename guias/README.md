# Guias do EasyAPI

| Arquivo | Para quem |
|---|---|
| [01-guia-rapido-python.md](01-guia-rapido-python.md) | aplicar em FastAPI/Starlette em 5 minutos (3 formas: sem código, opt-in, testes) |
| [02-guia-rapido-java.md](02-guia-rapido-java.md) | aplicar em Spring Boot via javaagent |
| [03-guia-para-agentes.md](03-guia-para-agentes.md) | roteiro completo com regras de segurança, verificação e formato de relatório |
| [PROMPT_AGENTE.md](PROMPT_AGENTE.md) | prompt pronto para entregar a outro agente |
| [verificar_easyapi.py](verificar_easyapi.py) | script de verificação (só stdlib) contra um app rodando |

Pacotes prontos para instalar (sem compilar nada):

Downloads em https://github.com/RafaelZamberlan/easyapi/releases/latest

- Python: `pip install "https://github.com/RafaelZamberlan/easyapi/releases/download/v0.1.1/easyapi_flow-0.1.1-py3-none-any.whl"`
- Java: https://github.com/RafaelZamberlan/easyapi/releases/latest/download/easyapi-agent.jar
- **Java para outro PC:** https://github.com/RafaelZamberlan/easyapi/releases/latest/download/easyapi-java-kit.zip (jar + atalhos
  `easyapi-java.ps1`/`.sh` + `verificar.ps1` + `LEIAME.md`; fontes do kit em `guias/kit-java/`)

Validação destes guias (feita do zero, num projeto FastAPI limpo e no demo Spring):
forma A (`python -m easyapi run`), forma B (opt-in), forma C (`pytest -p easyapi.pytest_plugin`) e
Java via `JAVA_TOOL_OPTIONS` — todas terminando em `RESULTADO: OK`.

Para regerar os pacotes (só quem mantém a lib): `cd ui && npm run build`, depois
`cd python && uv build --wheel -o ../dist`, e `java/easyapi-agent` → `mvn package` + copiar o jar para `dist/`.
