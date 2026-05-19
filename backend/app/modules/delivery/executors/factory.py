"""Execution executor factory."""

from app.modules.delivery.executors.base import ExecutionExecutor
from app.modules.delivery.executors.local_checks import LocalChecksExecutor


def get_execution_executor(executor_type: str) -> ExecutionExecutor:
    """Return the executor implementation for a run.

    The real Codex executor is intentionally behind this boundary. Until it is
    connected, both `codex` and `local_checks` execute the required local checks
    and persist evidence.
    """

    if executor_type in {"codex", "local_checks"}:
        return LocalChecksExecutor()
    return LocalChecksExecutor()
