# AI PJM v2 Interaction Flow

This document describes the user-facing interaction flow and the platform automation behind it.

## 1. Interaction Goal

The user should not operate every internal step. The platform should keep moving automatically when risk and evidence allow it, and only stop for human input when a hard gate requires it.

The intended interaction model is:

```text
user provides business input
-> platform generates spec, risk, gates, and task package
-> platform asks for human input only when needed
-> platform executes and records evidence
-> user reviews evidence and verifies business result
```

## 2. Primary User Journey

```mermaid
flowchart TD
  A["User submits demand"] --> B["Platform creates DemandItem"]
  B --> C["AI workflow generates SpecCard"]
  C --> D["Risk Engine classifies L0-L3"]
  D --> E["Gate Engine records gate checks"]
  E --> F{"Human input required?"}
  F -->|no| G["Platform auto-approves low-risk spec"]
  F -->|yes| H["User reviews spec/risk/questions"]
  H --> I{"Approved?"}
  I -->|no| J["Blocked or revise spec"]
  I -->|yes| G
  G --> K["Platform generates CodingTask package"]
  K --> L["Executor queue"]
  L --> M["Codex Worker executes task"]
  M --> N["Self-test and evidence collection"]
  N --> O{"Checks pass?"}
  O -->|no| P["AI fix loop"]
  P --> M
  O -->|yes| Q["MR/PR creation"]
  Q --> R["Review gates"]
  R --> S["Test deployment"]
  S --> T["Verification"]
  T --> U["Done"]
```

## 3. Human Touchpoints

Human interaction should be limited to these cases:

| Touchpoint | Required When | User Action |
| --- | --- | --- |
| Demand clarification | AI confidence is low or acceptance boundary is unclear. | Answer focused questions. |
| Spec approval | Risk is `L2` or `L3`, or automation policy disables auto-approval. | Approve, reject, or revise SpecCard. |
| Execution approval | Change touches protected areas such as auth, payment, secrets, production data, or migrations. | Explicitly approve execution scope. |
| Verification | Test environment is deployed and business acceptance is required. | Pass/fail against acceptance criteria. |
| Production release | Production deployment or irreversible operation is involved. | Explicit release approval. |

## 4. Automated Steps

The platform should automate these steps when gates pass:

- Generate demand summary and title.
- Generate SpecCard.
- Classify risk.
- Record `spec_ready` and `risk_classified` gates.
- Generate Codex-ready CodingTask.
- Dispatch Codex execution.
- Run required checks.
- Retry AI fix loop when checks fail.
- Create MR/PR.
- Collect review, test, and deployment evidence.

## 5. Current Implementation Status

The v2 delivery framework is now fully implemented with all 8 core entities and complete API endpoints:

### Core Data Models (Complete)
```text
DemandItem        # Raw business demand
-> SpecCard        # Engineering specification
-> GateCheck       # Hard gate evaluation results
-> RepoContext     # Repository context collection
-> ImpactAnalysis  # Code impact analysis
-> CodingTask      # Codex-ready task package
-> ExecutionRun    # Executor run attempts
-> ExecutionLog    # Structured execution logs
```

### API Endpoints (Complete)
```text
GET  /api/v2/demands                        # List recent demands
POST /api/v2/demands                        # Create demand
GET  /api/v2/demands/{demand_id}            # Get demand detail with artifacts
POST /api/v2/demands/{demand_id}/manual-approval       # Record manual approval or rejection
POST /api/v2/demands/{demand_id}/spec       # Generate spec card
GET  /api/v2/spec-cards/{spec_card_id}      # Get spec card
POST /api/v2/demands/{demand_id}/repo-context           # Collect repository context
GET  /api/v2/repo-contexts/{repo_context_id}           # Get repository context
POST /api/v2/demands/{demand_id}/impact-analysis       # Analyze impact
GET  /api/v2/impact-analyses/{impact_analysis_id}      # Get impact analysis
POST /api/v2/spec-cards/{spec_card_id}/coding-task     # Create coding task
GET  /api/v2/coding-tasks/{coding_task_id}             # Get coding task
POST /api/v2/coding-tasks/{coding_task_id}/runs        # Create execution run
POST /api/v2/coding-tasks/{coding_task_id}/retry       # Retry checks for an existing task
GET  /api/v2/execution-runs/{execution_run_id}        # Get execution run
POST /api/v2/execution-runs/{execution_run_id}/dispatch # Dispatch execution
GET  /health                                  # Health check
```

### Gate Engine (Complete)
- Risk classification: L0 (low), L1 (normal), L2 (high), L3 (critical)
- Confidence estimation based on input quality
- Automated spec approval for low-risk demands
- Manual review requirements for high-risk changes
- Execution gate blocking for unsafe operations
- Repository context sufficiency evaluation

### Provider Architecture (Complete)
- Provider interface contracts defined
- Local provider implemented (default): scans workspace structure, docs, configs, tests, dependency refs, and demand-related candidate files
- Mock provider remains available for deterministic fallback
- Provider factory for future Dify/OpenAI integration
- All providers return structured drafts only
- Backend maintains state and gate control

### Executor Architecture (Complete)
- Executor interface contracts defined
- LocalChecksExecutor implemented
- `codex` executor path prepares an isolated Git worktree and branch before running checks
- Configurable Codex command hook can run before checks when enabled
- Safe command execution (pytest, npm build, compileall)
- Execution evidence collection and persistence
- Support for future Codex worker integration

### Automation Status (Complete)
- ✅ Low-risk auto-approval flow
- ✅ High-risk manual review flow
- ✅ Gate check persistence
- ✅ Repository context collection
- ✅ Impact analysis generation
- ✅ Coding task packaging
- ✅ Execution run creation with gate checks
- ✅ Local command execution and evidence collection
- ✅ Self-test passed gate evaluation

Current failure handling for local checks:

- Failed required checks persist exit code, stdout tail, stderr tail, error, execution logs, and a failed `self_test_passed` gate.
- Failed tasks move to `blocked`.
- `POST /api/v2/coding-tasks/{coding_task_id}/retry` reruns checks for `ready`, `blocked`, or `completed` low-risk tasks.
- Retry does not bypass L2/L3 risk gates.

Current manual approval handling:

- L2/L3 demands still produce `manual_review` specs and draft coding tasks.
- A manual approval records gate evidence with approver, note, risk level, spec id, and task id.
- Approval promotes the latest spec to `approved` and the latest draft task to `ready`.
- Rejection blocks the demand and blocks the latest draft or ready task.
- After approval, `Continue` can resume execution without changing the recorded risk level.

### Frontend Implementation (Complete)
- ✅ Complete TypeScript type definitions
- ✅ API client library
- ✅ DeliveryV2Page with 6-step workflow UI
- ✅ Real-time pipeline visualization
- ✅ Evidence and results display
- ✅ Error handling and status tracking

Current operator console includes:

- History list and detail restore.
- Manual approval and rejection for high-risk blocked work.
- `Continue` for missing or failed low-risk workflow stages.
- `Retry checks` for existing task checks.
- Failed check output and failure details.

### Future Enhancements (Not Implemented)
- ⏳ Real Codex AI worker integration
- ⏳ MR/PR creation automation
- ⏳ Test deployment workflow
- ⏳ Business verification flow
- ⏳ Dify/OpenAI provider implementations

Current API path:

```text
GET  /api/v2/demands
POST /api/v2/demands
POST /api/v2/demands/{demand_id}/manual-approval
POST /api/v2/demands/{demand_id}/spec
POST /api/v2/demands/{demand_id}/repo-context
GET  /api/v2/repo-contexts/{repo_context_id}
POST /api/v2/demands/{demand_id}/impact-analysis
GET  /api/v2/impact-analyses/{impact_analysis_id}
POST /api/v2/spec-cards/{spec_card_id}/coding-task
POST /api/v2/coding-tasks/{coding_task_id}/runs
POST /api/v2/coding-tasks/{coding_task_id}/retry
POST /api/v2/execution-runs/{execution_run_id}/dispatch
GET  /api/v2/execution-runs/{execution_run_id}
GET  /api/v2/demands/{demand_id}
```

Current automation:

- Low-risk or normal-risk demand can auto-approve SpecCard.
- High-risk demand enters manual review.
- Gate checks are persisted for `spec_ready` and `risk_classified`.
- Repo context can be collected through the configured workflow provider.
- Impact analysis can be generated from the latest SpecCard and RepoContext.
- CodingTask is generated as `ready` only when risk and spec status allow it.
- ExecutionRun is created as `queued` only when `execution_allowed` passes.
- ExecutionRun is created as `blocked` when the gate requires manual input.
- Queued ExecutionRun can be dispatched through the local required-check executor.
- Required check results are persisted as execution evidence and `self_test_passed` gate checks.
- Failed check results are visible in the UI and can be retried as a new execution attempt.
- High-risk execution can continue only after manual approval evidence is recorded.
- For `executor_type = codex`, checks run inside a generated Git worktree and branch. Evidence records `workspace_root`, `original_workspace_root`, `branch_name`, and `commit_sha`.
- When Codex command execution is enabled, evidence also records command status, prompt file path, exit code, stdout/stderr tails, and changed files.

Not implemented yet:

- Production-ready Codex CLI or SDK command configuration.
- Automated code-fix loop.
- MR/PR creation.
- Test deployment.
- Verification workflow.

Provider status:

- `mock` provider is implemented and is the default.
- Dify/OpenAI providers are represented by the provider boundary but are not implemented yet.
- Workflow providers return structured drafts only; platform state and gates are owned by the backend.

## 6. UI Flow Target

The v2 UI should use a single progressive task screen:

```text
1. Intake
   - raw input
   - source type
   - optional requester/context

2. Spec and Risk
   - generated SpecCard
   - risk level
   - confidence score
   - open questions
   - gate results

3. Coding Task
   - Codex task prompt
   - allowed paths
   - forbidden actions
   - required checks
   - expected evidence

4. Execution
   - execution status
   - log stream
   - test results
   - changed files

5. Delivery
   - MR/PR link
   - test environment URL
   - verification result
```

## 7. Evidence Display

Each step must show why the platform moved forward:

- AI output version or provider.
- Risk decision and reason.
- Gate status.
- Test command and result.
- MR/PR URL.
- Deployment URL.
- Verification conclusion.
