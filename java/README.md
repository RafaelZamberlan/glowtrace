# EasyAPI para Java (javaagent)

Backend Java do EasyAPI: um **javaagent** que, sem alterar o código da aplicação,

1. mapeia estaticamente (JavaParser) todos os endpoints Spring MVC em grafos de fluxo estilo n8n
   (if/else, laços, try/catch, switch, chamadas, return, throw);
2. grava cada requisição real (Byte Buddy): métodos executados, argumentos, retornos, exceções e o
   caminho de nós percorrido em cada função;
3. serve a mesma UI e o mesmo contrato HTTP/JSON do backend Python (`docs/IR.md`) num servidor
   embutido (`com.sun.net.httpserver`), em `http://127.0.0.1:7070/_easyapi/`.

```
java/
  easyapi-agent/   agente (jar único com Byte Buddy e JavaParser realocados)
  demo-loja/       app Spring Boot 3 de exemplo (loja em memória, espelha python/examples/loja)
```

## Compilar

Requer JDK 17+ e Maven 3.9+.

```bash
cd java/easyapi-agent
mvn -q package            # gera target/easyapi-agent.jar
```

A UI já compilada (`python/src/easyapi/_ui/`, saída do `npm run build` em `ui/`) é copiada para dentro
do jar no build. Se ela não existir, o agente serve uma página simples com links para a API JSON.

## Usar

```bash
java -javaagent:easyapi-agent.jar=packages=org.example.app;sources=/caminho/src/main/java;port=7070 \
     -jar app.jar
```

Depois abra `http://127.0.0.1:7070/_easyapi/`.

| opção (`chave=valor;...`) | variável de ambiente | padrão | descrição |
|---|---|---|---|
| `packages` | `EASYAPI_PACKAGES` | inferido de `sources` | pacotes instrumentados (separados por vírgula) |
| `sources` | `EASYAPI_SOURCES` | `./src/main/java` | raízes de código-fonte (separadas por vírgula) |
| `port` | `EASYAPI_PORT` | `7070` | porta do servidor da UI/API |
| `mode` | `EASYAPI_MODE` | `trace` | `trace` (mapa + gravação), `graph` (só mapa), `off` |
| `token` | `EASYAPI_TOKEN` | — | exige `X-EasyAPI-Token`, cookie `easyapi_token` ou `?token=` |
| `host` | `EASYAPI_HOST` | `127.0.0.1` (`0.0.0.0` com token) | endereço de bind |
| `root` | `EASYAPI_ROOT` | pai de `src/main/java` | raiz usada nos caminhos relativos dos `fn_id` |
| `title` | `EASYAPI_TITLE` | nome da pasta do projeto | título exibido na UI |
| `generated` | `EASYAPI_GENERATED` | `true` | também indexa `target/generated-sources` (interfaces OpenAPI, MapStruct) |
| `max_executions` | `EASYAPI_MAX_EXECUTIONS` | `500` | tamanho do buffer circular de execuções |
| `debug` | `EASYAPI_DEBUG` | `false` | logs detalhados |

Também valem propriedades de sistema (`-Deasyapi.port=7071`). Precedência: argumentos do agente >
propriedades > ambiente. Sem token, o servidor só escuta e só responde em loopback.

Uma requisição pode pedir para não ser gravada com o header `x-easyapi-trace: 0`. Cada resposta gravada
recebe o header `x-easyapi-execution: <id>` (desligue com `expose_header=false`).

Análise estática sem subir a aplicação (útil para depurar o mapa):

```bash
java -jar easyapi-agent.jar "sources=/caminho/src/main/java" summary|routes|map|functions
java -jar easyapi-agent.jar "sources=/caminho/src/main/java" function "src/main/java/a/B.java::B.metodo"
```

### Demo

```bash
cd java/demo-loja && mvn -q package
java -javaagent:../easyapi-agent/target/easyapi-agent.jar=packages=org.example.loja;sources=src/main/java \
     -jar target/demo-loja.jar
curl -X POST localhost:8080/pedidos -H 'Authorization: Bearer joao.x' -H 'Content-Type: application/json' \
     -d '{"cliente":"Ana","itens":[{"produto":"camiseta","qtd":2}],"cupom":"VIP"}'
curl localhost:8080/pedidos/99      # 404
curl localhost:8080/quebra          # 500 (exceção não tratada)
```

## Como funciona

- **Mapa** (`analysis/`): JavaParser lê os fontes; cada método vira um `FunctionFlow` com as mesmas regras do
  `flow.py` (passos agrupados, nós `call` para chamadas a código do projeto/bibliotecas, `if`, `loop`,
  `match`/`case` para `switch`, `try`/`except`/`finally`, `with` para try-with-resources e `synchronized`,
  `raise`, `return`, `break`, `continue`). Chamadas são resolvidas por tipo declarado (campos, parâmetros,
  variáveis locais, `this`, estáticos); interface com uma única implementação no projeto aponta para a
  implementação; repositórios Spring Data e tipos de bibliotecas viram `external` (`lib` = `spring`,
  `jakarta`, `jackson`...). Endpoints: `@RestController`/`@Controller` + `@Get/Post/Put/Delete/Patch/RequestMapping`,
  inclusive anotações herdadas de interfaces (ex.: interfaces geradas pelo OpenAPI Generator), constantes
  (`OwnersApi.PATH_X`) e placeholders `${prop:padrão}`. Filtros do projeto (`OncePerRequestFilter`,
  `Filter`, `HandlerInterceptor`) aparecem como middlewares.
- **Gravação** (`instrument/`, `runtime/`): Byte Buddy injeta *advice* em todo método das classes dos
  `packages` (argumentos na entrada, retorno/exceção na saída) e, via ASM, uma chamada `Rec.line(id, linha)`
  no início de cada linha e antes de cada `athrow`. A linha executada é convertida no nó do grafo pela tabela
  `linha → nó` (igual ao recorder Python). O escopo da requisição começa no `ApplicationFilterChain.doFilter`
  do Tomcat (ou `HttpServlet.service`, jakarta ou javax) mais externo da thread e termina na saída dele.
  Fora de uma requisição gravada, cada sonda custa só um `ThreadLocal.get()`.
- **Captura de valores** (`runtime/Capture.java`): nunca chama `toString`/getters de objetos arbitrários;
  objetos são lidos pelos campos declarados (`{"__type__": "Classe", ...}`), com limites de profundidade (4),
  itens (25), texto (400) e orçamento por valor; proxies Hibernate/CGLIB e coleções lazy não inicializadas
  não são tocados (`<LazyProxy X>`, `<LazyCollection>`). Redação igual à do Python: chaves sensíveis, JWT,
  Bearer, CPF/CNPJ com DV válido, cartões (Luhn), e-mails mascarados e headers sensíveis.

## Limitações conhecidas

- `values` (valores de variáveis locais por nó: `watch`/`assigns`) fica vazio: o agente grava argumentos,
  retornos e exceções, mas não lê variáveis locais. `watch`/`assigns` continuam presentes no grafo.
- O campo `overlay` da execução não é enviado (a UI calcula).
- Corpos de requisição/resposta não são capturados (`body: null`); headers, query e path params sim.
- Só Spring MVC/servlet (thread por requisição). WebFlux, `@Async`, `CompletableFuture` e outras threads não
  são gravados (o código roda fora do escopo da requisição).
- Getters/setters triviais, `equals`, `hashCode` e `toString` não viram frames (como acesso a atributo no
  Python); construtores e inicializadores estáticos também não.
- Resolução de chamadas é heurística (sem resolução completa de tipos/genéricos): cadeias fluentes e `var`
  sem inicializador explícito podem ficar `unresolved`; interfaces com várias implementações apontam para o
  método da interface (o caminho real aparece nas arestas observadas).
- Exceções tratadas pelo Spring antes de chegar a código do projeto (ex.: erro de conversão de path
  param) não geram `error` na execução, só o `status`.
- Mapeamento runtime → `fn_id` é por classe + nome do método + número de parâmetros: sobrecargas com o
  mesmo número de parâmetros usam a primeira.
- Lambdas são atribuídas ao método que as declara; classes anônimas/locais não viram frames.
- O jar exclui as classes multi-release de Java 24+ do Byte Buddy (opcionais) para não vazar
  `net.bytebuddy` não realocado no classpath da aplicação.

## Testado com

- `demo-loja` (Spring Boot 3.5, Tomcat 10.1, Java 17).
- [spring-petclinic-rest](https://github.com/spring-petclinic/spring-petclinic-rest) (Spring Boot 4.1,
  Tomcat 11, Hibernate, H2): 118 arquivos, 721 funções, 3134 nós, 37 rotas (todas vindas de interfaces
  geradas pelo OpenAPI Generator); 24 requisições variadas gravadas, 22 associadas à rota, 481 frames,
  sem erros internos.
