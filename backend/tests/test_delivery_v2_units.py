"""Delivery v2 service rule tests that do not require a database."""

import pytest

from app.core.config import settings
from app.core.exceptions import AIServiceException
from app.modules.delivery.executors.local_checks import WorktreeChecksExecutor
from app.modules.delivery.enums import CodingTaskStatus, DeliveryRiskLevel, GateStatus, SpecStatus
from app.modules.delivery.gates import gate_engine
from app.modules.delivery.models import DemandItem, RepoContext
from app.modules.delivery.providers.dify import DifyWorkflowProvider
from app.modules.delivery.providers.factory import get_workflow_provider
from app.modules.delivery.providers.local import LocalWorkflowProvider
from app.modules.delivery.service import delivery_service


def test_delivery_v2_low_risk_auto_approval_rule():
    risk_level = delivery_service._classify_risk(
        "Add a compact execution status badge to the delivery dashboard."
    )
    confidence = delivery_service._estimate_confidence(
        "Add a compact execution status badge to the delivery dashboard."
    )
    status = delivery_service._decide_spec_status(
        risk_level=risk_level,
        confidence_score=confidence,
        auto_approve_low_risk=True,
    )

    assert risk_level == DeliveryRiskLevel.L1
    assert confidence >= 0.7
    assert status == SpecStatus.APPROVED


def test_delivery_v2_high_risk_requires_manual_review_rule():
    risk_level = delivery_service._classify_risk(
        "Change login permission logic and migrate production user tokens."
    )
    confidence = delivery_service._estimate_confidence(
        "Change login permission logic and migrate production user tokens."
    )
    status = delivery_service._decide_spec_status(
        risk_level=risk_level,
        confidence_score=confidence,
        auto_approve_low_risk=True,
    )

    assert risk_level == DeliveryRiskLevel.L2
    assert confidence >= 0.7
    assert status == SpecStatus.MANUAL_REVIEW


def test_delivery_v2_execution_gate_blocks_draft_task():
    decision = gate_engine.evaluate_execution_allowed(
        coding_task_id=1,
        coding_task_status=CodingTaskStatus.DRAFT,
        risk_level=DeliveryRiskLevel.L1,
    )

    assert decision.status == GateStatus.MANUAL_REQUIRED
    assert decision.evidence["coding_task_status"] == CodingTaskStatus.DRAFT


def test_delivery_v2_repo_context_gate_uses_confidence_threshold():
    decision = gate_engine.evaluate_repo_context(
        repo_context_id=1,
        confidence_score=0.55,
        source_refs=["demand.raw_input"],
    )

    assert decision.status == GateStatus.MANUAL_REQUIRED


def test_delivery_v2_dify_provider_resolves_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "ai_workflow_provider", "dify")
    monkeypatch.setattr(settings, "dify_api_base_url", "http://dify.local")
    monkeypatch.setattr(settings, "dify_api_key", "test-key")
    monkeypatch.setattr(settings, "dify_spec_workflow_id", "spec-flow")
    monkeypatch.setattr(settings, "dify_impact_workflow_id", "impact-flow")

    provider = get_workflow_provider()

    assert isinstance(provider, DifyWorkflowProvider)
    assert provider.name == "dify"


def test_delivery_v2_dify_provider_requires_base_config(monkeypatch):
    monkeypatch.setattr(settings, "dify_api_base_url", "")
    monkeypatch.setattr(settings, "dify_api_key", "")

    with pytest.raises(AIServiceException, match="DIFY_API_BASE_URL"):
        DifyWorkflowProvider()._require_base_config()


@pytest.mark.asyncio
async def test_local_provider_collects_real_workspace_context(tmp_path):
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "v2-delivery-blueprint.md").write_text("delivery docs\n", encoding="utf-8")
    (tmp_path / "frontend" / "src" / "app" / "pages").mkdir(parents=True)
    (tmp_path / "frontend" / "src" / "app" / "pages" / "DeliveryV2Page.tsx").write_text(
        "export function DeliveryV2Page() { return null; }\n",
        encoding="utf-8",
    )
    (tmp_path / "frontend" / "src" / "app").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "src" / "app" / "Root.tsx").write_text("export {}\n", encoding="utf-8")
    (tmp_path / "frontend" / "src" / "app" / "lib").mkdir(parents=True)
    (tmp_path / "frontend" / "src" / "app" / "lib" / "api.ts").write_text("export {}\n", encoding="utf-8")
    (tmp_path / "frontend" / "package.json").write_text(
        '{"scripts":{"build":"vite build","test":"vitest"}}',
        encoding="utf-8",
    )
    (tmp_path / "backend" / "app" / "modules" / "delivery").mkdir(parents=True)
    (tmp_path / "backend" / "app" / "modules" / "delivery" / "service.py").write_text(
        "class DeliveryService: pass\n",
        encoding="utf-8",
    )
    (tmp_path / "backend" / "tests").mkdir(parents=True)
    (tmp_path / "backend" / "tests" / "test_health.py").write_text("def test_health(): pass\n", encoding="utf-8")
    (tmp_path / "backend" / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / ".runtime").mkdir()
    (tmp_path / ".runtime" / "ignored.py").write_text("ignored\n", encoding="utf-8")

    demand = DemandItem(
        raw_input="Update the delivery dashboard page and API status display.",
        source_type="new_requirement",
        title="Update delivery dashboard",
    )
    draft = await LocalWorkflowProvider(workspace_root=tmp_path).collect_repo_context(demand)

    assert draft.confidence_score >= 0.6
    assert draft.provider_metadata["provider"] == "local"
    assert draft.provider_metadata["file_count"] >= 6
    assert "frontend/package.json:scripts.build" in draft.dependency_refs
    assert "backend/pyproject.toml" in draft.dependency_refs
    assert "workspace.root" in draft.source_refs
    assert "frontend/src/app/pages/DeliveryV2Page.tsx" in draft.discovered_files
    assert "backend/app/modules/delivery/service.py" in draft.discovered_files
    assert not any(path.startswith(".runtime") for path in draft.discovered_files)


@pytest.mark.asyncio
async def test_local_provider_analyzes_impact_from_repo_context():
    demand = DemandItem(
        raw_input="Update the delivery dashboard page and backend delivery status API.",
        source_type="new_requirement",
        title="Update delivery dashboard",
        risk_level=DeliveryRiskLevel.L1,
        confidence_score=0.82,
    )
    repo_context = RepoContext(
        id=1,
        demand_id=1,
        status="ready",
        provider="local",
        summary="local",
        source_refs_json=["workspace.root"],
        discovered_files_json=[
            "frontend/src/app/pages/DeliveryV2Page.tsx",
            "backend/app/modules/delivery/service.py",
        ],
        dependency_refs_json=[
            "frontend/package.json:scripts.build",
            "backend/tests",
        ],
        confidence_score=0.9,
        provider_metadata_json={"provider": "local"},
    )

    draft = await LocalWorkflowProvider().analyze_impact(demand, None, repo_context)

    assert draft.risk_level == DeliveryRiskLevel.L1
    assert draft.confidence_score == 0.82
    assert "frontend/src/app/pages/DeliveryV2Page.tsx" in draft.affected_files
    assert "backend/app/modules/delivery/service.py" in draft.affected_files
    assert "frontend/src/app/pages" in draft.impacted_areas
    assert "backend/app/modules/delivery" in draft.impacted_areas
    assert any("npm run build" in item for item in draft.recommendations)
    assert any("python -m pytest" in item for item in draft.recommendations)


def test_worktree_executor_links_dependency_cache(tmp_path):
    source_root = tmp_path / "source"
    worktree_root = tmp_path / "worktree"
    source_dependency = source_root / "frontend" / "node_modules"
    target_dependency = worktree_root / "frontend" / "node_modules"
    source_dependency.mkdir(parents=True)
    (worktree_root / "frontend").mkdir(parents=True)

    try:
        links = WorktreeChecksExecutor()._link_dependency_cache_dirs(source_root, worktree_root)

        assert len(links) == 1
        assert links[0]["path"] == "frontend/node_modules"
        assert links[0]["source"] == str(source_dependency)
        assert links[0]["target"] == str(target_dependency)
        assert links[0]["type"] in {"symlink", "junction"}
        assert target_dependency.is_dir()
    finally:
        if target_dependency.exists():
            target_dependency.rmdir() if not target_dependency.is_symlink() else target_dependency.unlink()
