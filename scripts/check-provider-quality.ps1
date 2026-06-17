param(
    [ValidateSet("local", "dify", "openai", "all")]
    [string]$Provider = "local",
    [double]$MinScore = 0.75,
    [string]$OutputFile = "",
    [string]$DemandFile = "",
    [int]$SampleLimit = 0,
    [switch]$IncludeImpact
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendDir = Join-Path $Root "backend"

if ($DemandFile) {
    if ([System.IO.Path]::IsPathRooted($DemandFile)) {
        $DemandFile = (Resolve-Path -LiteralPath $DemandFile).Path
    } else {
        $DemandFile = (Resolve-Path -LiteralPath (Join-Path $Root $DemandFile)).Path
    }
}

if (-not $OutputFile) {
    $timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $OutputDir = Join-Path $Root ".runtime\provider-quality"
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    $OutputFile = Join-Path $OutputDir "provider-quality-$Provider-$timestamp.json"
}

$argsList = @(
    "scripts/provider_quality_smoke.py",
    "--provider",
    $Provider,
    "--min-score",
    ([string]$MinScore),
    "--output-file",
    $OutputFile
)

if (-not $IncludeImpact) {
    $argsList += "--spec-only"
}
if ($DemandFile) {
    $argsList += @("--demand-file", $DemandFile)
}
if ($SampleLimit -gt 0) {
    $argsList += @("--sample-limit", [string]$SampleLimit)
}

Push-Location -LiteralPath $BackendDir
try {
    Write-Host "Running provider quality smoke for provider '$Provider'."
    Write-Host "Output file: $OutputFile"
    python @argsList
    if ($LASTEXITCODE -ne 0) {
        throw "Provider quality smoke failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

Write-Host "Provider quality smoke passed."
