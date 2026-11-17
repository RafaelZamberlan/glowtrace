# Glowtrace — guia rápido (Java / Spring Boot)

Mesmo resultado do Python (mapa de rotas + gravação de cada requisição, mesma interface), via
**javaagent**: nenhuma linha do projeto muda.

## 1. Requisitos

- JDK **17+**, app **Spring Boot** com Spring MVC (servlet / Tomcat)
- O código-fonte do app no disco (o mapa é montado lendo `src/main/java`)

## 2. O agente

Baixe o arquivo pronto (não precisa compilar nada) para uma pasta sem espaços, ex. `C:\glowtrace\`:
https://github.com/RafaelZamberlan/glowtrace/releases/latest/download/glowtrace-agent.jar

Ou o kit completo (jar + atalhos + LEIAME): https://github.com/RafaelZamberlan/glowtrace/releases/latest/download/glowtrace-java-kit.zip

## 3. Aplicar — escolha uma forma

```bash
# jar empacotado
java "-javaagent:C:/glowtrace/glowtrace-agent.jar=packages=com.minhaempresa.app;sources=C:/caminho/do/projeto/src/main/java" -jar target/app.jar

# Maven
mvn spring-boot:run "-Dspring-boot.run.jvmArguments=-javaagent:C:/glowtrace/glowtrace-agent.jar=packages=com.minhaempresa.app;sources=src/main/java"

# java -jar / script / container: variável de ambiente lida pela JVM
JAVA_TOOL_OPTIONS="-javaagent:C:/glowtrace/glowtrace-agent.jar=packages=com.minhaempresa.app;sources=C:/caminho/src/main/java"
```

> ⚠️ **Não** use `JAVA_TOOL_OPTIONS` com `mvn`/`gradle`: a JVM do próprio Maven/Gradle também carrega o
> agente e ocupa a porta da interface antes do app. Use `-Dspring-boot.run.jvmArguments` (Maven) ou
> gere o jar e rode com `java -javaagent:... -jar` (Gradle). Na IDE, cole o `-javaagent:...` em "VM options".

**Para outro PC:** use o kit portátil https://github.com/RafaelZamberlan/glowtrace/releases/latest/download/glowtrace-java-kit.zip
(jar + atalhos + `LEIAME.md`). Rodando de dentro da pasta do projeto, basta
`java -javaagent:C:\glowtrace\glowtrace-agent.jar -jar target\app.jar` — o agente acha `src/main/java` e o pacote sozinho.

- `packages` = pacote raiz do **seu** código (o que será instrumentado). Ex.: `org.springframework.samples.petclinic`.
- `sources` = pasta `src/main/java` do projeto (caminho absoluto é mais seguro).
- No PowerShell, coloque o argumento `-javaagent:...` entre aspas por causa do `;`.

## 4. Ver

A interface sobe numa **porta própria**: **http://127.0.0.1:7070/_glowtrace/** (troque com `port=7071`
no argumento do agente). Faça requisições à API e abra a aba **Execuções**.

## 5. Opções (dentro do argumento, `chave=valor;chave=valor`)

| Opção | Padrão | Para quê |
|---|---|---|
| `packages` | inferido de `sources` | pacotes instrumentados (vírgula separa vários) |
| `sources` | `./src/main/java` | código-fonte para o mapa |
| `port` | `7070` | porta da interface |
| `mode` | `trace` | `graph` (só mapa), `trace`, `off` |
| `token` | — | exige token para acesso fora do localhost |
| `generated` | `true` | também lê `target/generated-sources` (interfaces OpenAPI, MapStruct) |
| `max_executions` | `500` | execuções guardadas em memória |
| `max_depth` | `8` | níveis de objetos aninhados abertos (até 200) |
| `max_items` | `25` | itens de lista / campos de objeto mostrados (até 10000) |
| `max_values` | `400` | valores lidos por captura, somando todos os níveis (até 1000000) |
| `max_str` | `400` | caracteres guardados de cada texto |

Cada opção também vale como `-Dglowtrace.<opção>=…` ou variável `GLOWTRACE_<OPÇÃO>` (ex.: `GLOWTRACE_MAX_DEPTH=20`).
Quando um valor aparece como **não aberto** ou **cortado** na interface, passe o mouse: a dica diz qual limite atuou.
Limites maiores deixam cada execução maior (memória e tela); aumente só o necessário.

Header `x-glowtrace-trace: 0` numa requisição evita gravá-la.

## 6. Limitações atuais

- Não captura variáveis locais (argumentos, retornos e exceções sim).
- Valores lidos: POJOs/records do projeto, coleções, `Optional`, `ResponseEntity`, `ProblemDetail`, `Page`/`Slice`,
  `PageRequest`/`Sort`, `HttpHeaders`, `MediaType`, JSON do Jackson 2/3 e do Gson, `CompletableFuture` já concluído,
  `Authentication`/`Jwt` do Spring Security (com senha/token redigidos), `BindingResult`, `java.time`, `UUID`...
  **Não abertos de propósito** (aparecem como "não aberto"): `Stream`/`Iterator` (ler consumiria), coleções JPA
  ainda não carregadas, proxies, beans do Spring e `Iterable` próprio sem campos.
- Corpo: reconstruído do parâmetro `@RequestBody` e do retorno do controller (já com redação); o corpo bruto
  não é lido, então requisições que falham antes do controller (ex.: JSON inválido) aparecem como "não capturado".
- Só Spring MVC/servlet: WebFlux, `@Async` e `CompletableFuture` não são gravados.
- Validação feita pelo Spring antes do seu código (ex.: `@Valid` falhando) aparece só como status 4xx.
- *Reenviar / Editar e reenviar* ainda não existe no agente Java (os botões aparecem desabilitados);
  *Copiar como* cURL/HTTPie/requests/fetch funciona.

## 7. Conferir

```bash
# no kit: C:\glowtrace\verificar.ps1   |   ou, com Python: https://github.com/RafaelZamberlan/glowtrace/releases/latest/download/verificar_glowtrace.py
python verificar_glowtrace.py http://127.0.0.1:7070 --min-executions 1
```
