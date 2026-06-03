$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RuntimeRoot = Join-Path $Root ".runtime"
$pidPath = Join-Path $RuntimeRoot "symphony-worker.pid"
$statusFile = Join-Path $RuntimeRoot "symphony-worker\worker-status.json"

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

if (Test-Path -LiteralPath $pidPath) {
    $rawPid = Get-Content -LiteralPath $pidPath -ErrorAction SilentlyContinue | Select-Object -First 1
    $parsedPid = 0
    if ([int]::TryParse([string]$rawPid, [ref]$parsedPid)) {
        if (Test-WorkspaceProcess -ProcessId $parsedPid) {
            Stop-Process -Id $parsedPid -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
}

if (Test-Path -LiteralPath $statusFile) {
    $status = @{
        worker_id = $env:SYMPHONY_WORKER_ID
        state = "stopped"
        run_id = $null
        message = "Worker process stopped."
        workspace = $Root
        updated_at = (Get-Date).ToUniversalTime().ToString("o")
    }
    $status | ConvertTo-Json | Set-Content -Path $statusFile
}

Write-Host "Symphony worker stopped."
