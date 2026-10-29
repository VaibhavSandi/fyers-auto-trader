# Starts the FastAPI backend (API + trading engine + WebSocket).
$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RootDir "backend"

Push-Location $BackendDir
if (-not (Test-Path ".env")) {
    Write-Host "backend\.env not found. Run scripts\install.ps1 first." -ForegroundColor Red
    Pop-Location
    exit 1
}
Write-Host "Starting backend on http://127.0.0.1:8000 ..." -ForegroundColor Cyan
& ".\venv\Scripts\python.exe" run.py
Pop-Location
