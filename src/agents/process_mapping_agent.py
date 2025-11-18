
from typing import Optional, List, Any

from src.agents.base import Agent
from src.utils.logger import get_logger

# Initialize logger
logger = get_logger(__name__)

class ProcessMappingAgent(Agent):
    """
    The Process Mapping Agent is responsible for creating detailed business
    process maps and workflow diagrams.
    """
    
    def __init__(
        self,
        tools: Optional[List[Any]] = None,
        temperature: float = 0.4,
        max_iterations: int = 5,
    ):
        super().__init__(
            name="Process Mapping Agent",
            description="Creates detailed business process maps and workflow diagrams.",
            tools=tools,
            temperature=temperature,
            max_iterations=max_iterations,
        )

    def _build_prompt(self, query: str, context: Optional[str] = None) -> str:
        """Builds the prompt for the language model"""
        prompt = super()._build_prompt(query, context)
        prompt += "\n\nPlease focus on creating a clear and accurate representation of the business process."
        prompt += "\nIdentify the key steps, decision points, and actors involved in the process."
        prompt += "\nUse standard flowchart symbols and notations to create the process map."
        return prompt
