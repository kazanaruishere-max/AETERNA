param (
    [string]$Expert = "AeternaEA_DynamicATR\AeternaEA.ex5",
    [string]$Symbol = "XAUUSDm",
    [string]$FromDate = "2024.10.01",
    [string]$ToDate = "2024.11.01",
    [double]$Deposit = 4000.0
)

$ErrorActionPreference = "Stop"
$repoRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$terminal = "C:\Program Files\OANDA Global MetaTrader 5 Terminal\terminal64.exe"
$configDir = Join-Path $repoRoot "ea\Config"

New-Item -ItemType Directory -Path $configDir -Force | Out-Null

# Read credentials from .env
$envFile = Join-Path $repoRoot ".env"
$login = ""
$server = ""
$pass = ""

if (Test-Path $envFile) {
    $lines = Get-Content $envFile
    foreach ($line in $lines) {
        if ($line -match "^(EXNESS_MT5_PASSWORD|MT5_PASSWORD)=(.*)$") {
            $pass = ($matches[2].Trim().Trim('"').Trim("'") -split "\s+#", 2)[0].Trim()
        }
        if ($line -match "^(EXNESS_MT5_LOGIN|MT5_LOGIN)=(.*)$") {
            $login = ($matches[2].Trim().Trim('"').Trim("'") -split "\s+#", 2)[0].Trim()
        }
        if ($line -match "^(EXNESS_MT5_SERVER|MT5_SERVER)=(.*)$") {
            $server = ($matches[2].Trim().Trim('"').Trim("'") -split "\s+#", 2)[0].Trim()
        }
    }
}

if (-not $login -or -not $server) {
    Write-Host "[ERROR] Credentials missing in .env!" -ForegroundColor Red
    exit 1
}

$iniPath = Join-Path $configDir "visual_audit_l01.ini"

$iniContent = @"
[Common]
Login=$login
Password=$pass
Server=$server

[Tester]
Expert=$Expert
Symbol=$Symbol
Period=M15
Deposit=$Deposit
Currency=USD
Leverage=2000
Model=1
ExecutionMode=0
Optimization=0
FromDate=$FromDate
ToDate=$ToDate
ForwardMode=0
Report=Report_Visual_L01
ReplaceReport=1
ShutdownTerminal=0
Visual=1

[TesterInputs]
InpProfile=0
InpDryRun=false
InpEnforceNewsFilter=true
InpSlippageTolerancePts=50
InpMagicNumber=20261101
InpDonchianPeriod=24
InpAtrMultiplier=1.4
InpRewardRiskRatio=2.6
"@

Set-Content -Path $iniPath -Value $iniContent -Encoding UTF8

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "           AETERNA QUANT -- TAHAP L-01 VISUAL EXECUTION AUDIT                   " -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "Expert         : $Expert" -ForegroundColor Yellow
Write-Host "Symbol         : $Symbol | Period: M15 | Deposit: $Deposit USD" -ForegroundColor Yellow
Write-Host "Inspection Span: $FromDate -> $ToDate (Focused 1 Month Audit)" -ForegroundColor Yellow
Write-Host "Visual Mode    : Visual=1 (Chart Window will open for live visual inspection)" -ForegroundColor Yellow
Write-Host "Shutdown       : ShutdownTerminal=0 (Terminal remains open)" -ForegroundColor Yellow
Write-Host ""

# Stop background instance if running
Get-Process terminal64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

Write-Host "[*] Launching MetaTrader 5 in VISUAL MODE on your desktop..." -ForegroundColor Green
Write-Host "[*] Look at your screen: MetaTrader 5 will open with animated candlesticks." -ForegroundColor Green
Write-Host "[*] You can pause, speed up, or take screenshots of trades on the chart." -ForegroundColor Green

Start-Process -FilePath $terminal -ArgumentList "/config:`"$iniPath`""
Write-Host "[+] MT5 Visual Terminal successfully launched!" -ForegroundColor Cyan
