$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$runtimeRoot = Join-Path $projectRoot '.runtime'
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
function Get-Archive($Url, $Name, $Destination) {
    if (Test-Path -LiteralPath $Destination) { return }
    $archive = Join-Path $runtimeRoot ($Name + '.zip')
    & curl.exe -fL --retry 2 --connect-timeout 20 $Url -o $archive
    if ($LASTEXITCODE -ne 0) { throw "Download failed: $Name" }
    Expand-Archive -LiteralPath $archive -DestinationPath $Destination -Force
}
Get-Archive 'https://www.nuget.org/api/v2/package/python/3.12.10' 'python' (Join-Path $runtimeRoot 'python')
Get-Archive 'https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jdk/hotspot/normal/eclipse' 'java' (Join-Path $runtimeRoot 'java')
Get-Archive 'https://repo.maven.apache.org/maven2/com/buschmais/jqassistant/cli/jqassistant-commandline-neo4jv5/2.7.0/jqassistant-commandline-neo4jv5-2.7.0-distribution.zip' 'jqassistant' (Join-Path $runtimeRoot 'jqassistant')
& (Join-Path $runtimeRoot 'python\tools\python.exe') --version
Write-Output 'Workspace runtime downloads complete.'
