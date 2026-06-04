"""Recover Symphony execution runs whose worker lease has expired."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.db import utc_now
from app.modules.delivery.symphony_bridge import symphony_bridge_service


DEFAULT_STATUS_FILE = Path(".runtime/symphony-recovery-status.json")


async def recover_expired_runs(db: AsyncSession, *, limit: int) -> dict:
    recovered = await symphony_bridge_service.recover_expired_running_runs(db, limit=limit)
    return {
        "state": "completed",
        "checked_limit": limit,
        "recovered_count": len(recovered),
        "recovered_run_ids": [run.id for run in recovered],
        "updated_at": utc_now().isoformat(),
    }


async def run(database_url: str, *, limit: int, status_file: Path | None = None) -> dict:
    engine = create_async_engine(database_url, future=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_maker() as session:
            summary = await recover_expired_runs(session, limit=limit)
    finally:
        await engine.dispose()
    if status_file:
        status_file.parent.mkdir(parents=True, exist_ok=True)
        status_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recover expired AI PJM Symphony execution runs.")
    parser.add_argument("--database-url", default=settings.database_url, help="Defaults to DATABASE_URL.")
    parser.add_argument("--limit", type=int, default=100, help="Maximum running Symphony runs to inspect.")
    parser.add_argument(
        "--status-file",
        default=str(DEFAULT_STATUS_FILE),
        help="Optional JSON status file. Pass an empty string to disable.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = asyncio.run(
        run(
            args.database_url,
            limit=args.limit,
            status_file=Path(args.status_file) if args.status_file else None,
        )
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
