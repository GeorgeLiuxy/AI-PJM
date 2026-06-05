"""Local repository-aware workflow provider."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.modules.delivery.enums import DeliveryRiskLevel
from app.modules.delivery.models import DemandItem, RepoContext, SpecCard
from app.modules.delivery.providers.base import ImpactAnalysisDraft, RepoContextDraft
from app.modules.delivery.providers.mock import MockWorkflowProvider


class LocalWorkflowProvider(MockWorkflowProvider):
    """Provider that collects repository context from the local workspace."""

    name = "local"

    _ignored_dirs = {
        ".claude",
        ".git",
        ".idea",
        ".runtime",
        ".pytest_cache",
        ".vscode",
        ".mypy_cache",
        ".venv",
        "__pycache__",
        "backend/data",
        "backend/logs",
        "data",
        "dist",
        "logs",
        "node_modules",
    }
    _ignored_files = {
        "CLAUDE.md",
    }
    _important_files = {
        ".gitignore",
        "README.md",
        "backend/README.md",
        "backend/pyproject.toml",
        "backend/pytest.ini",
        "frontend/package.json",
        "frontend/vite.config.ts",
        "frontend/src/app/pages/DeliveryV2Page.tsx",
        "frontend/src/app/Root.tsx",
        "frontend/src/app/lib/api.ts",
        "frontend/src/app/types/index.ts",
        "backend/app/modules/delivery/service.py",
        "backend/app/modules/delivery/router.py",
        "backend/app/modules/delivery/providers/base.py",
        "backend/app/modules/delivery/providers/factory.py",
        "backend/app/modules/delivery/executors/local_checks.py",
        "backend/tests/test_delivery_v2.py",
        "backend/tests/test_delivery_v2_units.py",
    }
    _doc_prefixes = ("docs/",)
    _code_suffixes = (".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".toml", ".md", ".ps1")

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self._workspace_root_override = Path(workspace_root).resolve() if workspace_root else None

    async def collect_repo_context(self, demand: DemandItem) -> RepoContextDraft:
        root = self._workspace_root()
        files = self._list_candidate_files(root)
        payload = demand.context_payload or {}
        demand_text = self._contextual_demand_text(demand)
        explicit_files = self._as_string_list(payload.get("files"))
        explicit_sources = self._as_string_list(payload.get("sources"))
        explicit_dependencies = self._as_string_list(payload.get("dependencies"))

        path_hints = self._existing_paths(root, self._extract_path_hints(demand.raw_input), files)
        matched_files = self._match_demand_files(demand_text, files, root=root)
        important_files = self._select_important_files(files)
        discovered_files = self._dedupe([*explicit_files, *path_hints, *matched_files, *important_files])[:40]

        dependency_refs = self._dedupe([*explicit_dependencies, *self._collect_dependency_refs(root)])
        source_refs = self._dedupe(
            [
                *explicit_sources,
                "workspace.root",
                *self._collect_git_refs(root),
                *self._select_source_refs(files),
            ]
        )[:40]

        confidence = self._confidence_score(
            discovered_files=discovered_files,
            source_refs=source_refs,
            dependency_refs=dependency_refs,
        )

        return RepoContextDraft(
            summary=self._build_summary(
                root=root,
                files=files,
                discovered_files=discovered_files,
                dependency_refs=dependency_refs,
            ),
            source_refs=source_refs,
            discovered_files=discovered_files,
            dependency_refs=dependency_refs,
            confidence_score=confidence,
            provider_metadata={
                "provider": self.name,
                "workspace_root": str(root),
                "file_count": len(files),
                "scanner": "local_filesystem",
                "matcher": "path_and_content_tokens",
                "historical_context_items": self._historical_context_count(payload),
            },
        )

    async def analyze_impact(
        self,
        demand: DemandItem,
        spec: SpecCard | None,
        repo_context: RepoContext | None,
    ) -> ImpactAnalysisDraft:
        affected_files = self._select_affected_files(demand, spec, repo_context)
        impacted_areas = self._impacted_areas(affected_files)
        risk_level = demand.risk_level or DeliveryRiskLevel.L1
        confidence = min(demand.confidence_score or 0.72, repo_context.confidence_score if repo_context else 0.62)
        if not affected_files:
            confidence = min(confidence, 0.58)

        return ImpactAnalysisDraft(
            summary=(
                "Impact analysis used the local repository context and demand-specific candidate files. "
                f"Impacted areas: {', '.join(impacted_areas) if impacted_areas else 'none'}. "
                f"Affected candidate files: {len(affected_files)}."
            ),
            impacted_areas=impacted_areas or ["application"],
            affected_files=affected_files,
            recommendations=self._impact_recommendations(repo_context),
            risk_level=risk_level,
            confidence_score=confidence,
            provider_metadata={
                "provider": self.name,
                "spec_card_id": spec.id if spec else None,
                "repo_context_id": repo_context.id if repo_context else None,
                "analysis_source": "local_repo_context",
                "context_file_count": len(repo_context.discovered_files_json) if repo_context else 0,
            },
        )

    def _workspace_root(self) -> Path:
        if self._workspace_root_override:
            return self._workspace_root_override
        if settings.workspace_root:
            return Path(settings.workspace_root).expanduser().resolve()
        return Path(__file__).resolve().parents[5]

    def _list_candidate_files(self, root: Path, limit: int = 5000) -> list[str]:
        files: list[str] = []
        if not root.exists():
            return files

        for path in root.rglob("*"):
            if len(files) >= limit:
                break
            if not path.is_file():
                continue

            relative = path.relative_to(root).as_posix()
            if self._is_ignored(relative):
                continue
            if not relative.endswith(self._code_suffixes):
                continue

            files.append(relative)

        return sorted(files)

    def _is_ignored(self, relative_path: str) -> bool:
        if relative_path in self._ignored_files or Path(relative_path).name in self._ignored_files:
            return True

        parts = relative_path.split("/")
        for index in range(len(parts)):
            prefix = "/".join(parts[: index + 1])
            if prefix in self._ignored_dirs or parts[index] in self._ignored_dirs:
                return True
        return False

    def _existing_paths(self, root: Path, hints: list[str], files: list[str]) -> list[str]:
        file_set = set(files)
        existing: list[str] = []
        for hint in hints:
            normalized = hint.replace("\\", "/").strip("/")
            if normalized in file_set or (root / normalized).exists():
                existing.append(normalized)
        return existing

    def _match_demand_files(self, raw_input: str, files: list[str], root: Path | None = None) -> list[str]:
        normalized = raw_input.lower()
        keywords = self._keywords(raw_input)
        domain_hints = self._domain_hint_files(normalized, files)
        scored: dict[str, float] = {}

        for path in files:
            haystack = path.lower()
            score = sum(1 for keyword in keywords if keyword in haystack)
            if score:
                scored[path] = max(scored.get(path, 0), float(score))

        if root:
            for path, score in self._content_matched_files(root, files, keywords):
                scored[path] = max(scored.get(path, 0), score)

        ordered = sorted(scored.items(), key=lambda item: (-item[1], item[0]))
        return self._dedupe([*domain_hints, *[path for path, _ in ordered]])[:24]

    def _keywords(self, raw_input: str) -> list[str]:
        normalized = raw_input.lower()
        words = re.findall(r"[a-z0-9_]{3,}", normalized)
        chinese_chunks = re.findall(r"[\u4e00-\u9fff]+", normalized)
        for chunk in chinese_chunks:
            if len(chunk) >= 2:
                words.append(chunk)
                words.extend(f"{left}{right}" for left, right in zip(chunk, chunk[1:]))
        stop_words = {
            "add",
            "change",
            "create",
            "demand",
            "delivery",
            "feature",
            "from",
            "improve",
            "into",
            "requirement",
            "status",
            "with",
            "that",
            "this",
            "update",
        }
        return self._dedupe([word for word in words if word not in stop_words])

    def _content_matched_files(
        self,
        root: Path,
        files: list[str],
        keywords: list[str],
        limit: int = 800,
    ) -> list[tuple[str, float]]:
        if not keywords:
            return []

        keyword_set = set(keywords)
        scored: list[tuple[str, float]] = []
        for path in self._content_scan_candidates(files)[:limit]:
            sample = self._read_text_sample(root / path)
            if not sample:
                continue
            haystack = f"{path.lower()}\n{sample.lower()}"
            matches = [keyword for keyword in keyword_set if keyword in haystack]
            if not matches:
                continue
            path_bonus = sum(0.5 for keyword in matches if keyword in path.lower())
            coverage = len(matches) / len(keyword_set)
            score = len(matches) + path_bonus + coverage
            scored.append((path, score))

        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored[:24]

    def _content_scan_candidates(self, files: list[str]) -> list[str]:
        docs = [path for path in files if path.startswith(self._doc_prefixes) and path.endswith(".md")]
        important = [path for path in files if path in self._important_files]
        source = [path for path in files if path not in set(docs + important)]
        return self._dedupe([*docs, *important, *source])

    def _read_text_sample(self, path: Path, max_chars: int = 16000) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
        except OSError:
            return ""

    def _domain_hint_files(self, normalized_input: str, files: list[str]) -> list[str]:
        hints: list[str] = []
        file_set = set(files)

        def add_if_exists(path: str) -> None:
            if path in file_set:
                hints.append(path)

        frontend_terms = ("ui", "page", "dashboard", "workbench", "frontend", "页面", "工作台", "前端", "中文")
        backend_terms = (
            "api",
            "backend",
            "provider",
            "context",
            "gate",
            "execution",
            "codex",
            "后端",
            "接口",
            "上下文",
            "门禁",
            "执行",
        )
        delivery_terms = ("delivery", "交付", "需求", "任务")

        if any(term in normalized_input for term in frontend_terms):
            add_if_exists("frontend/src/app/pages/DeliveryV2Page.tsx")
            add_if_exists("frontend/src/app/Root.tsx")
            add_if_exists("frontend/src/app/lib/api.ts")
            add_if_exists("frontend/src/app/types/index.ts")
        if any(term in normalized_input for term in backend_terms):
            add_if_exists("backend/app/modules/delivery/service.py")
            add_if_exists("backend/app/modules/delivery/router.py")
            add_if_exists("backend/app/modules/delivery/providers/factory.py")
            add_if_exists("backend/app/modules/delivery/executors/local_checks.py")
        if any(term in normalized_input for term in delivery_terms):
            add_if_exists("docs/v2-delivery-blueprint.md")
            add_if_exists("docs/v2-execution-roadmap.md")
            add_if_exists("backend/app/modules/delivery/service.py")
            add_if_exists("frontend/src/app/pages/DeliveryV2Page.tsx")

        return hints

    def _select_important_files(self, files: list[str]) -> list[str]:
        selected = [path for path in files if path in self._important_files]
        selected.extend(path for path in files if path.startswith(self._doc_prefixes) and path.endswith(".md"))
        return self._dedupe(selected)[:24]

    def _select_source_refs(self, files: list[str]) -> list[str]:
        refs = ["demand.raw_input"]
        for path in self._select_important_files(files)[:20]:
            refs.append(path)
        return refs

    def _select_affected_files(
        self,
        demand: DemandItem,
        spec: SpecCard | None,
        repo_context: RepoContext | None,
    ) -> list[str]:
        discovered_files = repo_context.discovered_files_json if repo_context else []
        if not discovered_files:
            return []

        spec_text = ""
        if spec:
            spec_text = " ".join(
                [
                    spec.title or "",
                    spec.user_story or "",
                    spec.scope or "",
                    " ".join(spec.acceptance_criteria_json or []),
                ]
            )
        demand_text = f"{self._contextual_demand_text(demand)} {spec_text}".strip()
        matched_files = self._match_demand_files(demand_text, discovered_files)
        if matched_files:
            return matched_files[:16]
        return discovered_files[:8]

    def _contextual_demand_text(self, demand: DemandItem) -> str:
        payload = demand.context_payload or {}
        parts = [demand.title or "", demand.raw_input or ""]
        for item in self._historical_context_items(payload):
            if not isinstance(item, dict):
                continue
            parts.extend(
                [
                    str(item.get("title") or ""),
                    str(item.get("summary") or ""),
                ]
            )
        return "\n".join(part for part in parts if part)

    def _historical_context_count(self, payload: dict[str, Any]) -> int:
        return len(self._historical_context_items(payload))

    def _historical_context_items(self, payload: dict[str, Any]) -> list[Any]:
        items: list[Any] = []
        for key in ("historical_demands", "generated_historical_demands"):
            value = payload.get(key)
            if not isinstance(value, dict):
                continue
            raw_items = value.get("items")
            if isinstance(raw_items, list):
                items.extend(raw_items[:5])
        return items

    def _impacted_areas(self, affected_files: list[str]) -> list[str]:
        areas: list[str] = []
        for path in affected_files:
            parts = path.split("/")
            if path.startswith("frontend/src/app/") and len(parts) >= 4:
                areas.append("/".join(parts[:4]))
            elif path.startswith("backend/app/modules/") and len(parts) >= 4:
                areas.append("/".join(parts[:4]))
            elif len(parts) >= 2:
                areas.append("/".join(parts[:2]))
            elif parts:
                areas.append(parts[0])
        return self._dedupe(areas)[:12]

    def _impact_recommendations(self, repo_context: RepoContext | None) -> list[str]:
        dependency_refs = repo_context.dependency_refs_json if repo_context else []
        recommendations = [
            "Use the affected candidate files as the initial implementation scope.",
            "Keep changes inside the derived allowed paths unless a human expands scope.",
        ]
        if any(ref == "frontend/package.json:scripts.build" for ref in dependency_refs):
            recommendations.append("Run npm run build before creating a merge request.")
        if any(ref == "backend/tests" for ref in dependency_refs):
            recommendations.append("Run python -m pytest for backend changes.")
        recommendations.append("Escalate to human review if changed files exceed the analyzed scope.")
        return recommendations

    def _collect_dependency_refs(self, root: Path) -> list[str]:
        refs: list[str] = []
        package_json = root / "frontend" / "package.json"
        if package_json.is_file():
            refs.append("frontend/package.json")
            try:
                package_data = json.loads(package_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                package_data = {}
            scripts = package_data.get("scripts")
            if isinstance(scripts, dict):
                for name in sorted(scripts):
                    refs.append(f"frontend/package.json:scripts.{name}")

        pyproject = root / "backend" / "pyproject.toml"
        if pyproject.is_file():
            refs.append("backend/pyproject.toml")

        pytest_ini = root / "backend" / "pytest.ini"
        if pytest_ini.is_file():
            refs.append("backend/pytest.ini")

        tests_dir = root / "backend" / "tests"
        if tests_dir.is_dir():
            refs.append("backend/tests")

        return refs

    def _collect_git_refs(self, root: Path) -> list[str]:
        refs: list[str] = []
        branch = self._git_output(root, ["rev-parse", "--abbrev-ref", "HEAD"])
        if branch:
            refs.append(f"git.branch:{branch}")
        commit = self._git_output(root, ["rev-parse", "--short", "HEAD"])
        if commit:
            refs.append(f"git.commit:{commit}")
        return refs

    def _git_output(self, root: Path, args: list[str]) -> str | None:
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout.strip() or None

    def _confidence_score(
        self,
        *,
        discovered_files: list[str],
        source_refs: list[str],
        dependency_refs: list[str],
    ) -> float:
        score = 0.55
        if discovered_files:
            score += 0.18
        if len(discovered_files) >= 3:
            score += 0.07
        if source_refs:
            score += 0.08
        if dependency_refs:
            score += 0.07
        return min(score, 0.92)

    def _build_summary(
        self,
        *,
        root: Path,
        files: list[str],
        discovered_files: list[str],
        dependency_refs: list[str],
    ) -> str:
        top_dirs = sorted({path.split("/")[0] for path in files})[:8]
        return (
            "Local repository context was collected from the current workspace. "
            f"Workspace root: {root}. "
            f"Scanned {len(files)} candidate source and documentation files. "
            f"Top-level areas: {', '.join(top_dirs) if top_dirs else 'none'}. "
            f"Matched {len(discovered_files)} candidate files for this demand. "
            f"Dependency and check references: {', '.join(dependency_refs[:8]) if dependency_refs else 'none'}."
        )

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result
