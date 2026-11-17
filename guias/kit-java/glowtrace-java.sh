#!/usr/bin/env sh
# Glowtrace para Java (Linux/macOS/Git Bash). Rode DE DENTRO DA PASTA DO PROJETO:
#   /opt/glowtrace/glowtrace-java.sh jar target/minha-api.jar
#   /opt/glowtrace/glowtrace-java.sh maven
#   /opt/glowtrace/glowtrace-java.sh ide
# Variaveis opcionais: GLOWTRACE_PORT=7070 GLOWTRACE_PACKAGES=com.empresa.app GLOWTRACE_SOURCES=src/main/java GLOWTRACE_TOKEN=...
set -e
DIR=$(cd "$(dirname "$0")" && pwd)
JAR="$DIR/glowtrace-agent.jar"
[ -f "$JAR" ] || { echo "Nao achei $JAR"; exit 1; }
OPTS="port=${GLOWTRACE_PORT:-7070}"
[ -n "$GLOWTRACE_PACKAGES" ] && OPTS="$OPTS;packages=$GLOWTRACE_PACKAGES"
[ -n "$GLOWTRACE_SOURCES" ] && OPTS="$OPTS;sources=$(cd "$GLOWTRACE_SOURCES" && pwd)"
[ -n "$GLOWTRACE_TOKEN" ] && OPTS="$OPTS;token=$GLOWTRACE_TOKEN"
AGENT="-javaagent:$JAR=$OPTS"
echo "Glowtrace ligado. Interface: http://127.0.0.1:${GLOWTRACE_PORT:-7070}/_glowtrace/"
MODE=${1:-}; [ $# -gt 0 ] && shift
case "$MODE" in
  jar)   APP=$1; shift; exec java "$AGENT" -jar "$APP" "$@" ;;
  maven) MVN=mvn; [ -x ./mvnw ] && MVN=./mvnw; exec $MVN spring-boot:run "-Dspring-boot.run.jvmArguments=$AGENT" "$@" ;;
  ide)   echo "VM options:"; echo "$AGENT" ;;
  *)     echo "Uso: glowtrace-java.sh jar <arquivo.jar> | maven | ide"; exit 2 ;;
esac
