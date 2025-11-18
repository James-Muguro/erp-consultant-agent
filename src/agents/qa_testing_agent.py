from typing import Optional, List, Any

from src.agents.base import Agent
from src.utils.logger import get_logger

# Initialize logger
logger = get_logger(__name__)

class QATestingAgent(Agent):
    """
    The QA Testing Agent is responsible for generating comprehensive QA test
    cases and test scripts.
    """
    
    def __init__(
        self,
        tools: Optional[List[Any]] = None,
        temperature: float = 0.3,
        max_iterations: int = 5,
    ):
        super().__init__(
            name="QA Testing Agent",
            description="Generates comprehensive QA test cases and test scripts.",
            tools=tools,
            temperature=temperature,
            max_iterations=max_iterations,
        )

    def _build_prompt(self, query: str, context: Optional[str] = None) -> str:
        """Builds the prompt for the language model"""
        prompt = super()._build_prompt(query, context)
        prompt += "\n\nPlease focus on creating a comprehensive set of test cases that cover all functional and non-functional requirements."
        prompt += "\nInclude positive and negative test scenarios, as well as edge cases."
        prompt += "\nProvide detailed test steps, expected results, and acceptance criteria for each test case."
        return prompt
