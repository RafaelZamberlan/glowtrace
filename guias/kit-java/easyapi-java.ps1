# EasyAPI para Java - sobe a sua API Spring Boot com o EasyAPI, sem alterar o projeto.
#
# Rode DE DENTRO DA PASTA DO PROJETO (onde fica o pom.xml / build.gradle):
#
#   C:\easyapi\easyapi-java.ps1 jar target\minha-api.jar      # app empacotado (Maven ou Gradle)
#   C:\easyapi\easyapi-java.ps1 maven                         # mvn spring-boot:run (usa mvnw se existir)
#   C:\easyapi\easyapi-java.ps1 ide                           # mostra o texto para colar em "VM options" da IDE
#
# Opcoes do EasyAPI: -Porta 7070  -Pacotes com.empresa.app  -Fontes src\main\java  -Token <valor>
# Qualquer outro argumento vai para a sua aplicacao (ex.: --server.port=8081).
# Interface: http://127.0.0.1:<Porta>/_easyapi/
#
# Se o PowerShell bloquear scripts: Set-ExecutionPolicy -Scope Process Bypass

$ErrorActionPreference = "Stop"
$Porta = 7070; $Pacotes = ""; $Fontes = ""; $Token = ""
$pos = @(); $extra = @()
for ($i = 0; $i -lt $args.Count; $i++) {
    $a = [string]$args[$i]
    switch -Regex ($a) {
        '^-Porta$' { $Porta = [int]$args[++$i]; continue }
        '^-Pacotes$' { $Pacotes = [string]$args[++$i]; continue }
        '^-Fontes$' { $Fontes = [string]$args[++$i]; continue }
        '^-Token$' { $Token = [string]$args[++$i]; continue }
        default { if ($pos.Count -lt 2 -and -not $a.StartsWith("-")) { $pos += $a } else { $extra += $a } }
    }
}
$Modo = if ($pos.Count -gt 0) { $pos[0] } else { "" }
$Alvo = if ($pos.Count -gt 1) { $pos[1] } else { "" }

$jar = Join-Path $PSScriptRoot "easyapi-agent.jar"
if (-not (Test-Path $jar)) { Write-Host "Nao achei $jar (deixe este script na mesma pasta do easyapi-agent.jar)." -ForegroundColor Red; exit 1 }
if ($jar -match " ") { Write-Host "AVISO: o caminho do agente tem espaco ($jar). Prefira uma pasta sem espacos, ex.: C:\easyapi" -ForegroundColor Yellow }

# Java 17+ e obrigatorio na JVM que roda a API
if (Get-Command java -ErrorAction SilentlyContinue) {
    # java -version escreve no stderr; via cmd para o PowerShell 5.1 nao tratar como erro
    $ver = [string](cmd /c "java -version 2>&1" | Select-Object -First 1)
    if ($ver -match '"(\d+)(\.(\d+))?') {
        $major = [int]$Matches[1]; if ($major -eq 1) { $major = [int]$Matches[3] }
        if ($major -lt 17) { Write-Host "AVISO: java -version = $ver. O agente precisa de Java 17+ na JVM da API." -ForegroundColor Yellow }
    }
} elseif ($Modo -ne "ide") { Write-Host "AVISO: 'java' nao esta no PATH." -ForegroundColor Yellow }

$opts = @("port=$Porta")
if ($Pacotes) { $opts += "packages=$Pacotes" }
if ($Fontes) { $opts += "sources=$((Resolve-Path $Fontes).Path)" }
if ($Token) { $opts += "token=$Token" }
$agent = "-javaagent:$jar=" + ($opts -join ";")

if (-not (Test-Path "src\main\java") -and -not $Fontes) {
    Write-Host "AVISO: nao achei src\main\java aqui. Rode de dentro da pasta do projeto ou use -Fontes <pasta>." -ForegroundColor Yellow
}

switch ($Modo) {
    "jar" {
        if (-not $Alvo) { Write-Host "Informe o jar: easyapi-java.ps1 jar target\app.jar"; exit 2 }
        Write-Host "EasyAPI ligado. Interface: http://127.0.0.1:$Porta/_easyapi/" -ForegroundColor Green
        & java $agent -jar $Alvo @extra
        exit $LASTEXITCODE
    }
    "maven" {
        $mvn = if (Test-Path ".\mvnw.cmd") { ".\mvnw.cmd" } else { "mvn" }
        Write-Host "EasyAPI ligado. Interface: http://127.0.0.1:$Porta/_easyapi/" -ForegroundColor Green
        & $mvn spring-boot:run "-Dspring-boot.run.jvmArguments=$agent" @extra
        exit $LASTEXITCODE
    }
    "ide" {
        Write-Host "Cole isto em Run/Debug Configurations > VM options (IntelliJ) ou VM arguments (Eclipse):"
        Write-Host $agent
    }
    default {
        Write-Host "Uso: easyapi-java.ps1 jar <arquivo.jar> | maven | ide   [-Porta 7070] [-Pacotes x.y] [-Fontes pasta] [-Token valor]"
        exit 2
    }
}
