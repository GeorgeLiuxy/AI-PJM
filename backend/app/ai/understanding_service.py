"""Understanding service - AI understanding using MockAdapter"""

from typing import Any
from app.ai.adapters.mock_adapter import MockAIAdapter


class UnderstandingService:
    """
    Understanding Service - 使用 AI 理解用户输入
    
    当前阶段使用 MockAdapter，返回固定数据。
    后续阶段可替换为真实 AI 调用。
    """
    
    def __init__(self):
        self.adapter = MockAIAdapter()
    
    async def understand(
        self,
        input_text: str,
        source_type: str,
    ) -> dict[str, Any]:
        """
        理解用户输入，返回结构化建议
        
        Args:
            input_text: 用户原始输入
            source_type: 输入来源类型
        
        Returns:
            包含 AI 建议的字典
        """
        # 调用 MockAdapter
        result = await self.adapter.understand(
            input_text=input_text,
            context={"source_type": source_type}
        )
        
        # 标准化返回格式
        return {
            "title": result.get("title", "AI 生成的标题"),
            "type": result.get("type", "improvement"),
            "priority": result.get("priority", "medium"),
            "project": result.get("project", "默认项目"),
            "modules": result.get("modules", ["模块A", "模块B"]),
            "impact_scope": result.get("impact_scope", "影响范围待评估"),
            "questions": result.get("questions", [
                "问题1：是否需要XX功能？",
                "问题2：技术实现是否可行？"
            ]),
            "similar_cases": result.get("similar_cases", [
                {
                    "title": "相似案例1",
                    "similarity": 0.85,
                    "result": "成功上线"
                },
                {
                    "title": "相似案例2",
                    "similarity": 0.72,
                    "result": "已验证"
                }
            ]),
            "recommendation": result.get("recommendation", "建议：先评估后决策"),
            "confidence_score": result.get("confidence_score", 75.50),
            "evidence_summary": result.get("evidence_summary", "基于关键词匹配"),
        }


# Global service instance
understanding_service = UnderstandingService()
