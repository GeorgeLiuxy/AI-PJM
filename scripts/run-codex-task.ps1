param(
    [Parameter(Mandatory = $true)]
    [string]$PromptFile,

    [Parameter(Mandatory = $true)]
    [string]$WorkspaceRoot,

    [string]$Sandbox = "workspace-write",
    [string]$Approval = "never",
    [string]$ReasoningEffort = "low"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $PromptFile)) {
    throw "Prompt file not found: $PromptFile"
}
if (-not (Test-Path -LiteralPath $WorkspaceRoot)) {
    throw "Workspace root not found: $WorkspaceRoot"
}

$codexCommand = Get-Command codex.cmd -ErrorAction SilentlyContinue
if (-not $codexCommand) {
    $codexCommand = Get-Command codex -ErrorAction Stop
}

$promptText = Get-Content -LiteralPath $PromptFile -Raw
Write-Host "Codex executable: $($codexCommand.Source)"

$promptText | & $codexCommand.Source `
    --ask-for-approval $Approval `
    -c "model_reasoning_effort=`"$ReasoningEffort`"" `
    exec `
    --ephemeral `
    --sandbox $Sandbox `
    --color never `
    -C $WorkspaceRoot `
    -

exit $LASTEXITCODE
