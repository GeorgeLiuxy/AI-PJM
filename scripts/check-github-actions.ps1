param(
    [string]$Owner = "",
    [string]$Repo = "",
    [string]$Branch = $(if ($env:GITHUB_BRANCH) { $env:GITHUB_BRANCH } else { "main" }),
    [string]$CommitSha = "",
    [string]$Workflow = $(if ($env:GITHUB_WORKFLOW_NAME) { $env:GITHUB_WORKFLOW_NAME } else { "Production Validation" }),
    [string]$Token = $(if ($env:GITHUB_TOKEN) { $env:GITHUB_TOKEN } else { "" }),
    [string]$OutputFile = "",
    [switch]$Wait,
    [int]$TimeoutSeconds = 900,
    [int]$PollSeconds = 20,
    [switch]$AllowAnonymous,
    [switch]$ContinueOnFailure
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $OutputFile) {
    $timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $OutputDir = Join-Path $Root ".runtime\github-actions"
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    $OutputFile = Join-Path $OutputDir "github-actions-$timestamp.json"
}

function Get-OriginRepository {
    $remote = (& git -C $Root remote get-url origin 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $remote) {
        return $null
    }

    $text = ([string]$remote).Trim()
    if ($text -match "github\.com[:/](?<owner>[^/]+)/(?<repo>[^/.]+)(\.git)?$") {
        return [pscustomobject]@{
            owner = $Matches.owner
            repo = $Matches.repo
        }
    }
    return $null
}

function Invoke-GitHubApi {
    param([string]$Uri)

    $headers = @{
        "Accept" = "application/vnd.github+json"
        "User-Agent" = "AI-PJM-production-validation"
        "X-GitHub-Api-Version" = "2022-11-28"
    }
    if ($Token) {
        $headers["Authorization"] = "Bearer $Token"
    }

    try {
        $response = Invoke-WebRequest -Method GET -Uri $Uri -Headers $headers -UseBasicParsing
        $body = if ($response.Content) { $response.Content | ConvertFrom-Json } else { $null }
        return [pscustomobject]@{
            ok = $true
            status_code = [int]$response.StatusCode
            body = $body
            error = $null
        }
    } catch {
        $statusCode = 0
        $message = $_.Exception.Message
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            $message = $_.ErrorDetails.Message
        }
        $response = $_.Exception.Response
        if ($null -ne $response) {
            $statusCode = [int]$response.StatusCode
            try {
                $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
                try {
                    $text = $reader.ReadToEnd()
                    if ($text) {
                        $message = $text
                    }
                } finally {
                    $reader.Dispose()
                }
            } catch {
                $message = $_.Exception.Message
            }
        }
        return [pscustomobject]@{
            ok = $false
            status_code = $statusCode
            body = $null
            error = $message
        }
    }
}

function Convert-ApiError {
    param([string]$Message)
    if (-not $Message) {
        return "GitHub API request failed."
    }
    if ($Message -match "API rate limit exceeded") {
        return "GitHub API rate limit exceeded. Provide GITHUB_TOKEN for authenticated verification."
    }
    if ($Message -match "Bad credentials") {
        return "GitHub token was rejected."
    }
    return $Message
}

function Get-CheckRunDiagnostics {
    param([object]$Job)

    if (-not $Job.check_run_url) {
        return [pscustomobject]@{
            title = ""
            summary = ""
            text = ""
            annotations = @()
        }
    }

    $checkResult = Invoke-GitHubApi -Uri ([string]$Job.check_run_url)
    if (-not $checkResult.ok -or -not $checkResult.body) {
        return [pscustomobject]@{
            title = ""
            summary = ""
            text = ""
            annotations = @()
        }
    }

    $check = $checkResult.body
    $annotations = @()
    $annotationCount = 0
    if ($check.output -and $check.output.annotations_count) {
        $annotationCount = [int]$check.output.annotations_count
    }
    if ($annotationCount -gt 0) {
        $annotationsResult = Invoke-GitHubApi -Uri "$($Job.check_run_url)/annotations?per_page=50"
        if ($annotationsResult.ok -and $annotationsResult.body) {
            $annotations = @($annotationsResult.body | ForEach-Object {
                [pscustomobject]@{
                    path = $_.path
                    start_line = $_.start_line
                    end_line = $_.end_line
                    annotation_level = $_.annotation_level
                    message = $_.message
                }
            })
        }
    }

    return [pscustomobject]@{
        title = $(if ($check.output) { [string]$check.output.title } else { "" })
        summary = $(if ($check.output) { [string]$check.output.summary } else { "" })
        text = $(if ($check.output) { [string]$check.output.text } else { "" })
        annotations = $annotations
    }
}

function Get-RunClassification {
    param([object]$Run, [object[]]$Jobs)

    $status = [string]$Run.status
    $conclusion = [string]$Run.conclusion
    $externalReason = ""

    $jobMessages = @()
    foreach ($job in @($Jobs)) {
        if ($job.name) {
            $jobMessages += "$($job.name): status=$($job.status), conclusion=$($job.conclusion)"
        }
        if ($job.output_title) {
            $jobMessages += [string]$job.output_title
        }
        if ($job.output_summary) {
            $jobMessages += [string]$job.output_summary
        }
        if ($job.output_text) {
            $jobMessages += [string]$job.output_text
        }
        foreach ($annotation in @($job.annotations)) {
            if ($annotation.message) {
                $jobMessages += [string]$annotation.message
            }
        }
    }

    $raw = ($jobMessages -join " `n")
    if ($raw -match "billing" -or $raw -match "account.*locked") {
        $externalReason = "GitHub did not start CI because the account or billing state is locked."
    } elseif ($raw -match "job was not started" -or $raw -match "runner.*not.*started") {
        $externalReason = "GitHub did not start one or more CI jobs before assigning a runner."
    }

    if ($status -eq "completed" -and $conclusion -eq "success") {
        return [pscustomobject]@{
            status = "passed"
            blocker = $false
            summary = "GitHub Actions workflow completed successfully."
            next_action = ""
            external_reason = $externalReason
        }
    }

    if ($status -eq "completed") {
        $summary = "GitHub Actions workflow completed with conclusion '$conclusion'."
        if ($externalReason) {
            $summary = $externalReason
        }
        return [pscustomobject]@{
            status = $(if ($externalReason) { "blocked" } else { "failed" })
            blocker = $true
            summary = $summary
            next_action = $(if ($externalReason) { "Fix the GitHub account or billing lock, then rerun the workflow." } else { "Open the run URL, fix failed checks, and push again." })
            external_reason = $externalReason
        }
    }

    return [pscustomobject]@{
        status = "pending"
        blocker = $true
        summary = "GitHub Actions workflow is still $status."
        next_action = "Wait for completion or rerun this script with -Wait."
        external_reason = $externalReason
    }
}

if (-not $Owner -or -not $Repo) {
    $origin = Get-OriginRepository
    if ($origin) {
        if (-not $Owner) {
            $Owner = $origin.owner
        }
        if (-not $Repo) {
            $Repo = $origin.repo
        }
    }
}

if (-not $Owner -or -not $Repo) {
    throw "Unable to infer GitHub owner/repo from origin. Pass -Owner and -Repo explicitly."
}

if (-not $CommitSha) {
    $CommitSha = (& git -C $Root rev-parse HEAD).Trim()
}

if (-not $Token -and -not $AllowAnonymous) {
    $result = [pscustomobject]@{
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        repository = "$Owner/$Repo"
        branch = $Branch
        commit_sha = $CommitSha
        workflow = $Workflow
        status = "blocked"
        blocker = $true
        summary = "GITHUB_TOKEN is required for reliable GitHub Actions validation."
        next_action = "Set GITHUB_TOKEN and rerun this script. Use -AllowAnonymous only for an intentional unauthenticated check."
        evidence = @{
            token_used = $false
            anonymous_allowed = $false
        }
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputFile) | Out-Null
    $result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputFile -Encoding UTF8

    Write-Host "GitHub Actions validation"
    Write-Host "Repository: $Owner/$Repo"
    Write-Host "Commit: $CommitSha"
    Write-Host "Status: $($result.status)"
    Write-Host "Summary: $($result.summary)"
    Write-Host "Report: $OutputFile"

    if (-not $ContinueOnFailure) {
        exit 1
    }
    return
}

$startedAt = Get-Date
$result = $null

do {
    $runsUri = "https://api.github.com/repos/$Owner/$Repo/actions/runs?branch=$Branch&head_sha=$CommitSha&per_page=20"
    $runsResult = Invoke-GitHubApi -Uri $runsUri
    if (-not $runsResult.ok) {
        $summary = Convert-ApiError -Message ([string]$runsResult.error)
        $result = [pscustomobject]@{
            generated_at = (Get-Date).ToUniversalTime().ToString("o")
            repository = "$Owner/$Repo"
            branch = $Branch
            commit_sha = $CommitSha
            workflow = $Workflow
            status = "blocked"
            blocker = $true
            summary = $summary
            next_action = "Provide a valid GITHUB_TOKEN or verify GitHub API access, then rerun this script."
            evidence = @{
                api_status_code = $runsResult.status_code
                api_error = $summary
                token_used = [bool]$Token
            }
        }
        break
    }

    $runs = @($runsResult.body.workflow_runs | Where-Object {
        $_.name -eq $Workflow -or $_.path -like "*$Workflow*"
    })
    if ($runs.Count -eq 0) {
        $result = [pscustomobject]@{
            generated_at = (Get-Date).ToUniversalTime().ToString("o")
            repository = "$Owner/$Repo"
            branch = $Branch
            commit_sha = $CommitSha
            workflow = $Workflow
            status = "blocked"
            blocker = $true
            summary = "No GitHub Actions workflow run was found for this commit."
            next_action = "Confirm the workflow exists, the branch was pushed, and GitHub Actions is enabled for the repository."
            evidence = @{
                run_count = @($runsResult.body.workflow_runs).Count
                token_used = [bool]$Token
            }
        }
        break
    }

    $run = $runs | Sort-Object -Property run_attempt -Descending | Select-Object -First 1
    $jobs = @()
    if ($run.jobs_url) {
        $jobsResult = Invoke-GitHubApi -Uri ([string]$run.jobs_url)
        if ($jobsResult.ok) {
            $jobs = @($jobsResult.body.jobs | ForEach-Object {
                $diagnostics = Get-CheckRunDiagnostics -Job $_
                [pscustomobject]@{
                    name = $_.name
                    status = $_.status
                    conclusion = $_.conclusion
                    started_at = $_.started_at
                    completed_at = $_.completed_at
                    html_url = $_.html_url
                    check_run_url = $_.check_run_url
                    runner_id = $_.runner_id
                    runner_name = $_.runner_name
                    output_title = $diagnostics.title
                    output_summary = $diagnostics.summary
                    output_text = $diagnostics.text
                    annotations = @($diagnostics.annotations)
                }
            })
        }
    }

    $classification = Get-RunClassification -Run $run -Jobs $jobs
    $result = [pscustomobject]@{
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        repository = "$Owner/$Repo"
        branch = $Branch
        commit_sha = $CommitSha
        workflow = $Workflow
        status = $classification.status
        blocker = $classification.blocker
        summary = $classification.summary
        next_action = $classification.next_action
        evidence = @{
            run_id = $run.id
            run_number = $run.run_number
            run_attempt = $run.run_attempt
            run_status = $run.status
            run_conclusion = $run.conclusion
            run_url = $run.html_url
            created_at = $run.created_at
            updated_at = $run.updated_at
            external_reason = $classification.external_reason
            jobs = @($jobs | ForEach-Object {
                [pscustomobject]@{
                    name = $_.name
                    status = $_.status
                    conclusion = $_.conclusion
                    started_at = $_.started_at
                    completed_at = $_.completed_at
                    html_url = $_.html_url
                    runner_id = $_.runner_id
                    runner_name = $_.runner_name
                    output_title = $_.output_title
                    output_summary = $_.output_summary
                    output_text = $_.output_text
                    annotations = @($_.annotations)
                }
            })
        }
    }

    if (-not $Wait -or $result.status -ne "pending") {
        break
    }

    $elapsed = ((Get-Date) - $startedAt).TotalSeconds
    if ($elapsed -ge $TimeoutSeconds) {
        $result.status = "blocked"
        $result.blocker = $true
        $result.summary = "Timed out waiting for GitHub Actions workflow completion."
        $result.next_action = "Open the run URL or rerun this script after the workflow finishes."
        break
    }

    Write-Host "GitHub Actions is $($run.status); waiting $PollSeconds second(s)..."
    Start-Sleep -Seconds $PollSeconds
} while ($true)

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputFile) | Out-Null
$result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputFile -Encoding UTF8

Write-Host "GitHub Actions validation"
Write-Host "Repository: $Owner/$Repo"
Write-Host "Commit: $CommitSha"
Write-Host "Status: $($result.status)"
Write-Host "Summary: $($result.summary)"
$runUrl = $null
if ($result.evidence -is [hashtable] -and $result.evidence.ContainsKey("run_url")) {
    $runUrl = $result.evidence["run_url"]
} elseif ($result.evidence.PSObject.Properties.Name -contains "run_url") {
    $runUrl = $result.evidence.run_url
}
if ($runUrl) {
    Write-Host "Run URL: $runUrl"
}
Write-Host "Report: $OutputFile"

if ($result.status -ne "passed" -and -not $ContinueOnFailure) {
    exit 1
}
