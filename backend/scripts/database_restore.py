"""Restore SQLite or PostgreSQL database backups for AI PJM."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from scripts.database_backup import normalize_database_url_for_cli, sqlite_path_from_url


RESTORE_CONFIRMATION = "RESTORE_AI_PJM_DATABASE"


def restore_database(
    database_url: str,
    *,
    backup_file: Path,
    confirm: str,
    no_safety_copy: bool = False,
) -> Path | None:
    if confirm != RESTORE_CONFIRMATION:
        raise ValueError(f"Restore requires --confirm {RESTORE_CONFIRMATION}")
    if not backup_file.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_file}")

    sqlite_path = sqlite_path_from_url(database_url)
    if sqlite_path:
        safety_copy = None
        if sqlite_path.exists() and not no_safety_copy:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            safety_copy = sqlite_path.with_suffix(f"{sqlite_path.suffix}.pre-restore-{timestamp}.bak")
            shutil.copy2(sqlite_path, safety_copy)
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_file, sqlite_path)
        return safety_copy

    command = [
        "pg_restore",
        "--clean",
        "--if-exists",
        "--no-owner",
        "--dbname",
        normalize_database_url_for_cli(database_url),
        str(backup_file),
    ]
    subprocess.run(command, check=True)
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Restore the AI PJM database from a backup.")
    parser.add_argument("backup_file", help="Backup file to restore.")
    parser.add_argument("--database-url", default=settings.database_url, help="Defaults to DATABASE_URL.")
    parser.add_argument(
        "--confirm",
        required=True,
        help=f"Required confirmation token: {RESTORE_CONFIRMATION}",
    )
    parser.add_argument(
        "--no-safety-copy",
        action="store_true",
        help="For SQLite only: do not copy the current database before restore.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    safety_copy = restore_database(
        args.database_url,
        backup_file=Path(args.backup_file),
        confirm=args.confirm,
        no_safety_copy=args.no_safety_copy,
    )
    if safety_copy:
        print(f"Restore completed. Previous SQLite database copied to: {safety_copy}")
    else:
        print("Restore completed.")


if __name__ == "__main__":
    main()
