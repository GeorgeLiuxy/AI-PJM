param(
    [switch]$IncludePostgres,
    [ValidateSet("local", "dify", "openai", "all")]
    [string]$Provider = "local",
    [double]$ProviderMinScore = 0.75,
    [int]$AuditRetries = 1,
    [switch]$SkipAudit,
    [switch]$BuildComposeImages,
    [switch]$CheckSymphonyRunner,
    [switch]$UseRecommendedCodexRunner,
    [switch]$RequireCodexRunner,
    [switch]$ExecuteSymphonyRunner,
    [switch]$CheckRemoteActions
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Command
    )

    Write-Host ""
    Write-Host "==== $Name ===="
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

Invoke-Step -Name "Production readiness baseline" -Command {
    if ($SkipAudit) {
        & (Join-Path $Root "scripts\check-production-readiness.ps1") -AuditRetries $AuditRetries -SkipAudit
    } else {
        & (Join-Path $Root "scripts\check-production-readiness.ps1") -AuditRetries $AuditRetries
    }
}

if ($IncludePostgres) {
    Invoke-Step -Name "PostgreSQL migration smoke" -Command {
        & (Join-Path $Root "scripts\check-postgres-migrations.ps1")
    }
}

Invoke-Step -Name "Production compose config" -Command {
    if ($BuildComposeImages) {
        & (Join-Path $Root "scripts\check-production-compose.ps1") -BuildImages
    } else {
        & (Join-Path $Root "scripts\check-production-compose.ps1")
    }
}

Invoke-Step -Name "Provider quality smoke" -Command {
    & (Join-Path $Root "scripts\check-provider-quality.ps1") -Provider $Provider -MinScore $ProviderMinScore
}

if ($CheckSymphonyRunner) {
    Invoke-Step -Name "Symphony runner validation" -Command {
        & (Join-Path $Root "scripts\check-symphony-runner.ps1") `
            -UseRecommendedCodexCommand:$UseRecommendedCodexRunner `
            -RequireCodex:$RequireCodexRunner `
            -Execute:$ExecuteSymphonyRunner
    }
}

if ($CheckRemoteActions) {
    Invoke-Step -Name "GitHub Actions validation" -Command {
        & (Join-Path $Root "scripts\check-github-actions.ps1") -Wait
    }
}

Write-Host ""
Write-Host "Production suite passed."
