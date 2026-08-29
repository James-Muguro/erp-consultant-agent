"""
High-level LLM wrapper that returns a singleton LLM client.
Fallback chain: Gemini (primary, free) -> Groq (secondary, free) ->
OpenAI (tertiary, paid) -> Anthropic Claude (quaternary, paid) -> dev
stub (absolute last resort). OpenAI and Anthropic are kept configured
but sit behind the free Groq tier, so the agent keeps running on free
providers for as long as possible before needing a funded account.
Schema-requesting agents get best-effort JSON-schema hinting on every
tier (not decode-constrained strict mode) - if a fallback tier's JSON
doesn't perfectly validate, each agent's own heuristic parser (built
in Stage 1) is the safety net, so this degrades gracefully rather
than hard-failing.
"""
import json
import logging
from typing import Optional

from src.utils.llm_client import LLMClient as GeminiLLMClient
from openai import OpenAI
from src.config.settings import settings

try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

logger = logging.getLogger(__name__)

_LLM_INSTANCE: Optional["HybridLLMClient"] = None


def _to_response(text: str):
    return type("LLMResponse", (), {"text": text})()


def _openai_compatible_call(client, model, prompt, temperature, max_tokens, response_schema):
    """Shared call shape for any OpenAI-compatible endpoint (OpenAI itself,
    or Groq, which speaks the same protocol)."""
    kwargs = dict(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if response_schema is not None:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": response_schema.__name__,
                "schema": response_schema.model_json_schema(),
            },
        }
    resp = client.chat.completions.create(**kwargs)
    text = resp.choices[0].message.content.strip()
    return _to_response(text)


class HybridLLMClient:
    """Unified LLM client with a 4-tier fallback chain: Gemini, Groq,
    OpenAI, Anthropic, then a safe stub as an absolute last resort."""

    def __init__(self, model_key: str = "default", temperature: float = 0.7):
        self.temperature = temperature
        self.model_key = model_key

        # Tier 1: Gemini
        try:
            self.gemini = GeminiLLMClient(model_key=model_key, temperature=temperature)
            self.use_gemini = True
            logger.info("HybridLLM: Gemini client initialized")
        except Exception as e:
            logger.warning(f"HybridLLM: Failed to initialize Gemini client: {e}")
            self.gemini = None
            self.use_gemini = False

        # Tier 2: Groq (free tier, OpenAI-compatible endpoint)
        self.groq_client = (
            OpenAI(api_key=settings.groq_api_key, base_url="https://api.groq.com/openai/v1")
            if settings.groq_api_key else None
        )
        if self.groq_client:
            logger.info("HybridLLM: Groq fallback client initialized")

        # Tier 3: OpenAI
        self.openai_client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        if self.openai_client:
            logger.info("HybridLLM: OpenAI fallback client initialized")

        # Tier 4: Anthropic Claude
        self.anthropic_client = None
        if ANTHROPIC_AVAILABLE and settings.anthropic_api_key:
            self.anthropic_client = Anthropic(api_key=settings.anthropic_api_key)
            logger.info("HybridLLM: Anthropic fallback client initialized")

    def _try_anthropic(self, prompt, max_tokens, response_schema):
        # Anthropic Python SDK v1.0+ removed temperature/top_p/top_k from
        # Messages.create() entirely - no sampling control available here.
        if response_schema is not None:
            tool_name = "emit_" + response_schema.__name__
            resp = self.anthropic_client.messages.create(
                model=settings.anthropic_model,
                max_tokens=max_tokens,
                tools=[{
                    "name": tool_name,
                    "description": f"Emit data matching the {response_schema.__name__} schema.",
                    "input_schema": response_schema.model_json_schema(),
                }],
                tool_choice={"type": "tool", "name": tool_name},
                messages=[{"role": "user", "content": prompt}],
            )
            for block in resp.content:
                if block.type == "tool_use":
                    return _to_response(json.dumps(block.input))
            raise RuntimeError("Anthropic did not return a tool_use block")
        else:
            resp = self.anthropic_client.messages.create(
                model=settings.anthropic_model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(block.text for block in resp.content if block.type == "text")
            return _to_response(text)

    def generate_content(self, prompt: str, generation_config: Optional[dict] = None):
        """Try each configured provider in order. Always returns an
        object with a `.text` attribute, regardless of which tier
        succeeded - every agent relies on that being consistent."""
        generation_config = generation_config or {}
        temperature = generation_config.get("temperature", self.temperature)
        max_tokens = generation_config.get("max_output_tokens", settings.max_tokens)
        response_schema = generation_config.get("response_schema")

        if self.use_gemini and self.gemini:
            try:
                return self.gemini.generate_content(prompt, generation_config=generation_config)
            except Exception as e:
                logger.warning(f"HybridLLM: Gemini generation failed, trying Groq: {e}")

        if self.groq_client:
            try:
                return _openai_compatible_call(self.groq_client, settings.groq_model, prompt, temperature, max_tokens, response_schema)
            except Exception as e:
                logger.warning(f"HybridLLM: Groq generation failed, trying OpenAI: {e}")

        if self.openai_client:
            try:
                return _openai_compatible_call(self.openai_client, settings.openai_model, prompt, temperature, max_tokens, response_schema)
            except Exception as e:
                logger.warning(f"HybridLLM: OpenAI generation failed, trying Anthropic: {e}")

        if self.anthropic_client:
            try:
                return self._try_anthropic(prompt, max_tokens, response_schema)
            except Exception as e:
                logger.error(f"HybridLLM: Anthropic generation failed: {e}")

        logger.error("HybridLLM: No LLM backend succeeded")
        return _to_response("Error generating response: LLM unavailable")


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