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

function Get-ProviderNames {
    param([string]$SelectedProvider)

    if ($SelectedProvider -eq "all") {
        return @("local", "dify", "openai")
    }
    return @($SelectedProvider)
}

function Get-MissingProviderConfig {
    param(
        [string]$ProviderName,
        [bool]$RunImpact
    )

    $missing = New-Object System.Collections.Generic.List[string]
    if ($ProviderName -eq "dify") {
        if (-not $env:DIFY_API_BASE_URL) { $missing.Add("DIFY_API_BASE_URL") | Out-Null }
        if (-not $env:DIFY_API_KEY) { $missing.Add("DIFY_API_KEY") | Out-Null }
        if (-not $env:DIFY_SPEC_WORKFLOW_ID) { $missing.Add("DIFY_SPEC_WORKFLOW_ID") | Out-Null }
        if ($RunImpact -and -not $env:DIFY_IMPACT_WORKFLOW_ID) { $missing.Add("DIFY_IMPACT_WORKFLOW_ID") | Out-Null }
    } elseif ($ProviderName -eq "openai") {
        if (-not $env:OPENAI_API_KEY) { $missing.Add("OPENAI_API_KEY") | Out-Null }
    }
    return @($missing)
}

function Write-ExternalBlockerReport {
    param(
        [array]$ExternalBlockers,
        [string]$Path
    )

    $report = [pscustomobject]@{
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        provider = $Provider
        status = "blocked"
        passed = $false
        external_blocker = $true
        summary = "Provider quality smoke requires external provider configuration."
        blockers = $ExternalBlockers
        next_action = "Configure the missing provider credentials/workflow ids, or run -Provider local for local-only validation."
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Path -Encoding UTF8
    Write-Host "Provider quality smoke blocked by missing external configuration."
    Write-Host "Report: $Path"
}

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

$externalBlockers = @()
foreach ($providerName in (Get-ProviderNames -SelectedProvider $Provider)) {
    $missing = @(Get-MissingProviderConfig -ProviderName $providerName -RunImpact ([bool]$IncludeImpact))
    if ($missing.Count -gt 0) {
        $externalBlockers += [pscustomobject]@{
            provider = $providerName
            missing = $missing
        }
    }
}

if ($externalBlockers.Count -gt 0) {
    Write-ExternalBlockerReport -ExternalBlockers $externalBlockers -Path $OutputFile
    throw "Provider quality external blocker: missing external provider configuration."
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
