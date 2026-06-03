# AI PJM Backend

FastAPI backend for the AI PJM delivery orchestration flow.

## Active Flow

```text
DemandItem
-> SpecCard
-> RepoContext
-> ImpactAnalysis
-> CodingTask
-> ExecutionRun
-> MergeRequestRecord
-> DeployRecord
-> VerificationRecord
```

The backend owns workflow state, gate checks, and evidence records. AI providers return structured drafts through the delivery provider boundary.
External providers must consume credentials server-side through project SecretStore or backend settings; plaintext secrets are not returned to the frontend or persisted in evidence.

## Local Development

Install dependencies:

```powershell
cd backend
pip install -e ".[dev]"
```

Start the full local stack from the repository root:

```powershell
.\scripts\start-dev.ps1
```

Start the stack with the local Symphony worker:

```powershell
$env:SYMPHONY_BRIDGE_TOKEN="dev-bridge-token"
.\scripts\start-dev.ps1 -WithWorker
```

Stop services:

```powershell
.\scripts\stop-dev.ps1
```

Local URLs:

- API docs: http://localhost:8010/docs
- Health: http://localhost:8010/health

The default local database is SQLite at `backend/data/ai_pjm_dev.db`.

Production-style migration flow:

```powershell
$env:DATABASE_URL="postgresql+asyncpg://user:password@host:5432/ai_pjm"
python scripts/migrate.py upgrade head
python scripts/migrate.py current
```

Non-SQLite startup validates the database is at Alembic head when
`DATABASE_VALIDATE_MIGRATIONS=true`. Local SQLite development still uses
`create_all` plus compatibility fixes to preserve the lightweight dev loop.

Provider credential defaults:

- Dify: `dify_api_key`, fallback `DIFY_API_KEY`
- GitLab MR: `gitlab_token`, fallback `GITLAB_TOKEN`
- Webhook deployment: `deploy_token`, fallback `DEPLOY_TOKEN`
- OpenAI: `openai_api_key` is reserved for the future OpenAI provider

GitLab MR creation pushes the execution branch before calling the GitLab API when `MERGE_REQUEST_AUTO_PUSH_ENABLED=true`.
After a GitLab MR is created, `POST /api/v2/merge-requests/{id}/sync-review` can pull remote MR state, discussion comments, and commit CI statuses back into the delivery MR record, review gate, audit log, and redacted evidence.

## Verification

```powershell
python -m compileall app migrations
python -m pytest tests/test_migrations.py tests/test_delivery_v2_units.py tests/test_delivery_v2.py tests/test_auth.py tests/test_health.py -q
```

## Structure

```text
backend/
  app/
    api/                  # API router aggregation
    common/               # Shared response contracts
    core/                 # Config, DB, logging, exceptions
    modules/delivery/     # Delivery domain, gates, provider boundary
  migrations/             # Alembic migrations for the backend schema
  tests/                  # Delivery and health tests
```
