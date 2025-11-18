
from typing import Optional, List, Any

from src.agents.base import Agent
from src.utils.logger import get_logger

# Initialize logger
logger = get_logger(__name__)

class SolutionDesignAgent(Agent):
    """
    The Solution Design Agent is responsible for designing ERP solutions based on
    requirements and best practices.
    """
    
    def __init__(
        self,
        tools: Optional[List[Any]] = None,
        temperature: float = 0.6,
        max_iterations: int = 5,
    ):
        super().__init__(
            name="Solution Design Agent",
            description="Designs ERP solutions based on requirements and best practices.",
            tools=tools,
            temperature=temperature,
            max_iterations=max_iterations,
        )

    def _build_prompt(self, query: str, context: Optional[str] = None) -> str:
        """Builds the prompt for the language model"""
        prompt = super()._build_prompt(query, context)
        prompt += "\n\nPlease focus on creating a robust and scalable solution design."
        prompt += "\nConsider the existing system landscape, integration points, and data migration requirements."
        prompt += "\nProvide a high-level architecture diagram and a detailed description of the proposed solution."
        return prompt
