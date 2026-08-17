param(
    [string]$Source = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
)

$ErrorActionPreference = 'Stop'
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('sectorpulse-phase1c-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tempRoot | Out-Null
try {
    # 只在系统临时目录中解压归档，避免改变当前工作树。
    git -c safe.directory=$Source -C $Source archive HEAD | tar -x -C $tempRoot
    Push-Location $tempRoot
    $env:PYTHONPATH = 'backend/src'
    & "$Source\.venv\Scripts\python.exe" -m pytest backend/tests -q -p no:cacheprovider
    Push-Location web
    npm.cmd test -- --run
    npm.cmd run build
    Pop-Location
    Pop-Location
} finally {
    if ((Resolve-Path $tempRoot).Path.StartsWith([IO.Path]::GetTempPath(), [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
