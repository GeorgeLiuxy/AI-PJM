param(
    [switch]$BuildImages,
    [switch]$SmokeUp,
    [switch]$WithWorkers,
    [switch]$KeepRunning,
    [switch]$PreserveSmokeVolumes,
    [string]$ProjectName = "ai-pjm-smoke",
    [int]$BackendPort = 18010,
    [int]$FrontendPort = 18080,
    [int]$HealthTimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ComposeFile = Join-Path $Root "docker-compose.production.yml"
$EnvFile = Join-Path $Root "docker-compose.production.env.example"

function Invoke-Compose {
    param(
        [string]$Name,
        [string[]]$Arguments
    )

    Write-Host ""
    Write-Host "==> $Name"
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

function Invoke-SmokeHttpCheck {
    param(
        [string]$Name,
        [string]$Uri,
        [int]$TimeoutSeconds,
        [string]$ExpectedText = ""
    )

    Write-Host ""
    Write-Host "==> $Name"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = ""
    while ((Get-Date) -lt $deadline) {
        try {
            $request = [System.Net.HttpWebRequest]::Create($Uri)
            $request.Method = "GET"
            $request.Proxy = $null
            $request.Timeout = 5000
            $request.ReadWriteTimeout = 5000
            $response = $request.GetResponse()
            $statusCode = [int]$response.StatusCode
            $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
            try {
                $body = $reader.ReadToEnd()
            } finally {
                $reader.Dispose()
                $response.Dispose()
            }

            if ($statusCode -ge 200 -and $statusCode -lt 300) {
                if (-not $ExpectedText -or $body -match $ExpectedText) {
                    Write-Host "$Name passed with HTTP $statusCode"
                    return
                }
                $lastError = "$Name returned HTTP $statusCode but did not contain expected text."
            } else {
                $lastError = "$Name returned HTTP $statusCode."
            }
        } catch {
            $lastError = $_.Exception.Message
        }
        Start-Sleep -Seconds 3
    }

    throw "$Name did not become healthy within $TimeoutSeconds second(s). Last error: $lastError"
}

function Get-ComposeBaseArguments {
    $arguments = @(
        "compose",
        "-p",
        $ProjectName,
        "--env-file",
        $EnvFile,
        "-f",
        $ComposeFile
    )
    if ($WithWorkers) {
        $arguments += @("--profile", "workers")
    }
    return $arguments
}

if (-not (Test-Path -LiteralPath $ComposeFile)) {
    throw "Missing compose file: $ComposeFile"
}

if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Missing compose env example: $EnvFile"
}

Invoke-Compose -Name "production compose config" -Arguments @(
    "compose",
    "--env-file",
    $EnvFile,
    "-f",
    $ComposeFile,
    "config",
    "--quiet"
)

Invoke-Compose -Name "production compose worker profile config" -Arguments @(
    "compose",
    "--env-file",
    $EnvFile,
    "-f",
    $ComposeFile,
    "--profile",
    "workers",
    "config",
    "--quiet"
)

if ($BuildImages) {
    Invoke-Compose -Name "production compose image build" -Arguments @(
        "compose",
        "--env-file",
        $EnvFile,
        "-f",
        $ComposeFile,
        "build",
        "backend",
        "frontend"
    )
}

if ($SmokeUp) {
    $previousBackendPort = $env:BACKEND_PORT
    $previousFrontendPort = $env:FRONTEND_PORT
    $previousDeliveryAppBaseUrl = $env:DELIVERY_APP_BASE_URL
    $previousCorsOrigins = $env:CORS_ORIGINS

    $env:BACKEND_PORT = [string]$BackendPort
    $env:FRONTEND_PORT = [string]$FrontendPort
    $env:DELIVERY_APP_BASE_URL = "http://localhost:$FrontendPort"
    $env:CORS_ORIGINS = "[`"http://localhost:$FrontendPort`"]"

    $baseArguments = Get-ComposeBaseArguments
    try {
        Invoke-Compose -Name "production compose smoke up" -Arguments ($baseArguments + @(
            "up",
            "-d",
            "--build",
            "postgres",
            "migrate",
            "backend",
            "frontend"
        ))

        Invoke-SmokeHttpCheck -Name "backend health" -Uri "http://127.0.0.1:$BackendPort/health" -TimeoutSeconds $HealthTimeoutSeconds
        Invoke-SmokeHttpCheck -Name "frontend root" -Uri "http://127.0.0.1:$FrontendPort/" -TimeoutSeconds $HealthTimeoutSeconds -ExpectedText "<html|<!doctype"

        if ($WithWorkers) {
            Invoke-Compose -Name "production compose worker profile ps" -Arguments ($baseArguments + @("ps"))
        }
    } finally {
        $env:BACKEND_PORT = $previousBackendPort
        $env:FRONTEND_PORT = $previousFrontendPort
        $env:DELIVERY_APP_BASE_URL = $previousDeliveryAppBaseUrl
        $env:CORS_ORIGINS = $previousCorsOrigins

        if (-not $KeepRunning) {
            $downArguments = (Get-ComposeBaseArguments) + @(
                "down",
                "--remove-orphans"
            )
            if (-not $PreserveSmokeVolumes) {
                $downArguments += "--volumes"
            }
            Invoke-Compose -Name "production compose smoke down" -Arguments $downArguments
        } else {
            Write-Host ""
            Write-Host "Smoke stack left running. Stop it with:"
            Write-Host "docker compose -p $ProjectName --env-file `"$EnvFile`" -f `"$ComposeFile`" down --remove-orphans --volumes"
        }
    }
}

Write-Host ""
Write-Host "Production compose checks passed."
