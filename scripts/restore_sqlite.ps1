param(
  [Parameter(Mandatory = $true)][string]$BackupPath,
  [string]$DatabasePath = "data/sector-pulse.db"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $BackupPath)) {
  throw "Backup not found: $BackupPath"
}
if (Test-Path -LiteralPath $DatabasePath) {
  $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
  Copy-Item -LiteralPath $DatabasePath -Destination "$DatabasePath.before-restore-$stamp"
}
Copy-Item -LiteralPath $BackupPath -Destination $DatabasePath -Force
Write-Output $DatabasePath
