param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root '.env'
$tempFile = Join-Path $root '.env.gemini.tmp'
$secureKey = Read-Host 'Enter the rotated Gemini API key (input is hidden)' -AsSecureString
$pointer = [IntPtr]::Zero
try {
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    if ([string]::IsNullOrWhiteSpace($plainKey) -or $plainKey -match '[\r\n\s]') {
        throw 'The key must be a single non-empty token.'
    }
    $lines = if (Test-Path -LiteralPath $envFile) { [System.IO.File]::ReadAllLines($envFile) } else { @() }
    $kept = @($lines | Where-Object { $_ -notmatch '^\s*GEMINI_API_KEY\s*=' })
    $kept += 'GEMINI_API_KEY=' + $plainKey
    [System.IO.File]::WriteAllLines($tempFile, $kept, [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $tempFile -Destination $envFile -Force
    Write-Host 'Gemini key saved to the ignored local .env file. Restart ArchIntel to load it.'
} finally {
    if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    $plainKey = $null
    $secureKey.Dispose()
    if (Test-Path -LiteralPath $tempFile) { Remove-Item -LiteralPath $tempFile -Force }
}
