"""Create SQLite or PostgreSQL database backups for AI PJM."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings


BACKUP_ROOT = Path(".runtime/backups")


def normalize_database_url_for_cli(database_url: str) -> str:
    """Convert SQLAlchemy async URLs into URLs accepted by PostgreSQL CLI tools."""

    return (
        database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        .replace("postgresql+psycopg://", "postgresql://", 1)
        .replace("postgresql+psycopg2://", "postgresql://", 1)
    )


def sqlite_path_from_url(database_url: str) -> Path | None:
    if not database_url.startswith("sqlite"):
        return None
    if ":memory:" in database_url:
        raise ValueError("In-memory SQLite databases cannot be backed up with this script")
    if ":///" not in database_url:
        raise ValueError("SQLite DATABASE_URL must use an absolute or relative file URL")
    raw_path = database_url.split(":///", 1)[1].split("?", 1)[0]
    if not raw_path:
        raise ValueError("SQLite DATABASE_URL does not contain a database path")
    return Path(raw_path).expanduser()


def build_backup_path(database_url: str, output_dir: Path, output_file: str | None = None) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix = ".sqlite" if sqlite_path_from_url(database_url) else ".dump"
    filename = output_file or f"ai-pjm-{timestamp}{suffix}"
    return output_dir / filename


def backup_database(database_url: str, *, output_dir: Path, output_file: str | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = build_backup_path(database_url, output_dir, output_file)
    sqlite_path = sqlite_path_from_url(database_url)
    if sqlite_path:
        if not sqlite_path.exists():
            raise FileNotFoundError(f"SQLite database file not found: {sqlite_path}")
        shutil.copy2(sqlite_path, output_path)
        return output_path

    command = [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--file",
        str(output_path),
        normalize_database_url_for_cli(database_url),
    ]
    subprocess.run(command, check=True)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Back up the AI PJM database.")
    parser.add_argument("--database-url", default=settings.database_url, help="Defaults to DATABASE_URL.")
    parser.add_argument("--output-dir", default=str(BACKUP_ROOT), help="Backup output directory.")
    parser.add_argument("--output-file", help="Optional backup file name.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = backup_database(
        args.database_url,
        output_dir=Path(args.output_dir),
        output_file=args.output_file,
    )
    print(f"Backup created: {path}")


if __name__ == "__main__":
    main()
