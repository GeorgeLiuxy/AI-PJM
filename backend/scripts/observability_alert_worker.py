"""Poll AI PJM observability summary and optionally forward alerts."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


DEFAULT_STATUS_FILE = Path(".runtime/observability-alert-status.json")


def main() -> int:
    args = parse_args()
    try:
        if args.loop:
            asyncio.run(run_loop(args))
            return 0
        summary = asyncio.run(run_once(args))
        return exit_code(summary, fail_on_warning=args.fail_on_warning)
    except KeyboardInterrupt:
        return 130


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Forward AI PJM observability alerts.")
    parser.add_argument(
        "--api-base-url",
        default=os.environ.get("AI_PJM_API_BASE_URL", "http://127.0.0.1:8010/api/v2"),
        help="AI PJM API base URL.",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("AI_PJM_API_TOKEN", ""),
        help="Optional Bearer token when AUTH_ENABLED=true.",
    )
    parser.add_argument(
        "--alert-webhook-url",
        default=os.environ.get("OBSERVABILITY_ALERT_WEBHOOK_URL", ""),
        help="Optional webhook URL that receives alert JSON when status is warning or critical.",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Continuously poll observability summary.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=int(os.environ.get("OBSERVABILITY_ALERT_POLL_SECONDS", "120")),
        help="Loop polling interval.",
    )
    parser.add_argument(
        "--status-file",
        default=os.environ.get("OBSERVABILITY_ALERT_STATUS_FILE", str(DEFAULT_STATUS_FILE)),
        help="Status JSON file path. Pass an empty string to disable.",
    )
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Return non-zero for warning status in one-shot mode.",
    )
    return parser.parse_args()


async def run_loop(args: argparse.Namespace) -> None:
    while True:
        await run_once(args)
        await asyncio.sleep(max(args.poll_seconds, 1))


async def run_once(args: argparse.Namespace) -> dict[str, Any]:
    summary = await fetch_summary(args.api_base_url, token=args.token)
    if summary.get("status") in {"warning", "critical"} and args.alert_webhook_url:
        await forward_alert(args.alert_webhook_url, summary)
    status_payload = {
        "state": summary.get("status", "unknown"),
        "generated_at": summary.get("generated_at"),
        "alert_count": len(summary.get("alerts") or []),
        "metrics": summary.get("metrics") or {},
    }
    write_status(Path(args.status_file) if args.status_file else None, status_payload)
    print(json.dumps(status_payload, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return summary


async def fetch_summary(api_base_url: str, *, token: str = "") -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    url = f"{api_base_url.rstrip('/')}/observability/summary"
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
    body = response.json()
    if isinstance(body, dict) and isinstance(body.get("data"), dict):
        return body["data"]
    if isinstance(body, dict):
        return body
    raise RuntimeError("Observability summary response must be a JSON object")


async def forward_alert(webhook_url: str, summary: dict[str, Any]) -> None:
    payload = {
        "source": "ai-pjm",
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "status": summary.get("status"),
        "generated_at": summary.get("generated_at"),
        "metrics": summary.get("metrics") or {},
        "alerts": summary.get("alerts") or [],
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(webhook_url, json=payload)
        response.raise_for_status()


def write_status(path: Path | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"updated_at": datetime.now(timezone.utc).isoformat(), **payload}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")


def exit_code(summary: dict[str, Any], *, fail_on_warning: bool) -> int:
    status = summary.get("status")
    if status == "critical":
        return 2
    if status == "warning" and fail_on_warning:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
