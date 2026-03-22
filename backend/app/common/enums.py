"""Enum definitions for the application"""

from enum import Enum


class SourceType(str, Enum):
    """Input source type enumeration"""
    CUSTOMER_FEEDBACK = "customer_feedback"
    NEW_REQUIREMENT = "new_requirement"
    MEETING_NOTE = "meeting_note"
    BUG_REPORT = "bug_report"
    TICKET = "ticket"
    OTHER = "other"


class ItemType(str, Enum):
    """Item type enumeration (for final_type and type_suggestion)"""
    IMPROVEMENT = "improvement"
    NEW_FEATURE = "new_feature"
    BUG = "bug"
    MEETING_ACTION = "meeting_action"
    QUESTION = "question"


class ItemStatus(str, Enum):
    """Item status enumeration - 按既定状态机，不含 cancelled"""
    DRAFT = "draft"
    PENDING_CONFIRM = "pending_confirm"
    CONFIRMED = "confirmed"
    ANALYZING = "analyzing"
    DECIDED = "decided"
    OUTPUT_GENERATED = "output_generated"
    DONE = "done"


class Priority(str, Enum):
    """Priority level enumeration"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AnalysisStatus(str, Enum):
    """Analysis status enumeration - reject 回到 pending，无 REJECTED 终态"""
    PENDING = "pending"
    RUNNING = "running"
    PENDING_REVIEW = "pending_review"
    CONFIRMED = "confirmed"


class AnalysisType(str, Enum):
    """Analysis type enumeration - 当前阶段固定为影响评估"""
    IMPACT_ASSESSMENT = "impact_assessment"


class RiskLevel(str, Enum):
    """Risk level enumeration - 三档，不含 critical"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Recommendation(str, Enum):
    """Recommendation enumeration"""
    DO_NOW = "do_now"
    EVALUATE_FIRST = "evaluate_first"
    PLAN_LATER = "plan_later"
    HOLD = "hold"


class OutputStatus(str, Enum):
    """Output status enumeration"""
    PENDING_CONFIRM = "pending_confirm"
    CONFIRMED = "confirmed"
    ADOPTED = "adopted"


class OutputType(str, Enum):
    """Output type enumeration - 当前阶段只支持三种"""
    PRD = "prd"
    TEST_POINTS = "test_points"
    HANDLING_ADVICE = "handling_advice"


class AdoptedTarget(str, Enum):
    """Adopted target enumeration"""
    FORMAL_PRD = "formal_prd"
    TEST_TASK = "test_task"
    IMPLEMENTATION_NOTE = "implementation_note"


class ActionType(str, Enum):
    """Action type for action logs"""
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    STATUS_CHANGED = "status_changed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    AI_SUGGESTION = "ai_suggestion"
    AI_ANALYSIS = "ai_analysis"
    ITEM_CREATED = "item_created"
    ITEM_UNDERSTOOD = "item_understood"
    ITEM_CONFIRMED = "item_confirmed"
    # Analysis actions
    ANALYSIS_CREATED = "analysis_created"
    ANALYSIS_STARTED = "analysis_started"
    ANALYSIS_COMPLETED = "analysis_completed"
    ANALYSIS_CONFIRMED = "analysis_confirmed"
    ANALYSIS_REJECTED = "analysis_rejected"
    # Item status change actions (Analysis)
    ITEM_STATUS_CHANGED_TO_ANALYZING = "item_status_changed_to_analyzing"
    ITEM_STATUS_CHANGED_TO_DECIDED = "item_status_changed_to_decided"
    # Output actions
    OUTPUT_GENERATED = "output_generated"
    OUTPUT_CONFIRMED = "output_confirmed"
    OUTPUT_ADOPTED = "output_adopted"
    # Item status change actions (Output)
    ITEM_STATUS_CHANGED_TO_OUTPUT_GENERATED = "item_status_changed_to_output_generated"
    ITEM_STATUS_CHANGED_TO_DONE = "item_status_changed_to_done"


class OperatorType(str, Enum):
    """Operator type enumeration"""
    USER = "user"
    AI = "ai"
    SYSTEM = "system"


class BizType(str, Enum):
    """Business entity type enumeration"""
    ITEM = "item"
    ANALYSIS = "analysis"
    OUTPUT = "output"


class TodoType(str, Enum):
    """Todo type enumeration for workbench"""
    PENDING_ITEM_CONFIRM = "pending_item_confirm"
    PENDING_ANALYSIS_REVIEW = "pending_analysis_review"
    PENDING_OUTPUT_CONFIRM = "pending_output_confirm"
    PENDING_OUTPUT_ADOPT = "pending_output_adopt"
