from typing import Optional, List, Any

from src.agents.base import Agent
from src.utils.logger import get_logger

# Initialize logger
logger = get_logger(__name__)

class TrainingAgent(Agent):
    """
    The Training & Documentation Agent is responsible for creating user manuals,
    training guides, and process documentation.
    """
    
    def __init__(
        self,
        tools: Optional[List[Any]] = None,
        temperature: float = 0.5,
        max_iterations: int = 5,
    ):
        super().__init__(
            name="Training & Documentation Agent",
            description="Creates user manuals, training guides, and process documentation.",
            tools=tools,
            temperature=temperature,
            max_iterations=max_iterations,
        )

    def _build_prompt(self, query: str, context: Optional[str] = None) -> str:
        """Builds the prompt for the language model"""
        prompt = super()._build_prompt(query, context)
        prompt += "\n\nPlease focus on creating clear, concise, and user-friendly documentation."
        prompt += "\nUse a variety of formats, such as text, images, and videos, to make the documentation engaging and effective."
        prompt += "\nTailor the documentation to the specific needs of the target audience."
        return prompt
