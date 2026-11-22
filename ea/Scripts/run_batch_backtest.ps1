param (
    [ValidateSet("DayTrading", "SessionMomentum", "AsianRange", "MultiSessionHybrid", "All")]
    [string]$Profile = "MultiSessionHybrid",

    [string]$Expert = "AeternaEA\AeternaEA.ex5",
    [string]$Symbol = "XAUUSDm",
    [string]$FromDate = "2024.01.01",
    [string]$ToDate = "2024.11.01",
    [double]$Deposit = 1000.0,
    [int]$Model = 1, # 1: 1-minute OHLC, 0: Every tick, 4: Real ticks
    [int]$ExecutionMode = 0, # 0: Normal (zero latency), 32: Random Delay 100-300ms (Latency Stress)
    [int]$DonchianPeriod = 24,
    [double]$AtrMultiplier = 1.6,
    [double]$RewardRiskRatio = 2.6,
    [int]$TimeoutSeconds = 600
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
    $pwLine = Get-Content $envFile | Where-Object { $_ -match "^(EXNESS_MT5_PASSWORD|MT5_PASSWORD)=" }
    if ($pwLine) {
        $raw = ($pwLine -split '=', 2)[1].Trim().Trim('"').Trim("'")
        $pass = ($raw -split '\s+#', 2)[0].Trim()
    }
    $lLine = Get-Content $envFile | Where-Object { $_ -match "^(EXNESS_MT5_LOGIN|MT5_LOGIN)=" }
    if ($lLine) {
        $raw = ($lLine -split '=', 2)[1].Trim().Trim('"').Trim("'")
        $login = ($raw -split '\s+#', 2)[0].Trim()
    }
    $sLine = Get-Content $envFile | Where-Object { $_ -match "^(EXNESS_MT5_SERVER|MT5_SERVER)=" }
    if ($sLine) {
        $raw = ($sLine -split '=', 2)[1].Trim().Trim('"').Trim("'")
        $server = ($raw -split '\s+#', 2)[0].Trim()
    }
}

if (-not $login -or -not $server) {
    Write-Host "[ERROR] EXNESS_MT5_LOGIN or EXNESS_MT5_SERVER missing in .env!" -ForegroundColor Red
    exit 1
}

$symbolClean = ($Symbol -replace "m$", "")
$runs = @()
if ($Profile -eq "DayTrading" -or $Profile -eq "All") {
    $runs += @{
        Name = "${symbolClean}_DayTrading_M15"
        ProfileEnum = 0
        Period = "M15"
        Magic = 20261101
    }
}
if ($Profile -eq "SessionMomentum" -or $Profile -eq "All") {
    $runs += @{
        Name = "${symbolClean}_SessionMomentum_M5"
        ProfileEnum = 1
        Period = "M5"
        Magic = 20261102
    }
}
if ($Profile -eq "AsianRange" -or $Profile -eq "All") {
    $runs += @{
        Name = "${symbolClean}_AsianRange_M5"
        ProfileEnum = 2
        Period = "M5"
        Magic = 20261103
    }
}
if ($Profile -eq "MultiSessionHybrid" -or $Profile -eq "All") {
    $runs += @{
        Name = "${symbolClean}_MultiSessionHybrid_M15"
        ProfileEnum = 3
        Period = "M15"
        Magic = 20261100
    }
}

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "        AETERNA QUANT -- AUTOMATED STRATEGY TESTER BATCH RUNNER                " -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "Symbol         : $Symbol" -ForegroundColor Yellow
Write-Host "Period Range   : $FromDate -> $ToDate" -ForegroundColor Yellow
Write-Host "Deposit        : $Deposit USD | Leverage: 1:2000" -ForegroundColor Yellow
Write-Host "Execution Mode : Model=$Model (1=M1 OHLC, 0=Every Tick, 4=Real Ticks) | DelayMode=$ExecutionMode" -ForegroundColor Yellow
Write-Host "Total Scenarios: $($runs.Count)" -ForegroundColor Yellow
Write-Host ""

$summaryRecords = @()

foreach ($run in $runs) {
    $runName = $run.Name
    $period = $run.Period
    $profEnum = $run.ProfileEnum
    $magic = $run.Magic

    Write-Host "--------------------------------------------------------------------------------" -ForegroundColor DarkCyan
    Write-Host ">>> Executing Scenario: $runName ($period) [Magic: $magic]" -ForegroundColor Cyan
    Write-Host "--------------------------------------------------------------------------------" -ForegroundColor DarkCyan

    $reportBaseName = "Report_$runName"
    $iniPath = Join-Path $configDir "$runName.ini"

    $iniContent = @"
[Common]
Login=$login
Password=$pass
Server=$server

[Tester]
Expert=$Expert
Symbol=$Symbol
Period=$period
Deposit=$Deposit
Currency=USD
Leverage=2000
Model=$Model
ExecutionMode=$ExecutionMode
Optimization=0
FromDate=$FromDate
ToDate=$ToDate
ForwardMode=0
Report=$reportBaseName
ReplaceReport=1
ShutdownTerminal=1
Visual=0

[TesterInputs]
InpProfile=$profEnum
InpDryRun=false
InpEnforceNewsFilter=true
InpSlippageTolerancePts=50
InpMagicNumber=$magic
InpDonchianPeriod=$DonchianPeriod
InpAtrMultiplier=$AtrMultiplier
InpRewardRiskRatio=$RewardRiskRatio
"@

    Set-Content -Path $iniPath -Value $iniContent -Encoding UTF8

    # Pre-clean existing instance, reports, and cache to avoid stale reads
    Get-Process terminal64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1

    $reportSourceHtm = Join-Path $oandaData "$reportBaseName.htm"
    Remove-Item -Path $reportSourceHtm -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Path $oandaData -Filter "$reportBaseName*.png" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
    Remove-Item -Path "$oandaData\Tester\cache\*" -Force -Recurse -ErrorAction SilentlyContinue

    Write-Host "[*] Launching headless MetaTrader 5 Strategy Tester..." -ForegroundColor Gray
    $proc = Start-Process -FilePath $terminal -ArgumentList "/config:`"$iniPath`"" -PassThru

    $elapsed = 0
    $step = 3
    while (-not $proc.HasExited -and $elapsed -lt $TimeoutSeconds) {
        Start-Sleep -Seconds $step
        $elapsed += $step
        Write-Host "." -NoNewline -ForegroundColor DarkGray
    }
    Write-Host ""

    if (-not $proc.HasExited) {
        Write-Host "[WARNING] Process timed out after $TimeoutSeconds s. Terminating..." -ForegroundColor Red
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    } else {
        Write-Host "[+] Strategy Tester completed in $elapsed seconds (ExitCode: $($proc.ExitCode))." -ForegroundColor Green
    }

    # Locate generated report in terminal folder
    $reportSourceHtm = Join-Path $oandaData "$reportBaseName.htm"
    $scenarioReportDir = Join-Path $reportsDir $runName
    New-Item -ItemType Directory -Path $scenarioReportDir -Force | Out-Null

    if (Test-Path $reportSourceHtm) {
        # Copy HTML and associated PNG charts
        Copy-Item -Path $reportSourceHtm -Destination (Join-Path $scenarioReportDir "report.html") -Force
        Get-ChildItem -Path $oandaData -Filter "$reportBaseName*.png" | ForEach-Object {
            Copy-Item -Path $_.FullName -Destination $scenarioReportDir -Force
        }
        Write-Host "[+] Report files archived to: $scenarioReportDir" -ForegroundColor Green

        # Parse metrics from HTML
        $htmlText = Get-Content $reportSourceHtm -Raw

        function Extract-Val([string]$pattern, [string]$text, [string]$default="0") {
            if ($text -match $pattern) {
                return $matches[1].Trim().Replace("&nbsp;", " ")
            }
            return $default
        }

        $netProfit   = Extract-Val "Total Net Profit:</td>\s*<td[^>]*><b>([^<]+)</b>" $htmlText "0.0"
        $profitFactor= Extract-Val "Profit Factor:</td>\s*<td[^>]*><b>([^<]+)</b>" $htmlText "0.0"
        $expectedPay = Extract-Val "Expected Payoff:</td>\s*<td[^>]*><b>([^<]+)</b>" $htmlText "0.0"
        $totalTrades = Extract-Val "Total Trades:</td>\s*<td[^>]*><b>([^<]+)</b>" $htmlText "0"
        $maxDD       = Extract-Val "Equity Drawdown Maximal:</td>\s*<td[^>]*><b>([^<]+)</b>" $htmlText "0.0"
        $profitTrades= Extract-Val "Profit Trades \(% of total\):</td>\s*<td[^>]*><b>([^<]+)</b>" $htmlText "0 (0.00%)"
        $lossTrades  = Extract-Val "Loss Trades \(% of total\):</td>\s*<td[^>]*><b>([^<]+)</b>" $htmlText "0 (0.00%)"

        $rec = [PSCustomObject]@{
            Scenario       = $runName
            Period         = $period
            NetProfitUSD   = $netProfit
            ProfitFactor   = $profitFactor
            ExpectedPayoff = $expectedPay
            TotalTrades    = $totalTrades
            ProfitTrades   = $profitTrades
            LossTrades     = $lossTrades
            MaxDrawdown    = $maxDD
        }
        $summaryRecords += $rec

        Write-Host "    Net Profit     : $netProfit USD" -ForegroundColor White
        Write-Host "    Profit Factor  : $profitFactor" -ForegroundColor White
        Write-Host "    Expected Payoff: $expectedPay USD/trade" -ForegroundColor White
        Write-Host "    Total Trades   : $totalTrades" -ForegroundColor White
        Write-Host "    Win Rate       : $profitTrades" -ForegroundColor White
        Write-Host "    Max Drawdown   : $maxDD" -ForegroundColor White
    } else {
        Write-Host "[!] Report file not found at expected path: $reportSourceHtm" -ForegroundColor Red
        # Inspect tester logs
        $testerLogDir = Join-Path $oandaData "Tester\logs"
        if (Test-Path $testerLogDir) {
            $latestLog = Get-ChildItem -Path $testerLogDir | Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($latestLog) {
                Write-Host "--- Tail of $($latestLog.Name) ---" -ForegroundColor Yellow
                Get-Content $latestLog.FullName -Tail 15
            }
        }
    }
    Write-Host ""
}

# Export Summary CSV
if ($summaryRecords.Count -gt 0) {
    $summaryCsv = Join-Path $reportsDir "batch_summary.csv"
    $summaryRecords | Export-Csv -Path $summaryCsv -NoTypeInformation -Force
    Write-Host "================================================================================" -ForegroundColor Cyan
    Write-Host "                   HONEST BACKTEST PERFORMANCE SUMMARY                         " -ForegroundColor Cyan
    Write-Host "================================================================================" -ForegroundColor Cyan
    $summaryRecords | Format-Table -AutoSize | Out-String | Write-Host -ForegroundColor White
    Write-Host "[+] Consolidated report saved to: $summaryCsv" -ForegroundColor Green
}
