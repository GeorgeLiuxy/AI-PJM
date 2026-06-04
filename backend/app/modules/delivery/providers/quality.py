"""Deterministic quality evaluation for provider drafts."""

from __future__ import annotations

from typing import Any

from app.modules.delivery.providers.base import ImpactAnalysisDraft, SpecDraft


QUALITY_EVALUATION_VERSION = "provider-quality-v1"


def evaluate_spec_draft(draft: SpecDraft, min_score: float) -> dict[str, Any]:
    score = 1.0
    findings: list[str] = []

    if len(draft.acceptance_criteria) < 2:
        score -= 0.15
        findings.append("acceptance_criteria_has_less_than_two_items")
    if len(draft.scope.strip()) < 20:
        score -= 0.15
        findings.append("scope_is_too_short")
    if not draft.user_story.strip().lower().startswith("as "):
        score -= 0.1
        findings.append("user_story_does_not_follow_as_a_pattern")
    if not draft.constraints:
        score -= 0.1
        findings.append("constraints_are_empty")
    if not draft.risks:
        score -= 0.1
        findings.append("risks_are_empty")

    return _result(score, findings, min_score)


def evaluate_impact_draft(draft: ImpactAnalysisDraft, min_score: float) -> dict[str, Any]:
    score = 1.0
    findings: list[str] = []

    if len(draft.summary.strip()) < 20:
        score -= 0.1
        findings.append("summary_is_too_short")
    if not draft.impacted_areas:
        score -= 0.2
        findings.append("impacted_areas_are_empty")
    if not draft.affected_files:
        score -= 0.15
        findings.append("affected_files_are_empty")
    if not draft.recommendations:
        score -= 0.15
        findings.append("recommendations_are_empty")
    if draft.confidence_score < 0.6:
        score -= 0.15
        findings.append("confidence_score_is_low")

    return _result(score, findings, min_score)


def _result(score: float, findings: list[str], min_score: float) -> dict[str, Any]:
    normalized_score = round(min(max(score, 0.0), 1.0), 2)
    normalized_min_score = round(min(max(min_score, 0.0), 1.0), 2)
    return {
        "version": QUALITY_EVALUATION_VERSION,
        "score": normalized_score,
        "min_score": normalized_min_score,
        "passed": normalized_score >= normalized_min_score,
        "findings": findings,
    }
