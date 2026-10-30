# Starts the FastAPI backend and automatically restarts it if it exits for
# any reason (crash, Windows killing it for memory, etc.) - the ordinary
# start-backend.ps1 is a single run; this is what's meant to be left running
# unattended during market hours so an open live position is never left
# without the trading engine's monitoring for longer than a restart takes.
#
# Protective note: this restarts the PROCESS. It does not, by itself, make
# auto trading resume - app/engine/recovery.py still forces auto trading off
# and requires a passing recovery check after every restart, on purpose.
$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RootDir "backend"

if (-not (Test-Path (Join-Path $BackendDir ".env"))) {
    Write-Host "backend\.env not found. Run scripts\install.ps1 first." -ForegroundColor Red
    exit 1
}

# If 5 crashes happen within 2 minutes, something is structurally broken
# (bad venv, bad .env, port conflict) - stop retrying rather than loop
# forever and flood the logs / FYERS with reconnect attempts.
$MaxCrashesInWindow = 5
$CrashWindowSeconds = 120
$crashTimestamps = New-Object System.Collections.Generic.List[datetime]

Push-Location $BackendDir
try {
    while ($true) {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Starting backend on http://127.0.0.1:8000 ..." -ForegroundColor Cyan
        & ".\venv\Scripts\python.exe" run.py
        $exitCode = $LASTEXITCODE

        $now = Get-Date
        $crashTimestamps.Add($now)
        $crashTimestamps.RemoveAll({ param($t) ($now - $t).TotalSeconds -gt $CrashWindowSeconds }) | Out-Null

        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Backend process exited (code $exitCode)." -ForegroundColor Yellow

        if ($crashTimestamps.Count -ge $MaxCrashesInWindow) {
            Write-Host "Backend crashed $($crashTimestamps.Count) times in the last $CrashWindowSeconds seconds - stopping auto-restart." -ForegroundColor Red
            Write-Host "Check backend\logs for the actual error before restarting manually." -ForegroundColor Red
            break
        }

        Write-Host "Restarting in 5 seconds... (Ctrl+C to stop watching)" -ForegroundColor Yellow
        Start-Sleep -Seconds 5
    }
} finally {
    Pop-Location
}
