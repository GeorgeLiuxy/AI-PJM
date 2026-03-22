"""Base AI adapter interface"""

from abc import ABC, abstractmethod
from typing import Any


class BaseAIAdapter(ABC):
    """
    Abstract base class for AI adapters.

    All AI provider implementations (Anthropic, OpenAI, etc.) must inherit from this class.
    """

    @abstractmethod
    async def understand(
        self,
        input_text: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Analyze and understand input text.

        Args:
            input_text: The input text to analyze
            context: Additional context for understanding

        Returns:
            Dictionary containing understanding results:
            - type: Item type (feature, bug, etc.)
            - priority: Suggested priority
            - title: Suggested title
            - summary: Summary of the input
        """
        pass

    @abstractmethod
    async def analyze(
        self,
        item_data: dict[str, Any],
        analysis_type: str = "impact",
    ) -> dict[str, Any]:
        """
        Perform analysis on an item.

        Args:
            item_data: Item data to analyze
            analysis_type: Type of analysis (impact, risk, etc.)

        Returns:
            Dictionary containing analysis results
        """
        pass

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        generation_type: str = "prd",
        context: dict[str, Any] | None = None,
    ) -> str:
        """
        Generate output content.

        Args:
            prompt: Generation prompt
            generation_type: Type of output (prd, test_cases, etc.)
            context: Additional context for generation

        Returns:
            Generated content as string
        """
        pass
