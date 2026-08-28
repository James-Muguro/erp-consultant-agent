"""
Hybrid LLM Client supporting Gemini (primary) and OpenAI (fallback).
Provides a unified interface for agents and orchestrator.
"""

import os
import logging
from typing import Optional

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

from src.config.settings import settings

logger = logging.getLogger(__name__)

class LLMClient:
    """
    Hybrid LLM client that uses Gemini as primary and OpenAI as fallback.
    """

    def __init__(self, model_key: str = "default", temperature: float = 0.7):
        self.temperature = temperature
        self.model_key = model_key

        # Determine which LLM to use
        self.client_type = None
        if GEMINI_AVAILABLE and settings.gemini_api_key:
            genai.configure(api_key=settings.gemini_api_key)
            self.client_type = "gemini"
            logger.info("Using Gemini LLM")
        elif OPENAI_AVAILABLE and os.getenv("OPENAI_API_KEY"):
            openai.api_key = os.getenv("OPENAI_API_KEY")
            self.client_type = "openai"
            logger.info("Using OpenAI LLM fallback")
        else:
            self.client_type = "stub"
            logger.warning("No LLM available, using dev stub")

    def generate_content(self, prompt: str, generation_config: Optional[dict] = None):
        """
        Generate content using the chosen LLM.
        Args:
            prompt: The prompt to send to the model
            generation_config: Dict of parameters (temperature, max_output_tokens)
        Returns:
            response object with `.text` attribute
        """
        generation_config = generation_config or {}
        temperature = generation_config.get("temperature", self.temperature)
        max_tokens = generation_config.get("max_output_tokens", settings.max_tokens)

        if self.client_type == "gemini":
            try:
                response = genai.generate_text(
                    model=settings.gemini_model,
                    prompt=prompt,
                    temperature=temperature,
                    max_output_tokens=max_tokens
                )
                # Gemini returns a dict with 'candidates' list
                text = response.candidates[0].output if response.candidates else ""
                return type("LLMResponse", (), {"text": text})()
            except Exception as e:
                logger.error(f"Gemini API failed: {e}")
                # Fallback to OpenAI if available
                if OPENAI_AVAILABLE and os.getenv("OPENAI_API_KEY"):
                    self.client_type = "openai"
                    return self.generate_content(prompt, generation_config)
                else:
                    return type("LLMResponse", (), {"text": "[DEV STUB] " + prompt})()

        elif self.client_type == "openai":
            try:
                resp = openai.Completion.create(
                    model="text-davinci-003",
                    prompt=prompt,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                text = resp.choices[0].text.strip()
                return type("LLMResponse", (), {"text": text})()
            except Exception as e:
                logger.error(f"OpenAI API failed: {e}")
                return type("LLMResponse", (), {"text": "[DEV STUB] " + prompt})()

        else:
            # Dev stub
            return type("LLMResponse", (), {"text": "[DEV STUB] " + prompt})()

