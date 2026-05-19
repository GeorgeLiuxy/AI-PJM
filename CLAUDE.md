# AI PJM Development Guardrails

## Product Direction

AI PJM is an AI-assisted engineering delivery orchestration platform.

The primary product flow is:

```text
business input
-> context aggregation
-> SpecCard
-> risk and gate evaluation
-> CodingTask package
-> Codex execution record
-> self-test evidence
-> MR/PR
-> test deployment
-> verification
```

Do not reintroduce the removed legacy prototype product flow.

## Current Core Objects

- `DemandItem`: raw business input and normalized demand metadata.
- `SpecCard`: user story, scope, acceptance criteria, risks, and constraints.
- `RepoContext`: repository, branch, module, dependency, and test-command context.
- `ImpactAnalysis`: code impact, risk, confidence, and implementation recommendations.
- `CodingTask`: Codex-ready execution package with allowed paths and checks.
- `ExecutionRun`: execution attempt and logs.
- `GateCheck`: hard gate status, reason, and evidence.

Future delivery objects should extend this chain only when they serve MR/PR, deployment, verification, or audit evidence.

## Implementation Rules

1. Workflow state belongs to the backend, not to prompts.
2. AI providers return structured drafts only; they must not mutate workflow state directly.
3. Gate decisions must be deterministic and testable.
4. Human intervention should be required only for high-risk, low-confidence, irreversible, security-sensitive, or production-impacting work.
5. Default local development uses SQLite; PostgreSQL support remains available through SQLAlchemy/Alembic.
6. Keep the frontend centered on the new delivery flow. Do not add navigation to deleted legacy pages.
7. Keep tests aligned to the delivery chain and gate behavior.

## Provider Boundary

All AI workflow integration must go through `backend/app/modules/delivery/providers`.

Current provider:

- `mock`: deterministic local provider for development and tests.

Planned providers:

- Dify workflow provider.
- OpenAI provider.
- Codex executor/worker integration.

## Verification

Before handing off larger changes, run the relevant checks:

```powershell
cd backend
python -m compileall app migrations
python -m pytest tests/test_delivery_v2_units.py tests/test_delivery_v2.py tests/test_health.py -q

cd ..\frontend
npm run build
```
