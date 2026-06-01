# AI PJM v2 Implementation Plan

后续功能执行顺序以 `docs/v2-execution-roadmap.md` 为准。生产级落地、上线门槛、权限安全、运维和团队试点计划以 `docs/production-readiness-plan.md` 为准。本文保留切片实现状态，路线图负责约束下一步优先级、完成标准和暂不做事项。

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

AI / provider:

- Default provider is `local`, which scans the current workspace for repository structure, docs, frontend/backend config, tests, and demand-related candidate files.
- `mock` remains available for deterministic tests and fallback.
- Keep provider interface ready for Dify or OpenAI workflows. Dify can be enabled by configuration; OpenAI remains pending.

Gate:

- `spec_ready`
- `risk_classified`

## Slice 2: Repo Context and Impact Analysis

Goal: attach project/repository/branch context and generate an implementation analysis.

Status: local repository scanner implemented. Dify provider boundary is implemented for structured Spec and impact drafts. OpenAI provider and deeper semantic analysis are still pending.

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

Status: framework implemented. It creates a task package and can feed execution runs. Codex command execution is available through the configurable executor path when enabled.

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

Status: execution run record, gate, local check dispatch, Git worktree preparation, and configurable Codex command hook are implemented. Production-ready Codex command configuration is pending.

Backend:

- `POST /api/v2/coding-tasks/{id}/runs`
- `GET /api/v2/execution-runs/{id}`

Worker:

- create worktree: implemented for `executor_type = codex`
- call Codex CLI or SDK: configurable command hook implemented; concrete production command is pending
- capture logs: implemented for workspace setup and required checks
- run required checks: implemented
- retry fix loop when allowed: implemented for low-risk failed checks with bounded attempts

Data:

- `execution_runs`
- `execution_logs`

Gate:

- `execution_allowed`
- `self_test_passed`

## Slice 5: MR and Test Deployment

Goal: connect code output to review and test environment.

Status: MR/PR record, local review gate, test deployment record, and verification record are implemented. Real GitLab/GitHub review polling and real deployment providers are pending.

Backend:

- create MR/PR record: implemented with local provider
- poll review comments: pending for GitLab/GitHub providers
- create deployment record: implemented with local provider
- store verification result: implemented

Data:

- `merge_request_records`: implemented
- `deploy_records`: implemented
- `verification_records`: implemented

Gate:

- `review_passed`: implemented
- `test_deployed`: implemented
- `verification_passed`: implemented

## Slice 6: Execution Queue

Goal: make queued and running execution attempts visible and enforce a basic local concurrency limit.

Status: queue query, queue page, and dispatch concurrency guard are implemented. Symphony Bridge, automatic background workers, and lifecycle controls are pending. See `docs/symphony-integration-plan.md`.

Backend:

- list execution runs with task and demand context: implemented
- filter execution runs by status: implemented
- enforce `EXECUTION_MAX_CONCURRENCY` before dispatch: implemented

Frontend:

- queue tab in the delivery workbench: implemented

## Slice 7: External Workflow Providers

Goal: allow external AI workflow systems to generate structured drafts without owning platform state.

Status: Dify provider boundary and configuration validation are implemented. OpenAI provider is pending.

Backend:

- `mock`, `local`, and `dify` provider selection: implemented
- Dify Spec workflow structured output parsing: implemented
- Dify impact workflow structured output parsing: implemented
- Missing Dify configuration fails explicitly: implemented
- OpenAI provider: pending

## Explicit Deferrals

- Symphony Bridge / background multi-task parallel worker.
- Cancel, pause, and resume controls.
- Sub-agent review by default.
- Multi-repository orchestration.
- Production auto-release.
- Knowledge graph.
