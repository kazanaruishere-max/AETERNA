param (
    [string]$Expert = "AeternaEA_DynamicATR\AeternaEA.ex5",
    [string]$Symbol = "XAUUSDm",
    [string]$FromDate = "2022.01.01",
    [string]$ToDate = "2026.11.13",
    [double]$Deposit = 4000.0,
    [int]$OptimizationType = 1, # 1: Complete Slow, 2: Fast Genetic
    [int]$Criterion = 6,        # 6: Custom / Max Balance + Min DD
    [int]$TimeoutSeconds = 300
)

$ErrorActionPreference = "Stop"
$repoRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$terminal = "C:\Program Files\OANDA Global MetaTrader 5 Terminal\terminal64.exe"
$oandaData = Join-Path $env:APPDATA "MetaQuotes\Terminal\<TERMINAL_ID>"
$reportsDir = Join-Path $repoRoot "ea\Reports"
$configDir = Join-Path $repoRoot "ea\Config"

New-Item -ItemType Directory -Path $reportsDir -Force | Out-Null
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

$optIni = Join-Path $configDir "optimization.ini"
$reportBaseName = "Report_Optimization"

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
Optimization=$OptimizationType
OptimizationCriterion=$Criterion
FromDate=$FromDate
ToDate=$ToDate
ForwardMode=0
Report=$reportBaseName
ReplaceReport=1
ShutdownTerminal=1
Visual=0

[TesterInputs]
InpProfile=0
InpDryRun=false
InpEnforceNewsFilter=true
InpSlippageTolerancePts=50
InpMagicNumber=20261101
InpDonchianPeriod=20||16||4||24||Y
InpAtrMultiplier=1.5||1.4||0.1||1.6||Y
InpRewardRiskRatio=2.5||2.4||0.2||2.8||Y
"@

Set-Content -Path $optIni -Value $iniContent -Encoding UTF8

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "           AETERNA QUANT -- TAHAP L-03 GENETIC & SURFACE OPTIMIZATION           " -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "Expert         : $Expert" -ForegroundColor Yellow
Write-Host "Symbol         : $Symbol | Period: M15 | Deposit: $Deposit USD" -ForegroundColor Yellow
Write-Host "Range          : $FromDate -> $ToDate" -ForegroundColor Yellow
Write-Host "Optimization   : Mode=$OptimizationType (1=Complete 27 passes, 2=Fast Genetic)" -ForegroundColor Yellow
Write-Host "Parameter Grid : Donchian (16,20,24) x ATR_Mult (1.4,1.5,1.6) x RR (2.4,2.6,2.8)" -ForegroundColor Yellow
Write-Host ""

# Pre-clean
Get-Process terminal64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

Remove-Item -Path (Join-Path $oandaData "$reportBaseName.xml") -Force -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path $oandaData "$reportBaseName.htm") -Force -ErrorAction SilentlyContinue

Write-Host "[*] Launching MetaTrader 5 Multi-Core Optimization..." -ForegroundColor Gray
$proc = Start-Process -FilePath $terminal -ArgumentList "/config:`"$optIni`"" -PassThru

$elapsed = 0
$step = 3
while (-not $proc.HasExited -and $elapsed -lt $TimeoutSeconds) {
    Start-Sleep -Seconds $step
    $elapsed += $step
    Write-Host "." -NoNewline -ForegroundColor DarkCyan
}
Write-Host ""

if (-not $proc.HasExited) {
    Write-Host "[WARNING] Process timed out after $TimeoutSeconds s. Terminating..." -ForegroundColor Red
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
} else {
    Write-Host "[+] Optimization completed in $elapsed seconds (ExitCode: $($proc.ExitCode))." -ForegroundColor Green
}

# Locate results in terminal folder / cache
$cacheDir = Join-Path $oandaData "Tester\cache"
if (Test-Path $cacheDir) {
    $optFiles = Get-ChildItem -Path $cacheDir -Filter "*.opt" | Sort-Object LastWriteTime -Descending
    if ($optFiles) {
        Write-Host "[+] Optimization cache files found: $($optFiles[0].Name) ($($optFiles[0].Length) bytes)" -ForegroundColor Green
    }
}

# Inspect tester logs for top optimization passes
$testerLogDir = Join-Path $oandaData "Tester\logs"
if (Test-Path $testerLogDir) {
    $latestLog = Get-ChildItem -Path $testerLogDir | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latestLog) {
        Write-Host "--- Optimization Log Summary ---" -ForegroundColor Yellow
        Get-Content $latestLog.FullName | Select-String -Pattern "pass \d+|optimization finished|best pass" | Select-Object -Last 15
    }
}
