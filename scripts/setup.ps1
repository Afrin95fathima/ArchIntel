$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
& (Join-Path $PSScriptRoot 'bootstrap.ps1')
$python = Join-Path $projectRoot '.runtime/python/tools/python.exe'
& $python -m pip install -r backend/requirements.lock
if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
New-Item -ItemType Directory -Force -Path '.runtime/postgres' | Out-Null
Copy-Item 'infra/local-postgres/package.json' '.runtime/postgres/package.json'
Copy-Item 'infra/local-postgres/package-lock.json' '.runtime/postgres/package-lock.json'
& npm.cmd ci --prefix .runtime/postgres
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL runtime installation failed.' }
Push-Location frontend
try {
    & npm.cmd ci --legacy-peer-deps
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
& (Join-Path $PSScriptRoot 'build_exporter.ps1')
& $python scripts/build_samples.py
if ($LASTEXITCODE -ne 0) { throw 'Demo sample build failed.' }
if (-not (Test-Path '.env')) {
    $password = [Guid]::NewGuid().ToString('N')
    [IO.File]::WriteAllText((Join-Path $projectRoot '.env'), "POSTGRES_PASSWORD=$password`nDATABASE_URL=postgresql+psycopg://archintel:$password@127.0.0.1:15432/archintel`n", (New-Object Text.UTF8Encoding($false)))
}
Write-Output 'Setup complete. Run Start-ArchIntel.cmd.'
