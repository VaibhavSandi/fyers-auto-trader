# One-time setup: creates the Python virtual environment, installs backend
# and frontend dependencies, and creates backend\.env from the template if
# it doesn't exist yet.
$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"

Write-Host "=== FYERS Auto Trader - Install ===" -ForegroundColor Cyan

Write-Host "`n[1/4] Creating Python virtual environment..." -ForegroundColor Yellow
Push-Location $BackendDir
if (-not (Test-Path "venv")) {
    python -m venv venv
}

Write-Host "[2/4] Installing backend dependencies..." -ForegroundColor Yellow
& ".\venv\Scripts\python.exe" -m pip install --upgrade pip -q
& ".\venv\Scripts\python.exe" -m pip install -r requirements.txt -q

if (-not (Test-Path ".env")) {
    Write-Host "[2b] Creating backend\.env from .env.example (edit it with your FYERS credentials!)" -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    $fernetKey = & ".\venv\Scripts\python.exe" -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    (Get-Content ".env") -replace "APP_SECRET_KEY=.*", "APP_SECRET_KEY=$fernetKey" | Set-Content ".env"
    Write-Host "    Generated a unique APP_SECRET_KEY for you automatically." -ForegroundColor Green
}
Pop-Location

Write-Host "`n[3/4] Installing frontend dependencies (this can take a minute)..." -ForegroundColor Yellow
Push-Location $FrontendDir
npm install
Pop-Location

Write-Host "`n[4/4] Done." -ForegroundColor Green
Write-Host "`nNEXT STEP: open backend\.env and fill in FYERS_CLIENT_ID and FYERS_SECRET_KEY" -ForegroundColor Cyan
Write-Host "from https://myapi.fyers.in/dashboard before using Live trading." -ForegroundColor Cyan
Write-Host "`nThen run scripts\start-all.ps1 (or double-click scripts\start-all.bat) to launch the app." -ForegroundColor Cyan
