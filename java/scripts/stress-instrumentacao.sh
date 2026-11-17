#!/bin/sh
# Teste de estresse da instrumentação de bytecode do agente Java.
#
# Sobe um app Spring Boot instrumentando TAMBÉM bibliotecas grandes (Spring, Jackson, Hibernate,
# Tomcat, H2...): milhares de classes com todo tipo de bytecode. Qualquer erro de instrumentação
# aparece como ClassFormatError/VerifyError no carregamento.
#
# uso: java/scripts/stress-instrumentacao.sh <glowtrace-agent.jar> <app.jar> <pasta src/main/java> [porta-app]
# Esperado: "ClassFormatError/VerifyError: 0" e as requisições respondendo.
#
# Foi este teste que pegou o bug "bad offset for Uninitialized" (sonda antes de NEW): com o jar antigo
# o próprio carregador do Spring Boot quebra; com a correção, ~11 mil classes instrumentadas, 0 erros.
set -e
AGENT=$(cygpath -m "$1" 2>/dev/null || echo "$1")
APP="$2"
SRC=$(cygpath -m "$3" 2>/dev/null || echo "$3")
PORT=${4:-19966}
LOG=${TMPDIR:-/tmp}/glowtrace-stress.log
PKGS="org.springframework,com.fasterxml.jackson,org.hibernate,org.apache.catalina,org.apache.tomcat,org.apache.coyote,org.h2,org.mapstruct,io.swagger,org.springdoc"
java "-javaagent:$AGENT=port=7078;packages=$PKGS;sources=$SRC;debug=true" -jar "$APP" --server.port=$PORT > "$LOG" 2>&1 &
JPID=$!
for i in $(seq 1 180); do curl -s -o /dev/null "http://127.0.0.1:$PORT/" && break; kill -0 $JPID 2>/dev/null || break; sleep 1; done
sleep 3
echo "classes instrumentadas: $(grep -c 'glowtrace:debug\] instrumented' "$LOG" || true)"
echo "ClassFormatError/VerifyError: $(grep -cE 'ClassFormatError|VerifyError' "$LOG" || true)"
grep -oE '(ClassFormatError|VerifyError)[^)]{0,160}' "$LOG" | sort | uniq -c | sort -rn | head -5 || true
echo "erros de transformação: $(grep -c 'instrumenting ' "$LOG" || true)"
echo "log: $LOG  (o app continua rodando na porta $PORT; PID $JPID)"
