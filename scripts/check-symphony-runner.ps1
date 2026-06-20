param(
    [string]$Workspace = "",
    [string]$RunnerCommand = "",
    [string]$OutputFile = "",
    [switch]$UseRecommendedCodexCommand,
    [switch]$RequireCodex,
    [switch]$Execute,
    [int]$TimeoutSeconds = 120,
    [switch]$ContinueOnFailure
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $Workspace) {
    $Workspace = if ($env:SYMPHONY_WORKSPACE) { $env:SYMPHONY_WORKSPACE } else { $Root }
}
$Workspace = (Resolve-Path -LiteralPath $Workspace).Path

if (-not $OutputFile) {
    $timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $suffix = [guid]::NewGuid().ToString("N").Substring(0, 8)
    $OutputDir = Join-Path $Root ".runtime\symphony-runner"
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    $OutputFile = Join-Path $OutputDir "symphony-runner-$timestamp-$suffix.json"
}

function Quote-CmdArgument {
    param([string]$Value)
    if ($null -eq $Value) {
        return '""'
    }
    return '"' + ($Value -replace '"', '\"') + '"'
}

function Get-RecommendedCodexCommand {
    return "powershell -NoProfile -ExecutionPolicy Bypass -File {workspace_q}\scripts\run-codex-task.ps1 -PromptFile {task_prompt_file_q} -WorkspaceRoot {workspace_q}"
}

function Get-CodexCommand {
    $codex = Get-Command codex.cmd -ErrorAction SilentlyContinue
    if (-not $codex) {
        $codex = Get-Command codex -ErrorAction SilentlyContinue
    }
    return $codex
}

function New-SampleFiles {
    $runDir = Join-Path (Split-Path -Parent $OutputFile) "sample-task"
    New-Item -ItemType Directory -Force -Path $runDir | Out-Null
    $packageFile = Join-Path $runDir "task-package.json"
    $promptFile = Join-Path $runDir "task-prompt.md"

    $package = [ordered]@{
        run_id = 0
        coding_task_id = 0
        demand_id = 0
        risk_level = "L0"
        task_prompt = "Runner validation sample. Do not modify files."
        allowed_paths = @("README.md")
        forbidden_actions = @("Do not modify files during validation.")
        required_checks = @()
        expected_evidence = @("Runner command can be expanded.")
    }
    $package | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $packageFile -Encoding UTF8
    Set-Content -LiteralPath $promptFile -Encoding UTF8 -Value @(
        "# AI PJM Runner Validation",
        "",
        "This file is used to validate runner command template expansion.",
        "Do not modify repository files."
    )

    return [pscustomobject]@{
        task_package_file = (Resolve-Path -LiteralPath $packageFile).Path
        task_prompt_file = (Resolve-Path -LiteralPath $promptFile).Path
    }
}

function Expand-RunnerCommand {
    param(
        [string]$Template,
        [object]$Files
    )

    $expanded = $Template
    $map = [ordered]@{
        "{run_id}" = "0"
        "{workspace}" = $Workspace
        "{workspace_q}" = (Quote-CmdArgument $Workspace)
        "{task_package_file}" = $Files.task_package_file
        "{task_package_file_q}" = (Quote-CmdArgument $Files.task_package_file)
        "{task_prompt_file}" = $Files.task_prompt_file
        "{task_prompt_file_q}" = (Quote-CmdArgument $Files.task_prompt_file)
    }

    foreach ($key in $map.Keys) {
        $expanded = $expanded.Replace($key, [string]$map[$key])
    }
    return $expanded
}

function Invoke-CommandWithTimeout {
    param(
        [string]$Command,
        [string]$WorkingDirectory,
        [int]$Timeout
    )

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $process.StartInfo.FileName = if ($env:ComSpec) { $env:ComSpec } else { "cmd.exe" }
    $process.StartInfo.Arguments = "/d /s /c $Command"
    $process.StartInfo.WorkingDirectory = $WorkingDirectory
    $process.StartInfo.RedirectStandardOutput = $true
    $process.StartInfo.RedirectStandardError = $true
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.CreateNoWindow = $true

    $startedAt = Get-Date
    [void]$process.Start()
    $completed = $process.WaitForExit($Timeout * 1000)
    if (-not $completed) {
        try {
            $process.Kill()
        } catch {
            # Process already exited.
        }
        return [pscustomobject]@{
            exit_code = -1
            duration_ms = [int](((Get-Date) - $startedAt).TotalMilliseconds)
            stdout_tail = ""
            stderr_tail = ""
            error = "Timed out after $Timeout seconds."
        }
    }

    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    return [pscustomobject]@{
        exit_code = $process.ExitCode
        duration_ms = [int](((Get-Date) - $startedAt).TotalMilliseconds)
        stdout_tail = Get-Tail $stdout
        stderr_tail = Get-Tail $stderr
        error = ""
    }
}

function Get-Tail {
    param([string]$Value)
    if (-not $Value) {
        return ""
    }
    if ($Value.Length -le 4000) {
        return $Value
    }
    return $Value.Substring($Value.Length - 4000)
}

$runnerSource = "argument"
if (-not $RunnerCommand) {
    if ($env:SYMPHONY_RUNNER_COMMAND) {
        $RunnerCommand = $env:SYMPHONY_RUNNER_COMMAND
        $runnerSource = "environment"
    } elseif ($UseRecommendedCodexCommand) {
        $RunnerCommand = Get-RecommendedCodexCommand
        $runnerSource = "recommended_codex"
    }
}

$status = "passed"
$summary = "Symphony runner command is configured and can be expanded."
$nextAction = ""
$blocker = $false
$warnings = @()
$errors = @()
$execution = $null
$files = New-SampleFiles
$expandedCommand = ""
$codex = Get-CodexCommand

if (-not $RunnerCommand) {
    $status = "blocked"
    $blocker = $true
    $summary = "No Symphony runner command is configured."
    $nextAction = "Set SYMPHONY_RUNNER_COMMAND or run this script with -UseRecommendedCodexCommand."
} else {
    $expandedCommand = Expand-RunnerCommand -Template $RunnerCommand -Files $files
    $unknownPlaceholders = @(
        [regex]::Matches($expandedCommand, "\{[A-Za-z0-9_]+\}") |
            ForEach-Object { $_.Value } |
            Sort-Object -Unique
    )
    if ($unknownPlaceholders.Count -gt 0) {
        $status = "failed"
        $blocker = $true
        $errors += "Unknown runner command placeholder(s): $($unknownPlaceholders -join ', ')."
        $summary = "Symphony runner command contains unsupported placeholder(s)."
        $nextAction = "Use only {run_id}, {workspace}, {workspace_q}, {task_package_file}, {task_package_file_q}, {task_prompt_file}, and {task_prompt_file_q}."
    }

    if ($RunnerCommand -notmatch "\{task_prompt_file(_q)?\}" -and $RunnerCommand -notmatch "\{task_package_file(_q)?\}") {
        $warnings += "Runner command does not reference the task prompt or task package file."
    }

    if ($RequireCodex -and -not $codex) {
        $status = "blocked"
        $blocker = $true
        $summary = "Codex CLI was not found on PATH."
        $nextAction = "Install Codex CLI or adjust PATH before using the recommended Codex runner command."
    }

    if ($Execute -and $status -eq "passed") {
        $execution = Invoke-CommandWithTimeout -Command $expandedCommand -WorkingDirectory $Workspace -Timeout $TimeoutSeconds
        if ($execution.exit_code -ne 0) {
            $status = "failed"
            $blocker = $true
            $summary = "Symphony runner command execution failed."
            $nextAction = "Inspect stdout_tail and stderr_tail in the report, then fix the runner command."
        } else {
            $summary = "Symphony runner command executed successfully."
        }
    }
}

$result = [pscustomobject]@{
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    status = $status
    blocker = $blocker
    summary = $summary
    next_action = $nextAction
    evidence = [ordered]@{
        workspace = $Workspace
        runner_source = $runnerSource
        runner_command = $RunnerCommand
        expanded_command = $expandedCommand
        codex_found = [bool]$codex
        codex_path = $(if ($codex) { $codex.Source } else { "" })
        execute = [bool]$Execute
        timeout_seconds = $TimeoutSeconds
        sample_files = $files
        warnings = $warnings
        errors = $errors
        execution = $execution
    }
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputFile) | Out-Null
$result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputFile -Encoding UTF8

Write-Host "Symphony runner validation"
Write-Host "Status:  $($result.status)"
Write-Host "Summary: $($result.summary)"
Write-Host "Report:  $OutputFile"

if ($result.status -ne "passed" -and -not $ContinueOnFailure) {
    exit 1
}
