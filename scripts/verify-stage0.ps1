[CmdletBinding()]
param(
  [string]$PythonPath
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$temporaryRoot = Join-Path $repositoryRoot '.tmp\stage0'
$python = if ($PythonPath) {
  $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($PythonPath)
}
else {
  Join-Path $repositoryRoot '.venv\Scripts\python.exe'
}

if (-not (Test-Path -LiteralPath $python)) {
  throw "Python environment not found at $python. Create .venv and install .[dev,postgres] first."
}

New-Item -ItemType Directory -Force -Path $temporaryRoot | Out-Null

function Invoke-QualityCommand {
  param(
    [Parameter(Mandatory)]
    [string]$Label,
    [Parameter(Mandatory)]
    [scriptblock]$Command
  )

  Write-Host "`n==> $Label" -ForegroundColor Cyan
  & $Command
  if ($LASTEXITCODE -ne 0) {
    throw "$Label failed with exit code $LASTEXITCODE"
  }
}

Push-Location $repositoryRoot
try {
  $env:PYTHONPATH = Join-Path $repositoryRoot 'backend\src'
  $env:TEMP = $temporaryRoot
  $env:TMP = $temporaryRoot
  Invoke-QualityCommand 'Ruff' { & $python -m ruff check backend }
  Invoke-QualityCommand 'Mypy' { & $python -m mypy backend\src\sector_pulse }
  Invoke-QualityCommand 'Python dependency audit' {
    for ($attempt = 1; $attempt -le 3; $attempt++) {
      & $python -m pip_audit --vulnerability-service osv --timeout 60 --progress-spinner off
      if ($LASTEXITCODE -eq 0) { break }
      if ($attempt -lt 3) {
        Write-Warning "OSV audit attempt $attempt failed; retrying."
        Start-Sleep -Seconds (2 * $attempt)
      }
    }
  }
  Invoke-QualityCommand 'Backend tests (non-Live)' {
    # Python preserves an empty environment value on Windows, so dotenv cannot
    # reintroduce a user's PostgreSQL URL while ordinary tests are running.
    $pytestCommand = @'
import os
import pytest
os.environ["SECTOR_PULSE_DATABASE_URL"] = ""
os.environ["SECTOR_PULSE_LLM_PROVIDER"] = "fixture"
os.environ["SECTOR_PULSE_SCHEDULER_ENABLED"] = "false"
raise SystemExit(pytest.main([
    "-p", "no:cacheprovider", "-m", "not live and not live_llm",
    "--import-mode=importlib", "-q",
]))
'@
    $pytestCommand | & $python -
  }

  Push-Location (Join-Path $repositoryRoot 'web')
  try {
    Invoke-QualityCommand 'Frontend unit tests' { & npm.cmd test -- --run }
    Invoke-QualityCommand 'Frontend production build' { & npm.cmd run build }
    Invoke-QualityCommand 'Frontend browser tests' { & npm.cmd run test:e2e }
    Invoke-QualityCommand 'Production dependency audit' { & npm.cmd audit --omit=dev }
  }
  finally {
    Pop-Location
  }
}
finally {
  Pop-Location
}

Write-Host "`nStage 0 quality gate passed without Live data or LLM calls." -ForegroundColor Green
