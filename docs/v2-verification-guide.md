# AI PJM v2 Verification Guide

This guide defines how to verify each implementation slice without relying on subjective judgment.

## 1. Baseline Checks

Run from `backend/`:

```powershell
python -m compileall app
python -m pytest tests/test_delivery_v2_units.py -q
```

Expected result:

- Python modules compile.
- Unit tests for risk and approval rules pass.

## 2. Database-backed API Checks

Prerequisite:

- The tests use an isolated SQLite database session through `backend/tests/conftest.py`.
- PostgreSQL is not required for local verification.

Run:

```powershell
python -m pytest tests/test_delivery_v2.py -q
```

Expected result:

- Demand can be created.
- Spec can be generated.
- Gate checks are recorded.
- Repo context can be collected.
- Impact analysis can be generated.
- CodingTask can be generated.
- ExecutionRun can be created as queued or blocked by gate policy.
- Demand detail includes spec cards, gate checks, repo contexts, impact analyses, and coding tasks.

## 3. Manual API Verification

Start backend only when you intentionally want to test the API:

```powershell
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8010
```

Create a normal-risk demand:

```powershell
$demand = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8010/api/v2/demands" `
  -ContentType "application/json" `
  -Body '{"raw_input":"Add a compact execution status badge to the delivery dashboard.","source_type":"new_requirement"}'

$demand.data
```

Expected:

```text
status = intake
```

Generate spec:

```powershell
$spec = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8010/api/v2/demands/$($demand.data.id)/spec" `
  -ContentType "application/json" `
  -Body '{"auto_approve_low_risk":true}'

$spec.data
```

Expected:

```text
status = approved
```

Collect repository context:

```powershell
$repoContext = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8010/api/v2/demands/$($demand.data.id)/repo-context" `
  -ContentType "application/json" `
  -Body '{}'

$repoContext.data
```

Expected:

```text
status = ready
provider = mock
```

Generate impact analysis:

```powershell
$impact = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8010/api/v2/demands/$($demand.data.id)/impact-analysis" `
  -ContentType "application/json" `
  -Body "{`"repo_context_id`":$($repoContext.data.id)}"

$impact.data
```

Expected:

```text
status = ready
risk_level = L1
```

Generate CodingTask:

```powershell
$task = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8010/api/v2/spec-cards/$($spec.data.id)/coding-task" `
  -ContentType "application/json" `
  -Body '{"allowed_paths":["frontend/src/app/components"],"required_checks":["npm run build"]}'

$task.data
```

Expected:

```text
status = ready
task_prompt contains acceptance criteria and constraints
```

Create execution run record:

```powershell
$run = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8010/api/v2/coding-tasks/$($task.data.id)/runs" `
  -ContentType "application/json" `
  -Body '{"executor_type":"codex","trigger_mode":"manual"}'

$run.data
```

Expected:

```text
status = queued
logs count >= 1
```

Dispatch execution run:

```powershell
$run = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8010/api/v2/execution-runs/$($run.data.id)/dispatch" `
  -ContentType "application/json" `
  -Body '{}'

$run.data
```

Expected:

```text
status = succeeded
result_summary = Required checks passed (1/1).
evidence_json.dispatch.check_results count = 1
```

Fetch demand detail:

```powershell
$detail = Invoke-RestMethod `
  -Method Get `
  -Uri "http://localhost:8010/api/v2/demands/$($demand.data.id)"

$detail.data
```

Expected:

```text
status = planned
risk_level = L1
spec_cards count = 1
repo_contexts count = 1
impact_analyses count = 1
gate_checks count >= 5
coding_tasks count = 1
```

## 4. High-risk Gate Verification

Create a high-risk demand:

```powershell
$riskDemand = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8010/api/v2/demands" `
  -ContentType "application/json" `
  -Body '{"raw_input":"Change login permission logic and migrate production user tokens.","source_type":"bug_report"}'

$riskSpec = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8010/api/v2/demands/$($riskDemand.data.id)/spec" `
  -ContentType "application/json" `
  -Body '{}'

$riskDetail = Invoke-RestMethod `
  -Method Get `
  -Uri "http://localhost:8010/api/v2/demands/$($riskDemand.data.id)"

$riskDetail.data
```

Expected:

```text
demand.status = spec_manual_required
demand.risk_level = L2
spec.status = manual_review
one gate_check.status = manual_required
```

## 5. Slice-level Acceptance Criteria

## 5. Failed Check and Retry Verification

Use a safe command that fails deterministically:

```powershell
$failedTask = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8010/api/v2/spec-cards/$($spec.data.id)/coding-task" `
  -ContentType "application/json" `
  -Body '{"allowed_paths":["backend/app"],"required_checks":["python -m pytest tests/not_exists_for_delivery_failure.py -q"]}'

$failedRun = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8010/api/v2/coding-tasks/$($failedTask.data.id)/runs" `
  -ContentType "application/json" `
  -Body '{}'

$failedRun = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8010/api/v2/execution-runs/$($failedRun.data.id)/dispatch" `
  -ContentType "application/json" `
  -Body '{}'

$retryRun = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8010/api/v2/coding-tasks/$($failedTask.data.id)/retry" `
  -ContentType "application/json" `
  -Body '{}'
```

Expected:

```text
failedRun.data.status = failed
failedRun.data.result_summary = Required checks failed (0/1 passed).
failedRun.data.evidence_json.dispatch.check_results[0].status = failed
retryRun.data.status = failed
retryRun.data.trigger_mode = manual_retry
latest demand detail shows task.status = blocked
latest demand detail includes a failed self_test_passed gate
```

## 6. Manual Approval Verification

Prepare a high-risk task, then approve it:

```powershell
$riskDemand = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8010/api/v2/demands" `
  -ContentType "application/json" `
  -Body '{"raw_input":"Change login permission logic and migrate production user tokens.","source_type":"bug_report"}'

$riskSpec = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8010/api/v2/demands/$($riskDemand.data.id)/spec" `
  -ContentType "application/json" `
  -Body '{}'

$approval = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8010/api/v2/demands/$($riskDemand.data.id)/manual-approval" `
  -ContentType "application/json" `
  -Body '{"approved":true,"approver_ref":"local_operator","note":"Scope accepted for test execution."}'
```

Expected:

```text
riskSpec.data.status = manual_review
approval.data.spec_cards[0].status = approved
approval.data.gate_checks includes execution_allowed/passed with evidence_json.approval_type = manual
```

If a draft coding task already exists before approval, approval promotes the latest draft task to `ready`. The UI should then hide the manual approval panel and enable `Continue`.

## 7. Codex Command Hook Verification

The `codex` executor path can optionally run a configured command inside the generated worktree before required checks.

Codex CLI prerequisite on Windows:

```powershell
npm install -g @openai/codex
codex --version
```

The WindowsApps packaged `codex.exe` can return `Access is denied`; prefer the npm CLI entry so `where codex` resolves `C:\Users\<user>\AppData\Roaming\npm\codex.cmd` before the WindowsApps package.

Configuration:

```powershell
EXECUTION_CODEX_ENABLED=true
EXECUTION_CODEX_PREFLIGHT_COMMAND=codex --version
EXECUTION_CODEX_PREFLIGHT_TIMEOUT_SECONDS=30
EXECUTION_CODEX_COMMAND_TEMPLATE=powershell -NoProfile -ExecutionPolicy Bypass -File "{original_workspace_root}\scripts\run-codex-task.ps1" -PromptFile "{prompt_file}" -WorkspaceRoot "{workspace_root}"
EXECUTION_CODEX_TIMEOUT_SECONDS=1800
```

The recommended command template delegates quoting and stdin handling to `scripts/run-codex-task.ps1`. The script reads `{prompt_file}` and pipes it into `codex --ask-for-approval never -c model_reasoning_effort="low" exec --ephemeral --sandbox workspace-write -C {workspace_root} -`.

Supported template placeholders:

```text
{workspace_root}
{original_workspace_root}
{branch_name}
{commit_sha}
{prompt_file}
{run_id}
{task_id}
```

Expected evidence when the hook is enabled:

```text
evidence_json.dispatch.codex_invocation.enabled = true
evidence_json.dispatch.codex_invocation.status = passed or failed
evidence_json.dispatch.codex_invocation.prompt_file is recorded
evidence_json.dispatch.codex_invocation.preflight is recorded when EXECUTION_CODEX_PREFLIGHT_COMMAND is set
evidence_json.dispatch.codex_invocation.changed_files includes files changed by the command
```

If preflight fails, the executor stops before the Codex command and required checks. The run records `Codex execution preflight failed`, `timed out`, or `failed to start` evidence in `codex_invocation.preflight`.

Changed files are checked against `CodingTask.allowed_paths_json` after the Codex command. Out-of-scope changes fail the run before required checks and record `changed_file_violations`.

If `EXECUTION_CODEX_ENABLED=false`, the executor still creates a worktree and runs required checks, but records `codex_invocation.enabled = false`.

## 8. Automatic Repair Verification

Automatic repair is available for low-risk tasks after a failed run with failed check evidence.

Configuration:

```powershell
EXECUTION_AUTO_REPAIR_MAX_ATTEMPTS=1
```

API:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8010/api/v2/coding-tasks/<task_id>/auto-repair" `
  -ContentType "application/json" `
  -Body '{"executor_type":"codex","max_attempts":1}'
```

Expected evidence:

```text
execution_run.trigger_mode = auto_repair
evidence_json.execution_allowed.repair_context.source_run_id = previous failed run id
evidence_json.execution_allowed.repair_context.failed_checks contains failed check output
```

L2/L3 tasks and changed-file violations must not enter automatic repair.

## 9. Merge Request and Review Verification

After a task has a succeeded execution run:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8010/api/v2/coding-tasks/<task_id>/merge-request" `
  -ContentType "application/json" `
  -Body '{"provider":"local","target_branch":"main"}'
```

Expected evidence:

```text
merge_request.provider = local
merge_request.status = created
merge_request.review_status = pending
merge_request.source_branch = execution_run.branch_name
merge_request.url = local://merge-requests/<id>
```

Record a local review result:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8010/api/v2/merge-requests/<merge_request_id>/review" `
  -ContentType "application/json" `
  -Body '{"review_status":"passed","review_summary":"Local review passed.","review_comments":[],"blocking_issues":[]}'
```

Expected evidence:

```text
merge_request.status = review_passed
merge_request.review_status = passed
gate_check.gate_type = review_passed
gate_check.status = passed
```

## 10. Deployment and Verification Record Verification

After an MR/PR review has passed:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8010/api/v2/merge-requests/<merge_request_id>/deployments" `
  -ContentType "application/json" `
  -Body '{"provider":"local","environment":"test"}'
```

Expected evidence:

```text
deploy_record.provider = local
deploy_record.status = deployed
deploy_record.environment = test
deploy_record.url = local://deployments/<id>
gate_check.gate_type = test_deployed
gate_check.status = passed
```

Record verification:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8010/api/v2/deployments/<deploy_record_id>/verification" `
  -ContentType "application/json" `
  -Body '{"status":"passed","verifier_ref":"local_operator","summary":"Manual verification passed.","evidence_links":["local://deployments/<id>"]}'
```

Expected evidence:

```text
verification_record.status = passed
gate_check.gate_type = verification_passed
gate_check.status = passed
```

## 11. Execution Queue Verification

List recent execution records:

```powershell
Invoke-RestMethod -Method Get `
  -Uri "http://127.0.0.1:8010/api/v2/execution-runs?limit=30"
```

Filter queued records:

```powershell
Invoke-RestMethod -Method Get `
  -Uri "http://127.0.0.1:8010/api/v2/execution-runs?statuses=queued&limit=30"
```

Expected evidence:

```text
execution queue items include run id, status, trigger mode, task title, demand id, and risk level
dispatch refuses to start when running executions >= EXECUTION_MAX_CONCURRENCY
queued runs remain queued when the concurrency limit is reached
```

## 12. Dify Provider Configuration Verification

Dify is not enabled by default. To test the provider boundary, configure:

```powershell
$env:AI_WORKFLOW_PROVIDER="dify"
$env:DIFY_API_BASE_URL="https://<your-dify-host>"
$env:DIFY_API_KEY="<workflow-api-key>"
$env:DIFY_API_KEY_SECRET_NAME="dify_api_key"
$env:DIFY_SPEC_WORKFLOW_ID="<spec-workflow-id>"
$env:DIFY_IMPACT_WORKFLOW_ID="<impact-workflow-id>"
```

For project-scoped credentials, store a project secret with:

```text
name = dify_api_key
provider = dify
value = <workflow-api-key>
```

The Dify Provider resolves credentials in this order:

```text
project SecretStore value named by DIFY_API_KEY_SECRET_NAME
-> global DIFY_API_KEY
```

Expected Dify workflow outputs for Spec:

```text
title: string
user_story: string
scope: string
acceptance_criteria: string[] or newline string
constraints: string[] or newline string
risks: string[] or newline string
open_questions: string[] or newline string, optional
```

Expected Dify workflow outputs for impact analysis:

```text
summary: string
impacted_areas: string[] or newline string
affected_files: string[] or newline string
recommendations: string[] or newline string
risk_level: L0 | L1 | L2 | L3
confidence_score: number between 0 and 1
```

If required configuration or required output fields are missing, the provider must fail clearly and must not silently advance the workflow.

## 13. Auth and Project Access Verification

Local development keeps auth disabled unless `AUTH_ENABLED=true`.

To test local login and project permissions:

```powershell
cd backend
$env:AUTH_ENABLED="true"
$env:AUTH_BOOTSTRAP_ADMIN_PASSWORD="change-me-before-production"
python -m pytest tests/test_auth.py -q
```

Expected behavior:

- `/api/v2/auth/me` returns a local admin principal when auth is disabled.
- When auth is enabled, delivery APIs reject unauthenticated requests with `401`.
- A logged-in operator can create delivery work only inside accessible projects.
- Project members cannot read or operate another project's delivery records.
- Viewer role can read accessible work but cannot create new demand items.
- Key human or sensitive actions create project-scoped audit events.
- Project members cannot read audit events from another project.
- Admin users can list projects and users.
- Admin users can update local users, reset passwords, and maintain project roles.
- Non-admin users cannot manage users or project membership.
- The access management page can load project and user data without `failed to fetch`.

## 14. SecretStore Verification

SecretStore writes are disabled until a server-side master key is configured.

Run:

```powershell
cd backend
python -m pytest tests/test_auth.py tests/test_delivery_v2_units.py -q
```

Expected behavior:

- Creating a project secret without `SECRET_STORE_MASTER_KEY` returns `400`.
- Admin users can create and list project secrets after the master key is configured.
- API responses include `value_mask`, but never include the plaintext secret value.
- Project-scoped users cannot list or rotate secrets outside their project.
- Secret creation and rotation create audit events.
- Dify Provider can resolve `dify_api_key` from project SecretStore without returning the key to the frontend.

Manual local configuration:

```powershell
cd backend
$env:AUTH_ENABLED="true"
$env:AUTH_BOOTSTRAP_ADMIN_PASSWORD="change-me-before-production"
$env:SECRET_STORE_MASTER_KEY="replace-with-a-long-random-secret"
```

After startup, open the access management page and verify:

```text
项目密钥 section is visible.
Saving a secret succeeds when the master key is set.
The secret table shows only masked values, for example ****alue.
Plaintext secret values never appear after save or refresh.
```

## 15. Slice-level Acceptance Criteria

### Slice 0: Baseline

- v2 docs exist.
- v2 APIs are mounted under `/api/v2`.
- Legacy v1 product APIs and pages are removed from the active codebase.

### Slice 1: Demand to Spec

- A demand can be created.
- A SpecCard can be generated.
- Risk is classified as `L0`, `L1`, `L2`, or `L3`.
- `spec_ready` and `risk_classified` gates are persisted.
- Low-risk/normal-risk demands can auto-approve when policy allows.
- High-risk demands require manual review.
- Manual approval records gate evidence and promotes approved high-risk specs.

### Slice 2: Repo Context and Impact

- RepoContext is stored with provider, source refs, discovered files, dependencies, and confidence score.
- `repo_context_ready` gate is persisted.
- ImpactAnalysis is stored with impacted areas, affected files, recommendations, risk level, and confidence score.
- `impact_analyzed` gate is persisted.
- The default `local` provider scans the real workspace for repository structure, docs, configs, tests, dependency references, and demand-related candidate files.

### Slice 3: Codex Task

- CodingTask includes goal, prompt, allowed paths, forbidden actions, required checks, and expected evidence.
- CodingTask is `ready` only when gates allow automated execution.

### Slice 4: Execution

- ExecutionRun and ExecutionLog records are persisted.
- `execution_allowed` gate controls whether a run is `queued` or `blocked`.
- Queued runs can be dispatched through the local required-check executor.
- `executor_type = codex` prepares an isolated Git worktree and branch before running checks.
- Optional Codex command hook can run inside the prepared worktree before checks.
- Check command status, exit code, duration, stdout tail, and stderr tail are persisted as evidence.
- Failed checks mark the task as `blocked`, record a failed `self_test_passed` gate, and can be retried as a new execution attempt.
- Low-risk failed checks can enter a bounded automated repair attempt when policy allows.
- High-risk execution remains blocked until manual approval evidence exists.

To be added:

- Production Codex CLI or SDK command and runner operations are finalized for the target environment.
- Background worker dispatches queued execution outside HTTP request handling.

### Slice 5: Delivery

- MR/PR record is created after successful self-test.
- MR/PR link, source branch, target branch, and review status are visible in the workbench.
- `review_passed` gate is persisted when review passes.
- Test deployment record is created after review passes.
- Deployment URL, environment, and verification status are visible in the workbench.
- `test_deployed` and `verification_passed` gates are persisted.

To be added:

- GitLab/GitHub providers create real remote MR/PR and poll comments.
- Real deployment provider triggers a real test environment.
- Failed verification can automatically route back to repair once policy is defined.

### Slice 6: Queue and Parallel Control

- Execution queue can be queried and shown in the workbench.
- Dispatch respects `EXECUTION_MAX_CONCURRENCY`.
- Runs over the limit remain queued instead of starting silently.

To be added:

- Background worker dispatches queued runs automatically.
- Cancel, pause, and resume controls are available.
- Resource usage limits are visible in the workbench.

### Slice 7: Provider Integration

- Provider can be switched among `mock`, `local`, and `dify` through configuration.
- Dify outputs are parsed into structured drafts only.
- Invalid or missing Dify configuration fails explicitly.

To be added:

- OpenAI provider.
- Retry and fallback policy for transient provider failures.

## 16. Regression Checklist

Before every larger change:

- `python -m compileall app`
- `python -m pytest tests/test_auth.py -q`
- `python -m pytest tests/test_delivery_v2_units.py -q`
- `python -m pytest tests/test_delivery_v2.py tests/test_health.py -q`
- `npm run build` from `frontend/` when UI code changes
