"""Execution executor factory."""

from app.modules.delivery.executors.base import ExecutionExecutor
from app.modules.delivery.executors.local_checks import LocalChecksExecutor, WorktreeChecksExecutor
from app.modules.delivery.executors.symphony_bridge import SymphonyBridgeExecutor


def get_execution_executor(executor_type: str) -> ExecutionExecutor:
    """Return the executor implementation for a run.

    The real Codex executor is intentionally behind this boundary. The `codex`
    path already uses an isolated Git worktree so a future Codex CLI/SDK adapter
    can mutate files without touching the user's active workspace.
    """

    if executor_type == "codex":
        return WorktreeChecksExecutor()
    if executor_type == "worktree_checks":
        return WorktreeChecksExecutor()
    if executor_type == "local_checks":
        return LocalChecksExecutor()
    if executor_type == "symphony":
        return SymphonyBridgeExecutor()
    return LocalChecksExecutor()
