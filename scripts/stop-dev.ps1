$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RuntimeDir = Join-Path $Root ".runtime"

function Get-CommandLine {
    param([int]$ProcessId)

    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($process) {
        return [string]$process.CommandLine
    }
    return ""
}

function Test-WorkspaceProcess {
    param([int]$ProcessId)

    $commandLine = Get-CommandLine -ProcessId $ProcessId
    return $commandLine.IndexOf($Root, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
}

function Stop-FromPidFile {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    $rawPid = Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue | Select-Object -First 1
    $parsedPid = 0
    if ([int]::TryParse([string]$rawPid, [ref]$parsedPid)) {
        Stop-Process -Id $parsedPid -Force -ErrorAction SilentlyContinue
    }
}

function Stop-WorkspaceListeners {
    param([int[]]$Ports)

    $connections = Get-NetTCPConnection -LocalPort $Ports -State Listen -ErrorAction SilentlyContinue
    foreach ($connection in $connections) {
        if (Test-WorkspaceProcess -ProcessId $connection.OwningProcess) {
            Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    }
}

Stop-FromPidFile -Path (Join-Path $RuntimeDir "backend.pid")
Stop-FromPidFile -Path (Join-Path $RuntimeDir "frontend.pid")
Stop-FromPidFile -Path (Join-Path $RuntimeDir "symphony-worker.pid")
Stop-FromPidFile -Path (Join-Path $RuntimeDir "deployment-sync-worker.pid")
Stop-FromPidFile -Path (Join-Path $RuntimeDir "observability-alert-worker.pid")

$ports = @(8010, 5173, 5174, 5175, 5176)
$portsPath = Join-Path $RuntimeDir "ports.json"
if (Test-Path -LiteralPath $portsPath) {
    try {
        $savedPorts = Get-Content -LiteralPath $portsPath -Raw | ConvertFrom-Json
        $ports += @($savedPorts.backend, $savedPorts.frontend) | Where-Object { $_ }
    } catch {
        Write-Warning "Could not parse saved ports from $portsPath."
    }
}

Stop-WorkspaceListeners -Ports ($ports | Sort-Object -Unique)
Start-Sleep -Seconds 1

if (Test-Path -LiteralPath $RuntimeDir) {
    $resolvedRuntime = (Resolve-Path -LiteralPath $RuntimeDir).Path
    if (-not $resolvedRuntime.StartsWith($Root, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove runtime directory outside workspace: $resolvedRuntime"
    }
    Remove-Item -LiteralPath $resolvedRuntime -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "Development services stopped."
