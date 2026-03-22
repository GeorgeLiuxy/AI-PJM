"""Mock AI adapter for testing and development"""

from typing import Any
from app.ai.adapters.base import BaseAIAdapter


class MockAIAdapter(BaseAIAdapter):
    """
    Mock AI adapter that returns fixed responses.

    Used for development and testing without calling real AI APIs.
    """

    async def understand(
        self,
        input_text: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Mock understand - returns fixed analysis"""
        return {
            "title": "审批节点支持抄送并优化通知内容区分",
            "type": "improvement",
            "priority": "high",
            "project": "流程审批重构项目",
            "modules": ["审批流程引擎", "消息通知中心"],
            "impact_scope": "历史流程通知模板可能受影响",
            "questions": [
                "是否仅新流程支持，是否影响历史流程",
                "是否需要抄送人权限控制"
            ],
            "similar_cases": [
                {
                    "title": "审批抄送显示优化",
                    "similarity": 0.85,
                    "result": "成功上线"
                },
                {
                    "title": "通知模板区分改造",
                    "similarity": 0.72,
                    "result": "分两期实施"
                }
            ],
            "recommendation": "建议优先评估历史流程影响范围",
            "confidence_score": 75.50,
            "evidence_summary": "基于关键词匹配和历史案例（Mock数据）",
        }

    async def analyze(
        self,
        item_data: dict[str, Any],
        analysis_type: str = "impact",
    ) -> dict[str, Any]:
        """Mock analyze - returns fixed analysis"""
        return {
            "risk_level": "medium",
            "affected_modules": ["module_a", "module_b"],
            "business_value": "high",
            "technical_impact": "medium",
            "recommendation": "Mock: Proceed with caution",
        }

    async def generate(
        self,
        prompt: str,
        generation_type: str = "prd",
        context: dict[str, Any] | None = None,
    ) -> str:
        """Mock generate - returns fixed content"""
        return f"""# Mock Generated {generation_type.upper()}

This is a mock generated {generation_type}.

Prompt: {prompt[:100] if prompt else "No prompt"}...

## Content would go here

This is a placeholder for actual AI-generated content.
"""
