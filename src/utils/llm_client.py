"""
Gemini LLM client. Raises on failure - the caller (HybridLLMClient)
is responsible for falling back to other providers. This client does
NOT implement its own fallback logic; an earlier version did, and it
had a serious bug: it silently swallowed Gemini failures and returned
fake "[DEV STUB]" text instead of raising, which meant the real,
working fallback chain in HybridLLMClient could never actually run.

The response object returned from generate_content() carries the full
set of attributes HybridLLMClient's normalizer consumes:
    .text           non-empty string on success; the client raises
                    rather than returning "" for a blocked/empty response
    .usage          normalized token usage dict (or None)
    .provider       always "gemini"
    .model          the model identifier actually used
    .finish_reason  normalized: 'stop' | 'length' | 'content_filter' | other
                    ('length' means output was truncated by max_tokens,
                     which agents should treat as a quality warning)
    .raw            the raw google-genai GenerateContentResponse

Note on naming: this class is imported in src/utils/llm.py as
`GeminiLLMClient` for clarity. Its historical name (LLMClient) predates
the hybrid wrapper. Renaming the class here would break that import, so
the name is preserved; treat this file as Gemini-specific.

Note on safety: default Gemini safety thresholds are left at their
provider defaults. For ERP content (financials, HR, procurement) these
are unlikely to trigger, but if you see content_filter finishes on
legitimate business prompts, safety_settings are the tuning knob. Do
not blanket-disable them - that's a business/compliance decision, not
an engineering one.
"""
import logging
from typing import Any, Dict, Optional

try:
    from google import genai
    from google.genai import types as genai_types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

from src.config.settings import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response normalization helpers
# ---------------------------------------------------------------------------
def _normalize_finish_reason(response: Any) -> Optional[str]:
    """Map the Gemini FinishReason enum onto a small shared vocabulary:
    'stop' | 'length' | 'content_filter' | <lowercased-raw-name> | None.

    Kept in sync with the vocabulary in src/utils/llm.py; that normalizer
    is idempotent, so returning already-normalized values here is safe.
    """
    candidates = getattr(response, "candidates", None) or []
    if candidates:
        reason = getattr(candidates[0], "finish_reason", None)
        if reason is not None:
            name = getattr(reason, "name", None) or str(reason)
            name_upper = name.upper()
            if name_upper == "STOP":
                return "stop"
            if name_upper in ("MAX_TOKENS", "MAX_OUTPUT_TOKENS"):
                return "length"
            if name_upper in (
                "SAFETY",
                "RECITATION",
                "BLOCKLIST",
                "PROHIBITED_CONTENT",
                "SPII",
                "LANGUAGE",
            ):
                return "content_filter"
            return name.lower()

    # No candidates at all: prompt-level block. The SDK exposes this on
    # prompt_feedback.block_reason rather than a candidate finish reason.
    feedback = getattr(response, "prompt_feedback", None)
    block_reason = getattr(feedback, "block_reason", None) if feedback else None
    if block_reason is not None:
        return "content_filter"
    return None


def _extract_usage(response: Any) -> Optional[dict]:
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return None
    prompt_tokens = getattr(meta, "prompt_token_count", None)
    completion_tokens = getattr(meta, "candidates_token_count", None)
    total_tokens = getattr(meta, "total_token_count", None)
    if prompt_tokens is None and completion_tokens is None and total_tokens is None:
        return None
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _safe_response_text(response: Any) -> Optional[str]:
    """Read response.text, tolerating the SDK raising ValueError when the
    response has no text parts (blocked, empty, or candidate-less). Returns
    a stripped non-empty string, or None if there is genuinely no text."""
    try:
        text = response.text
    except Exception:  # noqa: BLE001 - SDK raises on empty/blocked responses
        return None
    if text is None:
        return None
    stripped = text.strip()
    return stripped or None


class _GeminiResponse:
    """Lightweight response with the uniform attribute surface consumed by
    HybridLLMClient._normalize_gemini_response. Deliberately not the same
    class as LLMResponse in src/utils/llm.py to avoid a circular import;
    the wrapper constructs its LLMResponse from these attributes."""

    __slots__ = ("text", "usage", "provider", "model", "finish_reason", "raw")

    def __init__(
        self,
        text: str,
        usage: Optional[dict],
        model: Optional[str],
        finish_reason: Optional[str],
        raw: Any,
    ):
        self.text = text
        self.usage = usage
        self.provider = "gemini"
        self.model = model
        self.finish_reason = finish_reason
        self.raw = raw


def _validate_response_schema(response_schema: Any) -> None:
    """Response schema must be either a pydantic BaseModel subclass (the
    form used by every agent, and the form HybridLLMClient relies on for
    its OpenAI/Anthropic schema handling via response_schema.__name__) or
    a JSON-schema dict (accepted by Gemini directly but not by the other
    providers, so prefer pydantic classes at call sites)."""
    if response_schema is None:
        return
    if isinstance(response_schema, type) and hasattr(response_schema, "model_json_schema"):
        return
    if isinstance(response_schema, dict):
        return
    raise TypeError(
        "response_schema must be a pydantic BaseModel subclass or a "
        f"JSON-schema dict, got {type(response_schema).__name__}"
    )


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

    # ------------------------------------------------------------------ #
    # Non-streaming generation
    # ------------------------------------------------------------------ #
    def generate_content(
        self, prompt: str, generation_config: Optional[dict] = None
    ) -> _GeminiResponse:
        generation_config = generation_config or {}
        temperature = generation_config.get("temperature", self.temperature)
        max_tokens = generation_config.get("max_output_tokens", settings.max_tokens)
        response_schema = generation_config.get("response_schema")
        model = generation_config.get("model", settings.gemini_model)

        _validate_response_schema(response_schema)

        config_kwargs: Dict[str, Any] = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            # We only ever read candidates[0]. Pinning candidate_count to 1
            # avoids silently paying for n>1 sampling if a caller ever
            # forwards a future config that sets it.
            "candidate_count": 1,
        }
        if response_schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = response_schema

        response = self.gemini_client.models.generate_content(
            model=model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(**config_kwargs),
        )

        finish_reason = _normalize_finish_reason(response)
        usage = _extract_usage(response)
        text = _safe_response_text(response)

        if text is None:
            # Distinguish the reasons so logs make it obvious what happened.
            feedback = getattr(response, "prompt_feedback", None)
            block_reason = (
                getattr(feedback, "block_reason", None) if feedback else None
            )
            raise RuntimeError(
                "Gemini returned no text content "
                f"(finish_reason={finish_reason!r}, "
                f"prompt_block_reason={block_reason!r})"
            )

        return _GeminiResponse(
            text=text,
            usage=usage,
            model=model,
            finish_reason=finish_reason,
            raw=response,
        )

    # ------------------------------------------------------------------ #
    # Streaming generation
    # ------------------------------------------------------------------ #
    def generate_content_stream(
        self, prompt: str, generation_config: Optional[dict] = None
    ):
        """Yields text chunks as they arrive from Gemini. Plain-text only -
        no response_schema support here, since structured/schema output
        isn't a meaningful thing to stream token-by-token and nothing in
        this codebase needs it to be (only the chat endpoint's free-text
        answer synthesis uses streaming).

        If the stream produces no text at all (prompt blocked, immediate
        filter), raises RuntimeError *before* yielding anything, so the
        HybridLLMClient streaming fallback can move on to the next tier.
        A mid-stream failure is not retried or fallen back - the caller
        has already seen partial output; see the wrapper's docstring.
        """
        generation_config = generation_config or {}
        temperature = generation_config.get("temperature", self.temperature)
        max_tokens = generation_config.get("max_output_tokens", settings.max_tokens)
        model = generation_config.get("model", settings.gemini_model)

        stream = self.gemini_client.models.generate_content_stream(
            model=model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
                candidate_count=1,
            ),
        )

        yielded_any = False
        last_finish_reason: Optional[str] = None

        for chunk in stream:
            # Track the finish_reason of the last chunk that reported one.
            fr = _normalize_finish_reason(chunk)
            if fr is not None:
                last_finish_reason = fr

            # chunk.text raises on blocked/empty chunks in some SDK
            # versions; treat that as "no text in this chunk" rather than
            # letting it kill an otherwise healthy stream.
            try:
                text = chunk.text
            except Exception:  # noqa: BLE001
                text = None

            if text:
                yielded_any = True
                yield text

        if not yielded_any:
            raise RuntimeError(
                "Gemini stream produced no text "
                f"(last_finish_reason={last_finish_reason!r})"
            )

        # Log the terminal finish_reason for observability. Streaming
        # can't surface it to the caller (the generator is exhausted),
        # but it should be visible if truncation or filtering occurred.
        if last_finish_reason and last_finish_reason not in ("stop",):
            logger.warning(
                "Gemini stream ended with finish_reason=%s (model=%s)",
                last_finish_reason,
                model,
            )