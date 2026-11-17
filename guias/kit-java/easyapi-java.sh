#!/usr/bin/env sh
# EasyAPI para Java (Linux/macOS/Git Bash). Rode DE DENTRO DA PASTA DO PROJETO:
#   /opt/easyapi/easyapi-java.sh jar target/minha-api.jar
#   /opt/easyapi/easyapi-java.sh maven
#   /opt/easyapi/easyapi-java.sh ide
# Variaveis opcionais: EASYAPI_PORT=7070 EASYAPI_PACKAGES=com.empresa.app EASYAPI_SOURCES=src/main/java EASYAPI_TOKEN=...
set -e
DIR=$(cd "$(dirname "$0")" && pwd)
JAR="$DIR/easyapi-agent.jar"
[ -f "$JAR" ] || { echo "Nao achei $JAR"; exit 1; }
OPTS="port=${EASYAPI_PORT:-7070}"
[ -n "$EASYAPI_PACKAGES" ] && OPTS="$OPTS;packages=$EASYAPI_PACKAGES"
[ -n "$EASYAPI_SOURCES" ] && OPTS="$OPTS;sources=$(cd "$EASYAPI_SOURCES" && pwd)"
[ -n "$EASYAPI_TOKEN" ] && OPTS="$OPTS;token=$EASYAPI_TOKEN"
AGENT="-javaagent:$JAR=$OPTS"
echo "EasyAPI ligado. Interface: http://127.0.0.1:${EASYAPI_PORT:-7070}/_easyapi/"
MODE=${1:-}; [ $# -gt 0 ] && shift
case "$MODE" in
  jar)   APP=$1; shift; exec java "$AGENT" -jar "$APP" "$@" ;;
  maven) MVN=mvn; [ -x ./mvnw ] && MVN=./mvnw; exec $MVN spring-boot:run "-Dspring-boot.run.jvmArguments=$AGENT" "$@" ;;
  ide)   echo "VM options:"; echo "$AGENT" ;;
  *)     echo "Uso: easyapi-java.sh jar <arquivo.jar> | maven | ide"; exit 2 ;;
esac
