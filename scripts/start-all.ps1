# Starts both the backend and frontend, each in its own new PowerShell
# window, then opens the app in your default browser.
$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot

Write-Host "Starting FYERS Auto Trader..." -ForegroundColor Cyan

Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $ScriptDir "start-backend.ps1")
Start-Sleep -Seconds 3
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $ScriptDir "start-frontend.ps1")

Write-Host "Waiting for the frontend to come up..." -ForegroundColor Yellow
Start-Sleep -Seconds 5
Start-Process "http://127.0.0.1:5173"

Write-Host "`nTwo new windows opened: one for the backend, one for the frontend." -ForegroundColor Green
Write-Host "Close this window any time - the other two keep the app running." -ForegroundColor Green
Write-Host "To stop the app, close the backend and frontend windows." -ForegroundColor Green
