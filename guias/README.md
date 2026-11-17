# Guias do Glowtrace

| Arquivo | Para quem |
|---|---|
| [01-guia-rapido-python.md](01-guia-rapido-python.md) | aplicar em FastAPI/Starlette em 5 minutos (3 formas: sem código, opt-in, testes) |
| [02-guia-rapido-java.md](02-guia-rapido-java.md) | aplicar em Spring Boot via javaagent |
| [03-guia-para-agentes.md](03-guia-para-agentes.md) | roteiro completo com regras de segurança, verificação e formato de relatório |
| [PROMPT_AGENTE.md](PROMPT_AGENTE.md) | prompt pronto para entregar a outro agente |
| [verificar_glowtrace.py](verificar_glowtrace.py) | script de verificação (só stdlib) contra um app rodando |

Pacotes prontos para instalar (sem compilar nada):

Downloads em https://github.com/RafaelZamberlan/glowtrace/releases/latest

- Python: `pip install "https://github.com/RafaelZamberlan/glowtrace/releases/download/v0.3.2/glowtrace-0.3.2-py3-none-any.whl"`
- Java: https://github.com/RafaelZamberlan/glowtrace/releases/latest/download/glowtrace-agent.jar
- **Java para outro PC:** https://github.com/RafaelZamberlan/glowtrace/releases/latest/download/glowtrace-java-kit.zip (jar + atalhos
  `glowtrace-java.ps1`/`.sh` + `verificar.ps1` + `LEIAME.md`; fontes do kit em `guias/kit-java/`)

Validação destes guias (feita do zero, num projeto FastAPI limpo e no demo Spring):
forma A (`python -m glowtrace run`), forma B (opt-in), forma C (`pytest -p glowtrace.pytest_plugin`) e
Java via `JAVA_TOOL_OPTIONS` — todas terminando em `RESULTADO: OK`.

Para regerar os pacotes (só quem mantém a lib): `cd ui && npm run build`, depois
`cd python && uv build --wheel -o ../dist`, e `java/glowtrace-agent` → `mvn package` + copiar o jar para `dist/`.
