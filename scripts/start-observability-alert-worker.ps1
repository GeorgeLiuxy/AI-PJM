param(
    [string]$ApiBaseUrl = "",
    [string]$Token = "",
    [string]$AlertWebhookUrl = "",
    [int]$PollSeconds = 0
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendDir = Join-Path $Root "backend"
$RuntimeRoot = Join-Path $Root ".runtime"
$WorkerDir = Join-Path $RuntimeRoot "observability-alert-worker"
$LogDir = Join-Path $RuntimeRoot "logs"

if (-not $ApiBaseUrl) {
    $ApiBaseUrl = if ($env:AI_PJM_API_BASE_URL) { $env:AI_PJM_API_BASE_URL } else { "http://127.0.0.1:8010/api/v2" }
}
if (-not $Token) {
    $Token = if ($env:AI_PJM_API_TOKEN) { $env:AI_PJM_API_TOKEN } else { "" }
}
if (-not $AlertWebhookUrl) {
    $AlertWebhookUrl = if ($env:OBSERVABILITY_ALERT_WEBHOOK_URL) { $env:OBSERVABILITY_ALERT_WEBHOOK_URL } else { "" }
}
if ($PollSeconds -le 0) {
    $PollSeconds = if ($env:OBSERVABILITY_ALERT_POLL_SECONDS) { [int]$env:OBSERVABILITY_ALERT_POLL_SECONDS } else { 120 }
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

$pidPath = Join-Path $RuntimeRoot "observability-alert-worker.pid"
$statusFile = Join-Path $WorkerDir "status.json"
$workerOut = Join-Path $LogDir "observability-alert-worker.out.log"
$workerErr = Join-Path $LogDir "observability-alert-worker.err.log"

Stop-FromPidFile -Path $pidPath

$workerCommandParts = @(
    "`$env:AI_PJM_API_TOKEN=$(Quote-PowerShellLiteral $Token)",
    "`$env:OBSERVABILITY_ALERT_WEBHOOK_URL=$(Quote-PowerShellLiteral $AlertWebhookUrl)",
    "Set-Location -LiteralPath $(Quote-PowerShellLiteral $BackendDir)",
    "python scripts\observability_alert_worker.py --loop --api-base-url $(Quote-PowerShellLiteral $ApiBaseUrl) --poll-seconds $PollSeconds --status-file $(Quote-PowerShellLiteral $statusFile)"
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
    message = "Observability alert worker process started."
    updated_at = (Get-Date).ToUniversalTime().ToString("o")
    api_base_url = $ApiBaseUrl
    poll_seconds = $PollSeconds
}
$status | ConvertTo-Json | Set-Content -Path $statusFile

Write-Host "Observability alert worker PID: $($worker.Id)"
Write-Host "Status: $statusFile"
Write-Host "Logs:   $LogDir"
