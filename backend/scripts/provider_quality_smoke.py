"""Run a provider quality smoke test without mutating delivery state."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.modules.delivery.enums import DeliveryRiskLevel, ImpactAnalysisStatus, RepoContextStatus, SpecStatus
from app.modules.delivery.models import DemandItem, RepoContext, SpecCard
from app.modules.delivery.providers.factory import get_workflow_provider
from app.modules.delivery.providers.quality import evaluate_impact_draft, evaluate_spec_draft
from app.modules.delivery.redaction import redact_value


DEFAULT_DEMAND = (
    "Add an operator-visible delivery trace summary that shows demand, task, execution, "
    "merge request, deployment, verification status, and failed gate reasons."
)


def main() -> int:
    args = parse_args()
    result = asyncio.run(
        run_quality_smoke(
            provider_name=args.provider,
            raw_input=args.demand,
            min_score=args.min_score,
            run_impact=not args.spec_only,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return 0 if result["passed"] else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test AI PJM workflow provider output quality.")
    parser.add_argument(
        "--provider",
        default=settings.ai_workflow_provider,
        choices=["local", "dify", "openai"],
        help="Provider to test. Dify/OpenAI require their normal environment configuration.",
    )
    parser.add_argument(
        "--demand",
        default=DEFAULT_DEMAND,
        help="Demand text used for the smoke test.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=settings.ai_workflow_provider_quality_min_score,
        help="Minimum deterministic quality score for Spec and Impact drafts.",
    )
    parser.add_argument(
        "--spec-only",
        action="store_true",
        help="Only call generate_spec. Useful while an impact workflow is not configured yet.",
    )
    return parser.parse_args()


async def run_quality_smoke(
    *,
    provider_name: str,
    raw_input: str,
    min_score: float,
    run_impact: bool,
) -> dict:
    provider = get_workflow_provider(provider_name)
    demand = DemandItem(
        id=0,
        raw_input=raw_input,
        source_type="provider_quality_smoke",
        title="Provider quality smoke",
        risk_level=DeliveryRiskLevel.L1,
        confidence_score=0.8,
        context_payload={
            "purpose": "provider_quality_smoke",
            "must_not_mutate_state": True,
        },
    )

    spec_draft = await provider.generate_spec(demand)
    spec_quality = evaluate_spec_draft(spec_draft, min_score)
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider_name,
        "passed": bool(spec_quality["passed"]),
        "spec": {
            "quality": spec_quality,
            "draft": redact_value(spec_draft.__dict__),
        },
        "impact": None,
    }

    if run_impact:
        repo_context_draft = await provider.collect_repo_context(demand)
        spec = SpecCard(
            id=0,
            demand_id=0,
            status=SpecStatus.APPROVED,
            title=spec_draft.title,
            user_story=spec_draft.user_story,
            scope=spec_draft.scope,
            acceptance_criteria_json=spec_draft.acceptance_criteria,
            constraints_json=spec_draft.constraints,
            risks_json=spec_draft.risks,
            open_questions_json=spec_draft.open_questions,
            provider_metadata_json=spec_draft.provider_metadata,
        )
        repo_context = RepoContext(
            id=0,
            demand_id=0,
            status=RepoContextStatus.READY,
            provider=repo_context_draft.provider_metadata.get("provider", provider_name),
            summary=repo_context_draft.summary,
            source_refs_json=repo_context_draft.source_refs,
            discovered_files_json=repo_context_draft.discovered_files,
            dependency_refs_json=repo_context_draft.dependency_refs,
            confidence_score=repo_context_draft.confidence_score,
            provider_metadata_json=repo_context_draft.provider_metadata,
        )
        impact_draft = await provider.analyze_impact(demand, spec, repo_context)
        impact_quality = evaluate_impact_draft(impact_draft, min_score)
        result["impact"] = {
            "quality": impact_quality,
            "draft": redact_value(impact_draft.__dict__),
        }
        result["passed"] = bool(spec_quality["passed"] and impact_quality["passed"])

    return result


if __name__ == "__main__":
    sys.exit(main())
