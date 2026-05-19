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

- PostgreSQL is running.
- Test database from `backend/tests/conftest.py` is reachable:

```text
postgresql+asyncpg://ai_pjm_user:ai_pjm_password@localhost:5432/ai_pjm_test
```

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
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Create a normal-risk demand:

```powershell
$demand = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8000/api/v2/demands" `
  -ContentType "application/json" `
  -Body '{"raw_input":"Add a compact status badge to the workbench todo list.","source_type":"new_requirement"}'

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
  -Uri "http://localhost:8000/api/v2/demands/$($demand.data.id)/spec" `
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
  -Uri "http://localhost:8000/api/v2/demands/$($demand.data.id)/repo-context" `
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
  -Uri "http://localhost:8000/api/v2/demands/$($demand.data.id)/impact-analysis" `
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
  -Uri "http://localhost:8000/api/v2/spec-cards/$($spec.data.id)/coding-task" `
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
  -Uri "http://localhost:8000/api/v2/coding-tasks/$($task.data.id)/runs" `
  -ContentType "application/json" `
  -Body '{"executor_type":"codex","trigger_mode":"manual"}'

$run.data
```

Expected:

```text
status = queued
logs count >= 1
```

Fetch demand detail:

```powershell
$detail = Invoke-RestMethod `
  -Method Get `
  -Uri "http://localhost:8000/api/v2/demands/$($demand.data.id)"

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
  -Uri "http://localhost:8000/api/v2/demands" `
  -ContentType "application/json" `
  -Body '{"raw_input":"Change login permission logic and migrate production user tokens.","source_type":"bug_report"}'

$riskSpec = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8000/api/v2/demands/$($riskDemand.data.id)/spec" `
  -ContentType "application/json" `
  -Body '{}'

$riskDetail = Invoke-RestMethod `
  -Method Get `
  -Uri "http://localhost:8000/api/v2/demands/$($riskDemand.data.id)"

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

### Slice 0: Baseline

- v2 docs exist.
- Existing v1 APIs remain mounted under `/api/v1`.
- v2 APIs are mounted under `/api/v2`.
- Old `Item -> Analysis -> Output` behavior is not changed.

### Slice 1: Demand to Spec

- A demand can be created.
- A SpecCard can be generated.
- Risk is classified as `L0`, `L1`, `L2`, or `L3`.
- `spec_ready` and `risk_classified` gates are persisted.
- Low-risk/normal-risk demands can auto-approve when policy allows.
- High-risk demands require manual review.

### Slice 2: Repo Context and Impact

- RepoContext is stored with provider, source refs, discovered files, dependencies, and confidence score.
- `repo_context_ready` gate is persisted.
- ImpactAnalysis is stored with impacted areas, affected files, recommendations, risk level, and confidence score.
- `impact_analyzed` gate is persisted.
- Real repository scanners are not implemented yet; current behavior uses the mock workflow provider.

### Slice 3: Codex Task

- CodingTask includes goal, prompt, allowed paths, forbidden actions, required checks, and expected evidence.
- CodingTask is `ready` only when gates allow automated execution.

### Slice 4: Execution

- ExecutionRun and ExecutionLog records are persisted.
- `execution_allowed` gate controls whether a run is `queued` or `blocked`.
- Real worker dispatch is not implemented yet.

To be added:

- worker creates isolated workspace.
- Codex CLI or SDK is invoked.
- required checks run.
- failed checks trigger fix loop when policy allows.

### Slice 5: Delivery

To be added:

- MR/PR is created.
- test environment is deployed.
- verification result is recorded.
- delivery cannot become `done` until verification passes.

## 6. Regression Checklist

Before every larger change:

- `python -m compileall app`
- `python -m pytest tests/test_delivery_v2_units.py -q`
- database-backed v2 tests when PostgreSQL is available
- existing v1 tests when the change touches shared core or routing
