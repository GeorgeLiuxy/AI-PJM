# AI PJM

AI PJM is an AI-assisted engineering delivery orchestration platform.

The active product flow is:

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

Current baseline documents:

- [v2 delivery blueprint](docs/v2-delivery-blueprint.md)
- [v2 localization glossary](docs/v2-localization-glossary.md)
- [v2 implementation plan](docs/v2-implementation-plan.md)
- [v2 interaction flow](docs/v2-interaction-flow.md)
- [v2 verification guide](docs/v2-verification-guide.md)

Current backend framework:

- `/api/v2/demands`
- `/api/v2/demands/{id}/spec`
- `/api/v2/demands/{id}/repo-context`
- `/api/v2/demands/{id}/impact-analysis`
- `/api/v2/spec-cards/{id}/coding-task`
- `/api/v2/coding-tasks/{id}/runs`
- `/api/v2/execution-runs/{id}/dispatch`

The default workflow provider is `mock`. Execution dispatch currently runs a safe local required-check executor and persists evidence. Dify/OpenAI providers and the real Codex execution worker are follow-up implementation slices.

## Local Development

Start both backend and frontend:

```powershell
.\scripts\start-dev.ps1
```

Stop local development services and remove runtime logs:

```powershell
.\scripts\stop-dev.ps1
```

Local URLs:

- Frontend: http://localhost:5173
- Delivery flow: http://localhost:5173
- Backend API docs: http://localhost:8010/docs

The default local database is SQLite at `backend/data/ai_pjm_dev.db`. Runtime files are ignored by Git.
