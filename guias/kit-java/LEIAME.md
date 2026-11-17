# EasyAPI para Java — kit portátil

Mapa visual de todas as rotas da sua API Spring Boot (estilo n8n) + gravação de cada requisição
mostrando o caminho que ela percorreu (métodos, `if/else`, loops, `try/catch`) e onde deu erro.
**Não altera nada no projeto**: entra como `-javaagent` na hora de subir a API.

## 1. Copie esta pasta para o outro PC

Coloque numa pasta **sem espaços no caminho**, por exemplo `C:\easyapi\` (Linux: `/opt/easyapi/`).

| Arquivo | O que é |
|---|---|
| `easyapi-agent.jar` | o EasyAPI inteiro (analisador + gravador + interface web, funciona offline) |
| `easyapi-java.ps1` / `easyapi-java.sh` | atalho para subir a API com o agente |
| `verificar.ps1` | confere se está funcionando |

Requisitos: **Java 17+** rodando a API, Spring MVC (Tomcat). Spring Boot 3 já usa Java 17.

## 2. Suba a API com o agente — de DENTRO da pasta do projeto

**Jeito mais direto** (qualquer app empacotado):

```powershell
cd C:\caminho\da\minha-api
java -javaagent:C:\easyapi\easyapi-agent.jar -jar target\minha-api.jar
```

Sem mais nada: rodando da pasta do projeto, o agente acha o `src\main\java` sozinho e descobre o pacote.

**Com o atalho:**

```powershell
cd C:\caminho\da\minha-api
C:\easyapi\easyapi-java.ps1 jar target\minha-api.jar   # app já empacotado
C:\easyapi\easyapi-java.ps1 maven                      # mvn spring-boot:run (usa mvnw se existir)
C:\easyapi\easyapi-java.ps1 ide                        # texto para colar em "VM options" do IntelliJ/Eclipse
```

(Se o PowerShell bloquear: `Set-ExecutionPolicy -Scope Process Bypass`.)
Gradle: gere o jar (`gradlew bootJar`) e use o modo `jar`.

> ⚠️ Não use `JAVA_TOOL_OPTIONS` com Maven/Gradle: o próprio Maven/Gradle também pegaria o agente e
> ocuparia a porta da interface. Use os modos acima.

## 3. Abra a interface

**http://127.0.0.1:7070/_easyapi/** → aba **Rotas** (o mapa). Faça requisições à API (Postman, curl,
front-end) e abra a aba **Execuções**. Botão **ir ao erro** pula para onde a requisição falhou.

```powershell
C:\easyapi\verificar.ps1        # resumo: rotas, execuções, erros internos
```

## 4. Opções

`C:\easyapi\easyapi-java.ps1 jar app.jar -Porta 7071 -Pacotes com.empresa.app -Fontes C:\proj\src\main\java -Token segredo`

| Opção | Quando usar |
|---|---|
| `-Porta` | a 7070 já está ocupada |
| `-Pacotes` | o pacote não foi detectado (vários módulos, por ex.) |
| `-Fontes` | você não está rodando de dentro da pasta do projeto |
| `-Token` | acessar a interface de outra máquina / de dentro de Docker (abra `/_easyapi/?token=<valor>`) |

Header `x-easyapi-trace: 0` numa requisição evita gravá-la.

## 5. Rodar os testes do projeto com o agente (opcional)

```powershell
mvn test "-DargLine=-javaagent:C:\easyapi\easyapi-agent.jar=port=7079"
```

Atenção: `-DargLine=` **substitui** o `argLine` que o `pom.xml` já define (memória, `--add-opens`,
jacoco...). Se o projeto define um, a contagem de testes pode mudar por causa disso, e não por causa do
EasyAPI. Para comparar com justiça, copie o `argLine` do pom e acrescente o `-javaagent:` no fim.
Compare `target\surefire-reports` das duas rodadas: os números devem ser iguais.

## 6. Problemas comuns

| Sintoma | Solução |
|---|---|
| `UnsupportedClassVersionError` ao subir | a API roda em Java < 17: use um JDK 17+ |
| `ClassFormatError` / `VerifyError` | bug de instrumentação do agente: mande a mensagem completa (classe e método) para corrigirmos. Enquanto isso, `mode=graph` sobe só o mapa |
| Interface não abre | porta ocupada (veja o log `[easyapi] UI: ...`) → `-Porta 7071` |
| 0 rotas na interface | não rodou da pasta do projeto → `-Fontes` e `-Pacotes` |
| Rotas aparecem mas sem execuções | o pacote em `-Pacotes` não é o do seu código |
| 403 na interface | acesso de outra máquina/Docker → `-Token` |

Limitações: não grava variáveis locais; o corpo vem do `@RequestBody` e do retorno do controller (o corpo
bruto não é lido); WebFlux, `@Async` e
`CompletableFuture` não são gravados. Dados sensíveis (senha, token, CPF/CNPJ, cartão, e-mail) são
mascarados antes de gravar — mesmo assim, não compartilhe prints com dados de pessoas.

## 7. Remover

Volte a subir a API do jeito normal (sem `-javaagent`). Nada foi alterado no projeto.
