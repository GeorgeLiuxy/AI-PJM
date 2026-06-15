param(
    [switch]$SkipBackend,
    [switch]$SkipFrontend,
    [switch]$SkipProviderSmoke,
    [switch]$SkipAudit,
    [switch]$SkipBuild,
    [int]$AuditRetries = 3,
    [switch]$ContinueOnError
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
$Results = New-Object System.Collections.Generic.List[object]

function Add-Result {
    param(
        [string]$Name,
        [string]$Status,
        [double]$Seconds,
        [string]$ErrorMessage = ""
    )

    $Results.Add([pscustomobject]@{
        name = $Name
        status = $Status
        seconds = [math]::Round($Seconds, 2)
        error = $ErrorMessage
    }) | Out-Null
}

function Invoke-Check {
    param(
        [string]$Name,
        [string]$WorkingDirectory,
        [scriptblock]$Command
    )

    Write-Host ""
    Write-Host "==> $Name"
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $Command
        if ($LASTEXITCODE -ne 0) {
            throw "$Name exited with code $LASTEXITCODE"
        }
        $timer.Stop()
        Add-Result -Name $Name -Status "passed" -Seconds $timer.Elapsed.TotalSeconds
        Write-Host "PASS $Name ($([math]::Round($timer.Elapsed.TotalSeconds, 2))s)"
    } catch {
        $timer.Stop()
        Add-Result -Name $Name -Status "failed" -Seconds $timer.Elapsed.TotalSeconds -ErrorMessage ([string]$_.Exception.Message)
        Write-Host "FAIL $Name ($([math]::Round($timer.Elapsed.TotalSeconds, 2))s)"
        Write-Host $_.Exception.Message
        if (-not $ContinueOnError) {
            throw
        }
    } finally {
        Pop-Location
    }
}

if (-not $SkipBackend) {
    Invoke-Check -Name "backend critical tests" -WorkingDirectory $BackendDir -Command {
        python -m pytest tests/test_auth.py tests/test_delivery_v2_units.py tests/test_delivery_v2.py tests/test_migrations.py tests/test_health.py -q
    }

    if (-not $SkipProviderSmoke) {
        Invoke-Check -Name "local provider quality smoke" -WorkingDirectory $BackendDir -Command {
            python scripts/provider_quality_smoke.py --provider local --spec-only --min-score 0.65
        }
    }
}

if (-not $SkipFrontend) {
    if (-not $SkipAudit) {
        Invoke-Check -Name "frontend npm audit" -WorkingDirectory $FrontendDir -Command {
            $attempts = [math]::Max(1, $AuditRetries)
            for ($attempt = 1; $attempt -le $attempts; $attempt++) {
                npm audit --audit-level=high
                if ($LASTEXITCODE -eq 0) {
                    return
                }
                if ($attempt -lt $attempts) {
                    Write-Host "npm audit failed on attempt $attempt/$attempts; retrying..."
                    Start-Sleep -Seconds 3
                }
            }
            throw "npm audit failed after $attempts attempt(s)."
        }
    }

    Invoke-Check -Name "frontend regression tests" -WorkingDirectory $FrontendDir -Command {
        npm test -- --run
    }

    if (-not $SkipBuild) {
        Invoke-Check -Name "frontend production build" -WorkingDirectory $FrontendDir -Command {
            npm run build
        }
    }
}

Write-Host ""
Write-Host "Production readiness check summary"
$Results | Format-Table -AutoSize

$Failed = @($Results | Where-Object { $_.status -ne "passed" })
if ($Failed.Count -gt 0) {
    exit 1
}

Write-Host "All selected checks passed."
