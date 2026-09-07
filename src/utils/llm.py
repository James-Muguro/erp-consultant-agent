"""
High-level LLM wrapper that returns a singleton LLM client.
Fallback chain: Gemini (primary, free) -> Groq (secondary, free) ->
OpenAI (tertiary, paid) -> Anthropic Claude (quaternary, paid). If every
configured tier fails, generate_content raises RuntimeError rather than
returning a fake successful-looking response - callers (every agent,
plus the chat endpoint) already catch exceptions from this call and
turn them into a proper structured error or a friendly fallback
message, so a real failure is never silently presented as real output.
Schema-requesting agents get best-effort JSON-schema hinting on every
tier (not decode-constrained strict mode) - if a fallback tier's JSON
doesn't perfectly validate, each agent's own heuristic parser (built
in Stage 1) is the safety net, so this degrades gracefully rather
than hard-failing.
"""
import json
from typing import Optional

from src.utils.llm_client import LLMClient as GeminiLLMClient
from openai import OpenAI
from src.config.settings import settings
from src.utils.resilience import call_with_retries, DEFAULT_RETRY_BASE_DELAY
from src.utils.logger import get_logger
import time

try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

logger = get_logger(__name__)

_LLM_INSTANCE: Optional["HybridLLMClient"] = None


class _TierFailedBeforeFirstChunk(Exception):
    """Internal sentinel: a streaming tier failed before yielding anything,
    so it's safe to move on to the next tier. Wraps the original error."""
    def __init__(self, cause):
        super().__init__(str(cause))
        self.__cause__ = cause


def _to_response(text: str, usage: Optional[dict] = None):
    return type("LLMResponse", (), {"text": text, "usage": usage})()


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
    usage = None
    if getattr(resp, "usage", None):
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
            "total_tokens": resp.usage.total_tokens,
        }
    return _to_response(text, usage)


def _openai_compatible_stream(client, model, prompt, temperature, max_tokens):
    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta


def _anthropic_usage(resp) -> Optional[dict]:
    usage = getattr(resp, "usage", None)
    if not usage:
        return None
    return {
        "prompt_tokens": usage.input_tokens,
        "completion_tokens": usage.output_tokens,
        "total_tokens": usage.input_tokens + usage.output_tokens,
    }


class HybridLLMClient:
    """Unified LLM client with a 4-tier fallback chain: Gemini, Groq,
    OpenAI, Anthropic, then a safe stub as an absolute last resort."""

    def __init__(self, temperature: float = 0.7):
        self.temperature = temperature

        # Tier 1: Gemini
        try:
            self.gemini = GeminiLLMClient(temperature=temperature)
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
            usage = _anthropic_usage(resp)
            for block in resp.content:
                if block.type == "tool_use":
                    return _to_response(json.dumps(block.input), usage)
            raise RuntimeError("Anthropic did not return a tool_use block")
        else:
            resp = self.anthropic_client.messages.create(
                model=settings.anthropic_model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(block.text for block in resp.content if block.type == "text")
            return _to_response(text, _anthropic_usage(resp))

    def _log_llm_call(self, provider: str, start_time: float, response) -> None:
        """Single structured log line per successful LLM call: which
        provider actually answered, how long it took, and token usage when
        the provider's SDK exposes it (all four do, in slightly different
        shapes - normalized to prompt/completion/total in _to_response,
        _anthropic_usage, and the Gemini client). This is deliberately a
        log line, not a new metrics store or exporter - the project's
        actual observability channel today is Render's log viewer, so that
        is what this feeds. A dedicated metrics backend (OpenTelemetry,
        etc.) is a bigger, separate decision left for if/when this needs
        querying beyond what grep-ing logs can answer."""
        duration_ms = round((time.time() - start_time) * 1000, 1)
        usage = getattr(response, "usage", None) or {}
        logger.info(
            "LLM call completed",
            provider=provider,
            duration_ms=duration_ms,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
        )

    def generate_content(self, prompt: str, generation_config: Optional[dict] = None):
        """Try each configured provider in order. Always returns an
        object with a `.text` attribute, regardless of which tier
        succeeded - every agent relies on that being consistent.

        Each tier gets up to settings.llm_retry_attempts attempts (with
        exponential backoff) before falling through to the next tier, and
        each individual attempt is bounded to settings.llm_call_timeout_seconds
        - see src/utils/resilience.py for what that timeout does and
        doesn't guarantee."""
        generation_config = generation_config or {}
        temperature = generation_config.get("temperature", self.temperature)
        max_tokens = generation_config.get("max_output_tokens", settings.max_tokens)
        response_schema = generation_config.get("response_schema")

        retry_kwargs = dict(max_attempts=settings.llm_retry_attempts, timeout=settings.llm_call_timeout_seconds)

        if self.use_gemini and self.gemini:
            start = time.time()
            try:
                resp = call_with_retries(
                    self.gemini.generate_content, prompt, generation_config=generation_config, **retry_kwargs
                )
                self._log_llm_call("gemini", start, resp)
                return resp
            except Exception as e:
                logger.warning(f"HybridLLM: Gemini generation failed after retries, trying Groq: {e}")

        if self.groq_client:
            start = time.time()
            try:
                # Groq's free tier has a much tighter per-minute token
                # budget than Gemini - cap the requested output size
                # regardless of what settings.max_tokens (Gemini-sized)
                # says, so a normal request doesn't get rejected outright.
                groq_max_tokens = min(max_tokens, 2048)
                resp = call_with_retries(
                    _openai_compatible_call, self.groq_client, settings.groq_model, prompt,
                    temperature, groq_max_tokens, response_schema, **retry_kwargs
                )
                self._log_llm_call("groq", start, resp)
                return resp
            except Exception as e:
                logger.warning(f"HybridLLM: Groq generation failed after retries, trying OpenAI: {e}")

        if self.openai_client:
            start = time.time()
            try:
                resp = call_with_retries(
                    _openai_compatible_call, self.openai_client, settings.openai_model, prompt,
                    temperature, max_tokens, response_schema, **retry_kwargs
                )
                self._log_llm_call("openai", start, resp)
                return resp
            except Exception as e:
                logger.warning(f"HybridLLM: OpenAI generation failed after retries, trying Anthropic: {e}")

        if self.anthropic_client:
            start = time.time()
            try:
                resp = call_with_retries(self._try_anthropic, prompt, max_tokens, response_schema, **retry_kwargs)
                self._log_llm_call("anthropic", start, resp)
                return resp
            except Exception as e:
                logger.error(f"HybridLLM: Anthropic generation failed after retries: {e}")

        logger.error("HybridLLM: No LLM backend succeeded")
        raise RuntimeError(
            "All configured LLM providers are currently unavailable "
            "(Gemini, Groq, OpenAI, and Anthropic all failed or are not configured)."
        )

    def _try_anthropic_stream(self, prompt, max_tokens):
        with self.anthropic_client.messages.stream(
            model=settings.anthropic_model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for text in stream.text_stream:
                yield text

    def generate_content_stream(self, prompt: str, generation_config: Optional[dict] = None):
        """Plain-text streaming generator, one tier at a time, same fallback
        order as generate_content. Important limitation: once a tier has
        started yielding chunks to the caller, a mid-stream failure on that
        tier cannot fall back to the next one - the caller has already seen
        (and likely displayed) partial output, and silently discarding it
        for a second attempt would show text disappearing and reappearing.
        So a mid-stream failure re-raises after logging; only a failure
        that happens before any chunk is yielded moves on to the next tier.
        No response_schema support - see generate_content_stream on the
        Gemini client for why."""
        generation_config = generation_config or {}
        temperature = generation_config.get("temperature", self.temperature)
        max_tokens = generation_config.get("max_output_tokens", settings.max_tokens)

        def _run(chunk_source):
            yielded_any = False
            try:
                for chunk in chunk_source:
                    yielded_any = True
                    yield chunk
            except Exception as e:
                if yielded_any:
                    logger.error(f"HybridLLM: stream failed mid-response: {e}")
                    raise
                raise _TierFailedBeforeFirstChunk(e)

        def _run_tier_with_retry(make_source, tier_label):
            """Retries a tier's stream-start (not a mid-stream failure -
            those still can't be retried transparently, see the docstring
            above) up to settings.llm_retry_attempts times with backoff,
            same as the non-streaming generate_content. make_source is a
            zero-arg callable that creates a *fresh* generator each call,
            since a generator that already raised can't be re-iterated."""
            last_exc = None
            for attempt in range(settings.llm_retry_attempts):
                try:
                    yield from _run(make_source())
                    return
                except _TierFailedBeforeFirstChunk as e:
                    last_exc = e
                    if attempt < settings.llm_retry_attempts - 1:
                        delay = DEFAULT_RETRY_BASE_DELAY * (2 ** attempt)
                        logger.warning(
                            f"HybridLLM: {tier_label} stream failed to start "
                            f"(attempt {attempt + 1}/{settings.llm_retry_attempts}): "
                            f"{e.__cause__}. Retrying in {delay:.1f}s"
                        )
                        time.sleep(delay)
            raise last_exc

        if self.use_gemini and self.gemini:
            try:
                yield from _run_tier_with_retry(
                    lambda: self.gemini.generate_content_stream(prompt, generation_config), "Gemini"
                )
                return
            except _TierFailedBeforeFirstChunk as e:
                logger.warning(f"HybridLLM: Gemini stream failed after retries, trying Groq: {e.__cause__}")

        if self.groq_client:
            try:
                groq_max_tokens = min(max_tokens, 2048)
                yield from _run_tier_with_retry(
                    lambda: _openai_compatible_stream(self.groq_client, settings.groq_model, prompt, temperature, groq_max_tokens),
                    "Groq"
                )
                return
            except _TierFailedBeforeFirstChunk as e:
                logger.warning(f"HybridLLM: Groq stream failed after retries, trying OpenAI: {e.__cause__}")

        if self.openai_client:
            try:
                yield from _run_tier_with_retry(
                    lambda: _openai_compatible_stream(self.openai_client, settings.openai_model, prompt, temperature, max_tokens),
                    "OpenAI"
                )
                return
            except _TierFailedBeforeFirstChunk as e:
                logger.warning(f"HybridLLM: OpenAI stream failed after retries, trying Anthropic: {e.__cause__}")

        if self.anthropic_client:
            try:
                yield from _run_tier_with_retry(lambda: self._try_anthropic_stream(prompt, max_tokens), "Anthropic")
                return
            except _TierFailedBeforeFirstChunk as e:
                logger.error(f"HybridLLM: Anthropic stream failed after retries: {e.__cause__}")

        logger.error("HybridLLM: No LLM backend succeeded (streaming)")
        raise RuntimeError(
            "All configured LLM providers are currently unavailable "
            "(Gemini, Groq, OpenAI, and Anthropic all failed or are not configured)."
        )


def get_llm(temperature: float = 0.7) -> HybridLLMClient:
    """Return the singleton hybrid LLM client."""
    global _LLM_INSTANCE
    if _LLM_INSTANCE is None:
        _LLM_INSTANCE = HybridLLMClient(temperature=temperature)
        logger.info("Initialized singleton Hybrid LLM instance")
    return _LLM_INSTANCE


def reload_llm(temperature: Optional[float] = None) -> HybridLLMClient:
    """Force-reload the singleton LLM instance with an optional new temperature."""
    global _LLM_INSTANCE
    _LLM_INSTANCE = HybridLLMClient(
        temperature=temperature or 0.7
    )
    logger.info("Reloaded singleton Hybrid LLM instance")
    return _LLM_INSTANCE