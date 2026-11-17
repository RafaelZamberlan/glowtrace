# Confere se o EasyAPI esta funcionando (nao precisa de Python).
#   .\verificar.ps1                 # porta 7070
#   .\verificar.ps1 -Porta 7071 -Token <valor>
param([int]$Porta = 7070, [string]$Token = "")
$base = "http://127.0.0.1:$Porta/_easyapi/api"
$h = @{}; if ($Token) { $h["X-EasyAPI-Token"] = $Token }
try { $meta = Invoke-RestMethod "$base/meta" -Headers $h -TimeoutSec 30 }
catch { Write-Host "FALHA: nao consegui abrir $base/meta ($($_.Exception.Message)). A API esta rodando com o agente? Porta certa?" -ForegroundColor Red; exit 1 }
$routes = (Invoke-RestMethod "$base/routes" -Headers $h).routes
$execs = (Invoke-RestMethod "$base/executions?limit=200" -Headers $h).executions
Write-Host "OK  EasyAPI ativo: app='$($meta.title)' $($meta.runtime) modo=$($meta.mode) erros internos=$($meta.internal_errors)" -ForegroundColor Green
Write-Host "OK  rotas mapeadas: $($routes.Count)  (com funcao do projeto: $(@($routes | Where-Object { $_.handler }).Count))"
if ($routes.Count -eq 0) { Write-Host "AVISO: nenhuma rota. Rodou de dentro da pasta do projeto? Use -Fontes / -Pacotes." -ForegroundColor Yellow }
Write-Host "OK  execucoes gravadas: $($execs.Count)"
if ($execs.Count -eq 0) { Write-Host "    Faca algumas requisicoes para a API e rode de novo." }
$execs | Select-Object -First 8 | ForEach-Object {
    $err = if ($_.error) { "  erro=$($_.error.type)" } else { "" }
    Write-Host ("    {0} {1} {2} -> {3} funcoes{4}" -f $_.status, $_.method, $_.path, $_.frame_count, $err)
}
Write-Host "Interface: http://127.0.0.1:$Porta/_easyapi/"
