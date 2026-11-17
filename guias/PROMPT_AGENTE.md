# Prompt para um agente aplicar o EasyAPI

Copie o bloco abaixo e troque `<CAMINHO_DO_PROJETO>` pelo projeto onde a lib deve ser aplicada.

---

```text
Quero que você aplique a biblioteca EasyAPI no projeto <CAMINHO_DO_PROJETO> e prove que ela funciona na prática.

O que é o EasyAPI: uma lib que mapeia todas as rotas de uma API (FastAPI/Starlette em Python, ou Spring Boot em Java) como um fluxo visual estilo n8n — funções chamadas, if/else, loops, try/except — e grava cada requisição real mostrando o caminho percorrido, os valores e onde um erro parou o fluxo. A interface fica em /_easyapi/ da própria API (Python) ou numa porta própria (Java, padrão 7070).

Leia primeiro, nesta ordem:
1. https://github.com/RafaelZamberlan/easyapi/blob/main/guias/03-guia-para-agentes.md   (regras e passo a passo — siga à risca)
2. https://github.com/RafaelZamberlan/easyapi/blob/main/guias/01-guia-rapido-python.md  (se o projeto for Python)
   ou https://github.com/RafaelZamberlan/easyapi/blob/main/guias/02-guia-rapido-java.md  (se for Java)
Downloads (pacotes prontos): https://github.com/RafaelZamberlan/easyapi/releases/latest

Regras inegociáveis:
- NÃO modifique o código-fonte do EasyAPI. Você é usuário: instale o pacote pronto da Release e use. Se achar bug/limitação da lib, registre no relatório com passos para reproduzir — não contorne editando a lib.
- No projeto alvo, trabalhe num branch novo (ou num git worktree, se houver alterações não commitadas). Não faça push e não faça commit sem me perguntar.
- Prefira aplicar SEM mudar o código do projeto (python -m easyapi run ... ou -javaagent). Só altere código se não houver alternativa, com mudança mínima e desligada por padrão (EASYAPI_ENABLED=1).
- Nunca conecte em bancos/serviços compartilhados ou de produção. Leia apenas os NOMES das variáveis de conexão (não imprima segredos) e aponte tudo para serviços locais descartáveis ou endereços mortos em 127.0.0.1. Não envie dados do projeto para fora da máquina.
- Ambiente virtual/dependências fora do repositório ou em pasta ignorada pelo git.

Entregáveis:
1. A API rodando com o EasyAPI e o script de verificação terminando em "RESULTADO: OK":
   python verificar_easyapi.py http://127.0.0.1:<porta> --min-executions 1
   (script: https://github.com/RafaelZamberlan/easyapi/releases/latest/download/verificar_easyapi.py; no kit Java também há verificar.ps1)
2. Tráfego variado gravado (sucesso, 4xx, 401/403, 404, 500 se existir) e, se houver navegador disponível, screenshots da interface mostrando uma execução com erro ("ir ao erro").
3. Se o projeto tiver testes: rodar a suíte sem e com o EasyAPI (Python: `pytest -p easyapi.pytest_plugin`) e comparar teste a teste (devem ser idênticas; reportar "internal errors" e "unexplained transitions").
4. Um relatório no formato da seção "Relatório final" do guia para agentes, incluindo o que mudou no projeto (diff, se houver), comandos exatos para reproduzir, problemas encontrados na lib e o que estava confuso nos guias.
```
