# 2026-05-19 Handoff: SQLite Dev Mode and v2 Framework

## Current User Goal

The user wants the project to be minimally runnable end to end before continuing deeper v2 features.

Immediate decision: do not spend time on local PostgreSQL. Switch local development to SQLite so the workbench and v2 workflow can be exercised quickly.

## Verified Problem

The frontend "failed to fetch" on the workbench is caused by backend 500 responses, not by the frontend itself.

Backend log showed:

```text
GET /api/v1/workbench/home HTTP/1.1" 500 Internal Server Error
OSError: Connect call failed ('127.0.0.1', 5432)
```

So the root cause is the backend trying to connect to PostgreSQL on `localhost:5432`, while no PostgreSQL service is listening.

## Work Completed In This Handoff Slice

- Added SQLite-compatible database type helpers in `backend/app/core/db.py`:
  - `DB_BIGINT`
  - `DB_JSON`
  - `is_sqlite_url`
  - SQLite parent directory creation
  - `import_all_models`
- Updated `backend/app/main.py` so SQLite development mode runs `init_db()` during startup.
- Replaced PostgreSQL-only `JSONB` model fields with `DB_JSON`.
- Replaced BigInteger model PK/FK types with `DB_BIGINT` where needed for SQLite autoincrement.
- Added `aiosqlite>=0.20.0` to `backend/pyproject.toml`.
- Changed local `backend/.env` database URL to:

```text
DATABASE_URL=sqlite+aiosqlite:///./data/ai_pjm_dev.db
```

Validation run:

```powershell
cd backend
python -m compileall app
```

Result: passed.

## Important Current Blocker

`aiosqlite` is not installed in the current Python environment.

Check result:

```text
False
```

Next account should install dependencies before restarting backend:

```powershell
cd "D:\projects\AI PJM\backend"
pip install -e ".[dev]"
```

If editable install is too slow or fails, use the minimal install:

```powershell
pip install aiosqlite
```

## Next Steps

1. Stop the currently running backend/frontend processes if they are still running:

```powershell
cd "D:\projects\AI PJM"
if (Test-Path .runtime\backend.pid) { Stop-Process -Id (Get-Content .runtime\backend.pid) -Force -ErrorAction SilentlyContinue }
if (Test-Path .runtime\frontend.pid) { Stop-Process -Id (Get-Content .runtime\frontend.pid) -Force -ErrorAction SilentlyContinue }
```

2. Install `aiosqlite`.

3. Restart backend:

```powershell
cd "D:\projects\AI PJM\backend"
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Expected startup log should include:

```text
SQLite development database initialized
```

4. Restart frontend:

```powershell
cd "D:\projects\AI PJM\frontend"
npm run dev -- --host 0.0.0.0
```

5. Verify workbench:

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/workbench/home
Invoke-RestMethod http://localhost:8000/api/v1/workbench/todos
```

Expected: HTTP 200 JSON responses, even if lists/counts are empty.

6. Verify v2 minimal workflow from Swagger or PowerShell:

```powershell
$demand = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8000/api/v2/demands" `
  -ContentType "application/json" `
  -Body '{"raw_input":"Add a compact status badge to the workbench todo list.","source_type":"new_requirement"}'

$spec = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8000/api/v2/demands/$($demand.data.id)/spec" `
  -ContentType "application/json" `
  -Body '{"auto_approve_low_risk":true}'

$repo = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8000/api/v2/demands/$($demand.data.id)/repo-context" `
  -ContentType "application/json" `
  -Body '{}'

$impact = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8000/api/v2/demands/$($demand.data.id)/impact-analysis" `
  -ContentType "application/json" `
  -Body "{`"repo_context_id`":$($repo.data.id)}"

$task = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8000/api/v2/spec-cards/$($spec.data.id)/coding-task" `
  -ContentType "application/json" `
  -Body '{"allowed_paths":["frontend/src/app/components"],"required_checks":["npm run build"]}'

Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8000/api/v2/coding-tasks/$($task.data.id)/runs" `
  -ContentType "application/json" `
  -Body '{"executor_type":"codex","trigger_mode":"manual"}'
```

Expected:

- demand created
- spec status is `approved` for low-risk demand
- repo context status is `ready`
- impact analysis status is `ready`
- coding task status is `ready`
- execution run status is `queued`

## Follow-up Implementation Tasks

- Add project-level `scripts/start-dev.ps1` and `scripts/stop-dev.ps1`.
- Update `backend/.env.example` to document SQLite local dev and PostgreSQL production options.
- Decide whether tests should use SQLite by default for local development or keep PostgreSQL integration tests separate.
- Add a lightweight frontend page for the v2 flow; current frontend still mostly uses v1 workbench APIs.
- Do not implement Dify or Codex Worker until the SQLite local loop is stable.

## Notes

- Alembic migrations remain PostgreSQL-oriented because existing migrations use PostgreSQL JSONB.
- In SQLite local dev mode, the app uses SQLAlchemy `create_all()` on startup instead of Alembic.
- This is acceptable for minimal local validation, but production/staging should still use PostgreSQL and Alembic.
