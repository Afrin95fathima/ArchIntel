$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$pidFile = Join-Path $projectRoot '.data/api.pid'
if (Test-Path -LiteralPath $pidFile) {
    $apiProcessId = [int](Get-Content -LiteralPath $pidFile)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $apiProcessId" -ErrorAction SilentlyContinue
    if ($process -and $process.CommandLine -like '*app.main:create_app*' -and $process.ExecutablePath -like "$projectRoot*python.exe") { Stop-Process -Id $apiProcessId }
}
$pgCtl = Join-Path $projectRoot '.runtime/postgres/node_modules/@embedded-postgres/windows-x64/native/bin/pg_ctl.exe'
$pgData = Join-Path $projectRoot '.data/postgres'
if (Test-Path -LiteralPath (Join-Path $pgData 'postmaster.pid')) { & $pgCtl -D $pgData -m fast stop }
$launcherFile = Join-Path $projectRoot '.data/postgres-launcher.pid'
if (Test-Path -LiteralPath $launcherFile) {
    $launcherId = [int](Get-Content -LiteralPath $launcherFile)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $launcherId" -ErrorAction SilentlyContinue
    if ($process -and $process.CommandLine -like '*scripts/postgres.mjs*') { Stop-Process -Id $launcherId }
}
Write-Output 'ArchIntel stopped. Saved analyses remain in .data/postgres.'

$graphPidFile = Join-Path $projectRoot '.data/knowledge-graph/java.pid'
if (Test-Path -LiteralPath $graphPidFile) {
  $graphProcessId = [int](Get-Content -LiteralPath $graphPidFile)
  $graphProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $graphProcessId" -ErrorAction SilentlyContinue
  if ($graphProcess -and $graphProcess.CommandLine -like '*org.neo4j.server.CommunityEntryPoint*' -and $graphProcess.CommandLine -like "*$projectRoot*knowledge-graph*" -and $graphProcess.ExecutablePath -like "$projectRoot*java.exe") { Stop-Process -Id $graphProcessId }
}
