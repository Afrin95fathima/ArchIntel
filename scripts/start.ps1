param([switch]$KeepOpen)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
$dataRoot = Join-Path $projectRoot '.data'
New-Item -ItemType Directory -Force -Path $dataRoot | Out-Null
function Port-Open($Port) {
  $client = New-Object Net.Sockets.TcpClient
  try { $task = $client.ConnectAsync('127.0.0.1', $Port); return ($task.Wait(500) -and $client.Connected) } catch { return $false } finally { $client.Dispose() }
}
if (-not (Test-Path '.env')) { throw 'Run scripts/setup.ps1 first.' }
$envText = Get-Content -LiteralPath '.env' -Raw
$portMatch = [regex]::Match($envText, '(?m)^DATABASE_URL=.*@(?:127\.0\.0\.1|localhost):(\d+)/')
if (-not $portMatch.Success) { throw 'Local launcher requires DATABASE_URL with an explicit localhost port in .env.' }
$databasePort = [int]$portMatch.Groups[1].Value
$python = Join-Path $projectRoot '.runtime/python/tools/python.exe'
if (-not (Test-Path $python)) { throw 'Workspace Python missing. Run scripts/setup.ps1.' }
$env:PYTHONHASHSEED = '0'
if (-not (Port-Open $databasePort)) {
  $pgProcess = Start-Process -FilePath 'node.exe' -ArgumentList 'scripts/postgres.mjs' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $dataRoot 'postgres.out.log') -RedirectStandardError (Join-Path $dataRoot 'postgres.err.log')
  $pgProcess.Id | Set-Content (Join-Path $dataRoot 'postgres-launcher.pid')
  for ($attempt=0; $attempt -lt 60 -and -not (Port-Open $databasePort); $attempt++) { Start-Sleep -Milliseconds 500 }
  if (-not (Port-Open $databasePort)) { throw 'PostgreSQL did not start. Inspect .data/postgres.err.log.' }
} else {
  & $python scripts/check_database.py
  if ($LASTEXITCODE -ne 0) { throw "Port $databasePort is occupied but ArchIntel database is unavailable. Check for a port conflict or incorrect database credentials in .env." }
}
$databaseReady = $false
for ($attempt=0; $attempt -lt 30; $attempt++) {
  & $python scripts/check_database.py
  if ($LASTEXITCODE -eq 0) { $databaseReady = $true; break }
  Start-Sleep -Milliseconds 500
}
if (-not $databaseReady) { throw 'PostgreSQL has not finished starting. Inspect .data/postgres.err.log.' }
if ($envText -match '(?mi)^KNOWLEDGE_GRAPH_ENABLED=true\s*$') {
  & $python scripts/knowledge_graph.py start
  if ($LASTEXITCODE -ne 0) { Write-Warning 'Persistent graph unavailable. Static analysis and canonical evidence remain accessible; inspect .data/knowledge-graph/launcher.log.' }
}
if (-not (Port-Open 8000)) {
  $apiProcess = Start-Process -FilePath $python -ArgumentList '-m uvicorn app.main:create_app --factory --app-dir backend --host 0.0.0.0 --port 8000' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $dataRoot 'api.out.log') -RedirectStandardError (Join-Path $dataRoot 'api.err.log')
  $apiProcess.Id | Set-Content (Join-Path $dataRoot 'api.pid')
}
for ($attempt=0; $attempt -lt 60; $attempt++) {
  try {
    $health = Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/ready' -TimeoutSec 2
    if ($health.status -eq 'ready') { break }
  } catch {}
  Start-Sleep -Milliseconds 500
}
if ($attempt -ge 60) { throw 'API did not become ready. Inspect .data/api.err.log.' }
Write-Output 'ArchIntel ready: http://127.0.0.1:8000'
if ($KeepOpen) {
  Start-Process 'http://127.0.0.1:8000'
  Write-Output 'Keep this window open while using ArchIntel. Use Stop-ArchIntel.cmd to stop the services.'
  while ($true) {
    Start-Sleep -Seconds 5
    if ($envText -match '(?mi)^KNOWLEDGE_GRAPH_ENABLED=true\s*$') {
  & $python scripts/knowledge_graph.py start
  if ($LASTEXITCODE -ne 0) { Write-Warning 'Persistent graph unavailable. Static analysis and canonical evidence remain accessible; inspect .data/knowledge-graph/launcher.log.' }
}
if (-not (Port-Open 8000)) { throw 'ArchIntel server stopped. Inspect .data/api.err.log, then run Start-ArchIntel.cmd again.' }
  }
}
