"""
High-level LLM wrapper that returns a singleton LLM client.
This version implements a hybrid approach: Gemini primary, GPT-4 fallback.
"""
from typing import Optional
import logging
from src.utils.llm_client import LLMClient as GeminiLLMClient
from openai import OpenAI
from src.config.settings import settings

logger = logging.getLogger(__name__)

_LLM_INSTANCE: Optional["HybridLLMClient"] = None

class HybridLLMClient:
    """Unified LLM client that tries Gemini first, then GPT-4 fallback."""

    def __init__(self, model_key: str = "default", temperature: float = 0.7):
        self.temperature = temperature
        self.model_key = model_key

        # Initialize Gemini client
        try:
            self.gemini = GeminiLLMClient(model_key=model_key, temperature=temperature)
            self.use_gemini = True
            logger.info("HybridLLM: Gemini client initialized")
        except Exception as e:
            logger.warning(f"HybridLLM: Failed to initialize Gemini client: {e}")
            self.gemini = None
            self.use_gemini = False

        # Initialize GPT-4 fallback (OpenAI) - only if a key is actually configured
        self.gpt_model = "gpt-4"
        self.openai_client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    def generate_content(self, prompt: str, generation_config: Optional[dict] = None):
        """Generate content using Gemini if available, otherwise GPT-4.
        Always returns an object with a `.text` attribute, regardless of
        which path was used - every agent relies on that being consistent."""
        generation_config = generation_config or {}
        temperature = generation_config.get("temperature", self.temperature)
        max_tokens = generation_config.get("max_output_tokens", settings.max_tokens)

        # Try Gemini first
        if self.use_gemini and self.gemini:
            try:
                return self.gemini.generate_content(prompt, generation_config=generation_config)
            except Exception as e:
                logger.warning(f"HybridLLM: Gemini generation failed, falling back to GPT-4: {e}")

        # GPT-4 fallback
        if self.openai_client:
            try:
                response = self.openai_client.chat.completions.create(
                    model=self.gpt_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                text = response.choices[0].message.content.strip()
                return type("LLMResponse", (), {"text": text})()
            except Exception as e:
                logger.error(f"HybridLLM: GPT-4 generation failed: {e}")

        logger.error("HybridLLM: No LLM backend succeeded")
        return type("LLMResponse", (), {"text": "Error generating response: LLM unavailable"})()

def get_llm(model_key: str = "default", temperature: float = 0.7) -> HybridLLMClient:
    """Return the singleton hybrid LLM client."""
    global _LLM_INSTANCE
    if _LLM_INSTANCE is None:
        _LLM_INSTANCE = HybridLLMClient(model_key=model_key, temperature=temperature)
        logger.info("Initialized singleton Hybrid LLM instance")
    return _LLM_INSTANCE

def reload_llm(model_key: Optional[str] = None, temperature: Optional[float] = None) -> HybridLLMClient:
    """Force-reload the singleton LLM instance with optional new settings."""
    global _LLM_INSTANCE
    _LLM_INSTANCE = HybridLLMClient(
        model_key=model_key or "default",
        temperature=temperature or 0.7
    )
    logger.info("Reloaded singleton Hybrid LLM instance")
    return _LLM_INSTANCE
