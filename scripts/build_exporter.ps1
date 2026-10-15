$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$javaRoot = (Get-ChildItem (Join-Path $projectRoot '.runtime/java') -Directory | Select-Object -First 1).FullName
$jqaRoot = (Get-ChildItem (Join-Path $projectRoot '.runtime/jqassistant') -Directory | Select-Object -First 1).FullName
$destination = Join-Path $projectRoot '.runtime/exporter'
New-Item -ItemType Directory -Force -Path $destination | Out-Null
& (Join-Path $javaRoot 'bin/javac.exe') --release 17 -proc:none -cp (Join-Path $jqaRoot 'lib/*') -d $destination (Join-Path $projectRoot 'backend/scanner-java/ExportGraph.java')
if ($LASTEXITCODE -ne 0) { throw 'Graph exporter compilation failed.' }
