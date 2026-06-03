"""Minimal command-line worker for the AI PJM Symphony bridge.

This worker is intentionally small: it consumes the internal bridge API and
executes a local runner command plus required checks. A real Symphony daemon can
replace the local command layer later while keeping the same AI PJM API contract.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_API_BASE_URL = "http://127.0.0.1:8010/api/v2"
DEFAULT_TIMEOUT_SECONDS = 1800
TAIL_LIMIT = 4000


@dataclass
class CommandResult:
    command: str
    command_type: str
    cwd: str
    status: str
    exit_code: int
    duration_ms: int
    stdout_tail: str
    stderr_tail: str
    error: str | None = None


class BridgeClient:
    def __init__(self, api_base_url: str, token: str, timeout_seconds: int = 30) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds

    def get(self, path: str, query: dict[str, Any] | None = None) -> Any:
        if query:
            path = f"{path}?{urllib.parse.urlencode(query)}"
        return self._request("GET", path)

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        return self._request("POST", path, payload)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.api_base_url}{path}",
            data=body,
            method=method,
            headers={
                "Content-Type": "application/json",
                "X-Symphony-Bridge-Token": self.token,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc


def main() -> int:
    args = parse_args()
    token = args.token or os.environ.get("SYMPHONY_BRIDGE_TOKEN", "")
    if not token:
        print("SYMPHONY_BRIDGE_TOKEN is required.", file=sys.stderr)
        return 2

    worker = Worker(
        client=BridgeClient(args.api_base_url, token),
        worker_id=args.worker_id,
        workspace=Path(args.workspace).resolve(),
        runtime_dir=Path(args.runtime_dir).resolve(),
        status_file=Path(args.status_file).resolve() if args.status_file else None,
        runner_command=args.runner_command,
        timeout_seconds=args.command_timeout_seconds,
        lease_seconds=args.lease_seconds,
        skip_required_checks=args.skip_required_checks,
    )

    if args.loop:
        while True:
            handled = worker.run_once()
            if not handled:
                time.sleep(args.poll_seconds)
    handled = worker.run_once()
    return 0 if handled else 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one or more AI PJM Symphony bridge tasks.")
    parser.add_argument(
        "--api-base-url",
        default=os.environ.get("AI_PJM_API_BASE_URL", DEFAULT_API_BASE_URL),
        help="AI PJM API base URL, including /api/v2.",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Bridge token. Defaults to SYMPHONY_BRIDGE_TOKEN.",
    )
    parser.add_argument(
        "--worker-id",
        default=os.environ.get("SYMPHONY_WORKER_ID", f"symphony-worker-{uuid.uuid4().hex[:8]}"),
        help="Stable worker identifier written into run evidence.",
    )
    parser.add_argument(
        "--workspace",
        default=os.environ.get("SYMPHONY_WORKSPACE", os.getcwd()),
        help="Workspace directory used for runner commands and required checks.",
    )
    parser.add_argument(
        "--runtime-dir",
        default=os.environ.get("SYMPHONY_WORKER_RUNTIME_DIR", ".runtime/symphony-worker"),
        help="Directory used for task package and prompt files.",
    )
    parser.add_argument(
        "--status-file",
        default=os.environ.get("SYMPHONY_WORKER_STATUS_FILE", ""),
        help="Optional JSON status file updated by the worker loop.",
    )
    parser.add_argument(
        "--runner-command",
        default=os.environ.get("SYMPHONY_RUNNER_COMMAND", ""),
        help=(
            "Optional local command template. Supports {run_id}, {workspace}, "
            "{workspace_q}, {task_package_file}, {task_package_file_q}, "
            "{task_prompt_file}, and {task_prompt_file_q}."
        ),
    )
    parser.add_argument(
        "--skip-required-checks",
        action="store_true",
        help="Do not run task package required_checks after the runner command.",
    )
    parser.add_argument(
        "--command-timeout-seconds",
        type=int,
        default=int(os.environ.get("SYMPHONY_WORKER_COMMAND_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)),
        help="Timeout for each local command.",
    )
    parser.add_argument(
        "--lease-seconds",
        type=int,
        default=int(os.environ.get("SYMPHONY_WORKER_LEASE_SECONDS", str(DEFAULT_TIMEOUT_SECONDS + 300))),
        help="Worker lease duration requested during claim and heartbeat.",
    )
    parser.add_argument("--loop", action="store_true", help="Continuously poll for work.")
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=int(os.environ.get("SYMPHONY_WORKER_POLL_SECONDS", "5")),
        help="Poll interval when --loop is enabled.",
    )
    return parser.parse_args()


class Worker:
    def __init__(
        self,
        *,
        client: BridgeClient,
        worker_id: str,
        workspace: Path,
        runtime_dir: Path,
        runner_command: str,
        timeout_seconds: int,
        lease_seconds: int,
        skip_required_checks: bool,
        status_file: Path | None = None,
    ) -> None:
        self.client = client
        self.worker_id = worker_id
        self.workspace = workspace
        self.runtime_dir = runtime_dir
        self.status_file = status_file
        self.runner_command = runner_command.strip()
        self.timeout_seconds = timeout_seconds
        self.lease_seconds = lease_seconds
        self.skip_required_checks = skip_required_checks

    def run_once(self) -> bool:
        self._write_status("polling", message="Polling for queued execution runs.")
        queue = self.client.get("/internal/symphony/execution-runs", {"limit": 1})
        items = queue.get("data") or []
        if not items:
            self._write_status("idle", message="No queued Symphony execution runs.")
            print("No queued Symphony execution runs.")
            return False

        run_id = int(items[0]["id"])
        self._write_status("claiming", run_id=run_id, message="Claiming execution run.")
        self.client.post(
            f"/internal/symphony/execution-runs/{run_id}/claim",
            {"worker_id": self.worker_id, "lease_seconds": self.lease_seconds},
        )
        self._write_status("running", run_id=run_id, message="Execution run claimed.")
        package = self.client.get(f"/internal/symphony/execution-runs/{run_id}/task-package")["data"]
        package_files = self._write_package_files(run_id, package)
        self._event(run_id, "info", "Task package loaded.", {"package_files": package_files})

        command_results: list[CommandResult] = []
        try:
            if self.runner_command:
                command = self._format_command(run_id, package_files)
                command_results.append(self._run_command(run_id, command, "runner_command"))

            if not self.skip_required_checks:
                for command in package.get("required_checks") or []:
                    command_results.append(self._run_command(run_id, command, "required_check"))

            failed = [result for result in command_results if result.exit_code != 0]
            if not command_results:
                status = "failed"
                summary = "No runner command or required checks were executed."
            else:
                status = "failed" if failed else "succeeded"
                summary = (
                    f"{len(failed)} command(s) failed."
                    if failed
                    else f"{len(command_results)} command(s) completed successfully."
                )
            changed_files = self._git_changed_files()
            self.client.post(
                f"/internal/symphony/execution-runs/{run_id}/complete",
                {
                    "worker_id": self.worker_id,
                    "status": status,
                    "summary": summary,
                    "worktree_path": str(self.workspace),
                    "branch_name": self._git_output(["rev-parse", "--abbrev-ref", "HEAD"]),
                    "commit_sha": self._git_output(["rev-parse", "HEAD"]),
                    "evidence": {
                        "worker_id": self.worker_id,
                        "workspace": str(self.workspace),
                        "changed_files": changed_files,
                        "command_results": [result.__dict__ for result in command_results],
                        "task_package_file": package_files["task_package_file"],
                        "task_prompt_file": package_files["task_prompt_file"],
                    },
                },
            )
            self._write_status(status, run_id=run_id, message=summary)
            print(f"Execution run {run_id} completed with status {status}.")
            return True
        except Exception as exc:
            self._safe_complete_failed(run_id, command_results, exc)
            self._write_status("failed", run_id=run_id, message=str(exc))
            raise

    def _run_command(self, run_id: int, command: str, command_type: str) -> CommandResult:
        self._heartbeat(run_id)
        self._event(run_id, "info", f"{command_type} started.", {"command": command})
        cwd = self._command_cwd(command) if command_type == "required_check" else self.workspace
        start = time.perf_counter()
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                shell=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            duration_ms = int((time.perf_counter() - start) * 1000)
            status = "passed" if result.returncode == 0 else "failed"
            command_result = CommandResult(
                command=command,
                command_type=command_type,
                cwd=str(cwd),
                status=status,
                exit_code=result.returncode,
                duration_ms=duration_ms,
                stdout_tail=tail(result.stdout),
                stderr_tail=tail(result.stderr),
            )
        except subprocess.TimeoutExpired as exc:
            command_result = self._timeout_result(
                command=command,
                command_type=command_type,
                cwd=cwd,
                started=start,
                exc=exc,
            )
        self._event(
            run_id,
            "info" if command_result.exit_code == 0 else "error",
            f"{command_type} {command_result.status}.",
            command_result.__dict__,
        )
        self._heartbeat(run_id)
        return command_result

    def _timeout_result(
        self,
        *,
        command: str,
        command_type: str,
        cwd: Path,
        started: float,
        exc: subprocess.TimeoutExpired,
    ) -> CommandResult:
        return CommandResult(
            command=command,
            command_type=command_type,
            cwd=str(cwd),
            status="failed",
            exit_code=-1,
            duration_ms=int((time.perf_counter() - started) * 1000),
            stdout_tail=tail(exc.stdout),
            stderr_tail=tail(exc.stderr),
            error=f"Timed out after {self.timeout_seconds} seconds.",
        )

    def _command_cwd(self, command: str) -> Path:
        normalized = command.strip().lower().split()
        if not normalized:
            return self.workspace
        backend_dir = self.workspace / "backend"
        frontend_dir = self.workspace / "frontend"
        if normalized[:3] == ["npm", "run", "build"] and frontend_dir.is_dir():
            return frontend_dir
        if normalized[0] == "pytest" and backend_dir.is_dir():
            return backend_dir
        if normalized[:3] in (["python", "-m", "pytest"], ["python", "-m", "compileall"]):
            return backend_dir if backend_dir.is_dir() else self.workspace
        return self.workspace

    def _write_package_files(self, run_id: int, package: dict[str, Any]) -> dict[str, str]:
        run_dir = self.runtime_dir / str(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        package_file = run_dir / "task-package.json"
        prompt_file = run_dir / "task-prompt.md"
        package_file.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
        prompt_file.write_text(self._render_task_prompt(package), encoding="utf-8")
        return {
            "task_package_file": str(package_file),
            "task_prompt_file": str(prompt_file),
        }

    def _render_task_prompt(self, package: dict[str, Any]) -> str:
        lines = [
            "# AI PJM Symphony Task",
            "",
            f"Run ID: {package.get('run_id')}",
            f"Task ID: {package.get('coding_task_id')}",
            f"Demand ID: {package.get('demand_id')}",
            f"Risk Level: {package.get('risk_level')}",
            "",
            "## Task Prompt",
            str(package.get("task_prompt") or ""),
            "",
            "## Allowed Paths",
            *format_list(package.get("allowed_paths")),
            "",
            "## Forbidden Actions",
            *format_list(package.get("forbidden_actions")),
            "",
            "## Required Checks",
            *format_list(package.get("required_checks")),
            "",
            "## Expected Evidence",
            *format_list(package.get("expected_evidence")),
            "",
            "## Acceptance Criteria",
            *format_list(package.get("acceptance_criteria")),
            "",
            "## Repository Context",
            str(package.get("repo_context_summary") or "No repository context was provided."),
            "",
            "## Impact Summary",
            str(package.get("impact_summary") or "No impact summary was provided."),
            "",
            "## Execution Rules",
            "- Modify only files inside the allowed paths.",
            "- Do not perform forbidden actions.",
            "- Run all required checks before reporting completion.",
            "- Provide changed files and command results as execution evidence.",
            "",
        ]
        return "\n".join(lines)

    def _format_command(self, run_id: int, package_files: dict[str, str]) -> str:
        workspace = str(self.workspace)
        task_package_file = package_files["task_package_file"]
        task_prompt_file = package_files["task_prompt_file"]
        return self.runner_command.format(
            run_id=run_id,
            workspace=workspace,
            workspace_q=quote_arg(workspace),
            task_package_file=task_package_file,
            task_package_file_q=quote_arg(task_package_file),
            task_prompt_file=task_prompt_file,
            task_prompt_file_q=quote_arg(task_prompt_file),
        )

    def _git_changed_files(self) -> list[str]:
        output = self._git_output(["status", "--porcelain"])
        changed_files: list[str] = []
        for line in output.splitlines():
            if not line.strip() or len(line) < 4:
                continue
            path = line[3:]
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            changed_files.append(path.replace("\\", "/"))
        return changed_files

    def _git_output(self, args: list[str]) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    def _event(self, run_id: int, level: str, message: str, event_json: dict[str, Any]) -> None:
        self.client.post(
            f"/internal/symphony/execution-runs/{run_id}/events",
            {
                "worker_id": self.worker_id,
                "level": level,
                "message": message,
                "event_json": event_json,
            },
        )

    def _heartbeat(self, run_id: int) -> None:
        self.client.post(
            f"/internal/symphony/execution-runs/{run_id}/heartbeat",
            {"worker_id": self.worker_id, "lease_seconds": self.lease_seconds},
        )
        self._write_status("running", run_id=run_id, message="Heartbeat sent.")

    def _safe_complete_failed(
        self,
        run_id: int,
        command_results: list[CommandResult],
        exc: Exception,
    ) -> None:
        try:
            self.client.post(
                f"/internal/symphony/execution-runs/{run_id}/complete",
                {
                    "worker_id": self.worker_id,
                    "status": "failed",
                    "summary": f"Worker failed: {exc}",
                    "worktree_path": str(self.workspace),
                    "branch_name": self._git_output(["rev-parse", "--abbrev-ref", "HEAD"]),
                    "commit_sha": self._git_output(["rev-parse", "HEAD"]),
                    "evidence": {
                        "worker_id": self.worker_id,
                        "workspace": str(self.workspace),
                        "changed_files": self._git_changed_files(),
                        "command_results": [result.__dict__ for result in command_results],
                        "error": str(exc),
                    },
                },
            )
        except Exception as complete_error:
            print(f"Failed to write completion error for run {run_id}: {complete_error}", file=sys.stderr)

    def _write_status(self, state: str, run_id: int | None = None, message: str | None = None) -> None:
        if not self.status_file:
            return
        payload = {
            "worker_id": self.worker_id,
            "state": state,
            "run_id": run_id,
            "message": message,
            "workspace": str(self.workspace),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.status_file.parent.mkdir(parents=True, exist_ok=True)
            self.status_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            print(f"Failed to write worker status file {self.status_file}: {exc}", file=sys.stderr)


def tail(value: str | bytes | None) -> str:
    text = coerce_text(value)
    if len(text) <= TAIL_LIMIT:
        return text
    return text[-TAIL_LIMIT:]


def coerce_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def format_list(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        return ["- None"]
    return [f"- {item}" for item in value]


def quote_arg(value: str) -> str:
    return subprocess.list2cmdline([value])


if __name__ == "__main__":
    raise SystemExit(main())
