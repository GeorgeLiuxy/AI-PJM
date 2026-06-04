"""Backfill missing delivery trace ids."""

from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.modules.delivery.trace_backfill import backfill_delivery_trace_ids


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill AI PJM delivery trace ids.")
    parser.add_argument(
        "--database-url",
        default=settings.database_url,
        help="Database URL to update. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report rows that would be updated.",
    )
    return parser.parse_args()


async def run(database_url: str, *, dry_run: bool) -> dict:
    engine = create_async_engine(database_url, future=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_maker() as session:
            result = await backfill_delivery_trace_ids(session, dry_run=dry_run)
            if dry_run:
                await session.rollback()
            else:
                await session.commit()
            return {
                "dry_run": result.dry_run,
                "total_updated": result.total_updated,
                "updated": result.updated,
            }
    finally:
        await engine.dispose()


def main() -> None:
    args = parse_args()
    summary = asyncio.run(run(args.database_url, dry_run=args.dry_run))
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
