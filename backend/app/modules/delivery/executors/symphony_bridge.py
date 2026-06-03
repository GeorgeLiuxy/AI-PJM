"""Deferred executor that hands runs to the Symphony bridge worker queue."""

from app.core.config import settings
from app.modules.delivery.executors.base import ExecutionDispatchResult
from app.modules.delivery.models import CodingTask, ExecutionRun
from app.modules.delivery.redaction import redact_value


class SymphonyBridgeExecutor:
    """Queue a run for external worker claim instead of executing in HTTP."""

    name = "symphony_bridge"
    deferred = True

    async def dispatch(
        self,
        *,
        run: ExecutionRun,
        task: CodingTask,
        timeout_seconds: int,
    ) -> ExecutionDispatchResult:
        bridge_ready = bool(settings.symphony_bridge_token)
        evidence = redact_value(
            {
                "executor": self.name,
                "run_id": run.id,
                "coding_task_id": task.id,
                "status": "queued",
                "deferred": True,
                "bridge_ready": bridge_ready,
                "claim_endpoint": f"/api/v2/internal/symphony/execution-runs/{run.id}/claim",
                "task_package_endpoint": f"/api/v2/internal/symphony/execution-runs/{run.id}/task-package",
                "required_checks": task.required_checks_json or [],
                "allowed_paths": task.allowed_paths_json or [],
                "timeout_seconds": timeout_seconds,
            }
        )
        if not bridge_ready:
            evidence["warning"] = "SYMPHONY_BRIDGE_TOKEN is not configured; workers cannot claim this run yet."

        summary = (
            "Execution is queued for Symphony worker claim."
            if bridge_ready
            else "Execution is queued for Symphony, but the bridge token is not configured."
        )

        return ExecutionDispatchResult(
            succeeded=False,
            deferred=True,
            summary=summary,
            evidence=evidence,
            logs=[
                (
                    "info" if bridge_ready else "warning",
                    summary,
                    evidence,
                )
            ],
        )
