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

    def __init__(self, temperature: float = 0.7):
        self.temperature = temperature

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
        usage = None
        meta = getattr(response, "usage_metadata", None)
        if meta is not None:
            usage = {
                "prompt_tokens": meta.prompt_token_count,
                "completion_tokens": meta.candidates_token_count,
                "total_tokens": meta.total_token_count,
            }
        return type("LLMResponse", (), {"text": text, "usage": usage})()

    def generate_content_stream(self, prompt: str, generation_config: Optional[dict] = None):
        """Yields text chunks as they arrive from Gemini. Plain-text only -
        no response_schema support here, since structured/schema output
        isn't a meaningful thing to stream token-by-token and nothing in
        this codebase needs it to be (only the chat endpoint's free-text
        answer synthesis uses streaming)."""
        generation_config = generation_config or {}
        temperature = generation_config.get("temperature", self.temperature)
        max_tokens = generation_config.get("max_output_tokens", settings.max_tokens)

        stream = self.gemini_client.models.generate_content_stream(
            model=settings.gemini_model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
        )
        for chunk in stream:
            if chunk.text:
                yield chunk.text