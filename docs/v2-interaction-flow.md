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

## 5. Current Implementation Slice

The current code implements the main orchestration framework up to executor run creation:

```text
DemandItem
-> SpecCard
-> GateCheck
-> RepoContext
-> ImpactAnalysis
-> CodingTask
-> ExecutionRun
-> ExecutionLog
```

Current API path:

```text
POST /api/v2/demands
POST /api/v2/demands/{demand_id}/spec
POST /api/v2/demands/{demand_id}/repo-context
GET  /api/v2/repo-contexts/{repo_context_id}
POST /api/v2/demands/{demand_id}/impact-analysis
GET  /api/v2/impact-analyses/{impact_analysis_id}
POST /api/v2/spec-cards/{spec_card_id}/coding-task
POST /api/v2/coding-tasks/{coding_task_id}/runs
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

Not implemented yet:

- Real Codex execution worker.
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
