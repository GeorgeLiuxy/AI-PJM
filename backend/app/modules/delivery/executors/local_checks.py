"""Local required-check executor for delivery runs."""

import asyncio
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from app.core.config import settings
from app.modules.delivery.executors.base import (
    CheckResult,
    ExecutionDispatchResult,
)
from app.modules.delivery.models import CodingTask, ExecutionRun


class LocalChecksExecutor:
    """Run a safe subset of local verification commands."""

    name = "local_checks"

    async def dispatch(
        self,
        *,
        run: ExecutionRun,
        task: CodingTask,
        timeout_seconds: int,
    ) -> ExecutionDispatchResult:
        workspace_root = self._workspace_root()
        checks = task.required_checks_json or []

        if not checks:
            return ExecutionDispatchResult(
                succeeded=True,
                summary="No required checks were declared.",
                evidence={
                    "executor": self.name,
                    "run_id": run.id,
                    "coding_task_id": task.id,
                    "workspace_root": str(workspace_root),
                    "check_results": [],
                },
                logs=[
                    (
                        "warning",
                        "No required checks were declared for this coding task.",
                        {"coding_task_id": task.id},
                    )
                ],
            )

        results: list[CheckResult] = []
        for command in checks:
            results.append(
                await self._run_check(
                    command=command,
                    workspace_root=workspace_root,
                    timeout_seconds=timeout_seconds,
                )
            )

        succeeded = all(result.status == "passed" for result in results)
        passed_count = sum(1 for result in results if result.status == "passed")
        summary = (
            f"Required checks passed ({passed_count}/{len(results)})."
            if succeeded
            else f"Required checks failed ({passed_count}/{len(results)} passed)."
        )
        logs = [
            (
                "info" if result.status == "passed" else "error",
                f"Check {result.status}: {result.command}",
                self._check_to_dict(result),
            )
            for result in results
        ]

        return ExecutionDispatchResult(
            succeeded=succeeded,
            summary=summary,
            evidence={
                "executor": self.name,
                "run_id": run.id,
                "coding_task_id": task.id,
                "workspace_root": str(workspace_root),
                "check_results": [self._check_to_dict(result) for result in results],
            },
            logs=logs,
        )

    async def _run_check(
        self,
        *,
        command: str,
        workspace_root: Path,
        timeout_seconds: int,
    ) -> CheckResult:
        started = time.perf_counter()
        try:
            argv, cwd = self._resolve_command(command, workspace_root)
        except ValueError as exc:
            return CheckResult(
                command=command,
                cwd=str(workspace_root),
                status="failed",
                exit_code=None,
                duration_ms=self._duration_ms(started),
                error=str(exc),
            )

        executable = shutil.which(argv[0])
        if not executable:
            return CheckResult(
                command=command,
                cwd=str(cwd),
                status="failed",
                exit_code=None,
                duration_ms=self._duration_ms(started),
                error=f"Executable not found: {argv[0]}",
            )

        try:
            executable_args = self._build_process_args(executable, argv[1:])
            completed = await asyncio.to_thread(
                subprocess.run,
                executable_args,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return CheckResult(
                command=command,
                cwd=str(cwd),
                status="failed",
                exit_code=None,
                duration_ms=self._duration_ms(started),
                error=f"Timed out after {timeout_seconds} seconds.",
                stdout_tail=self._tail(self._coerce_text(exc.stdout)),
                stderr_tail=self._tail(self._coerce_text(exc.stderr)),
            )
        except OSError as exc:
            return CheckResult(
                command=command,
                cwd=str(cwd),
                status="failed",
                exit_code=None,
                duration_ms=self._duration_ms(started),
                error=str(exc),
            )

        return CheckResult(
            command=command,
            cwd=str(cwd),
            status="passed" if completed.returncode == 0 else "failed",
            exit_code=completed.returncode,
            duration_ms=self._duration_ms(started),
            stdout_tail=self._tail(completed.stdout),
            stderr_tail=self._tail(completed.stderr),
        )

    def _resolve_command(self, command: str, workspace_root: Path) -> tuple[list[str], Path]:
        parts = shlex.split(command)
        if not parts:
            raise ValueError("Empty check command is not allowed.")

        normalized = [part.lower() for part in parts]
        backend_dir = workspace_root / "backend"
        frontend_dir = workspace_root / "frontend"

        if normalized[:3] == ["npm", "run", "build"]:
            return parts, frontend_dir
        if normalized[0] in {"pytest"}:
            return parts, backend_dir
        if normalized[:3] == ["python", "-m", "pytest"]:
            return parts, backend_dir
        if normalized[:3] == ["python", "-m", "compileall"]:
            return parts, backend_dir

        raise ValueError(
            "Unsupported check command. Allowed commands: npm run build, pytest, "
            "python -m pytest, python -m compileall."
        )

    def _workspace_root(self) -> Path:
        if settings.workspace_root:
            return Path(settings.workspace_root).expanduser().resolve()
        return Path(__file__).resolve().parents[5]

    def _duration_ms(self, started: float) -> int:
        return int((time.perf_counter() - started) * 1000)

    def _build_process_args(self, executable: str, args: list[str]) -> list[str]:
        if os.name == "nt" and executable.lower().endswith((".cmd", ".bat")):
            return ["cmd.exe", "/c", executable, *args]
        return [executable, *args]

    def _tail(self, text: str, limit: int = 4000) -> str:
        text = text.strip()
        if len(text) <= limit:
            return text
        return text[-limit:]

    def _coerce_text(self, value: str | bytes | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    def _check_to_dict(self, result: CheckResult) -> dict:
        return {
            "command": result.command,
            "cwd": result.cwd,
            "status": result.status,
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "stdout_tail": result.stdout_tail,
            "stderr_tail": result.stderr_tail,
            "error": result.error,
        }
