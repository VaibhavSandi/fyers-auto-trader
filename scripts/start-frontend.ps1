# Starts the React/Vite frontend dev server.
$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $PSScriptRoot
$FrontendDir = Join-Path $RootDir "frontend"

Push-Location $FrontendDir
if (-not (Test-Path "node_modules")) {
    Write-Host "frontend\node_modules not found. Run scripts\install.ps1 first." -ForegroundColor Red
    Pop-Location
    exit 1
}
Write-Host "Starting frontend on http://127.0.0.1:5173 ..." -ForegroundColor Cyan
npm run dev
Pop-Location
