param(
    [string]$Image = "postgres:16-alpine",
    [int]$Port = 55432,
    [string]$ContainerName = "",
    [switch]$KeepContainer
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendDir = Join-Path $Root "backend"

if (-not $ContainerName) {
    $suffix = [guid]::NewGuid().ToString("N").Substring(0, 8)
    $ContainerName = "ai-pjm-postgres-migration-$suffix"
}

function Invoke-Native {
    param(
        [string]$Name,
        [scriptblock]$Command
    )

    Write-Host "==> $Name"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name exited with code $LASTEXITCODE"
    }
}

function Test-PortFree {
    param([int]$Candidate)

    $listener = Get-NetTCPConnection -LocalPort $Candidate -State Listen -ErrorAction SilentlyContinue
    return -not $listener
}

function Get-AvailablePort {
    param([int]$Preferred)

    for ($offset = 0; $offset -lt 50; $offset++) {
        $candidate = $Preferred + $offset
        if (Test-PortFree -Candidate $candidate) {
            return $candidate
        }
    }
    throw "No available local port found from $Preferred to $($Preferred + 49)."
}

$Port = Get-AvailablePort -Preferred $Port
$DatabaseUrl = "postgresql+asyncpg://ai_pjm:ai_pjm_test@127.0.0.1:$Port/ai_pjm_test"
$started = $false

try {
    Invoke-Native -Name "docker daemon check" -Command {
        docker info --format "{{.ServerVersion}}"
    }

    Invoke-Native -Name "start temporary PostgreSQL" -Command {
        docker run -d `
            --name $ContainerName `
            -e POSTGRES_USER=ai_pjm `
            -e POSTGRES_PASSWORD=ai_pjm_test `
            -e POSTGRES_DB=ai_pjm_test `
            -p "${Port}:5432" `
            $Image
    }
    $started = $true

    Write-Host "Waiting for PostgreSQL readiness on 127.0.0.1:$Port..."
    $ready = $false
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        $probeOutput = docker exec $ContainerName pg_isready -U ai_pjm -d ai_pjm_test 2>&1
        $probeExitCode = $LASTEXITCODE
        if ($probeExitCode -eq 0) {
            $ready = $true
            break
        }
        $probeText = ($probeOutput | Out-String).Trim()
        if ($probeText -match "failed to connect|Cannot connect|daemon") {
            throw "Docker daemon became unavailable while waiting for PostgreSQL readiness: $probeText"
        }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) {
        throw "PostgreSQL container did not become ready within 60 seconds."
    }

    Push-Location -LiteralPath $BackendDir
    try {
        Invoke-Native -Name "alembic upgrade head on PostgreSQL" -Command {
            python scripts/migrate.py upgrade head --database-url $DatabaseUrl
        }
        Invoke-Native -Name "alembic current on PostgreSQL" -Command {
            python scripts/migrate.py current --database-url $DatabaseUrl
        }
    } finally {
        Pop-Location
    }

    Write-Host "PostgreSQL migration smoke passed."
} finally {
    if ($started -and -not $KeepContainer) {
        try {
            docker rm -f $ContainerName | Out-Null
            Write-Host "Removed temporary container $ContainerName."
        } catch {
            Write-Host "Could not remove temporary container $ContainerName. Check Docker daemon status and remove it manually if needed."
        }
    } elseif ($started) {
        Write-Host "Kept temporary container $ContainerName."
    }
}
