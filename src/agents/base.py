from typing import List, Any, Optional
from termcolor import cprint

from src.utils.llm import get_llm
from src.config.settings import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

class Agent:
    """Base class for all agents using hybrid LLMs (Gemini primary, GPT-4 fallback)"""

    def __init__(
        self,
        name: str,
        description: str,
        tools: Optional[List[Any]] = None,
        temperature: float = 0.7,
        max_iterations: int = 5,
    ):
        self.name = name
        self.description = description
        self.tools = tools or []
        self.temperature = temperature
        self.max_iterations = max_iterations

        # Use hybrid LLM manager singleton
        self.model = get_llm()

    async def run(self, query: str, context: Optional[str] = None) -> str:
        """Main entry point for the agent"""
        cprint(f"Agent '{self.name}' received query: '{query}'", "blue")

        prompt = self._build_prompt(query, context)

        generation_config = {
            "temperature": self.temperature,
            "max_output_tokens": settings.max_tokens,
        }

        # Try generating content with hybrid LLM
        try:
            response = self.model.generate_content(prompt, generation_config=generation_config)
        except Exception as e:
            logger.error(f"Error in LLM generate_content: {e}")
            response = "I'm sorry, I couldn't generate a response at this time."

        return response

    def _build_prompt(self, query: str, context: Optional[str] = None) -> str:
        """Build prompt for LLM"""
        prompt = f"You are {self.name}, {self.description}.\n\n"
        if context:
            prompt += f"Relevant context:\n{context}\n\n"
        prompt += f"User query: {query}\n\nPlease provide a detailed and helpful response."
        return prompt
