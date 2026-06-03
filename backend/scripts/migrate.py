"""Run Alembic migrations with backend-local defaults."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from alembic import command
from alembic.config import Config


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def build_config() -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("version_locations", str(BACKEND_ROOT / "migrations" / "versions"))
    return config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage AI PJM backend database migrations.")
    parser.add_argument(
        "command",
        choices=("upgrade", "downgrade", "current", "heads", "history"),
        help="Alembic command to run.",
    )
    parser.add_argument(
        "revision",
        nargs="?",
        default="head",
        help="Target revision for upgrade/downgrade. Defaults to head.",
    )
    parser.add_argument(
        "--database-url",
        help="Override DATABASE_URL for this migration command.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url

    config = build_config()
    if args.command == "upgrade":
        command.upgrade(config, args.revision)
    elif args.command == "downgrade":
        command.downgrade(config, args.revision)
    elif args.command == "current":
        command.current(config, verbose=True)
    elif args.command == "heads":
        command.heads(config, verbose=True)
    elif args.command == "history":
        command.history(config, verbose=True)


if __name__ == "__main__":
    main()
