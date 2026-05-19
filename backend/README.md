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
```

The backend owns workflow state, gate checks, and evidence records. AI providers return structured drafts through the delivery provider boundary.

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

Stop services:

```powershell
.\scripts\stop-dev.ps1
```

Local URLs:

- API docs: http://localhost:8010/docs
- Health: http://localhost:8010/health

The default local database is SQLite at `backend/data/ai_pjm_dev.db`.

## Verification

```powershell
python -m compileall app migrations
python -m pytest tests/test_delivery_v2_units.py tests/test_delivery_v2.py tests/test_health.py -q
```

## Structure

```text
backend/
  app/
    api/                  # API router aggregation
    common/               # Shared response contracts
    core/                 # Config, DB, logging, exceptions
    modules/delivery/     # Delivery domain, gates, provider boundary
  migrations/             # Alembic migrations for the delivery schema
  tests/                  # Delivery and health tests
```
