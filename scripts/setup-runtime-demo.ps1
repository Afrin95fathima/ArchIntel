$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
$revision = '30aab0ae764ad845b5eedd76028756835fec771f'
$agentVersion = '2.31.1'
New-Item -ItemType Directory -Force '.runtime/otel' | Out-Null
$installedVersion = if (Test-Path '.runtime/otel/version.txt') { (Get-Content '.runtime/otel/version.txt' -Raw).Trim() } else { '' }
if (-not (Test-Path '.runtime/otel/opentelemetry-javaagent.jar') -or $installedVersion -ne "v$agentVersion") {
    Invoke-WebRequest "https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/download/v$agentVersion/opentelemetry-javaagent.jar" -OutFile '.runtime/otel/opentelemetry-javaagent.jar' -UseBasicParsing
}
"v$agentVersion" | Set-Content '.runtime/otel/version.txt'
$source = Join-Path $projectRoot ".runtime/petclinic/spring-petclinic-$revision"
if (-not (Test-Path -LiteralPath $source)) {
    Invoke-WebRequest "https://codeload.github.com/spring-projects/spring-petclinic/zip/$revision" -OutFile '.runtime/petclinic.zip' -UseBasicParsing
    Expand-Archive '.runtime/petclinic.zip' '.runtime/petclinic' -Force
}
$revision | Set-Content '.runtime/petclinic-version.txt'
$env:JAVA_HOME = (Get-ChildItem '.runtime/java' -Directory | Select-Object -First 1).FullName
$env:MAVEN_USER_HOME = Join-Path $projectRoot '.runtime/maven'
Push-Location $source
try {
    & .\mvnw.cmd -B -s "$projectRoot/scripts/maven-central-settings.xml" '-Dmaven.test.skip=true' '-Dcheckstyle.skip=true' '-Dspring-javaformat.skip=true' "-Dmaven.repo.local=$projectRoot/.runtime/m2" package
    if ($LASTEXITCODE -ne 0) { throw 'PetClinic validation artifact build failed.' }
} finally { Pop-Location }
Write-Output 'Runtime sample ready. Start ArchIntel, then run .runtime/python/tools/python.exe scripts/validate_runtime_petclinic.py'
