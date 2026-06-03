"""Migration-chain verification tests."""

from __future__ import annotations

import os
import subprocess
import sys


def test_alembic_upgrade_head_on_fresh_sqlite(tmp_path) -> None:
    db_path = tmp_path / "ai_pjm_migration_test.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path.as_posix()}"

    result = subprocess.run(
        [sys.executable, "scripts/migrate.py", "upgrade", "head"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
