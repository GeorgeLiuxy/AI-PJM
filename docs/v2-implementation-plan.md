# AI PJM v2 Implementation Plan

## Slice 0: Baseline and Guardrails

Goal: prevent implementation drift.

Status: implemented.

- Add v2 blueprint and glossary.
- Add v2 domain enums.
- Add delivery module skeleton.
- Keep old APIs unchanged.
- Add tests for enum and schema stability.

Done when:

- Baseline docs exist.
- Backend imports pass.
- v2 module has no dependency on old item/analysis/output flow.

## Slice 1: Demand to Spec

Goal: turn raw business input into a structured Spec Card.

Status: implemented with deterministic mock provider and local gate engine.

Backend:

- `POST /api/v2/demands`
- `GET /api/v2/demands/{id}`
- `POST /api/v2/demands/{id}/spec`
- `GET /api/v2/spec-cards/{id}`

Data:

- `demand_items`
- `spec_cards`
- `gate_checks`

AI:

- Start with a deterministic mock provider.
- Keep provider interface ready for Dify or OpenAI workflows.

Gate:

- `spec_ready`
- `risk_classified`

## Slice 2: Repo Context and Impact Analysis

Goal: attach project/repository/branch context and generate an implementation analysis.

Status: framework implemented with mock provider. Real repository scanners and Dify/OpenAI providers are still pending.

Backend:

- `POST /api/v2/demands/{id}/repo-context`
- `POST /api/v2/demands/{id}/impact-analysis`

Data:

- `repo_contexts`
- `impact_analyses`

Gate:

- `repo_context_ready`
- `impact_analyzed`

## Slice 3: Codex Task Package

Goal: generate a Codex-ready task package.

Status: framework implemented. It creates a task package but does not execute Codex yet.

Backend:

- `POST /api/v2/spec-cards/{id}/coding-task`
- `GET /api/v2/coding-tasks/{id}`

Data:

- `coding_tasks`

Output:

- task goal
- allowed files/modules
- forbidden operations
- required checks
- expected evidence

Gate:

- `coding_task_ready`

## Slice 4: Codex Execution Worker

Goal: run a coding task in an isolated workspace.

Status: execution run record and gate are implemented. Real worker dispatch is pending.

Backend:

- `POST /api/v2/coding-tasks/{id}/runs`
- `GET /api/v2/execution-runs/{id}`

Worker:

- create worktree
- call Codex CLI or SDK
- capture logs
- run required checks
- retry fix loop when allowed

Data:

- `execution_runs`
- `execution_logs`

Gate:

- `execution_allowed`
- `self_test_passed`

## Slice 5: MR and Test Deployment

Goal: connect code output to review and test environment.

Backend:

- create MR/PR record
- poll review comments
- create deployment record
- store verification result

Data:

- `merge_request_records`
- `deploy_records`
- `verification_records`

Gate:

- `review_passed`
- `test_deployed`
- `verification_passed`

## Explicit Deferrals

- Multi-task parallel execution.
- Sub-agent review by default.
- Multi-repository orchestration.
- Production auto-release.
- Knowledge graph.
