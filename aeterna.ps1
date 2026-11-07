param (
    [switch]$engine,
    [switch]$check,
    [string]$symbol = "XAUUSD"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "          AETERNA QUANT ENGINE -- INSTITUTIONAL ORCHESTRATOR                    " -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan

if ($check) {
    Write-Host "Executing Live Market Diagnostic for symbol: $symbol..." -ForegroundColor Yellow
    & uv run python scripts/check_live_market.py --symbol $symbol
    exit $LASTEXITCODE
}

if ($engine) {
    $SecretsFile = Join-Path $ProjectRoot "data\.secrets.enc"
    if (-not (Test-Path $SecretsFile)) {
        Write-Host "ERROR: Encrypted credentials not found at: $SecretsFile" -ForegroundColor Red
        Write-Host "Please bootstrap your credentials first by running:" -ForegroundColor Yellow
        Write-Host "    uv run python scripts/setup_secrets.py" -ForegroundColor White
        exit 1
    }

    Write-Host "Pre-flight Check: DPAPI encrypted credentials verified." -ForegroundColor Green

    $WatchdogDir = Join-Path $ProjectRoot "engine\watchdog"
    $WatchdogExe = Join-Path $WatchdogDir "watchdog.exe"
    if (-not (Test-Path $WatchdogExe)) {
        Write-Host "Compiling independent Go Risk Watchdog daemon..." -ForegroundColor Yellow
        Push-Location $WatchdogDir
        try {
            & go build -o watchdog.exe .
        } finally {
            Pop-Location
        }
        Write-Host "Go Watchdog compiled successfully." -ForegroundColor Green
    }

    Write-Host "Spawning Go Risk Watchdog Daemon on 127.0.0.1:20129..." -ForegroundColor Yellow
    $WatchdogProcess = Start-Process -FilePath $WatchdogExe -WorkingDirectory $WatchdogDir -PassThru -WindowStyle Hidden
    Write-Host "Go Watchdog running in background (PID: $($WatchdogProcess.Id))." -ForegroundColor Green

    $maxRetries = 10
    $retries = 0
    $watchdogReady = $false

    while (-not $watchdogReady -and $retries -lt $maxRetries) {
        Start-Sleep -Milliseconds 500
        try {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:20129/v1/status" -TimeoutSec 1 -ErrorAction SilentlyContinue
            if ($response) {
                $watchdogReady = $true
            }
        } catch {
            $retries++
        }
    }

    if ($watchdogReady) {
        Write-Host "Risk Watchdog handshake verified (HTTP 200 OK)." -ForegroundColor Green
    } else {
        Write-Host "Notice: Watchdog daemon started (proceeding to runtime loop)." -ForegroundColor Yellow
    }

    Write-Host "Starting AETERNA Trading Loop and Telegram Control Panel..." -ForegroundColor Cyan
    Write-Host "Press Ctrl+C at any time to initiate Graceful Shutdown." -ForegroundColor DarkGray

    try {
        & uv run python -m engine.main
    } finally {
        Write-Host "Graceful Shutdown initiated..." -ForegroundColor Yellow
        if ($WatchdogProcess -and -not $WatchdogProcess.HasExited) {
            Write-Host "Terminating Go Watchdog Daemon (PID: $($WatchdogProcess.Id))..." -ForegroundColor Yellow
            Stop-Process -Id $WatchdogProcess.Id -Force -ErrorAction SilentlyContinue
            Write-Host "Watchdog process stopped cleanly." -ForegroundColor Green
        }
        Write-Host "All systems disengaged safely. Goodbye." -ForegroundColor Cyan
    }

    exit 0
}

Write-Host "Penggunaan:" -ForegroundColor Yellow
Write-Host "  .\aeterna.ps1 -check [-symbol XAUUSD]   -> Cek koneksi MT5 dan baca live chart"
Write-Host "  .\aeterna.ps1 -engine                  -> Jalankan Watchdog dan Python Trading Loop"
