$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
$dockerCli = (Get-Command docker.exe -ErrorAction SilentlyContinue).Source
if (-not $dockerCli -and $env:LOCALAPPDATA) {
  $candidate = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'
  if (Test-Path -LiteralPath $candidate) { $dockerCli = $candidate }
}
if (-not $dockerCli) { throw 'Docker CLI is unavailable. Start Docker Desktop or install its CLI.' }
$dockerBin = Split-Path -Parent $dockerCli
$env:PATH = $dockerBin + ';' + $env:PATH
$dockerHost = if ($env:OS -eq 'Windows_NT') { 'npipe:////./pipe/docker_engine' } else { 'unix:///var/run/docker.sock' }
$trivyBase = 'aquasec/trivy@sha256:af6acf9a6b85dfe389a1941505c0ce9efef52a4719635e1a962f022a3d855daa'
$cache = Join-Path $projectRoot '.runtime\trivy-cache'
$envPath = Join-Path $projectRoot '.env'
$imageTag = 'archintel-dependencies:phase7'

$engine = & $dockerCli --host $dockerHost info --format '{{.OSType}}'
if ($LASTEXITCODE -ne 0 -or $engine.Trim() -ne 'linux') { throw 'Start Docker Desktop with Linux containers before provisioning dependency scanning.' }
New-Item -ItemType Directory -Force -Path $cache | Out-Null
$version = & $dockerCli --host $dockerHost run --rm --network none $trivyBase --version --format json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $version.Version -ne '0.75.0') { throw 'The pinned Trivy image is unavailable or has the wrong version.' }

$mount = 'type=bind,source=' + $cache + ',target=/opt/trivy-cache'
& $dockerCli --host $dockerHost run --rm --network bridge --mount $mount $trivyBase --cache-dir /opt/trivy-cache image --download-db-only
if ($LASTEXITCODE -ne 0) { throw 'Trivy vulnerability database download failed. No dependency image was configured.' }
& $dockerCli --host $dockerHost run --rm --network bridge --mount $mount $trivyBase --cache-dir /opt/trivy-cache image --download-java-db-only
if ($LASTEXITCODE -ne 0) { throw 'Trivy Java database download failed. No dependency image was configured.' }

& $dockerCli --host $dockerHost build --pull=false --build-arg ('TRIVY_BASE=' + $trivyBase) -f infra/docker/dependency-security/Dockerfile -t $imageTag infra/docker/dependency-security
if ($LASTEXITCODE -ne 0) { throw 'Dependency scanner image build failed.' }
$imageId = & $dockerCli --host $dockerHost image inspect --format '{{.Id}}' $imageTag
if ($LASTEXITCODE -ne 0 -or $imageId -notmatch '^sha256:[0-9a-f]{64}$') { throw 'Could not verify the dependency scanner image ID.' }

$content = [System.IO.File]::ReadAllText($envPath)
$line = 'DEPENDENCY_SANDBOX_IMAGE=' + $imageId
if ($content -match '(?m)^DEPENDENCY_SANDBOX_IMAGE=.*$') {
  $content = [regex]::Replace($content, '(?m)^DEPENDENCY_SANDBOX_IMAGE=.*$', [System.Text.RegularExpressions.MatchEvaluator]{ param($match) $line }, 1)
} else {
  $content = $content.TrimEnd("`r", "`n") + "`r`n" + $line + "`r`n"
}
[System.IO.File]::WriteAllText($envPath, $content, [System.Text.UTF8Encoding]::new($false))
Write-Output ('Dependency scanner provisioned: ' + $imageId)
Write-Output ('Database cache stored at: ' + $cache)
Write-Output 'Restart ArchIntel before running a candidate dependency scan.'
