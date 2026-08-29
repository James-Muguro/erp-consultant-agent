"""
Gemini LLM client. Raises on failure - the caller (HybridLLMClient)
is responsible for falling back to other providers. This client does
NOT implement its own fallback logic; an earlier version did, and it
had a serious bug: it silently swallowed Gemini failures and returned
fake "[DEV STUB]" text instead of raising, which meant the real,
working fallback chain in HybridLLMClient could never actually run.
"""
import logging
from typing import Optional
try:
    from google import genai
    from google.genai import types as genai_types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

from src.config.settings import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Thin wrapper around the Gemini API only. Raises on any failure -
    it does not fall back to another provider itself."""

    def __init__(self, model_key: str = "default", temperature: float = 0.7):
        self.temperature = temperature
        self.model_key = model_key

        if not (GEMINI_AVAILABLE and settings.gemini_api_key):
            raise RuntimeError("Gemini is not available: missing package or API key")

        self.gemini_client = genai.Client(api_key=settings.gemini_api_key)
        self.client_type = "gemini"
        logger.info("Using Gemini LLM")

    def generate_content(self, prompt: str, generation_config: Optional[dict] = None):
        generation_config = generation_config or {}
        temperature = generation_config.get("temperature", self.temperature)
        max_tokens = generation_config.get("max_output_tokens", settings.max_tokens)
        response_schema = generation_config.get("response_schema")

        config_kwargs = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        if response_schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = response_schema

        response = self.gemini_client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(**config_kwargs)
        )
        text = response.text or ""
        return type("LLMResponse", (), {"text": text})()