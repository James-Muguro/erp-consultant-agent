from typing import Optional, List, Any

from src.agents.base import Agent
from src.utils.logger import get_logger

# Initialize logger
logger = get_logger(__name__)

class UATTestingAgent(Agent):
    """
    The UAT Testing Agent is responsible for creating user acceptance testing
    scenarios and test scripts.
    """
    
    def __init__(
        self,
        tools: Optional[List[Any]] = None,
        temperature: float = 0.4,
        max_iterations: int = 5,
    ):
        super().__init__(
            name="UAT Testing Agent",
            description="Creates user acceptance testing scenarios and test scripts.",
            tools=tools,
            temperature=temperature,
            max_iterations=max_iterations,
        )

    def _build_prompt(self, query: str, context: Optional[str] = None) -> str:
        """Builds the prompt for the language model"""
        prompt = super()._build_prompt(query, context)
        prompt += "\n\nPlease focus on creating realistic user acceptance testing scenarios that reflect real-world usage of the system."
        prompt += "\nInvolve end-users in the process of creating and executing the test scenarios."
        prompt += "\nProvide clear instructions and expected outcomes for each test scenario."
        return prompt
