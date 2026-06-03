"""Executor contracts for delivery execution runs."""

from dataclasses import dataclass, field
from typing import Protocol

from app.modules.delivery.models import CodingTask, ExecutionRun


@dataclass
class CheckResult:
    """Result for one required check command."""

    command: str
    cwd: str
    status: str
    exit_code: int | None
    duration_ms: int
    stdout_tail: str = ""
    stderr_tail: str = ""
    error: str | None = None


@dataclass
class ExecutionDispatchResult:
    """Structured executor result persisted as run evidence."""

    succeeded: bool
    summary: str
    evidence: dict
    logs: list[tuple[str, str, dict | None]] = field(default_factory=list)
    deferred: bool = False


class ExecutionExecutor(Protocol):
    """Executor implementation boundary."""

    name: str

    async def dispatch(
        self,
        *,
        run: ExecutionRun,
        task: CodingTask,
        timeout_seconds: int,
    ) -> ExecutionDispatchResult:
        """Execute the run and return structured evidence."""
