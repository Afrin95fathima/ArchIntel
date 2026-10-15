$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$pidFile = Join-Path $projectRoot '.data/api.pid'
if (Test-Path -LiteralPath $pidFile) {
    $apiProcessId = [int](Get-Content -LiteralPath $pidFile)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $apiProcessId" -ErrorAction SilentlyContinue
    if ($process -and $process.CommandLine -like '*app.main:create_app*' -and $process.ExecutablePath -like "$projectRoot*python.exe") {
        Stop-Process -Id $apiProcessId
        Start-Sleep -Milliseconds 500
    }
}
& (Join-Path $PSScriptRoot 'start.ps1')
