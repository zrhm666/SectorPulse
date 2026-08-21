param(
  [string]$DatabasePath = "data/sector-pulse.db",
  [string]$BackupDirectory = "data/backups"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $DatabasePath)) {
  throw "Database not found: $DatabasePath"
}
New-Item -ItemType Directory -Force -Path $BackupDirectory | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$target = Join-Path $BackupDirectory "sector-pulse-$stamp.db"
Copy-Item -LiteralPath $DatabasePath -Destination $target
Write-Output $target
