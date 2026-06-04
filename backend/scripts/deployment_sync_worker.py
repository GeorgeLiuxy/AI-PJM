"""Poll pending deployment records and sync their remote status."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.core.db import assert_database_current, async_session_maker, init_db, is_sqlite_url
from app.modules.delivery.redaction import redact_text, redact_value
from app.modules.delivery.service import delivery_service


DEFAULT_LIMIT = 20
DEFAULT_POLL_SECONDS = 120

SyncFunc = Callable[[int, list[int] | None], Awaitable[dict[str, Any]]]


def main() -> int:
    args = parse_args()
    try:
        if args.loop:
            asyncio.run(
                run_loop(
                    limit=args.limit,
                    project_ids=args.project_id,
                    poll_seconds=args.poll_seconds,
                    status_file=Path(args.status_file).resolve() if args.status_file else None,
                )
            )
            return 0
        summary = asyncio.run(
            run_once(
                limit=args.limit,
                project_ids=args.project_id,
                status_file=Path(args.status_file).resolve() if args.status_file else None,
            )
        )
        return 0 if summary["error_count"] == 0 else 1
    except KeyboardInterrupt:
        return 130


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync pending AI PJM deployment records.")
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.environ.get("DEPLOYMENT_SYNC_LIMIT", str(DEFAULT_LIMIT))),
        help="Maximum pending deployment records to scan per pass.",
    )
    parser.add_argument(
        "--project-id",
        action="append",
        type=int,
        default=None,
        help="Optional project id filter. Can be passed more than once.",
    )
    parser.add_argument("--loop", action="store_true", help="Continuously poll and sync pending deployments.")
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=int(os.environ.get("DEPLOYMENT_SYNC_POLL_SECONDS", str(DEFAULT_POLL_SECONDS))),
        help="Poll interval when --loop is enabled.",
    )
    parser.add_argument(
        "--status-file",
        default=os.environ.get("DEPLOYMENT_SYNC_STATUS_FILE", ""),
        help="Optional JSON status file updated after each pass.",
    )
    return parser.parse_args()


async def run_loop(
    *,
    limit: int,
    project_ids: list[int] | None,
    poll_seconds: int,
    status_file: Path | None = None,
    sync_func: SyncFunc = None,
) -> None:
    sync = sync_func or sync_once
    while True:
        await run_once(limit=limit, project_ids=project_ids, status_file=status_file, sync_func=sync)
        await asyncio.sleep(max(poll_seconds, 1))


async def run_once(
    *,
    limit: int,
    project_ids: list[int] | None,
    status_file: Path | None = None,
    sync_func: SyncFunc = None,
) -> dict[str, Any]:
    sync = sync_func or sync_once
    write_status(status_file, {"state": "running", "message": "Syncing pending deployments."})
    try:
        raw_result = await sync(max(limit, 1), project_ids)
        summary = summarize_result(raw_result)
        write_status(
            status_file,
            {
                "state": "succeeded",
                "message": "Pending deployment sync completed.",
                **summary,
            },
        )
        print(json.dumps(summary, ensure_ascii=False, default=str))
        return summary
    except Exception as exc:
        message = redact_text(str(exc))[:1000]
        write_status(
            status_file,
            {
                "state": "failed",
                "message": message,
                "error_type": exc.__class__.__name__,
            },
        )
        raise


async def sync_once(limit: int, project_ids: list[int] | None) -> dict[str, Any]:
    await prepare_database()
    async with async_session_maker() as db:
        try:
            result = await delivery_service.sync_pending_deploy_records(
                db,
                limit=limit,
                project_ids=project_ids,
                actor_ref="deployment-sync-worker",
            )
            await db.commit()
            return result
        except Exception:
            await db.rollback()
            raise


async def prepare_database() -> None:
    if is_sqlite_url(settings.database_url):
        await init_db()
        return
    await assert_database_current()


def summarize_result(result: dict[str, Any]) -> dict[str, Any]:
    synced = result.get("synced") or []
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scanned": int(result.get("scanned") or 0),
        "synced_count": int(result.get("synced_count") or 0),
        "error_count": int(result.get("error_count") or 0),
        "synced_ids": [getattr(record, "id", None) for record in synced],
        "errors": redact_value(result.get("errors") or []),
    }


def write_status(path: Path | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"updated_at": datetime.now(timezone.utc).isoformat(), **payload}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
