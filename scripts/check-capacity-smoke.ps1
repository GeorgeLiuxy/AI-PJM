param(
    [int]$Count = 10000,
    [int]$BatchSize = 500,
    [string]$Prefix = "capacity",
    [switch]$IncludeDeliveryRecords,
    [switch]$SkipSeed,
    [switch]$AllowProduction,
    [string]$BaseUrl = $(if ($env:AI_PJM_PERF_BASE_URL) { $env:AI_PJM_PERF_BASE_URL } else { "http://127.0.0.1:8010" }),
    [int]$Requests = 120,
    [int]$Concurrency = 12,
    [double]$MaxP95Ms = 1000,
    [double]$MaxErrorRatePercent = 1,
    [string]$Token = $(if ($env:AI_PJM_API_TOKEN) { $env:AI_PJM_API_TOKEN } else { "" })
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendDir = Join-Path $Root "backend"
$OutputDir = Join-Path $Root ".runtime\capacity"
$Timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

function Invoke-CapturedCommand {
    param(
        [string]$Name,
        [string]$WorkingDirectory,
        [string[]]$Command,
        [string]$OutputFile
    )

    Write-Host ""
    Write-Host "==> $Name"
    Push-Location -LiteralPath $WorkingDirectory
    try {
        $commandArgs = @()
        if ($Command.Length -gt 1) {
            $commandArgs = @($Command[1..($Command.Length - 1)])
        }
        $output = & $Command[0] @commandArgs 2>&1
        $exitCode = $LASTEXITCODE
        $output | Set-Content -Encoding utf8 -LiteralPath $OutputFile
        $output | ForEach-Object { Write-Host $_ }
        if ($exitCode -ne 0) {
            throw "$Name failed with exit code $exitCode. Output saved to $OutputFile"
        }
    } finally {
        Pop-Location
    }
}

if (-not $SkipSeed) {
    $seedArgs = @(
        "scripts/seed_delivery_capacity.py",
        "--count",
        [string]$Count,
        "--batch-size",
        [string]$BatchSize,
        "--prefix",
        $Prefix,
        "--confirm"
    )
    if ($IncludeDeliveryRecords) {
        $seedArgs += "--include-delivery-records"
    }
    if ($AllowProduction) {
        $seedArgs += "--allow-production"
    }

    $seedCommand = @("python") + $seedArgs
    Invoke-CapturedCommand -Name "capacity seed" -WorkingDirectory $BackendDir -Command $seedCommand -OutputFile (Join-Path $OutputDir "capacity-seed-$Timestamp.json")
}

$perfArgs = @(
    "scripts/performance_smoke.py",
    "--base-url",
    $BaseUrl,
    "--requests",
    [string]$Requests,
    "--concurrency",
    [string]$Concurrency,
    "--max-p95-ms",
    [string]$MaxP95Ms,
    "--max-error-rate-percent",
    [string]$MaxErrorRatePercent
)
if ($Token) {
    $perfArgs += @("--token", $Token)
}

$perfCommand = @("python") + $perfArgs
Invoke-CapturedCommand -Name "capacity performance smoke" -WorkingDirectory $BackendDir -Command $perfCommand -OutputFile (Join-Path $OutputDir "capacity-performance-$Timestamp.json")

Write-Host ""
Write-Host "Capacity smoke checks passed. Evidence directory: $OutputDir"
