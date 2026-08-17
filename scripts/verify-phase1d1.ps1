param([switch]$RunLive)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$temp = Join-Path $repo '.tmp-test'
New-Item -ItemType Directory -Force -Path $temp | Out-Null
$env:TEMP = $temp
$env:TMP = $temp
$env:PYTHONPATH = Join-Path $repo 'backend/src'
Push-Location $repo
try {
  & '.venv/Scripts/python.exe' -m pytest backend/tests -q -p no:cacheprovider
  & '.venv/Scripts/python.exe' -m ruff check --no-cache backend/src backend/tests
  Push-Location web
  try {
    & npm.cmd test -- --run
    & npm.cmd run build
  } finally { Pop-Location }
  if ($RunLive) {
    & '.venv/Scripts/python.exe' -m pytest backend/tests/live/test_phase1d1_live.py -m live -v -p no:cacheprovider
  }
} finally { Pop-Location }
