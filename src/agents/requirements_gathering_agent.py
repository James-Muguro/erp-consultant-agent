
from typing import Optional, List, Any

from src.agents.base import Agent
from src.utils.logger import get_logger

# Initialize logger
logger = get_logger(__name__)

class RequirementsGatheringAgent(Agent):
    """
    The Requirements Gathering Agent is responsible for analyzing stakeholder inputs
    and generating comprehensive requirement documents.
    """
    
    def __init__(
        self,
        tools: Optional[List[Any]] = None,
        temperature: float = 0.5,
        max_iterations: int = 5,
    ):
        super().__init__(
            name="Requirements Gathering Agent",
            description="Analyzes stakeholder inputs and generates comprehensive requirement documents.",
            tools=tools,
            temperature=temperature,
            max_iterations=max_iterations,
        )

    def _build_prompt(self, query: str, context: Optional[str] = None) -> str:
        """Builds the prompt for the language model"""
        prompt = super()._build_prompt(query, context)
        prompt += "\n\nPlease focus on extracting clear, concise, and unambiguous requirements from the user's query."
        prompt += "\nIdentify the key stakeholders, their needs, and the desired outcomes."
        prompt += "\nOrganize the requirements into functional and non-functional categories."
        return prompt
