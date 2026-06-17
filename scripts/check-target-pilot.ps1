param(
    [string]$BaseUrl = $(if ($env:AI_PJM_TARGET_BASE_URL) { $env:AI_PJM_TARGET_BASE_URL } else { "http://127.0.0.1:8080" }),
    [string]$Username = $(if ($env:AUTH_BOOTSTRAP_ADMIN_USERNAME) { $env:AUTH_BOOTSTRAP_ADMIN_USERNAME } else { "admin" }),
    [string]$Password = $(if ($env:AUTH_BOOTSTRAP_ADMIN_PASSWORD) { $env:AUTH_BOOTSTRAP_ADMIN_PASSWORD } else { "" }),
    [string]$ApiToken = $(if ($env:AI_PJM_API_TOKEN) { $env:AI_PJM_API_TOKEN } else { "" }),
    [string]$SymphonyBridgeToken = $(if ($env:SYMPHONY_BRIDGE_TOKEN) { $env:SYMPHONY_BRIDGE_TOKEN } else { "" }),
    [string]$OutputFile = "",
    [switch]$SkipSymphonyBridge,
    [switch]$RunProviderQuality,
    [ValidateSet("local", "dify", "openai", "all")]
    [string]$Provider = "local",
    [double]$ProviderMinScore = 0.75,
    [switch]$ContinueOnBlocker
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BaseUrl = $BaseUrl.TrimEnd("/")
$Checks = New-Object System.Collections.Generic.List[object]

if (-not $OutputFile) {
    $timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $OutputDir = Join-Path $Root ".runtime\target-pilot"
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    $OutputFile = Join-Path $OutputDir "target-pilot-$timestamp.json"
}

function New-CheckResult {
    param(
        [string]$Id,
        [string]$Title,
        [ValidateSet("passed", "warning", "failed", "skipped")]
        [string]$Status,
        [bool]$Blocker,
        [string]$Summary,
        [string]$NextAction = "",
        [hashtable]$Evidence = @{}
    )

    $Checks.Add([pscustomobject]@{
        id = $Id
        title = $Title
        status = $Status
        blocker = $Blocker
        summary = $Summary
        next_action = $NextAction
        evidence = $Evidence
    }) | Out-Null
}

function Invoke-Http {
    param(
        [string]$Method,
        [string]$Uri,
        [hashtable]$Headers = @{},
        [object]$Body = $null
    )

    $request = [System.Net.HttpWebRequest]::Create($Uri)
    $request.Method = $Method
    $request.Accept = "*/*"
    $request.Timeout = 30000
    $request.ReadWriteTimeout = 30000

    foreach ($name in $Headers.Keys) {
        if ($name -eq "Authorization") {
            $request.Headers["Authorization"] = [string]$Headers[$name]
        } else {
            $request.Headers.Add($name, [string]$Headers[$name])
        }
    }

    if ($null -ne $Body) {
        $request.ContentType = "application/json"
        $json = $Body | ConvertTo-Json -Depth 16 -Compress
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
        $request.ContentLength = $bytes.Length
        $stream = $request.GetRequestStream()
        try {
            $stream.Write($bytes, 0, $bytes.Length)
        } finally {
            $stream.Dispose()
        }
    }

    try {
        $response = $request.GetResponse()
    } catch [System.Net.WebException] {
        $response = $_.Exception.Response
        if ($null -eq $response) {
            throw
        }
    }

    $statusCode = [int]$response.StatusCode
    $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
    try {
        $text = $reader.ReadToEnd()
    } finally {
        $reader.Dispose()
        $response.Dispose()
    }

    return [pscustomobject]@{
        status_code = $statusCode
        body = $text
    }
}

function Convert-JsonBody {
    param([string]$Text)
    if (-not $Text) {
        return $null
    }
    return $Text | ConvertFrom-Json
}

function Get-AuthHeaders {
    param([string]$Token)
    return @{ Authorization = "Bearer $Token" }
}

Write-Host "Target pilot readiness check"
Write-Host "Base URL: $BaseUrl"

$token = $ApiToken

try {
    $health = Invoke-Http -Method "GET" -Uri "$BaseUrl/health"
    if ($health.status_code -ge 200 -and $health.status_code -lt 300) {
        New-CheckResult -Id "http_health" -Title "HTTP health" -Status "passed" -Blocker $true -Summary "Application health endpoint is reachable." -Evidence @{
            status_code = $health.status_code
            url = "$BaseUrl/health"
        }
    } else {
        New-CheckResult -Id "http_health" -Title "HTTP health" -Status "failed" -Blocker $true -Summary "Application health endpoint returned HTTP $($health.status_code)." -NextAction "Start or repair the target AI PJM service before pilot validation." -Evidence @{
            status_code = $health.status_code
            url = "$BaseUrl/health"
        }
    }
} catch {
    New-CheckResult -Id "http_health" -Title "HTTP health" -Status "failed" -Blocker $true -Summary "Application health endpoint is not reachable." -NextAction "Start or repair the target AI PJM service before pilot validation." -Evidence @{
        url = "$BaseUrl/health"
        error = $_.Exception.Message
    }
}

if (-not $token) {
    if (-not $Password) {
        New-CheckResult -Id "auth" -Title "Authentication" -Status "failed" -Blocker $true -Summary "No API token or password was provided." -NextAction "Pass -ApiToken or -Password, or set AI_PJM_API_TOKEN / AUTH_BOOTSTRAP_ADMIN_PASSWORD."
    } else {
        try {
            $login = Invoke-Http -Method "POST" -Uri "$BaseUrl/api/v2/auth/login" -Body @{
                username = $Username
                password = $Password
            }
            $loginBody = Convert-JsonBody -Text $login.body
            $token = [string]$loginBody.data.access_token
            if ($login.status_code -ge 200 -and $login.status_code -lt 300 -and $token) {
                New-CheckResult -Id "auth" -Title "Authentication" -Status "passed" -Blocker $true -Summary "Authenticated against the target environment." -Evidence @{
                    username = $Username
                    token_type = [string]$loginBody.data.token_type
                }
            } else {
                New-CheckResult -Id "auth" -Title "Authentication" -Status "failed" -Blocker $true -Summary "Login did not return a bearer token." -NextAction "Verify target admin credentials or provide AI_PJM_API_TOKEN." -Evidence @{
                    status_code = $login.status_code
                    username = $Username
                }
            }
        } catch {
            New-CheckResult -Id "auth" -Title "Authentication" -Status "failed" -Blocker $true -Summary "Login failed." -NextAction "Verify target admin credentials or provide AI_PJM_API_TOKEN." -Evidence @{
                username = $Username
                error = $_.Exception.Message
            }
        }
    }
} else {
    New-CheckResult -Id "auth" -Title "Authentication" -Status "passed" -Blocker $true -Summary "Using provided API token." -Evidence @{
        token_source = "parameter_or_environment"
    }
}

if ($token) {
    $authHeaders = Get-AuthHeaders -Token $token
    try {
        $config = Invoke-Http -Method "GET" -Uri "$BaseUrl/api/v2/observability/config-health" -Headers $authHeaders
        $configBody = Convert-JsonBody -Text $config.body
        $configData = $configBody.data
        $checksById = @{}
        foreach ($check in @($configData.checks)) {
            $checksById[[string]$check.id] = $check
        }

        $pilotBlockingIds = @(
            "database",
            "workspace_root",
            "git",
            "secret_store",
            "workflow_provider",
            "merge_request_provider",
            "deployment_provider",
            "worker_scripts"
        )
        $criticalChecks = @($configData.checks | Where-Object { $_.status -eq "critical" })
        $pilotBlockers = @()
        foreach ($id in $pilotBlockingIds) {
            if (-not $checksById.ContainsKey($id)) {
                $pilotBlockers += [pscustomobject]@{ id = $id; status = "missing"; title = "Missing config check"; next_action = "Update config-health to expose this required check." }
                continue
            }
            $check = $checksById[$id]
            if ($check.status -ne "healthy") {
                $pilotBlockers += $check
            }
        }
        $warnings = @($configData.checks | Where-Object { $_.status -eq "warning" })

        if ($criticalChecks.Count -gt 0 -or $pilotBlockers.Count -gt 0) {
            New-CheckResult -Id "config_health" -Title "Configuration health" -Status "failed" -Blocker $true -Summary "Configuration has pilot-blocking issues." -NextAction "Fix database/workspace/git/secrets/MR/deployment/worker configuration before a real pilot." -Evidence @{
                overall_status = [string]$configData.status
                critical_count = $criticalChecks.Count
                pilot_blockers = @($pilotBlockers | ForEach-Object { "$($_.id):$($_.status)" })
                warnings = @($warnings | ForEach-Object { "$($_.id):$($_.status)" })
            }
        } elseif ($warnings.Count -gt 0) {
            New-CheckResult -Id "config_health" -Title "Configuration health" -Status "warning" -Blocker $false -Summary "Configuration is usable, with non-blocking warnings." -NextAction "Review warning checks after the pilot path is stable." -Evidence @{
                overall_status = [string]$configData.status
                warnings = @($warnings | ForEach-Object { "$($_.id):$($_.status)" })
            }
        } else {
            New-CheckResult -Id "config_health" -Title "Configuration health" -Status "passed" -Blocker $true -Summary "Configuration health is ready for pilot validation." -Evidence @{
                overall_status = [string]$configData.status
            }
        }
    } catch {
        New-CheckResult -Id "config_health" -Title "Configuration health" -Status "failed" -Blocker $true -Summary "Unable to read configuration health." -NextAction "Verify auth, backend routing, and /api/v2/observability/config-health." -Evidence @{
            error = $_.Exception.Message
        }
    }

    try {
        $metrics = Invoke-Http -Method "GET" -Uri "$BaseUrl/api/v2/observability/metrics" -Headers $authHeaders
        if ($metrics.status_code -ge 200 -and $metrics.status_code -lt 300 -and $metrics.body -match "ai_pjm_observability_status_code") {
            New-CheckResult -Id "metrics" -Title "Prometheus metrics" -Status "passed" -Blocker $true -Summary "Prometheus metrics endpoint is readable." -Evidence @{
                status_code = $metrics.status_code
                has_observability_status = $true
            }
        } else {
            New-CheckResult -Id "metrics" -Title "Prometheus metrics" -Status "failed" -Blocker $true -Summary "Metrics endpoint did not return expected AI PJM metrics." -NextAction "Verify /api/v2/observability/metrics and auth configuration." -Evidence @{
                status_code = $metrics.status_code
            }
        }
    } catch {
        New-CheckResult -Id "metrics" -Title "Prometheus metrics" -Status "failed" -Blocker $true -Summary "Unable to read Prometheus metrics." -NextAction "Verify /api/v2/observability/metrics and auth configuration." -Evidence @{
            error = $_.Exception.Message
        }
    }
}

if ($SkipSymphonyBridge) {
    New-CheckResult -Id "symphony_bridge" -Title "Symphony bridge" -Status "skipped" -Blocker $false -Summary "Symphony bridge check was skipped." -NextAction "Run without -SkipSymphonyBridge before a real pilot."
} elseif (-not $SymphonyBridgeToken) {
    New-CheckResult -Id "symphony_bridge" -Title "Symphony bridge" -Status "failed" -Blocker $true -Summary "No Symphony bridge token was provided." -NextAction "Pass -SymphonyBridgeToken or set SYMPHONY_BRIDGE_TOKEN."
} else {
    try {
        $queue = Invoke-Http -Method "GET" -Uri "$BaseUrl/api/v2/internal/symphony/execution-runs?limit=1" -Headers @{
            "X-Symphony-Bridge-Token" = $SymphonyBridgeToken
        }
        $queueBody = Convert-JsonBody -Text $queue.body
        if ($queue.status_code -ge 200 -and $queue.status_code -lt 300) {
            $queueCount = @($queueBody.data).Count
            New-CheckResult -Id "symphony_bridge" -Title "Symphony bridge" -Status "passed" -Blocker $true -Summary "Symphony bridge API is reachable." -Evidence @{
                queued_sample_count = $queueCount
                status_code = $queue.status_code
            }
        } else {
            New-CheckResult -Id "symphony_bridge" -Title "Symphony bridge" -Status "failed" -Blocker $true -Summary "Symphony bridge API returned HTTP $($queue.status_code)." -NextAction "Verify SYMPHONY_BRIDGE_TOKEN and backend internal routing." -Evidence @{
                status_code = $queue.status_code
            }
        }
    } catch {
        New-CheckResult -Id "symphony_bridge" -Title "Symphony bridge" -Status "failed" -Blocker $true -Summary "Unable to reach Symphony bridge API." -NextAction "Verify SYMPHONY_BRIDGE_TOKEN and backend internal routing." -Evidence @{
            error = $_.Exception.Message
        }
    }
}

if ($RunProviderQuality) {
    $providerOutput = Join-Path (Split-Path -Parent $OutputFile) "provider-quality-$Provider.json"
    try {
        & (Join-Path $Root "scripts\check-provider-quality.ps1") -Provider $Provider -MinScore $ProviderMinScore -OutputFile $providerOutput
        if ($LASTEXITCODE -eq 0) {
            New-CheckResult -Id "provider_quality" -Title "Provider quality" -Status "passed" -Blocker $true -Summary "Provider quality smoke passed." -Evidence @{
                provider = $Provider
                output_file = $providerOutput
                min_score = $ProviderMinScore
            }
        } else {
            New-CheckResult -Id "provider_quality" -Title "Provider quality" -Status "failed" -Blocker $true -Summary "Provider quality smoke exited with code $LASTEXITCODE." -NextAction "Fix provider configuration or keep provider disabled for pilot." -Evidence @{
                provider = $Provider
                output_file = $providerOutput
            }
        }
    } catch {
        New-CheckResult -Id "provider_quality" -Title "Provider quality" -Status "failed" -Blocker $true -Summary "Provider quality smoke failed." -NextAction "Fix provider configuration or keep provider disabled for pilot." -Evidence @{
            provider = $Provider
            output_file = $providerOutput
            error = $_.Exception.Message
        }
    }
}

$Blockers = @($Checks | Where-Object { $_.blocker -and $_.status -ne "passed" })
$Followups = @($Checks | Where-Object { -not $_.blocker -and $_.status -ne "passed" })
$Report = [pscustomobject]@{
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    base_url = $BaseUrl
    status = $(if ($Blockers.Count -gt 0) { "blocked" } elseif ($Followups.Count -gt 0) { "warning" } else { "ready" })
    blocker_count = $Blockers.Count
    followup_count = $Followups.Count
    blockers = @($Blockers | ForEach-Object { $_.id })
    followups = @($Followups | ForEach-Object { $_.id })
    checks = $Checks
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputFile) | Out-Null
$Report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputFile -Encoding UTF8

Write-Host ""
Write-Host "Target pilot readiness summary"
$Checks | Select-Object id, status, blocker, summary | Format-Table -AutoSize
Write-Host "Report: $OutputFile"

if ($Blockers.Count -gt 0) {
    Write-Host ""
    Write-Host "Blocking checks:"
    $Blockers | Select-Object id, summary, next_action | Format-Table -AutoSize
    if (-not $ContinueOnBlocker) {
        exit 1
    }
}

if ($Followups.Count -gt 0) {
    Write-Host ""
    Write-Host "Non-blocking follow-ups:"
    $Followups | Select-Object id, summary, next_action | Format-Table -AutoSize
}

if ($Blockers.Count -eq 0) {
    Write-Host "Target pilot readiness checks passed."
}
