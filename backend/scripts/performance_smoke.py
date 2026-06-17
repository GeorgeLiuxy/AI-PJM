"""Run a small read-only performance smoke test against AI PJM APIs."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import httpx


DEFAULT_ENDPOINTS = (
    "/health",
    "/api/v2/demands?limit=30",
    "/api/v2/execution-runs?limit=30",
    "/api/v2/observability/summary",
)


@dataclass(frozen=True)
class Sample:
    endpoint: str
    status_code: int | None
    elapsed_ms: float
    error: str | None = None


def main() -> int:
    args = parse_args()
    summary = asyncio.run(
        run_smoke(
            base_url=args.base_url,
            endpoints=args.endpoint,
            total_requests=args.requests,
            concurrency=args.concurrency,
            timeout_seconds=args.timeout_seconds,
            token=args.token,
            trust_env=args.trust_env,
        )
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if summary["error_rate_percent"] > args.max_error_rate_percent:
        return 1
    if summary["p95_ms"] > args.max_p95_ms:
        return 1
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only AI PJM API performance smoke test.")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("AI_PJM_PERF_BASE_URL", "http://127.0.0.1:8010"),
        help="Backend base URL, for example http://127.0.0.1:8010.",
    )
    parser.add_argument(
        "--endpoint",
        action="append",
        default=None,
        help="Endpoint path to test. Can be passed multiple times. Defaults to core read endpoints.",
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=int(os.environ.get("AI_PJM_PERF_REQUESTS", "80")),
        help="Total requests across all endpoints.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.environ.get("AI_PJM_PERF_CONCURRENCY", "8")),
        help="Maximum concurrent requests.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(os.environ.get("AI_PJM_PERF_TIMEOUT_SECONDS", "10")),
        help="Per-request timeout.",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("AI_PJM_API_TOKEN", ""),
        help="Optional Bearer token when AUTH_ENABLED=true.",
    )
    parser.add_argument(
        "--trust-env",
        action="store_true",
        help="Use proxy and SSL settings from the environment. Disabled by default for stable target smoke tests.",
    )
    parser.add_argument(
        "--max-p95-ms",
        type=float,
        default=float(os.environ.get("AI_PJM_PERF_MAX_P95_MS", "1000")),
        help="Fail when overall p95 exceeds this value.",
    )
    parser.add_argument(
        "--max-error-rate-percent",
        type=float,
        default=float(os.environ.get("AI_PJM_PERF_MAX_ERROR_RATE_PERCENT", "1")),
        help="Fail when error rate exceeds this percentage.",
    )
    return parser.parse_args()


async def run_smoke(
    *,
    base_url: str,
    endpoints: Iterable[str] | None = None,
    total_requests: int,
    concurrency: int,
    timeout_seconds: float,
    token: str = "",
    trust_env: bool = False,
) -> dict:
    endpoint_list = tuple(endpoints or DEFAULT_ENDPOINTS)
    if not endpoint_list:
        raise ValueError("At least one endpoint is required")

    safe_total = max(total_requests, 1)
    safe_concurrency = max(concurrency, 1)
    semaphore = asyncio.Semaphore(safe_concurrency)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    base = base_url.rstrip("/")
    timeout = httpx.Timeout(timeout_seconds)

    async with httpx.AsyncClient(
        base_url=base,
        headers=headers,
        timeout=timeout,
        trust_env=trust_env,
    ) as client:
        tasks = [
            asyncio.create_task(_timed_get(client, endpoint_list[index % len(endpoint_list)], semaphore))
            for index in range(safe_total)
        ]
        samples = await asyncio.gather(*tasks)
    return summarize(samples, endpoint_list, safe_total, safe_concurrency)


async def _timed_get(client: httpx.AsyncClient, endpoint: str, semaphore: asyncio.Semaphore) -> Sample:
    async with semaphore:
        started = time.perf_counter()
        try:
            response = await client.get(endpoint)
            elapsed_ms = (time.perf_counter() - started) * 1000
            error = None if response.status_code < 500 else response.text[:500]
            return Sample(endpoint=endpoint, status_code=response.status_code, elapsed_ms=elapsed_ms, error=error)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            return Sample(endpoint=endpoint, status_code=None, elapsed_ms=elapsed_ms, error=str(exc)[:500])


def summarize(
    samples: list[Sample],
    endpoints: Iterable[str],
    total_requests: int,
    concurrency: int,
) -> dict:
    elapsed_values = sorted(sample.elapsed_ms for sample in samples)
    failed = [
        sample
        for sample in samples
        if sample.error is not None or sample.status_code is None or sample.status_code >= 500
    ]
    by_endpoint = {}
    for endpoint in endpoints:
        endpoint_samples = [sample for sample in samples if sample.endpoint == endpoint]
        endpoint_values = sorted(sample.elapsed_ms for sample in endpoint_samples)
        by_endpoint[endpoint] = {
            "count": len(endpoint_samples),
            "error_count": len(
                [
                    sample
                    for sample in endpoint_samples
                    if sample.error is not None or sample.status_code is None or sample.status_code >= 500
                ]
            ),
            "p95_ms": round(percentile(endpoint_values, 95), 2),
            "max_ms": round(max(endpoint_values), 2) if endpoint_values else 0,
            "status_codes": sorted(
                {
                    str(sample.status_code)
                    for sample in endpoint_samples
                    if sample.status_code is not None
                }
            ),
        }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_requests": total_requests,
        "concurrency": concurrency,
        "error_count": len(failed),
        "error_rate_percent": round((len(failed) / len(samples)) * 100, 2) if samples else 0,
        "p50_ms": round(percentile(elapsed_values, 50), 2),
        "p95_ms": round(percentile(elapsed_values, 95), 2),
        "max_ms": round(max(elapsed_values), 2) if elapsed_values else 0,
        "by_endpoint": by_endpoint,
        "sample_errors": [
            {
                "endpoint": sample.endpoint,
                "status_code": sample.status_code,
                "elapsed_ms": round(sample.elapsed_ms, 2),
                "error": sample.error,
            }
            for sample in failed[:5]
        ],
    }


def percentile(values: list[float], percent: int) -> float:
    if not values:
        return 0
    if len(values) == 1:
        return values[0]
    index = (len(values) - 1) * (percent / 100)
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (index - lower)


if __name__ == "__main__":
    sys.exit(main())
