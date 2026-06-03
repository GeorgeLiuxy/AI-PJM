"""Local required-check executor for delivery runs."""

import asyncio
import os
import shlex
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings
from app.modules.delivery.executors.base import (
    CheckResult,
    ExecutionDispatchResult,
)
from app.modules.delivery.models import CodingTask, ExecutionRun
from app.modules.delivery.redaction import redact_text, redact_value


@dataclass
class WorkspaceContext:
    """Workspace prepared for one execution attempt."""

    workspace_root: Path
    original_workspace_root: Path
    branch_name: str | None = None
    commit_sha: str | None = None
    dependency_links: list[dict[str, str]] = field(default_factory=list)
    setup_logs: list[tuple[str, str, dict | None]] = field(default_factory=list)


@dataclass
class PreCheckActionResult:
    """Result of an optional code-generation action before checks run."""

    succeeded: bool
    evidence: dict = field(default_factory=dict)
    logs: list[tuple[str, str, dict | None]] = field(default_factory=list)
    summary: str | None = None


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
        try:
            workspace = await self._prepare_workspace(run=run, task=task)
        except Exception as exc:
            workspace_root = self._workspace_root()
            return ExecutionDispatchResult(
                succeeded=False,
                summary=f"Execution workspace preparation failed: {exc}",
                evidence={
                    "executor": self.name,
                    "run_id": run.id,
                    "coding_task_id": task.id,
                    "workspace_root": str(workspace_root),
                    "error": str(exc),
                },
                logs=[
                    (
                        "error",
                        "Execution workspace preparation failed.",
                        {"error": str(exc), "executor": self.name},
                    )
                ],
            )

        workspace_root = workspace.workspace_root
        checks = task.required_checks_json or []
        evidence_base = self._workspace_evidence(workspace, run, task)
        action_result = await self._run_pre_check_action(
            workspace=workspace,
            run=run,
            task=task,
            timeout_seconds=timeout_seconds,
        )
        evidence_base = {**evidence_base, **action_result.evidence}

        if not action_result.succeeded:
            return ExecutionDispatchResult(
                succeeded=False,
                summary=action_result.summary or "Pre-check execution action failed.",
                evidence={**evidence_base, "check_results": []},
                logs=[*workspace.setup_logs, *action_result.logs],
            )

        if not checks:
            return ExecutionDispatchResult(
                succeeded=True,
                summary="No required checks were declared.",
                evidence={**evidence_base, "check_results": []},
                logs=[
                    *workspace.setup_logs,
                    *action_result.logs,
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
                **evidence_base,
                "check_results": [self._check_to_dict(result) for result in results],
            },
            logs=[*workspace.setup_logs, *action_result.logs, *logs],
        )

    async def _prepare_workspace(
        self,
        *,
        run: ExecutionRun,
        task: CodingTask,
    ) -> WorkspaceContext:
        workspace_root = self._workspace_root()
        return WorkspaceContext(
            workspace_root=workspace_root,
            original_workspace_root=workspace_root,
        )

    async def _run_pre_check_action(
        self,
        *,
        workspace: WorkspaceContext,
        run: ExecutionRun,
        task: CodingTask,
        timeout_seconds: int,
    ) -> PreCheckActionResult:
        return PreCheckActionResult(succeeded=True)

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
                stdout_tail=self._tail(exc.stdout),
                stderr_tail=self._tail(exc.stderr),
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

    def _worktree_root(self, workspace_root: Path) -> Path:
        if settings.execution_worktree_root:
            return Path(settings.execution_worktree_root).expanduser().resolve()
        return workspace_root / ".runtime" / "worktrees"

    def _duration_ms(self, started: float) -> int:
        return int((time.perf_counter() - started) * 1000)

    def _build_process_args(self, executable: str, args: list[str]) -> list[str]:
        if os.name == "nt" and executable.lower().endswith((".cmd", ".bat")):
            return ["cmd.exe", "/c", executable, *args]
        return [executable, *args]

    def _tail(self, text: str | bytes | None, limit: int = 4000) -> str:
        text = redact_text(self._coerce_text(text))
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
        return redact_value(
            {
                "command": result.command,
                "cwd": result.cwd,
                "status": result.status,
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "stdout_tail": result.stdout_tail,
                "stderr_tail": result.stderr_tail,
                "error": result.error,
            }
        )

    def _workspace_evidence(
        self,
        workspace: WorkspaceContext,
        run: ExecutionRun,
        task: CodingTask,
    ) -> dict:
        evidence = {
            "executor": self.name,
            "run_id": run.id,
            "coding_task_id": task.id,
            "workspace_root": str(workspace.workspace_root),
            "original_workspace_root": str(workspace.original_workspace_root),
            "branch_name": workspace.branch_name,
            "commit_sha": workspace.commit_sha,
        }
        if workspace.dependency_links:
            evidence["dependency_links"] = workspace.dependency_links
        return evidence


class WorktreeChecksExecutor(LocalChecksExecutor):
    """Run checks inside an isolated Git worktree."""

    name = "worktree_checks"

    async def _run_pre_check_action(
        self,
        *,
        workspace: WorkspaceContext,
        run: ExecutionRun,
        task: CodingTask,
        timeout_seconds: int,
    ) -> PreCheckActionResult:
        if not settings.execution_codex_enabled:
            return PreCheckActionResult(
                succeeded=True,
                evidence={"codex_invocation": {"enabled": False}},
            )

        if not settings.execution_codex_command_template.strip():
            return PreCheckActionResult(
                succeeded=False,
                summary="Codex execution is enabled but no command template is configured.",
                evidence={
                    "codex_invocation": {
                        "enabled": True,
                        "status": "failed",
                        "error": "Missing EXECUTION_CODEX_COMMAND_TEMPLATE.",
                    }
                },
                logs=[
                    (
                        "error",
                        "Codex execution command template is missing.",
                        {"run_id": run.id, "coding_task_id": task.id},
                    )
                ],
            )

        prompt_file = self._write_codex_prompt(workspace, run, task)
        command = self._render_codex_command_template(
            template=settings.execution_codex_command_template,
            workspace=workspace,
            run=run,
            task=task,
            prompt_file=prompt_file,
        )
        preflight = await self._run_codex_preflight(
            workspace=workspace,
            run=run,
            task=task,
            prompt_file=prompt_file,
            command=command,
        )
        if preflight and not preflight["succeeded"]:
            invocation = {
                "enabled": True,
                "status": "failed",
                "command": command,
                "prompt_file": str(prompt_file),
                "preflight": preflight["evidence"],
                "error": preflight["summary"],
            }
            return PreCheckActionResult(
                succeeded=False,
                summary=preflight["summary"],
                evidence={"codex_invocation": invocation},
                logs=[("error", preflight["log_message"], invocation)],
            )

        started = time.perf_counter()

        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                command,
                cwd=str(workspace.workspace_root),
                shell=True,
                capture_output=True,
                timeout=settings.execution_codex_timeout_seconds or timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            changed_files = self._git_changed_files(workspace.workspace_root)
            changed_file_violations = self._changed_files_outside_allowed_paths(
                changed_files=changed_files,
                allowed_paths=task.allowed_paths_json or [],
            )
            evidence = {
                "codex_invocation": {
                    "enabled": True,
                    "status": "failed",
                    "command": command,
                    "prompt_file": str(prompt_file),
                    "exit_code": None,
                    "duration_ms": self._duration_ms(started),
                    "error": f"Timed out after {settings.execution_codex_timeout_seconds or timeout_seconds} seconds.",
                    "stdout_tail": self._tail(exc.stdout),
                    "stderr_tail": self._tail(exc.stderr),
                    "changed_files": changed_files,
                    "changed_file_violations": changed_file_violations,
                }
            }
            return PreCheckActionResult(
                succeeded=False,
                summary="Codex execution timed out.",
                evidence=evidence,
                logs=[("error", "Codex execution timed out.", evidence["codex_invocation"])],
            )
        except OSError as exc:
            evidence = {
                "codex_invocation": {
                    "enabled": True,
                    "status": "failed",
                    "command": command,
                    "prompt_file": str(prompt_file),
                    "exit_code": None,
                    "duration_ms": self._duration_ms(started),
                    "error": str(exc),
                }
            }
            return PreCheckActionResult(
                succeeded=False,
                summary="Codex execution failed to start.",
                evidence=evidence,
                logs=[("error", "Codex execution failed to start.", evidence["codex_invocation"])],
            )

        changed_files = self._git_changed_files(workspace.workspace_root)
        changed_file_violations = self._changed_files_outside_allowed_paths(
            changed_files=changed_files,
            allowed_paths=task.allowed_paths_json or [],
        )
        invocation = {
            "enabled": True,
            "status": "passed" if completed.returncode == 0 and not changed_file_violations else "failed",
            "command": command,
            "prompt_file": str(prompt_file),
            "exit_code": completed.returncode,
            "duration_ms": self._duration_ms(started),
            "stdout_tail": self._tail(completed.stdout),
            "stderr_tail": self._tail(completed.stderr),
            "changed_files": changed_files,
        }
        if preflight:
            invocation["preflight"] = preflight["evidence"]
        if changed_file_violations:
            invocation["changed_file_violations"] = changed_file_violations
            invocation["error"] = "Changed files are outside the allowed paths."

        succeeded = completed.returncode == 0 and not changed_file_violations
        summary = None
        if completed.returncode != 0:
            summary = "Codex execution command failed."
        elif changed_file_violations:
            summary = "Codex execution changed files outside allowed paths."

        return PreCheckActionResult(
            succeeded=succeeded,
            summary=summary,
            evidence={"codex_invocation": invocation},
            logs=[
                (
                    "info" if succeeded else "error",
                    "Codex execution command completed." if succeeded else "Codex execution command failed.",
                    invocation,
                )
            ],
        )

    async def _run_codex_preflight(
        self,
        *,
        workspace: WorkspaceContext,
        run: ExecutionRun,
        task: CodingTask,
        prompt_file: Path,
        command: str,
    ) -> dict | None:
        template = settings.execution_codex_preflight_command.strip()
        if not template:
            return None

        preflight_command = self._render_codex_command_template(
            template=template,
            workspace=workspace,
            run=run,
            task=task,
            prompt_file=prompt_file,
        )
        timeout_seconds = settings.execution_codex_preflight_timeout_seconds or 30
        started = time.perf_counter()
        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                preflight_command,
                cwd=str(workspace.workspace_root),
                shell=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            evidence = {
                "command": preflight_command,
                "status": "failed",
                "exit_code": None,
                "duration_ms": self._duration_ms(started),
                "error": f"Timed out after {timeout_seconds} seconds.",
                "stdout_tail": self._tail(exc.stdout),
                "stderr_tail": self._tail(exc.stderr),
            }
            return {
                "succeeded": False,
                "summary": "Codex execution preflight timed out.",
                "log_message": "Codex execution preflight timed out.",
                "evidence": evidence,
            }
        except OSError as exc:
            evidence = {
                "command": preflight_command,
                "status": "failed",
                "exit_code": None,
                "duration_ms": self._duration_ms(started),
                "error": str(exc),
            }
            return {
                "succeeded": False,
                "summary": "Codex execution preflight failed to start.",
                "log_message": "Codex execution preflight failed to start.",
                "evidence": evidence,
            }

        succeeded = completed.returncode == 0
        evidence = {
            "command": preflight_command,
            "status": "passed" if succeeded else "failed",
            "exit_code": completed.returncode,
            "duration_ms": self._duration_ms(started),
            "stdout_tail": self._tail(completed.stdout),
            "stderr_tail": self._tail(completed.stderr),
        }
        if not succeeded:
            evidence["error"] = "Codex preflight command returned a non-zero exit code."

        return {
            "succeeded": succeeded,
            "summary": None if succeeded else "Codex execution preflight failed.",
            "log_message": "Codex execution preflight completed." if succeeded else "Codex execution preflight failed.",
            "evidence": evidence,
        }

    async def _prepare_workspace(
        self,
        *,
        run: ExecutionRun,
        task: CodingTask,
    ) -> WorkspaceContext:
        workspace_root = self._workspace_root()
        git_root = await asyncio.to_thread(self._git_root, workspace_root)
        base_sha = await asyncio.to_thread(self._git_output, git_root, ["rev-parse", "HEAD"])
        suffix = uuid.uuid4().hex[:10]
        branch_name = f"codex/delivery-run-{run.id}-{suffix}"
        worktree_path = self._worktree_root(git_root) / f"run-{run.id}-{suffix}"
        worktree_path.parent.mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(
            self._git_run,
            git_root,
            ["worktree", "add", "-b", branch_name, str(worktree_path), base_sha],
        )
        dependency_links = await asyncio.to_thread(
            self._link_dependency_cache_dirs,
            git_root,
            worktree_path,
        )

        setup_logs = [
            (
                "info",
                "Isolated git worktree prepared.",
                {
                    "workspace_root": str(worktree_path),
                    "original_workspace_root": str(git_root),
                    "branch_name": branch_name,
                    "base_sha": base_sha,
                },
            )
        ]
        if dependency_links:
            setup_logs.append(
                (
                    "info",
                    "Runtime dependency cache linked.",
                    {"dependency_links": dependency_links},
                )
            )

        return WorkspaceContext(
            workspace_root=worktree_path,
            original_workspace_root=git_root,
            branch_name=branch_name,
            commit_sha=base_sha,
            dependency_links=dependency_links,
            setup_logs=setup_logs,
        )

    def _link_dependency_cache_dirs(self, source_root: Path, worktree_root: Path) -> list[dict[str, str]]:
        dependency_dirs = [
            Path("frontend") / "node_modules",
            Path("backend") / ".venv",
            Path(".venv"),
        ]
        links: list[dict[str, str]] = []

        for relative_path in dependency_dirs:
            source = source_root / relative_path
            target = worktree_root / relative_path
            if not source.is_dir() or target.exists():
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            link_type = self._create_directory_link(source, target)
            links.append(
                {
                    "path": relative_path.as_posix(),
                    "source": str(source),
                    "target": str(target),
                    "type": link_type,
                }
            )

        return links

    def _create_directory_link(self, source: Path, target: Path) -> str:
        try:
            target.symlink_to(source, target_is_directory=True)
            return "symlink"
        except (OSError, NotImplementedError) as exc:
            if os.name != "nt":
                raise

            completed = subprocess.run(
                ["cmd.exe", "/c", "mklink", "/J", str(target), str(source)],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode == 0:
                return "junction"

            raise OSError(
                "Failed to create dependency junction: "
                f"{self._tail(completed.stderr or completed.stdout)}"
            ) from exc

    def _write_codex_prompt(self, workspace: WorkspaceContext, run: ExecutionRun, task: CodingTask) -> Path:
        prompt_dir = workspace.original_workspace_root / ".runtime" / "codex-prompts"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = prompt_dir / f"codex-task-{run.id}.md"
        prompt_file.write_text(
            "\n".join(
                [
                    "# AI PJM Coding Task",
                    "",
                    f"Run ID: {run.id}",
                    f"Task ID: {task.id}",
                    "",
                    "## Task Prompt",
                    task.task_prompt,
                    "",
                    "## Allowed Paths",
                    *[f"- {item}" for item in (task.allowed_paths_json or [])],
                    "",
                    "## Forbidden Actions",
                    *[f"- {item}" for item in (task.forbidden_actions_json or [])],
                    "",
                    "## Required Checks",
                    *[f"- {item}" for item in (task.required_checks_json or [])],
                    "",
                    "## Expected Evidence",
                    *[f"- {item}" for item in (task.expected_evidence_json or [])],
                    "",
                    *self._repair_context_prompt_lines(run),
                ]
            ),
            encoding="utf-8",
        )
        return prompt_file

    def _repair_context_prompt_lines(self, run: ExecutionRun) -> list[str]:
        evidence = run.evidence_json or {}
        repair_context = evidence.get("repair_context") if isinstance(evidence, dict) else None
        if not isinstance(repair_context, dict):
            return []

        lines = [
            "## Repair Context",
            f"Repair attempt: {repair_context.get('attempt')} / {repair_context.get('max_attempts')}",
            f"Source failed run: {repair_context.get('source_run_id')}",
            f"Failure summary: {repair_context.get('failure_summary')}",
            "",
            "Failed checks:",
        ]
        failed_checks = repair_context.get("failed_checks")
        if isinstance(failed_checks, list) and failed_checks:
            for check in failed_checks:
                if not isinstance(check, dict):
                    continue
                lines.extend(
                    [
                        f"- Command: {check.get('command')}",
                        f"  Status: {check.get('status')}",
                        f"  Exit code: {check.get('exit_code')}",
                        f"  Error: {check.get('error') or ''}",
                        f"  Stdout tail: {check.get('stdout_tail') or ''}",
                        f"  Stderr tail: {check.get('stderr_tail') or ''}",
                    ]
                )
        else:
            lines.append("- No structured failed check output was recorded.")

        review_issues = repair_context.get("review_issues")
        if isinstance(review_issues, list) and review_issues:
            lines.extend(["", "Review blocking issues:"])
            for issue in review_issues:
                text = str(issue).strip()
                if text:
                    lines.append(f"- {text}")

        lines.extend(
            [
                "",
                "Repair instructions:",
                "- Fix only the failure described above.",
                "- Keep changes inside the allowed paths.",
                "- Re-run the required checks before finishing.",
                "",
            ]
        )
        return lines

    def _render_codex_command_template(
        self,
        *,
        template: str,
        workspace: WorkspaceContext,
        run: ExecutionRun,
        task: CodingTask,
        prompt_file: Path,
    ) -> str:
        values = {
            "workspace_root": str(workspace.workspace_root),
            "original_workspace_root": str(workspace.original_workspace_root),
            "branch_name": workspace.branch_name or "",
            "commit_sha": workspace.commit_sha or "",
            "prompt_file": str(prompt_file),
            "run_id": str(run.id),
            "task_id": str(task.id),
        }
        command = template
        for key, value in values.items():
            command = command.replace("{" + key + "}", value.replace('"', '\\"'))
        return command

    def _git_changed_files(self, cwd: Path) -> list[str]:
        output = self._git_output(cwd, ["status", "--porcelain"])
        changed_files: list[str] = []
        for line in output.splitlines():
            if not line.strip():
                continue
            path = line[3:]
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            changed_files.append(path.replace("\\", "/"))
        return changed_files

    def _changed_files_outside_allowed_paths(
        self,
        *,
        changed_files: list[str],
        allowed_paths: list[str],
    ) -> list[str]:
        normalized_allowed = [
            path.replace("\\", "/").strip("/")
            for path in allowed_paths
            if path and path.strip()
        ]
        if not changed_files or not normalized_allowed:
            return []

        violations: list[str] = []
        for changed_file in changed_files:
            normalized_file = changed_file.replace("\\", "/").strip("/")
            if not any(
                normalized_file == allowed_path or normalized_file.startswith(f"{allowed_path.rstrip('/')}/")
                for allowed_path in normalized_allowed
            ):
                violations.append(normalized_file)
        return violations

    def _git_root(self, workspace_root: Path) -> Path:
        output = self._git_output(workspace_root, ["rev-parse", "--show-toplevel"])
        return Path(output).resolve()

    def _git_output(self, cwd: Path, args: list[str]) -> str:
        completed = self._git_run(cwd, args)
        return completed.stdout.strip()

    def _git_run(self, cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "git command failed"
            raise RuntimeError(detail)
        return completed
