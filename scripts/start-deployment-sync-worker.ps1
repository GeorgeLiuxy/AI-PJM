param(
    [int]$Limit = 0,
    [int]$PollSeconds = 0,
    [int[]]$ProjectId = @()
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendDir = Join-Path $Root "backend"
$RuntimeRoot = Join-Path $Root ".runtime"
$WorkerDir = Join-Path $RuntimeRoot "deployment-sync-worker"
$LogDir = Join-Path $RuntimeRoot "logs"

if ($Limit -le 0) {
    $Limit = if ($env:DEPLOYMENT_SYNC_LIMIT) { [int]$env:DEPLOYMENT_SYNC_LIMIT } else { 20 }
}
if ($PollSeconds -le 0) {
    $PollSeconds = if ($env:DEPLOYMENT_SYNC_POLL_SECONDS) { [int]$env:DEPLOYMENT_SYNC_POLL_SECONDS } else { 120 }
}

New-Item -ItemType Directory -Force -Path $RuntimeRoot, $WorkerDir, $LogDir | Out-Null

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

$pidPath = Join-Path $RuntimeRoot "deployment-sync-worker.pid"
$statusFile = Join-Path $WorkerDir "status.json"
$workerOut = Join-Path $LogDir "deployment-sync-worker.out.log"
$workerErr = Join-Path $LogDir "deployment-sync-worker.err.log"

Stop-FromPidFile -Path $pidPath

$projectArgs = @()
foreach ($id in $ProjectId) {
    $projectArgs += "--project-id $id"
}
$projectArgText = $projectArgs -join " "

$workerCommandParts = @(
    "Set-Location -LiteralPath $(Quote-PowerShellLiteral $BackendDir)",
    "python scripts\deployment_sync_worker.py --loop --limit $Limit --poll-seconds $PollSeconds --status-file $(Quote-PowerShellLiteral $statusFile) $projectArgText"
)
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
    state = "starting"
    message = "Deployment sync worker process started."
    updated_at = (Get-Date).ToUniversalTime().ToString("o")
    limit = $Limit
    poll_seconds = $PollSeconds
}
$status | ConvertTo-Json | Set-Content -Path $statusFile

Write-Host "Deployment sync worker PID: $($worker.Id)"
Write-Host "Status: $statusFile"
Write-Host "Logs:   $LogDir"
