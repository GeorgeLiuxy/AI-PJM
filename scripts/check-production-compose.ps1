param(
    [switch]$BuildImages
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

Write-Host ""
Write-Host "Production compose checks passed."
