param(
    [ValidateSet("auto", "github", "gitlab", "both")]
    [string]$Provider = "auto",
    [string]$TargetBranch = $(if ($env:MERGE_REQUEST_DEFAULT_TARGET_BRANCH) { $env:MERGE_REQUEST_DEFAULT_TARGET_BRANCH } else { "main" }),
    [string]$GitHubApiBaseUrl = $(if ($env:GITHUB_API_BASE_URL) { $env:GITHUB_API_BASE_URL } else { "https://api.github.com" }),
    [string]$GitHubRepository = $(if ($env:GITHUB_REPOSITORY) { $env:GITHUB_REPOSITORY } else { "" }),
    [string]$GitHubToken = $(if ($env:GITHUB_TOKEN) { $env:GITHUB_TOKEN } else { "" }),
    [string]$GitLabApiBaseUrl = $(if ($env:GITLAB_API_BASE_URL) { $env:GITLAB_API_BASE_URL } else { "" }),
    [string]$GitLabProjectId = $(if ($env:GITLAB_PROJECT_ID) { $env:GITLAB_PROJECT_ID } else { "" }),
    [string]$GitLabToken = $(if ($env:GITLAB_TOKEN) { $env:GITLAB_TOKEN } else { "" }),
    [string]$OutputFile = "",
    [switch]$ContinueOnFailure
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $OutputFile) {
    $timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $suffix = [guid]::NewGuid().ToString("N").Substring(0, 8)
    $OutputDir = Join-Path $Root ".runtime\merge-request-provider"
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    $OutputFile = Join-Path $OutputDir "merge-request-provider-$timestamp-$suffix.json"
}

function Get-OriginGitHubRepository {
    $remote = (& git -C $Root remote get-url origin 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $remote) {
        return ""
    }
    $text = ([string]$remote).Trim()
    if ($text -match "github\.com[:/](?<owner>[^/]+)/(?<repo>[^/.]+)(\.git)?$") {
        return "$($Matches.owner)/$($Matches.repo)"
    }
    return ""
}

function Invoke-Api {
    param(
        [string]$Uri,
        [hashtable]$Headers
    )

    try {
        $response = Invoke-WebRequest -Method GET -Uri $Uri -Headers $Headers -UseBasicParsing
        $body = if ($response.Content) { $response.Content | ConvertFrom-Json } else { $null }
        return [pscustomobject]@{
            ok = $true
            status_code = [int]$response.StatusCode
            body = $body
            error = ""
        }
    } catch {
        $statusCode = 0
        $message = $_.Exception.Message
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            $message = $_.ErrorDetails.Message
        }
        if ($_.Exception.Response) {
            $statusCode = [int]$_.Exception.Response.StatusCode
        }
        return [pscustomobject]@{
            ok = $false
            status_code = $statusCode
            body = $null
            error = $message
        }
    }
}

function Test-GitHubProvider {
    $repository = $GitHubRepository
    if (-not $repository) {
        $repository = Get-OriginGitHubRepository
    }

    $missing = @()
    if (-not $GitHubApiBaseUrl) { $missing += "GITHUB_API_BASE_URL" }
    if (-not $repository) { $missing += "GITHUB_REPOSITORY" }
    if (-not $GitHubToken) { $missing += "GITHUB_TOKEN or project github_token" }
    if (-not $TargetBranch) { $missing += "MERGE_REQUEST_DEFAULT_TARGET_BRANCH" }

    if ($missing.Count -gt 0) {
        return [pscustomobject]@{
            provider = "github"
            status = "blocked"
            blocker = $true
            summary = "GitHub PR provider is missing configuration."
            next_action = "Configure $($missing -join ', ') before creating real PRs."
            evidence = @{
                api_base_url = $GitHubApiBaseUrl
                repository = $repository
                target_branch = $TargetBranch
                missing = $missing
                token_present = [bool]$GitHubToken
            }
        }
    }

    $headers = @{
        "Authorization" = "Bearer $GitHubToken"
        "Accept" = "application/vnd.github+json"
        "X-GitHub-Api-Version" = "2022-11-28"
        "User-Agent" = "AI-PJM-mr-provider-check"
    }
    $repoPath = ($repository -split "/", 2 | ForEach-Object { [System.Uri]::EscapeDataString($_) }) -join "/"
    $repoUrl = "$($GitHubApiBaseUrl.TrimEnd('/'))/repos/$repoPath"
    $branchUrl = "$repoUrl/branches/$([System.Uri]::EscapeDataString($TargetBranch))"
    $pullsUrl = "$repoUrl/pulls?state=open&per_page=1"

    $repoResult = Invoke-Api -Uri $repoUrl -Headers $headers
    $branchResult = if ($repoResult.ok) { Invoke-Api -Uri $branchUrl -Headers $headers } else { $null }
    $pullsResult = if ($repoResult.ok) { Invoke-Api -Uri $pullsUrl -Headers $headers } else { $null }

    $checks = @(
        @{ name = "repository"; result = $repoResult },
        @{ name = "target_branch"; result = $branchResult },
        @{ name = "pulls_read"; result = $pullsResult }
    )
    $failed = @($checks | Where-Object { -not $_.result -or -not $_.result.ok })

    return [pscustomobject]@{
        provider = "github"
        status = $(if ($failed.Count -eq 0) { "passed" } else { "blocked" })
        blocker = $failed.Count -gt 0
        summary = $(if ($failed.Count -eq 0) { "GitHub PR provider read preflight passed." } else { "GitHub PR provider preflight is blocked." })
        next_action = $(if ($failed.Count -eq 0) { "Ensure the token also has pull request write permission and git push permission before creating PRs." } else { "Fix GitHub token permissions, repository name, or target branch, then rerun this script." })
        evidence = @{
            api_base_url = $GitHubApiBaseUrl
            repository = $repository
            target_branch = $TargetBranch
            token_present = [bool]$GitHubToken
            destructive_actions = $false
            checks = @($checks | ForEach-Object {
                [pscustomobject]@{
                    name = $_.name
                    ok = [bool]($_.result -and $_.result.ok)
                    status_code = $(if ($_.result) { $_.result.status_code } else { 0 })
                    error = $(if ($_.result) { $_.result.error } else { "not executed" })
                }
            })
        }
    }
}

function Test-GitLabProvider {
    $missing = @()
    if (-not $GitLabApiBaseUrl) { $missing += "GITLAB_API_BASE_URL" }
    if (-not $GitLabProjectId) { $missing += "GITLAB_PROJECT_ID" }
    if (-not $GitLabToken) { $missing += "GITLAB_TOKEN or project gitlab_token" }
    if (-not $TargetBranch) { $missing += "MERGE_REQUEST_DEFAULT_TARGET_BRANCH" }

    if ($missing.Count -gt 0) {
        return [pscustomobject]@{
            provider = "gitlab"
            status = "blocked"
            blocker = $true
            summary = "GitLab MR provider is missing configuration."
            next_action = "Configure $($missing -join ', ') before creating real MRs."
            evidence = @{
                api_base_url = $GitLabApiBaseUrl
                project_id = $GitLabProjectId
                target_branch = $TargetBranch
                missing = $missing
                token_present = [bool]$GitLabToken
            }
        }
    }

    $headers = @{ "PRIVATE-TOKEN" = $GitLabToken }
    $projectRef = [System.Uri]::EscapeDataString($GitLabProjectId)
    $projectUrl = "$($GitLabApiBaseUrl.TrimEnd('/'))/projects/$projectRef"
    $branchUrl = "$projectUrl/repository/branches/$([System.Uri]::EscapeDataString($TargetBranch))"
    $mrsUrl = "$projectUrl/merge_requests?state=opened&per_page=1"

    $projectResult = Invoke-Api -Uri $projectUrl -Headers $headers
    $branchResult = if ($projectResult.ok) { Invoke-Api -Uri $branchUrl -Headers $headers } else { $null }
    $mrsResult = if ($projectResult.ok) { Invoke-Api -Uri $mrsUrl -Headers $headers } else { $null }

    $checks = @(
        @{ name = "project"; result = $projectResult },
        @{ name = "target_branch"; result = $branchResult },
        @{ name = "merge_requests_read"; result = $mrsResult }
    )
    $failed = @($checks | Where-Object { -not $_.result -or -not $_.result.ok })

    return [pscustomobject]@{
        provider = "gitlab"
        status = $(if ($failed.Count -eq 0) { "passed" } else { "blocked" })
        blocker = $failed.Count -gt 0
        summary = $(if ($failed.Count -eq 0) { "GitLab MR provider read preflight passed." } else { "GitLab MR provider preflight is blocked." })
        next_action = $(if ($failed.Count -eq 0) { "Ensure the token also has api/write_repository permission and git push permission before creating MRs." } else { "Fix GitLab token permissions, project id, or target branch, then rerun this script." })
        evidence = @{
            api_base_url = $GitLabApiBaseUrl
            project_id = $GitLabProjectId
            target_branch = $TargetBranch
            token_present = [bool]$GitLabToken
            destructive_actions = $false
            checks = @($checks | ForEach-Object {
                [pscustomobject]@{
                    name = $_.name
                    ok = [bool]($_.result -and $_.result.ok)
                    status_code = $(if ($_.result) { $_.result.status_code } else { 0 })
                    error = $(if ($_.result) { $_.result.error } else { "not executed" })
                }
            })
        }
    }
}

$selectedProviders = @()
if ($Provider -eq "both") {
    $selectedProviders = @("github", "gitlab")
} elseif ($Provider -eq "auto") {
    if ($GitLabApiBaseUrl -or $GitLabProjectId -or $GitLabToken) {
        $selectedProviders = @("gitlab")
    } else {
        $selectedProviders = @("github")
    }
} else {
    $selectedProviders = @($Provider)
}

$providerResults = @()
foreach ($selected in $selectedProviders) {
    if ($selected -eq "github") {
        $providerResults += Test-GitHubProvider
    } elseif ($selected -eq "gitlab") {
        $providerResults += Test-GitLabProvider
    }
}

$blocked = @($providerResults | Where-Object { $_.status -ne "passed" })
$result = [pscustomobject]@{
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    status = $(if ($blocked.Count -eq 0) { "passed" } else { "blocked" })
    blocker = $blocked.Count -gt 0
    summary = $(if ($blocked.Count -eq 0) { "Merge request provider preflight passed." } else { "Merge request provider preflight is blocked." })
    next_action = $(if ($blocked.Count -eq 0) { "Run a real low-risk MR/PR pilot when source branch push is ready." } else { "Configure the blocked provider items in evidence and rerun this script." })
    providers = $providerResults
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputFile) | Out-Null
$result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputFile -Encoding UTF8

Write-Host "Merge request provider validation"
Write-Host "Status:  $($result.status)"
Write-Host "Summary: $($result.summary)"
Write-Host "Report:  $OutputFile"

if ($result.status -ne "passed" -and -not $ContinueOnFailure) {
    exit 1
}
