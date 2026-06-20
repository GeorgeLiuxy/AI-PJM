param(
    [ValidateSet("webhook", "local-config")]
    [string]$Provider = "webhook",
    [string]$Environment = "test",
    [string]$DeployWebhookUrl = $(if ($env:DEPLOY_WEBHOOK_URL) { $env:DEPLOY_WEBHOOK_URL } else { "" }),
    [string]$DeployToken = $(if ($env:DEPLOY_TOKEN) { $env:DEPLOY_TOKEN } else { "" }),
    [string]$DeployEnvironmentConfigJson = $(if ($env:DEPLOY_ENVIRONMENT_CONFIG_JSON) { $env:DEPLOY_ENVIRONMENT_CONFIG_JSON } else { "" }),
    [string]$OutputFile = "",
    [switch]$ContinueOnFailure
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $OutputFile) {
    $timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $suffix = [guid]::NewGuid().ToString("N").Substring(0, 8)
    $OutputDir = Join-Path $Root ".runtime\deployment-provider"
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    $OutputFile = Join-Path $OutputDir "deployment-provider-$timestamp-$suffix.json"
}

function Test-AbsoluteHttpUrl {
    param([string]$Value)
    if (-not $Value) {
        return $false
    }
    $uri = $null
    if (-not [System.Uri]::TryCreate($Value, [System.UriKind]::Absolute, [ref]$uri)) {
        return $false
    }
    return $uri.Scheme -in @("http", "https")
}

function Read-EnvironmentConfig {
    param([string]$JsonText)

    if (-not $JsonText) {
        return [pscustomobject]@{
            ok = $true
            configured = $false
            error = ""
            environments = @()
            selected = $null
            selected_has_url = $false
            selected_has_log_url = $false
        }
    }

    try {
        $parsed = $JsonText | ConvertFrom-Json
    } catch {
        return [pscustomobject]@{
            ok = $false
            configured = $true
            error = $_.Exception.Message
            environments = @()
            selected = $null
            selected_has_url = $false
            selected_has_log_url = $false
        }
    }

    $names = @($parsed.PSObject.Properties | ForEach-Object { $_.Name })
    $selectedProperty = $parsed.PSObject.Properties[$Environment]
    $selected = if ($selectedProperty) { $selectedProperty.Value } else { $null }
    $selectedHasUrl = $false
    $selectedHasLogUrl = $false
    if ($selected -is [string]) {
        $selectedHasUrl = Test-AbsoluteHttpUrl $selected
    } elseif ($selected) {
        $url = [string]($selected.url)
        $logUrl = [string]($selected.log_url)
        $selectedHasUrl = Test-AbsoluteHttpUrl $url
        $selectedHasLogUrl = Test-AbsoluteHttpUrl $logUrl
    }

    return [pscustomobject]@{
        ok = $true
        configured = $true
        error = ""
        environments = $names
        selected = $Environment
        selected_has_url = $selectedHasUrl
        selected_has_log_url = $selectedHasLogUrl
    }
}

$environmentConfig = Read-EnvironmentConfig -JsonText $DeployEnvironmentConfigJson
$missing = @()
$warnings = @()
$errors = @()

if ($Provider -eq "webhook") {
    if (-not $DeployWebhookUrl) {
        $missing += "DEPLOY_WEBHOOK_URL"
    } elseif (-not (Test-AbsoluteHttpUrl $DeployWebhookUrl)) {
        $errors += "DEPLOY_WEBHOOK_URL must be an absolute http or https URL."
    }
    if (-not $DeployToken) {
        $missing += "DEPLOY_TOKEN or project deploy_token"
    }
}

if (-not $environmentConfig.ok) {
    $errors += "DEPLOY_ENVIRONMENT_CONFIG_JSON is invalid JSON: $($environmentConfig.error)"
} elseif ($environmentConfig.configured -and -not $environmentConfig.selected_has_url) {
    $warnings += "Environment '$Environment' has no valid fallback url in DEPLOY_ENVIRONMENT_CONFIG_JSON."
}

if ($Provider -eq "local-config" -and -not $environmentConfig.configured) {
    $missing += "DEPLOY_ENVIRONMENT_CONFIG_JSON"
} elseif ($Provider -eq "local-config" -and -not $environmentConfig.selected_has_url) {
    $missing += "DEPLOY_ENVIRONMENT_CONFIG_JSON.$Environment.url"
}

$status = "passed"
$summary = "Deployment provider preflight passed."
$nextAction = "Use a real low-risk deployment pilot to verify webhook response, status_url, log_url, and failure parsing."
if ($errors.Count -gt 0) {
    $status = "failed"
    $summary = "Deployment provider configuration is invalid."
    $nextAction = "Fix configuration errors and rerun this script."
} elseif ($missing.Count -gt 0) {
    $status = "blocked"
    $summary = "Deployment provider is missing configuration."
    $nextAction = "Configure $($missing -join ', ') before triggering real test deployments."
}

$result = [pscustomobject]@{
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    provider = $Provider
    status = $status
    blocker = $status -ne "passed"
    summary = $summary
    next_action = $nextAction
    evidence = @{
        environment = $Environment
        webhook_url_present = [bool]$DeployWebhookUrl
        webhook_url_valid = $(if ($DeployWebhookUrl) { Test-AbsoluteHttpUrl $DeployWebhookUrl } else { $false })
        deploy_token_present = [bool]$DeployToken
        environment_config = $environmentConfig
        destructive_actions = $false
        missing = $missing
        warnings = $warnings
        errors = $errors
    }
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputFile) | Out-Null
$result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputFile -Encoding UTF8

Write-Host "Deployment provider validation"
Write-Host "Status:  $($result.status)"
Write-Host "Summary: $($result.summary)"
Write-Host "Report:  $OutputFile"

if ($result.status -ne "passed" -and -not $ContinueOnFailure) {
    exit 1
}
