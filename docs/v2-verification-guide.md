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
- PostgreSQL is not required for normal local verification.

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

## 3. PostgreSQL Migration Verification

Use this when validating production-equivalent migration behavior. Docker can be used locally:

```powershell
docker run --rm -d --name ai-pjm-postgres-test `
  -e POSTGRES_USER=ai_pjm `
  -e POSTGRES_PASSWORD=ai_pjm_test `
  -e POSTGRES_DB=ai_pjm_test `
  -p 55432:5432 postgres:16-alpine

cd backend
python scripts/migrate.py upgrade head --database-url "postgresql+asyncpg://ai_pjm:ai_pjm_test@127.0.0.1:55432/ai_pjm_test"
python scripts/migrate.py current --database-url "postgresql+asyncpg://ai_pjm:ai_pjm_test@127.0.0.1:55432/ai_pjm_test"

docker rm -f ai-pjm-postgres-test
```

Expected result:

```text
Alembic reports the latest head revision.
The migration reaches revision 012 or newer.
delivery_* workflow tables include trace_id columns.
```

This was last verified on 2026-06-04 with Docker PostgreSQL 16 and Alembic head `012`.

## 4. Backup and Restore Verification

SQLite local backup:

```powershell
cd backend
python scripts/database_backup.py --database-url "sqlite+aiosqlite:///./data/ai_pjm.db"
```

SQLite restore requires an explicit confirmation token:

```powershell
python scripts/database_restore.py ".runtime/backups/<backup-file>.sqlite" `
  --database-url "sqlite+aiosqlite:///./data/ai_pjm.db" `
  --confirm RESTORE_AI_PJM_DATABASE
```

PostgreSQL backup and restore use `pg_dump` and `pg_restore`; ensure those CLI tools are installed on the host:

```powershell
python scripts/database_backup.py --database-url "postgresql+asyncpg://user:pass@host:5432/ai_pjm"

python scripts/database_restore.py ".runtime/backups/<backup-file>.dump" `
  --database-url "postgresql+asyncpg://user:pass@host:5432/ai_pjm" `
  --confirm RESTORE_AI_PJM_DATABASE
```

Expected behavior:

```text
Backup creates a timestamped file under .runtime/backups by default.
SQLite restore creates a pre-restore safety copy unless --no-safety-copy is used.
Restore refuses to run without --confirm RESTORE_AI_PJM_DATABASE.
```

## 5. Trace Backfill Verification

Run dry-run first:

```powershell
cd backend
python scripts/backfill_delivery_trace_ids.py --dry-run
```

If the output is expected, run the real update:

```powershell
python scripts/backfill_delivery_trace_ids.py
```

Expected behavior:

```text
dry_run = true does not write to the database.
updated reports per-table counts.
New or backfilled demand, spec, gate, context, impact, task, run, log, MR, deployment, and verification rows share one trace_id per demand.
```

## 6. Manual API Verification

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
trace_id starts with dlv-
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
trace_id equals demand.data.trace_id
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
trace_id equals demand.data.trace_id
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
trace_id equals demand.data.trace_id
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
trace_id equals demand.data.trace_id
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
trace_id equals demand.data.trace_id
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
trace_id is the same across demand, spec, repo context, impact analysis, task, run, and logs
```

## 7. High-risk Gate Verification

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

## 8. Failed Check and Retry Verification

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

## 9. Manual Approval Verification

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

## 10. Codex Command Hook Verification

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

## 11. Automatic Repair Verification

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

## 12. Merge Request and Review Verification

After a task has a succeeded execution run:

```powershell
$env:DELIVERY_APP_BASE_URL="http://127.0.0.1:5174"

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
merge_request.evidence_json.evidence_links.demand.url contains ?demand_id=<id>&tab=summary when DELIVERY_APP_BASE_URL is configured
MR description contains AI PJM Delivery Summary, Check Results, Changed Files, and Evidence Links
```

Open a generated evidence link such as `http://127.0.0.1:5174/?demand_id=<id>&tab=execution`. The delivery workspace should load that demand and open the requested tab without browser console errors.

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

For GitLab MR provider defaults, configure labels and reviewers before creating the MR:

```powershell
$env:GITLAB_DEFAULT_LABELS="ai-pjm,delivery"
$env:GITLAB_REVIEWER_IDS="101,102"
$env:GITLAB_ASSIGNEE_IDS="201"
```

For GitHub PR provider, configure the repository, token, and optional defaults before creating the PR:

```powershell
$env:GITHUB_API_BASE_URL="https://api.github.com"
$env:GITHUB_REPOSITORY="<owner>/<repo>"
$env:GITHUB_TOKEN="<github-token>"
$env:GITHUB_DEFAULT_LABELS="ai-pjm,delivery"
$env:GITHUB_REVIEWERS="alice,bob"
$env:GITHUB_ASSIGNEES="carol"
```

Project SecretStore can be used instead of `GITHUB_TOKEN` by creating a `github_token` secret with provider `github`.

For GitHub webhook verification, configure the webhook secret and post a signed check-run event after a GitHub PR record exists:

```powershell
$env:GITHUB_WEBHOOK_SECRET="local-github-webhook-secret"
$body = '{"action":"completed","check_run":{"name":"unit","status":"completed","conclusion":"success","pull_requests":[{"number":42}]}}'
$secretBytes = [Text.Encoding]::UTF8.GetBytes($env:GITHUB_WEBHOOK_SECRET)
$bodyBytes = [Text.Encoding]::UTF8.GetBytes($body)
$hmac = [System.Security.Cryptography.HMACSHA256]::new($secretBytes)
$signature = "sha256=" + ([BitConverter]::ToString($hmac.ComputeHash($bodyBytes)).Replace("-", "").ToLowerInvariant())

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8010/api/v2/github/webhook" `
  -Headers @{"X-GitHub-Event"="check_run"; "X-Hub-Signature-256"=$signature} `
  -ContentType "application/json" `
  -Body $body
```

Expected evidence:

```text
The existing GitHub PR record whose external_id is 42 is updated.
review_status becomes passed for a successful check_run or status event.
gate_check.gate_type = review_passed is written through the same gate path.
evidence_json.github_webhook.last_event stores the redacted webhook event.
```

For GitLab webhook verification, configure the secret token and post a pipeline event after a GitLab MR record exists:

```powershell
$env:GITLAB_WEBHOOK_SECRET_TOKEN="local-webhook-secret"

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8010/api/v2/gitlab/webhook" `
  -Headers @{"X-Gitlab-Token"="local-webhook-secret"} `
  -ContentType "application/json" `
  -Body '{"object_kind":"pipeline","object_attributes":{"status":"success"},"merge_request":{"iid":12}}'
```

Expected evidence:

```text
The existing GitLab MR record whose external_id is 12 is updated.
review_status becomes passed for a success pipeline.
gate_check.gate_type = review_passed is written through the same gate path.
evidence_json.gitlab_webhook.last_event stores the redacted webhook event.
```

## 13. Deployment and Verification Record Verification

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
deploy_record.trace_id equals the demand trace_id
gate_check.gate_type = test_deployed
gate_check.status = passed
```

Environment-level defaults can be verified without a real deployment system:

```powershell
$env:DEPLOY_ENVIRONMENT_CONFIG_JSON='{"test":{"url":"https://test.example/app","log_url":"https://ci.example/jobs/42","description":"Shared test environment"}}'
```

When creating a `local` deployment with `environment = test` and no request URL, expected evidence is:

```text
deploy_record.url = https://test.example/app
deploy_record.evidence_json.deployment_config.environment = test
deploy_record.evidence_json.deployment_config.source = DEPLOY_ENVIRONMENT_CONFIG_JSON
deploy_record.evidence_json.deployment_logs.configured_log_url = https://ci.example/jobs/42
```

Project-level deployment environment settings take precedence over the global fallback. Configure and verify them through the API:

```powershell
Invoke-RestMethod -Method Put `
  -Uri "http://127.0.0.1:8010/api/v2/projects/<project_id>/deployment-environments" `
  -ContentType "application/json" `
  -Body '{"environments":{"test":{"url":"https://project-test.example/app","log_url":"https://ci.example/project/jobs/42","description":"Project test environment","environment_name":"Project Test"}}}'

Invoke-RestMethod -Method Get `
  -Uri "http://127.0.0.1:8010/api/v2/projects/<project_id>/deployment-environments"
```

When creating a deployment for a demand in that project with `environment = test` and no request URL, expected evidence is:

```text
deploy_record.url = https://project-test.example/app
deploy_record.evidence_json.deployment_config.source = project_settings
deploy_record.evidence_json.deployment_config.log_url = https://ci.example/project/jobs/42
```

The same project-level settings can be edited from the frontend: open `Access` / `访问管理`, use the `测试环境配置` panel, select a project, fill `环境名 = test`, and save the URL/log URL.

For webhook deployments, if the provider response includes `log_url`, `logs_url`, `deployment_log_url`, `logs`, `log`, or `output`, the evidence should contain redacted `deployment_logs.provider_log_url` and/or `deployment_logs.logs_tail`.

Webhook status sync also normalizes common CI/CD status shapes. A response with nested `pipeline.jobs`, `stages`, `steps`, `checks`, `tasks`, or `deployments` should produce:

```text
deploy_record.evidence_json.remote_status.raw_status = failed/running/success/...
deploy_record.evidence_json.remote_status.normalized_status = failed/pending/deployed
deploy_record.evidence_json.remote_status.status_path = pipeline.jobs[1].status
deploy_record.evidence_json.remote_status.status_item = deploy
deploy_record.evidence_json.remote_status.failed_status_items = [failed node summary]
```

If a create response has no explicit status but includes `status_url`, the deployment remains `pending` until status sync resolves it.

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

## 14. Execution Queue Verification

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
manual retry evidence contains execution_allowed.retry_context.source_run_id
manual retry evidence contains execution_allowed.retry_context.retry_chain
repeating retry while a queued/running/paused run exists returns the active run instead of creating another queued run
```

Recover expired running Symphony runs:

```powershell
cd backend
python scripts/recover_symphony_runs.py --limit 100 --status-file .runtime/symphony-recovery-status.json
```

Expected behavior:

```text
Expired running Symphony runs are marked failed.
The coding task is moved to blocked.
A failed self_test_passed gate and execution log are recorded.
The status file records recovered_count and recovered_run_ids.
```

Run the local Symphony worker continuously:

```powershell
.\scripts\start-symphony-worker.ps1
```

Expected behavior:

```text
.runtime/symphony-worker/worker-status.json is written.
Loop mode keeps polling after a transient worker/API error and writes state = error.
Pass --fail-fast to backend/scripts/symphony_worker.py only when a supervisor should restart the process on first error.
```

## 15. Dify Provider Configuration Verification

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

## 16. OpenAI Provider Configuration Verification

OpenAI is not enabled by default. To test the provider boundary, configure:

```powershell
$env:AI_WORKFLOW_PROVIDER="openai"
$env:OPENAI_API_BASE_URL="https://api.openai.com/v1"
$env:OPENAI_API_KEY="<openai-api-key>"
$env:OPENAI_API_KEY_SECRET_NAME="openai_api_key"
$env:OPENAI_MODEL="gpt-4o-mini"
$env:OPENAI_REQUEST_TIMEOUT_SECONDS="120"
$env:AI_WORKFLOW_PROVIDER_SCHEMA_VERSION="delivery-v2.1"
$env:AI_WORKFLOW_PROVIDER_PROMPT_VERSION="delivery-v2.1"
```

For project-scoped credentials, store a project secret with:

```text
name = openai_api_key
provider = openai
value = <openai-api-key>
```

The OpenAI Provider resolves credentials in this order:

```text
project SecretStore value named by OPENAI_API_KEY_SECRET_NAME
-> global OPENAI_API_KEY
```

Expected OpenAI behavior:

```text
Spec and impact analysis are requested through the Responses API with strict JSON Schema output.
Repository context collection and coding task generation still use local rules.
Provider metadata records provider, model, response id, schema name, schema version, prompt version, and credential source only.
Plaintext API keys must never be stored in provider metadata or frontend responses.
Spec/Impact metadata includes quality_evaluation with score, min_score, passed, findings, and version.
```

If required configuration, output text, valid JSON, required fields, risk level, or confidence score are missing, the provider must fail clearly and must not silently advance the workflow.

External provider recovery is controlled by:

```powershell
$env:AI_WORKFLOW_PROVIDER_RETRY_ATTEMPTS="2"
$env:AI_WORKFLOW_PROVIDER_RETRY_BACKOFF_SECONDS="0.25"
$env:AI_WORKFLOW_PROVIDER_FALLBACK_ENABLED="true"
```

Expected recovery behavior:

```text
Dify/OpenAI Spec and impact operations retry before failing.
When fallback is enabled and retries are exhausted, local rules generate the draft.
Spec fallback adds an open question warning.
Spec gates and impact metadata include provider_recovery with failed provider, fallback provider, attempts, and redacted errors.
```

Provider quality smoke test:

```powershell
cd backend
python scripts/provider_quality_smoke.py --provider local
python scripts/provider_quality_smoke.py --provider openai --min-score 0.65
python scripts/provider_quality_smoke.py --provider dify --min-score 0.65
```

Expected behavior:

```text
The script does not write delivery state.
It generates Spec and Impact drafts through the selected provider.
It prints deterministic quality scores, findings, redacted provider metadata, and exits non-zero when the score is below threshold.
Dify/OpenAI runs require the same environment variables described above.
```

Dify remote credential probing is intentionally opt-in because calling an arbitrary workflow could produce side effects. Configure a safe read-only endpoint first:

```powershell
$env:DIFY_HEALTH_CHECK_URL="https://<your-dify-host>/<safe-readonly-health-endpoint>"
```

## 16.1 Deployment Sync Worker Verification

For webhook deployments that return `pending` with a `status_url`, run a one-shot sync from `backend/`:

```powershell
python scripts/deployment_sync_worker.py --limit 20 --status-file .runtime/deployment-sync-status.json
```

For continuous polling:

```powershell
$env:DEPLOYMENT_SYNC_POLL_SECONDS="120"
python scripts/deployment_sync_worker.py --loop --limit 20 --status-file .runtime/deployment-sync-status.json
```

From the repository root, the same background worker can be started and stopped through the project script:

```powershell
.\scripts\start-deployment-sync-worker.ps1
.\scripts\stop-deployment-sync-worker.ps1
```

It can also be started together with the development stack:

```powershell
.\scripts\start-dev.ps1 -WithDeploymentSync
```

Expected behavior:

```text
Pending deploy records are scanned.
Remote status is synced through the same service path as POST /api/v2/deployments/sync-pending.
Successful or failed deployment status updates write gates, audit events, and redacted evidence.
The optional status file records state, counts, synced ids, and redacted errors.
```

## 16.2 Performance Smoke Verification

To prepare a controlled capacity dataset in a test or pre-production database, run from `backend/`:

```powershell
python scripts/seed_delivery_capacity.py --count 10000 --batch-size 500 --prefix capacity --include-delivery-records --confirm
```

Production safety:

```powershell
# Only for a controlled benchmark environment, never for live business data.
python scripts/seed_delivery_capacity.py --count 10000 --confirm --allow-production
```

Expected seed behavior:

```text
The script refuses to write without --confirm.
ENVIRONMENT=production also requires --allow-production.
It creates synthetic demand, Spec, task, execution run, and optionally local MR/deployment records.
Synthetic rows are marked with source_type = capacity_seed and context_payload.capacity_seed = true.
```

After the backend is running, execute a read-only smoke test from `backend/`:

```powershell
python scripts/performance_smoke.py --base-url http://127.0.0.1:8010 --requests 80 --concurrency 8
```

When auth is enabled, pass a bearer token:

```powershell
$env:AI_PJM_API_TOKEN="<token>"
python scripts/performance_smoke.py --base-url http://127.0.0.1:8010 --requests 120 --concurrency 12 --max-p95-ms 1000 --max-error-rate-percent 1
```

Expected behavior:

```text
The script calls core read endpoints only.
It prints total requests, p50, p95, max latency, error rate, per-endpoint status codes, and sample errors.
The process exits non-zero when p95 or error-rate thresholds are exceeded.
```

## 16.3 Observability Alert Worker Verification

Project-level health summary:

```powershell
Invoke-RestMethod -Method Get `
  -Uri "http://127.0.0.1:8010/api/v2/observability/projects"
```

Expected response:

```text
Each project item includes project id/key/name, status, alert counts, metrics, and up to three top alerts.
When auth is enabled, only projects visible to the current user are returned.
```

Prometheus-compatible text metrics:

```powershell
Invoke-WebRequest -Method Get `
  -Uri "http://127.0.0.1:8010/api/v2/observability/metrics"
```

Expected response:

```text
Content-Type starts with text/plain.
Body contains ai_pjm_observability_status_code, ai_pjm_execution_runs, ai_pjm_worker_expired_runs, ai_pjm_failed_deployments, ai_pjm_secret_health, ai_pjm_recent_execution_failure_rate_percent, and ai_pjm_alerts.
When auth is enabled, metrics are computed only from projects visible to the current user.
```

Run a one-shot check from `backend/`:

```powershell
python scripts/observability_alert_worker.py --api-base-url http://127.0.0.1:8010/api/v2 --status-file .runtime/observability-alert-status.json
```

Forward warnings or critical alerts to an external webhook:

```powershell
$env:OBSERVABILITY_ALERT_WEBHOOK_URL="https://<alert-system>/webhook"
python scripts/observability_alert_worker.py --api-base-url http://127.0.0.1:8010/api/v2 --fail-on-warning
```

For continuous polling:

```powershell
$env:OBSERVABILITY_ALERT_POLL_SECONDS="120"
python scripts/observability_alert_worker.py --loop --api-base-url http://127.0.0.1:8010/api/v2 --status-file .runtime/observability-alert-status.json
```

From the repository root, the same background worker can be started and stopped through the project script:

```powershell
.\scripts\start-observability-alert-worker.ps1 -ApiBaseUrl http://127.0.0.1:8010/api/v2
.\scripts\stop-observability-alert-worker.ps1
```

It can also be started together with the development stack:

```powershell
.\scripts\start-dev.ps1 -WithObservabilityAlert
```

Expected behavior:

```text
The worker reads GET /api/v2/observability/summary.
warning/critical summaries are optionally forwarded as JSON to OBSERVABILITY_ALERT_WEBHOOK_URL.
The status file records state, generated_at, alert_count, and metrics.
One-shot mode returns code 2 for critical status and can return code 1 for warning with --fail-on-warning.
```

Structured application logs:

```powershell
cd backend
$env:LOG_FORMAT="json"
python -c "import logging; import app.core.logging; logging.getLogger('ai_pjm.verify').info('structured log probe', extra={'trace_id':'trace-demo','project_id':1})"
```

Expected output:

```text
One JSON object per line.
Fields include timestamp, level, logger, message, trace_id, and project_id.
Use LOG_FORMAT=text to keep the local human-readable format.
```

## 17. Auth and Project Access Verification

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

## 18. SecretStore Verification

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
- Secret status updates support only `active` and `disabled`; cross-project users cannot update status.
- Disabled secrets return `health_status = disabled` and are not consumed by providers.
- Dify Provider can resolve `dify_api_key` from project SecretStore without returning the key to the frontend.
- OpenAI Provider can resolve `openai_api_key` from project SecretStore without returning the key to the frontend.
- `GET /api/v2/secrets/{id}/health?remote=true` decrypts only server-side, probes OpenAI/GitLab/GitHub with read-only endpoints, probes Dify only when `DIFY_HEALTH_CHECK_URL` is configured, writes `metadata_json.last_provider_health`, and never returns plaintext.
- The access management page health-check button uses the remote probe and shows the latest remote provider status when available.
- The access management page provides a key rotation repair entry. Select an unhealthy or expiring secret, enter the new value, submit rotation, and verify that the table still shows only masked values.

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
轮换项目密钥 section is visible.
Rotating a secret succeeds and refreshes the masked secret table.
停用/启用 buttons are visible in the project secret table.
Disabling a secret changes health_status to disabled.
```

## 19. Slice-level Acceptance Criteria

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

- Production Codex CLI, SDK command, or Symphony Bridge runner operations are finalized for the target environment.
- Symphony Bridge / background worker dispatches queued execution outside HTTP request handling.

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
- A scheduler or worker periodically calls `POST /api/v2/deployments/sync-pending`.

### Slice 6: Queue and Parallel Control

- Execution queue can be queried and shown in the workbench.
- Dispatch respects `EXECUTION_MAX_CONCURRENCY`.
- Runs over the limit remain queued instead of starting silently.

To be added:

- Symphony Bridge / background worker dispatches queued runs automatically.
- Cancel, pause, and resume controls are available.
- Resource usage limits are visible in the workbench.

### Slice 7: Provider Integration

- Provider can be switched among `mock`, `local`, `dify`, and `openai` through configuration.
- Dify outputs are parsed into structured drafts only.
- Invalid or missing Dify configuration fails explicitly.
- OpenAI Responses API outputs are parsed into structured drafts only.
- Invalid or missing OpenAI configuration or malformed structured output fails explicitly.

- Retry and fallback policy for transient provider failures is available for Dify/OpenAI Spec and impact operations.

## 20. Regression Checklist

Before every larger change:

- `python -m compileall app`
- `python -m pytest tests/test_auth.py -q`
- `python -m pytest tests/test_delivery_v2_units.py -q`
- `python -m pytest tests/test_delivery_v2.py tests/test_health.py -q`
- `npm run build` from `frontend/` when UI code changes
