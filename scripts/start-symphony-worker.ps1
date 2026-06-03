param(
    [string]$ApiBaseUrl = "",
    [string]$WorkerId = "",
    [string]$Workspace = "",
    [string]$RuntimeDir = "",
    [string]$RunnerCommand = "",
    [int]$PollSeconds = 0,
    [int]$CommandTimeoutSeconds = 0,
    [int]$LeaseSeconds = 0,
    [switch]$SkipRequiredChecks
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendDir = Join-Path $Root "backend"
$RuntimeRoot = Join-Path $Root ".runtime"
$LogDir = Join-Path $RuntimeRoot "logs"

if (-not $ApiBaseUrl) {
    $ApiBaseUrl = if ($env:AI_PJM_API_BASE_URL) { $env:AI_PJM_API_BASE_URL } else { "http://127.0.0.1:8010/api/v2" }
}
if (-not $WorkerId) {
    $WorkerId = if ($env:SYMPHONY_WORKER_ID) { $env:SYMPHONY_WORKER_ID } else { "symphony-worker-local" }
}
if (-not $Workspace) {
    $Workspace = if ($env:SYMPHONY_WORKSPACE) { $env:SYMPHONY_WORKSPACE } else { $Root }
}
if (-not $RuntimeDir) {
    $RuntimeDir = if ($env:SYMPHONY_WORKER_RUNTIME_DIR) { $env:SYMPHONY_WORKER_RUNTIME_DIR } else { Join-Path $RuntimeRoot "symphony-worker" }
}
if (-not $RunnerCommand) {
    $RunnerCommand = if ($env:SYMPHONY_RUNNER_COMMAND) { $env:SYMPHONY_RUNNER_COMMAND } else { "" }
}
if ($PollSeconds -le 0) {
    $PollSeconds = if ($env:SYMPHONY_WORKER_POLL_SECONDS) { [int]$env:SYMPHONY_WORKER_POLL_SECONDS } else { 5 }
}
if ($CommandTimeoutSeconds -le 0) {
    $CommandTimeoutSeconds = if ($env:SYMPHONY_WORKER_COMMAND_TIMEOUT_SECONDS) { [int]$env:SYMPHONY_WORKER_COMMAND_TIMEOUT_SECONDS } else { 1800 }
}
if ($LeaseSeconds -le 0) {
    $LeaseSeconds = if ($env:SYMPHONY_WORKER_LEASE_SECONDS) { [int]$env:SYMPHONY_WORKER_LEASE_SECONDS } else { $CommandTimeoutSeconds + 300 }
}

if (-not $env:SYMPHONY_BRIDGE_TOKEN) {
    throw "SYMPHONY_BRIDGE_TOKEN is required before starting the Symphony worker."
}

New-Item -ItemType Directory -Force -Path $RuntimeRoot, $LogDir, $RuntimeDir | Out-Null

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
        if (Test-WorkspaceProcess -ProcessId $parsedPid) {
            Stop-Process -Id $parsedPid -Force -ErrorAction SilentlyContinue
        }
    }
}

function Quote-PowerShellLiteral {
    param([string]$Value)
    return "'" + ($Value -replace "'", "''") + "'"
}

$pidPath = Join-Path $RuntimeRoot "symphony-worker.pid"
$statusFile = Join-Path $RuntimeDir "worker-status.json"
$workerOut = Join-Path $LogDir "symphony-worker.out.log"
$workerErr = Join-Path $LogDir "symphony-worker.err.log"

Stop-FromPidFile -Path $pidPath

$workerCommandParts = @(
    "`$env:AI_PJM_API_BASE_URL=$(Quote-PowerShellLiteral $ApiBaseUrl)",
    "`$env:SYMPHONY_WORKER_ID=$(Quote-PowerShellLiteral $WorkerId)",
    "`$env:SYMPHONY_WORKSPACE=$(Quote-PowerShellLiteral ((Resolve-Path -LiteralPath $Workspace).Path))",
    "`$env:SYMPHONY_WORKER_RUNTIME_DIR=$(Quote-PowerShellLiteral $RuntimeDir)",
    "`$env:SYMPHONY_WORKER_STATUS_FILE=$(Quote-PowerShellLiteral $statusFile)",
    "`$env:SYMPHONY_RUNNER_COMMAND=$(Quote-PowerShellLiteral $RunnerCommand)",
    "`$env:SYMPHONY_WORKER_COMMAND_TIMEOUT_SECONDS=$(Quote-PowerShellLiteral ([string]$CommandTimeoutSeconds))",
    "`$env:SYMPHONY_WORKER_LEASE_SECONDS=$(Quote-PowerShellLiteral ([string]$LeaseSeconds))",
    "`$env:SYMPHONY_WORKER_POLL_SECONDS=$(Quote-PowerShellLiteral ([string]$PollSeconds))",
    "Set-Location -LiteralPath $(Quote-PowerShellLiteral $BackendDir)"
)

$workerArgs = "scripts\symphony_worker.py --loop"
if ($SkipRequiredChecks) {
    $workerArgs = "$workerArgs --skip-required-checks"
}
$workerCommandParts += "python $workerArgs"
$workerCommand = $workerCommandParts -join "; "

$worker = Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $workerCommand) `
    -WorkingDirectory $BackendDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $workerOut `
    -RedirectStandardError $workerErr `
    -PassThru

Set-Content -Path $pidPath -Value $worker.Id

$status = @{
    worker_id = $WorkerId
    state = "starting"
    run_id = $null
    message = "Worker process started."
    workspace = (Resolve-Path -LiteralPath $Workspace).Path
    updated_at = (Get-Date).ToUniversalTime().ToString("o")
}
$status | ConvertTo-Json | Set-Content -Path $statusFile

Write-Host "Symphony worker: $WorkerId"
Write-Host "PID:             $($worker.Id)"
Write-Host "API:             $ApiBaseUrl"
Write-Host "Status:          $statusFile"
Write-Host "Logs:            $LogDir"
