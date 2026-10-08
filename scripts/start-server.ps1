$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Ambiente Python assente. Segui la procedura di installazione nel README.'
}
Set-Location -LiteralPath $projectPath
& $pythonPath run.py
