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
    }

    $raw = ($jobMessages -join " `n")
    if ($raw -match "billing" -or $raw -match "account.*locked") {
        $externalReason = "GitHub did not start CI because the account or billing state is locked."
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
            status = "failed"
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
            $jobs = @($jobsResult.body.jobs)
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
