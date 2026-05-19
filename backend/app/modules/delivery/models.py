"""Delivery v2 models."""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, DB_BIGINT, DB_JSON, utc_now
from app.modules.delivery.enums import (
    CodingTaskStatus,
    DeliveryRiskLevel,
    DemandStatus,
    ExecutionLogLevel,
    ExecutionRunStatus,
    GateStatus,
    GateType,
    ImpactAnalysisStatus,
    RepoContextStatus,
    SpecStatus,
)


class DemandItem(Base):
    """Raw demand normalized into the v2 delivery workflow."""

    __tablename__ = "delivery_demand_items"

    id: Mapped[int] = mapped_column(DB_BIGINT, primary_key=True, autoincrement=True)
    raw_input: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, default="other")
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    requester_ref: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=DemandStatus.INTAKE,
    )
    risk_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    confidence_score: Mapped[Optional[float]] = mapped_column(nullable=True)
    context_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(DB_JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    spec_cards: Mapped[list["SpecCard"]] = relationship(
        "SpecCard",
        back_populates="demand",
        cascade="all, delete-orphan",
    )
    gate_checks: Mapped[list["GateCheck"]] = relationship(
        "GateCheck",
        back_populates="demand",
        cascade="all, delete-orphan",
    )
    repo_contexts: Mapped[list["RepoContext"]] = relationship(
        "RepoContext",
        back_populates="demand",
        cascade="all, delete-orphan",
    )
    impact_analyses: Mapped[list["ImpactAnalysis"]] = relationship(
        "ImpactAnalysis",
        back_populates="demand",
        cascade="all, delete-orphan",
    )
    coding_tasks: Mapped[list["CodingTask"]] = relationship(
        "CodingTask",
        back_populates="demand",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_delivery_demand_items_status", "status"),
        Index("ix_delivery_demand_items_risk_level", "risk_level"),
        Index("ix_delivery_demand_items_created_at", "created_at"),
    )


class SpecCard(Base):
    """Engineering spec generated from a demand item."""

    __tablename__ = "delivery_spec_cards"

    id: Mapped[int] = mapped_column(DB_BIGINT, primary_key=True, autoincrement=True)
    demand_id: Mapped[int] = mapped_column(
        DB_BIGINT,
        ForeignKey("delivery_demand_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default=SpecStatus.DRAFT)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    user_story: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    acceptance_criteria_json: Mapped[list[str]] = mapped_column(DB_JSON, nullable=False, default=list)
    constraints_json: Mapped[list[str]] = mapped_column(DB_JSON, nullable=False, default=list)
    risks_json: Mapped[list[str]] = mapped_column(DB_JSON, nullable=False, default=list)
    open_questions_json: Mapped[list[str]] = mapped_column(DB_JSON, nullable=False, default=list)
    created_by: Mapped[str] = mapped_column(String(50), nullable=False, default="ai")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    demand: Mapped["DemandItem"] = relationship("DemandItem", back_populates="spec_cards")
    coding_tasks: Mapped[list["CodingTask"]] = relationship("CodingTask", back_populates="spec_card")

    __table_args__ = (
        Index("ix_delivery_spec_cards_demand_id", "demand_id"),
        Index("ix_delivery_spec_cards_status", "status"),
    )


class GateCheck(Base):
    """Hard gate evaluation result."""

    __tablename__ = "delivery_gate_checks"

    id: Mapped[int] = mapped_column(DB_BIGINT, primary_key=True, autoincrement=True)
    demand_id: Mapped[int] = mapped_column(
        DB_BIGINT,
        ForeignKey("delivery_demand_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    gate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[Optional[dict[str, Any]]] = mapped_column(DB_JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    demand: Mapped["DemandItem"] = relationship("DemandItem", back_populates="gate_checks")

    __table_args__ = (
        Index("ix_delivery_gate_checks_demand_id", "demand_id"),
        Index("ix_delivery_gate_checks_gate_type", "gate_type"),
        Index("ix_delivery_gate_checks_status", "status"),
    )


class RepoContext(Base):
    """Repository and documentation context collected for a demand."""

    __tablename__ = "delivery_repo_contexts"

    id: Mapped[int] = mapped_column(DB_BIGINT, primary_key=True, autoincrement=True)
    demand_id: Mapped[int] = mapped_column(
        DB_BIGINT,
        ForeignKey("delivery_demand_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default=RepoContextStatus.READY)
    provider: Mapped[str] = mapped_column(String(100), nullable=False, default="mock")
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    source_refs_json: Mapped[list[str]] = mapped_column(DB_JSON, nullable=False, default=list)
    discovered_files_json: Mapped[list[str]] = mapped_column(DB_JSON, nullable=False, default=list)
    dependency_refs_json: Mapped[list[str]] = mapped_column(DB_JSON, nullable=False, default=list)
    confidence_score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    provider_metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(DB_JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    demand: Mapped["DemandItem"] = relationship("DemandItem", back_populates="repo_contexts")
    impact_analyses: Mapped[list["ImpactAnalysis"]] = relationship(
        "ImpactAnalysis",
        back_populates="repo_context",
    )

    __table_args__ = (
        Index("ix_delivery_repo_contexts_demand_id", "demand_id"),
        Index("ix_delivery_repo_contexts_status", "status"),
    )


class ImpactAnalysis(Base):
    """Code and delivery impact analysis for a demand."""

    __tablename__ = "delivery_impact_analyses"

    id: Mapped[int] = mapped_column(DB_BIGINT, primary_key=True, autoincrement=True)
    demand_id: Mapped[int] = mapped_column(
        DB_BIGINT,
        ForeignKey("delivery_demand_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    repo_context_id: Mapped[Optional[int]] = mapped_column(
        DB_BIGINT,
        ForeignKey("delivery_repo_contexts.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default=ImpactAnalysisStatus.READY)
    provider: Mapped[str] = mapped_column(String(100), nullable=False, default="mock")
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    impacted_areas_json: Mapped[list[str]] = mapped_column(DB_JSON, nullable=False, default=list)
    affected_files_json: Mapped[list[str]] = mapped_column(DB_JSON, nullable=False, default=list)
    recommendations_json: Mapped[list[str]] = mapped_column(DB_JSON, nullable=False, default=list)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence_score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    provider_metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(DB_JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    demand: Mapped["DemandItem"] = relationship("DemandItem", back_populates="impact_analyses")
    repo_context: Mapped[Optional["RepoContext"]] = relationship(
        "RepoContext",
        back_populates="impact_analyses",
    )

    __table_args__ = (
        Index("ix_delivery_impact_analyses_demand_id", "demand_id"),
        Index("ix_delivery_impact_analyses_repo_context_id", "repo_context_id"),
        Index("ix_delivery_impact_analyses_status", "status"),
        Index("ix_delivery_impact_analyses_risk_level", "risk_level"),
    )


class CodingTask(Base):
    """Codex-ready task package."""

    __tablename__ = "delivery_coding_tasks"

    id: Mapped[int] = mapped_column(DB_BIGINT, primary_key=True, autoincrement=True)
    demand_id: Mapped[int] = mapped_column(
        DB_BIGINT,
        ForeignKey("delivery_demand_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    spec_card_id: Mapped[int] = mapped_column(
        DB_BIGINT,
        ForeignKey("delivery_spec_cards.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default=CodingTaskStatus.DRAFT)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    task_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_paths_json: Mapped[list[str]] = mapped_column(DB_JSON, nullable=False, default=list)
    forbidden_actions_json: Mapped[list[str]] = mapped_column(DB_JSON, nullable=False, default=list)
    required_checks_json: Mapped[list[str]] = mapped_column(DB_JSON, nullable=False, default=list)
    expected_evidence_json: Mapped[list[str]] = mapped_column(DB_JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    demand: Mapped["DemandItem"] = relationship("DemandItem", back_populates="coding_tasks")
    spec_card: Mapped["SpecCard"] = relationship("SpecCard", back_populates="coding_tasks")
    execution_runs: Mapped[list["ExecutionRun"]] = relationship(
        "ExecutionRun",
        back_populates="coding_task",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_delivery_coding_tasks_demand_id", "demand_id"),
        Index("ix_delivery_coding_tasks_spec_card_id", "spec_card_id"),
        Index("ix_delivery_coding_tasks_status", "status"),
    )


class ExecutionRun(Base):
    """One executor dispatch attempt for a coding task."""

    __tablename__ = "delivery_execution_runs"

    id: Mapped[int] = mapped_column(DB_BIGINT, primary_key=True, autoincrement=True)
    coding_task_id: Mapped[int] = mapped_column(
        DB_BIGINT,
        ForeignKey("delivery_coding_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default=ExecutionRunStatus.QUEUED)
    executor_type: Mapped[str] = mapped_column(String(50), nullable=False, default="codex")
    trigger_mode: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    worktree_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    branch_name: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    commit_sha: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    result_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[Optional[dict[str, Any]]] = mapped_column(DB_JSON, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    coding_task: Mapped["CodingTask"] = relationship("CodingTask", back_populates="execution_runs")
    logs: Mapped[list["ExecutionLog"]] = relationship(
        "ExecutionLog",
        back_populates="execution_run",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_delivery_execution_runs_coding_task_id", "coding_task_id"),
        Index("ix_delivery_execution_runs_status", "status"),
        Index("ix_delivery_execution_runs_executor_type", "executor_type"),
    )


class ExecutionLog(Base):
    """Structured log event for an execution run."""

    __tablename__ = "delivery_execution_logs"

    id: Mapped[int] = mapped_column(DB_BIGINT, primary_key=True, autoincrement=True)
    execution_run_id: Mapped[int] = mapped_column(
        DB_BIGINT,
        ForeignKey("delivery_execution_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    level: Mapped[str] = mapped_column(String(50), nullable=False, default=ExecutionLogLevel.INFO)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    event_json: Mapped[Optional[dict[str, Any]]] = mapped_column(DB_JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    execution_run: Mapped["ExecutionRun"] = relationship("ExecutionRun", back_populates="logs")

    __table_args__ = (
        Index("ix_delivery_execution_logs_execution_run_id", "execution_run_id"),
        Index("ix_delivery_execution_logs_level", "level"),
    )
