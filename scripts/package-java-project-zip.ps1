param(
  [Parameter(Mandatory=$true)][string]$SourceRoot,
  [Parameter(Mandatory=$true)][string]$OutputZip,
  [int]$MaxUploadMB = 100
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $SourceRoot).Path.TrimEnd('\')
$output = [IO.Path]::GetFullPath($OutputZip)
if ($output.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
  throw 'Choose an output ZIP path outside the source checkout.'
}
if ($MaxUploadMB -lt 1 -or $MaxUploadMB -gt 1000) { throw 'MaxUploadMB must be between 1 and 1000.' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
Add-Type -AssemblyName System.IO.Compression
$files = Get-ChildItem -LiteralPath $root -Recurse -File -Filter '*.class' -ErrorAction Stop | Where-Object {
  $_.FullName -match '[\\/](target|build)[\\/]classes[\\/]' -and
  $_.FullName -notmatch '[\\/](\.git|node_modules|\.m2|deps|dependencies|\.gradle)[\\/]'
}
if (-not $files) { throw 'No compiled Java classes found. Build the application first, then run this script again.' }
if (Test-Path -LiteralPath $output) { throw 'Output ZIP already exists. Choose a new output path so an existing file is preserved.' }
$outputDirectory = Split-Path -Parent $output
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
$archive = [IO.Compression.ZipFile]::Open($output, [IO.Compression.ZipArchiveMode]::Create)
try {
  foreach ($file in $files) {
    $relative = $file.FullName.Substring($root.Length).TrimStart('\').Replace('\','/')
    [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $file.FullName, $relative, [IO.Compression.CompressionLevel]::Optimal) | Out-Null
  }
} finally { $archive.Dispose() }
$size = (Get-Item -LiteralPath $output).Length
if ($size -gt ($MaxUploadMB * 1MB)) {
  Remove-Item -LiteralPath $output -Force
  throw "ZIP is $([math]::Round($size/1MB,1)) MiB, above ArchIntel's $MaxUploadMB MiB upload limit. Package fewer modules or raise the configured upload limit."
}
Write-Output "Created compiled Java project bundle: $output"
Write-Output "Included $($files.Count) class files; compressed size $([math]::Round($size/1MB,1)) MiB."
