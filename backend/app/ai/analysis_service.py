"""Analysis service - Mock implementation for impact assessment"""

from typing import Any


class MockAnalysisService:
    """Mock analysis service - returns fixed structured results"""

    async def analyze(self, item_raw_input: str, item_source_type: str) -> dict[str, Any]:
        """
        执行影响评估分析（Mock）

        Args:
            item_raw_input: Item 的原始输入
            item_source_type: Item 的来源类型

        Returns:
            固定结构的分析结果
        """
        # Mock 返回固定结果
        return {
            # 评分（Integer 1-5）
            "business_value_score": 5,
            "technical_impact_score": 4,

            # 风险等级（三档）
            "risk_level": "medium",

            # JSONB 字段
            "candidate_capabilities_json": [
                "审批能力",
                "通知能力"
            ],
            "candidate_modules_json": [
                "审批流程引擎",
                "消息通知中心",
                "通知模板配置"
            ],
            "similar_cases_json": [
                {
                    "case": "电商审批抄送功能",
                    "similarity": 0.85,
                    "source": "历史需求库"
                },
                {
                    "case": "OA 系统审批加签",
                    "similarity": 0.72,
                    "source": "内部案例库"
                }
            ],

            # AI 建议（枚举）
            "ai_recommendation": "do_now",

            # AI 元信息
            "confidence_score": 82.50,
            "evidence_summary": "客户多次提及审批节点支持抄送的需求，属于高频场景。涉及审批核心流程，业务价值较高。技术实现难度中等，复用现有通知模块即可。",
            "missing_information": None,
            "needs_deep_analysis": False
        }


# Global service instance
analysis_service = MockAnalysisService()
