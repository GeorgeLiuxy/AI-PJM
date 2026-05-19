$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$RuntimeDir = Join-Path $Root ".runtime"

function Stop-FromPidFile {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    $RawPid = Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue | Select-Object -First 1
    $ParsedPid = 0
    if ([int]::TryParse([string]$RawPid, [ref]$ParsedPid)) {
        Stop-Process -Id $ParsedPid -Force -ErrorAction SilentlyContinue
    }
}

Stop-FromPidFile -Path (Join-Path $RuntimeDir "backend.pid")
Stop-FromPidFile -Path (Join-Path $RuntimeDir "frontend.pid")

Start-Sleep -Seconds 1

$connections = Get-NetTCPConnection -LocalPort @(8000, 8010, 5173, 5174, 5175, 5176) -State Listen -ErrorAction SilentlyContinue
foreach ($connection in $connections) {
    Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue
}

Start-Sleep -Seconds 1

if (Test-Path -LiteralPath $RuntimeDir) {
    $ResolvedRuntime = (Resolve-Path -LiteralPath $RuntimeDir).Path
    if (-not $ResolvedRuntime.StartsWith($Root.Path, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove runtime directory outside workspace: $ResolvedRuntime"
    }
    Remove-Item -LiteralPath $ResolvedRuntime -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "Development services stopped."
