"""
High-level LLM wrapper that returns a singleton LLM client.

Fallback chain: Gemini (primary, free) -> Groq (secondary, free) ->
OpenAI (tertiary, paid) -> Anthropic Claude (quaternary, paid). If every
configured tier fails, generate_content raises RuntimeError rather than
returning a fake successful-looking response - callers (every agent,
plus the chat endpoint) already catch exceptions from this call and
turn them into a proper structured error or a friendly fallback
message, so a real failure is never silently presented as real output.

Provider model identifiers are controlled exclusively through
environment-backed settings:
    Gemini    -> settings.gemini_model
    Groq      -> settings.groq_model
    OpenAI    -> settings.openai_model
    Anthropic -> settings.anthropic_model
A provider is considered configured only when BOTH its API credential and
its model setting are present. A missing model disables that tier rather
than sending an invalid request; task profiles are not consulted for
model identifiers (they no longer carry any).

Schema-requesting agents get best-effort JSON-schema hinting on every
tier (not decode-constrained strict mode everywhere) - if a fallback
tier's JSON doesn't perfectly validate, each agent's own heuristic
parser is the safety net, so this degrades gracefully rather than
hard-failing.

Every successful call returns an LLMResponse with a uniform surface:
    .text          model text output (empty string if provider returned
                   no content; never None)
    .usage         normalized token usage dict (or None)
    .provider      which tier answered ('gemini'|'groq'|'openai'|'anthropic')
    .model         model identifier used for the successful call
    .finish_reason normalized stop reason; 'length' means the model was
                   truncated by max_tokens. Agents should consult this
                   (rather than inferring truncation from brace balance
                   alone) to decide whether output can be trusted.
    .raw           provider-native response object, for callers that
                   need to dig into provider-specifics.
"""
import functools
import json
import time
from typing import Any, Dict, Iterator, Optional

from src.utils.llm_client import LLMClient as GeminiLLMClient
from openai import OpenAI
from src.config.settings import settings
from src.utils.resilience import call_with_retries, DEFAULT_RETRY_BASE_DELAY
from src.utils.logger import get_logger

try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

logger = get_logger(__name__)

_LLM_INSTANCE: Optional["HybridLLMClient"] = None

# Groq caps output tokens far lower than Gemini/OpenAI on most models.
# Passing a larger max_tokens returns a 400 and burns a fallback tier;
# clamp conservatively. If you deploy a Groq model with a higher cap,
# raise this constant rather than removing the clamp.
_GROQ_MAX_OUTPUT_TOKENS_CAP = 8192


class _TierFailedBeforeFirstChunk(Exception):
    """Internal sentinel: a streaming tier failed before yielding anything,
    so it's safe to move on to the next tier. Wraps the original error."""
    def __init__(self, cause):
        super().__init__(str(cause))
        self.__cause__ = cause


class LLMResponse:
    """Uniform response object across all four providers.

    Never `None` text — an empty string means the provider returned no
    content (filtered, refused, or otherwise empty). Callers can check
    `.finish_reason == 'length'` to detect truncation reliably.
    """
    __slots__ = ("text", "usage", "provider", "model", "finish_reason", "raw")

    def __init__(
        self,
        text: Optional[str],
        usage: Optional[dict] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        finish_reason: Optional[str] = None,
        raw: Any = None,
    ):
        self.text = text if text is not None else ""
        self.usage = usage
        self.provider = provider
        self.model = model
        self.finish_reason = finish_reason
        self.raw = raw


def _to_response(text: str, usage: Optional[dict] = None):
    """Kept for backward compatibility. Prefer constructing LLMResponse
    directly so provider/model/finish_reason are populated."""
    return LLMResponse(text=text, usage=usage)


def _normalize_finish_reason(reason: Optional[str]) -> Optional[str]:
    """Map provider-specific stop reasons onto a small common vocabulary:
    'stop', 'length', 'content_filter', or the raw lowercase string."""
    if reason is None:
        return None
    r = str(reason).lower()
    if r in ("length", "max_tokens", "max_output_tokens"):
        return "length"
    if r in ("stop", "end_turn", "stop_sequence", "tool_use", "tool_calls"):
        return "stop"
    if "content_filter" in r or "safety" in r or "blocked" in r:
        return "content_filter"
    return r


def _is_configured_model(value: Optional[str]) -> bool:
    """True when `value` is a non-empty string. Used to double-check, at
    call time, that a provider still has a model configured before we
    send a request. A tier whose model went missing after construction
    is skipped cleanly rather than sending an invalid model to the
    provider (which would surface as an opaque 400 and burn the tier)."""
    return isinstance(value, str) and bool(value.strip())


def _openai_compatible_call(
    client,
    model,
    prompt,
    temperature,
    max_tokens,
    response_schema,
    *,
    provider: str = "openai",
):
    """Shared call shape for any OpenAI-compatible endpoint (OpenAI itself,
    or Groq, which speaks the same protocol).

    Groq and OpenAI disagree on structured-output format:
      - OpenAI: response_format={"type": "json_schema", "json_schema": {...}}
      - Groq:   response_format={"type": "json_object"} plus the schema
                supplied as a prompt instruction, and the literal token
                "JSON" must appear in the prompt.
    Passing OpenAI's shape to Groq returns a 400 and burns a fallback
    tier, so this differentiates by provider.
    """
    kwargs: Dict[str, Any] = dict(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if response_schema is not None:
        schema_json = response_schema.model_json_schema()
        if provider == "groq":
            kwargs["messages"] = [{
                "role": "user",
                "content": (
                    prompt
                    + "\n\nRespond with a single JSON object conforming to "
                      "the JSON schema below. Return JSON only, with no "
                      "surrounding text or markdown:\n"
                    + json.dumps(schema_json)
                ),
            }]
            kwargs["response_format"] = {"type": "json_object"}
        else:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": response_schema.__name__,
                    "schema": schema_json,
                },
            }
    resp = client.chat.completions.create(**kwargs)
    return _openai_response_to_llm_response(resp, provider=provider, model=model)


def _openai_response_to_llm_response(resp, *, provider: str, model: str) -> LLMResponse:
    choice = resp.choices[0] if getattr(resp, "choices", None) else None
    msg = getattr(choice, "message", None) if choice else None
    raw_text = getattr(msg, "content", None) if msg else None
    finish_reason = getattr(choice, "finish_reason", None) if choice else None

    # `content` is None when the model emits only a tool call, or when a
    # content filter blocks the completion. The original code called
    # `.strip()` on it unconditionally, which raised AttributeError and
    # was logged as a provider outage rather than the real cause.
    if raw_text is None:
        raise RuntimeError(
            f"{provider} returned no message content "
            f"(finish_reason={finish_reason!r}); treating as provider failure"
        )

    usage = None
    u = getattr(resp, "usage", None)
    if u is not None:
        usage = {
            "prompt_tokens": getattr(u, "prompt_tokens", None),
            "completion_tokens": getattr(u, "completion_tokens", None),
            "total_tokens": getattr(u, "total_tokens", None),
        }

    return LLMResponse(
        text=raw_text.strip(),
        usage=usage,
        provider=provider,
        model=model,
        finish_reason=_normalize_finish_reason(finish_reason),
        raw=resp,
    )


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
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    if input_tokens is None or output_tokens is None:
        return None
    return {
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


class HybridLLMClient:
    """Unified LLM client with a 4-tier fallback chain: Gemini, Groq,
    OpenAI, Anthropic. Raises RuntimeError if all tiers fail or are
    unconfigured.

    A tier is configured only when BOTH its API credential and its
    environment-driven model setting are present."""

    def __init__(self, temperature: float = 0.7):
        self.temperature = temperature

        # Tier 1: Gemini (configured only when API key + model are set)
        if settings.gemini_api_key and settings.gemini_model:
            try:
                self.gemini = GeminiLLMClient(temperature=temperature)
                self.use_gemini = True
                logger.info("HybridLLM: Gemini client initialized")
            except Exception as e:
                logger.warning(f"HybridLLM: Failed to initialize Gemini client: {e}")
                self.gemini = None
                self.use_gemini = False
        else:
            self.gemini = None
            self.use_gemini = False

        # Tier 2: Groq (free tier, OpenAI-compatible endpoint)
        self.groq_client = (
            OpenAI(api_key=settings.groq_api_key, base_url="https://api.groq.com/openai/v1")
            if (settings.groq_api_key and settings.groq_model) else None
        )
        if self.groq_client:
            logger.info("HybridLLM: Groq fallback client initialized")

        # Tier 3: OpenAI
        self.openai_client = (
            OpenAI(api_key=settings.openai_api_key)
            if (settings.openai_api_key and settings.openai_model) else None
        )
        if self.openai_client:
            logger.info("HybridLLM: OpenAI fallback client initialized")

        # Tier 4: Anthropic Claude
        self.anthropic_client = None
        if ANTHROPIC_AVAILABLE and settings.anthropic_api_key and settings.anthropic_model:
            self.anthropic_client = Anthropic(api_key=settings.anthropic_api_key)
            logger.info("HybridLLM: Anthropic fallback client initialized")

    # ------------------------------------------------------------------ #
    # Anthropic (schema via tool use, text via plain messages)
    # ------------------------------------------------------------------ #
    def _try_anthropic(self, prompt, max_tokens, response_schema, model=None):
        # Anthropic Python SDK v1.0+ removed temperature/top_p/top_k from
        # Messages.create() entirely - no sampling control available here.
        #
        # Model resolution: the caller-supplied `model` argument is
        # honored when it is a non-empty string; otherwise we fall back
        # to settings.anthropic_model. Neither path is hardcoded. If no
        # model is available, we refuse to send an invalid request rather
        # than let Anthropic reject it with an opaque error.
        resolved_model = model if _is_configured_model(model) else settings.anthropic_model
        if not _is_configured_model(resolved_model):
            raise RuntimeError(
                "Anthropic model is not configured. Set ANTHROPIC_MODEL "
                "(exposed as settings.anthropic_model)."
            )

        if response_schema is not None:
            tool_name = "emit_" + response_schema.__name__
            resp = self.anthropic_client.messages.create(
                model=resolved_model,
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
            finish = _normalize_finish_reason(getattr(resp, "stop_reason", None))
            for block in resp.content:
                if getattr(block, "type", None) == "tool_use":
                    return LLMResponse(
                        text=json.dumps(block.input),
                        usage=usage,
                        provider="anthropic",
                        model=resolved_model,
                        finish_reason=finish,
                        raw=resp,
                    )
            # No tool_use block usually means the model declined, or the
            # stop reason was max_tokens before it could emit the tool call.
            raise RuntimeError(
                f"Anthropic returned no tool_use block "
                f"(stop_reason={getattr(resp, 'stop_reason', None)!r})"
            )

        resp = self.anthropic_client.messages.create(
            model=resolved_model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )
        return LLMResponse(
            text=text,
            usage=_anthropic_usage(resp),
            provider="anthropic",
            model=resolved_model,
            finish_reason=_normalize_finish_reason(getattr(resp, "stop_reason", None)),
            raw=resp,
        )

    # ------------------------------------------------------------------ #
    # Normalization of Gemini responses (client returns provider-shaped
    # objects; agents expect LLMResponse).
    # ------------------------------------------------------------------ #
    @staticmethod
    def _normalize_gemini_response(resp, gemini_config: Dict[str, Any]) -> LLMResponse:
        if isinstance(resp, LLMResponse):
            if resp.provider is None:
                resp.provider = "gemini"
            if resp.model is None:
                resp.model = gemini_config.get("model")
            return resp
        return LLMResponse(
            text=getattr(resp, "text", "") or "",
            usage=getattr(resp, "usage", None),
            provider="gemini",
            model=gemini_config.get("model"),
            finish_reason=_normalize_finish_reason(
                getattr(resp, "finish_reason", None)
            ),
            raw=resp,
        )

    # ------------------------------------------------------------------ #
    # Structured logging
    # ------------------------------------------------------------------ #
    def _log_llm_call(self, provider: str, start_time: float, response: LLMResponse) -> None:
        """One structured log line per successful LLM call: which provider
        actually answered, which model, how long it took, token usage when
        the provider exposes it, and the normalized stop reason. 'length'
        is escalated to a warning because it means the model's output was
        truncated by max_tokens - a silent quality failure that callers
        should catch and act on."""
        duration_ms = round((time.time() - start_time) * 1000, 1)
        usage = getattr(response, "usage", None) or {}
        finish = getattr(response, "finish_reason", None)
        logger.info(
            "LLM call completed",
            provider=provider,
            model=getattr(response, "model", None),
            finish_reason=finish,
            duration_ms=duration_ms,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
        )
        if finish == "length":
            logger.warning(
                "LLM output truncated by max_tokens",
                provider=provider,
                model=getattr(response, "model", None),
            )

    # ------------------------------------------------------------------ #
    # Structured logging
    # ------------------------------------------------------------------ #
    def _log_llm_call(self, provider: str, start_time: float, response: LLMResponse) -> None:
        """One structured log line per successful LLM call: which provider
        actually answered, which model, how long it took, token usage when
        the provider exposes it, and the normalized stop reason. 'length'
        is escalated to a warning because it means the model's output was
        truncated by max_tokens - a silent quality failure that callers
        should catch and act on."""
        duration_ms = round((time.time() - start_time) * 1000, 1)
        usage = getattr(response, "usage", None) or {}
        finish = getattr(response, "finish_reason", None)
        logger.info(
            "LLM call completed",
            provider=provider,
            model=getattr(response, "model", None),
            finish_reason=finish,
            duration_ms=duration_ms,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
        )
        if finish == "length":
            logger.warning(
                "LLM output truncated by max_tokens",
                provider=provider,
                model=getattr(response, "model", None),
            )

    @staticmethod
    def _looks_truncated_json(text: str) -> bool:
        """Cheap brace-balance check for JSON-like output. Returns True if
        braces or brackets are unbalanced outside string literals — the
        classic truncation signature. Non-JSON prose returns False; the
        caller's schema validation is the ultimate arbiter there.

        This duplicates the same-named helper on the agent classes; the two
        are kept in sync deliberately, since the wrapper uses it for a
        pre-emptive truncation warning and the agents use it in their own
        repair pipelines."""
        s = text.strip()
        if not s.startswith("{"):
            return False
        depth = 0
        in_str = False
        esc = False
        for ch in s:
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch in "{[":
                depth += 1
            elif ch in "}]":
                depth -= 1
        return depth != 0

    # ------------------------------------------------------------------ #
    # Public: non-streaming generation
    # ------------------------------------------------------------------ #
    def generate_content(
        self, prompt: str, generation_config: Optional[dict] = None
    ) -> LLMResponse:
        """Try each configured provider in order. Always returns an
        LLMResponse with `.text` populated, regardless of which tier
        succeeded - every agent relies on that being consistent.

        Each tier gets up to settings.llm_retry_attempts attempts (with
        exponential backoff) before falling through to the next tier, and
        each individual attempt is bounded to settings.llm_call_timeout_seconds
        - see src/utils/resilience.py for what that timeout does and
        doesn't guarantee.

        Provider model identifiers come only from environment-backed
        settings (settings.<provider>_model); task profiles do not override
        them. A tier whose model setting has gone missing is skipped
        cleanly rather than sending an invalid model to the provider."""
        generation_config = generation_config or {}
        temperature = generation_config.get("temperature", self.temperature)
        max_tokens = generation_config.get("max_output_tokens", settings.max_tokens)
        response_schema = generation_config.get("response_schema")

        retry_kwargs = dict(
            max_attempts=settings.llm_retry_attempts,
            timeout=settings.llm_call_timeout_seconds,
        )

        # -------- Tier 1: Gemini --------
        if self.use_gemini and self.gemini:
            gemini_model = settings.gemini_model
            if not _is_configured_model(gemini_model):
                logger.warning(
                    "HybridLLM: Gemini model is not configured; skipping "
                    "Gemini tier."
                )
            else:
                start = time.time()
                try:
                    gemini_config = dict(generation_config)
                    # `task` is a routing hint for this wrapper, not a Gemini
                    # SDK parameter. The model is always the environment-driven
                    # settings.gemini_model.
                    gemini_config.pop("task", None)
                    gemini_config["model"] = gemini_model
                    resp = call_with_retries(
                        self.gemini.generate_content,
                        prompt,
                        generation_config=gemini_config,
                        **retry_kwargs,
                    )
                    normalized = self._normalize_gemini_response(resp, gemini_config)
                    self._log_llm_call("gemini", start, normalized)
                    return normalized
                except Exception as e:
                    logger.warning(
                        f"HybridLLM: Gemini generation failed after retries, "
                        f"trying Groq: {e}"
                    )

        # -------- Tier 2: Groq --------
        if self.groq_client:
            groq_model = settings.groq_model
            if not _is_configured_model(groq_model):
                logger.warning(
                    "HybridLLM: Groq model is not configured; skipping "
                    "Groq tier."
                )
            else:
                start = time.time()
                try:
                    # Groq caps output far lower than Gemini/OpenAI. Clamp
                    # rather than let the request 400 and burn the tier.
                    groq_max_tokens = min(max_tokens, _GROQ_MAX_OUTPUT_TOKENS_CAP)
                    groq_call = functools.partial(
                        _openai_compatible_call, provider="groq"
                    )
                    resp = call_with_retries(
                        groq_call,
                        self.groq_client,
                        groq_model,
                        prompt,
                        temperature,
                        groq_max_tokens,
                        response_schema,
                        **retry_kwargs,
                    )
                    self._log_llm_call("groq", start, resp)
                    return resp
                except Exception as e:
                    logger.warning(
                        f"HybridLLM: Groq generation failed after retries, "
                        f"trying OpenAI: {e}"
                    )

        # -------- Tier 3: OpenAI --------
        if self.openai_client:
            openai_model = settings.openai_model
            if not _is_configured_model(openai_model):
                logger.warning(
                    "HybridLLM: OpenAI model is not configured; skipping "
                    "OpenAI tier."
                )
            else:
                start = time.time()
                try:
                    openai_call = functools.partial(
                        _openai_compatible_call, provider="openai"
                    )
                    resp = call_with_retries(
                        openai_call,
                        self.openai_client,
                        openai_model,
                        prompt,
                        temperature,
                        max_tokens,
                        response_schema,
                        **retry_kwargs,
                    )
                    self._log_llm_call("openai", start, resp)
                    return resp
                except Exception as e:
                    logger.warning(
                        f"HybridLLM: OpenAI generation failed after retries, "
                        f"trying Anthropic: {e}"
                    )

        # -------- Tier 4: Anthropic --------
        if self.anthropic_client:
            anthropic_model = settings.anthropic_model
            if not _is_configured_model(anthropic_model):
                logger.warning(
                    "HybridLLM: Anthropic model is not configured; skipping "
                    "Anthropic tier."
                )
            else:
                start = time.time()
                try:
                    resp = call_with_retries(
                        self._try_anthropic,
                        prompt,
                        max_tokens,
                        response_schema,
                        anthropic_model,
                        **retry_kwargs,
                    )
                    self._log_llm_call("anthropic", start, resp)
                    return resp
                except Exception as e:
                    logger.error(
                        f"HybridLLM: Anthropic generation failed after retries: {e}"
                    )

        logger.error("HybridLLM: No LLM backend succeeded")
        raise RuntimeError(
            "All configured LLM providers are currently unavailable "
            "(Gemini, Groq, OpenAI, and Anthropic all failed or are not configured)."
        )

    # ------------------------------------------------------------------ #
    # Streaming
    # ------------------------------------------------------------------ #
    def _try_anthropic_stream(self, prompt, max_tokens, model=None):
        # Same model resolution order as _try_anthropic: honor the
        # caller-supplied model when it's a usable non-empty string,
        # otherwise fall back to settings.anthropic_model. Never
        # hardcoded.
        resolved_model = model if _is_configured_model(model) else settings.anthropic_model
        if not _is_configured_model(resolved_model):
            raise RuntimeError(
                "Anthropic model is not configured. Set ANTHROPIC_MODEL "
                "(exposed as settings.anthropic_model)."
            )
        with self.anthropic_client.messages.stream(
            model=resolved_model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for text in stream.text_stream:
                yield text

    def generate_content_stream(
        self, prompt: str, generation_config: Optional[dict] = None
    ) -> Iterator[str]:
        """Plain-text streaming generator, one tier at a time, same fallback
        order as generate_content. Important limitation: once a tier has
        started yielding chunks to the caller, a mid-stream failure on that
        tier cannot fall back to the next one - the caller has already seen
        (and likely displayed) partial output, and silently discarding it
        for a second attempt would show text disappearing and reappearing.
        So a mid-stream failure re-raises after logging; only a failure
        that happens before any chunk is yielded moves on to the next tier.
        No response_schema support - schema enforcement is incompatible
        with token-by-token streaming on all four providers.

        Provider model identifiers come only from environment-backed
        settings (settings.<provider>_model). A tier whose model setting
        has gone missing is skipped cleanly, mirroring the non-streaming
        path."""
        generation_config = generation_config or {}

        if generation_config.get("response_schema") is not None:
            logger.warning(
                "HybridLLM: generate_content_stream does not support "
                "response_schema; schema hint is being ignored. Callers that "
                "need schema-constrained output should use generate_content."
            )

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
            those still can't be retried transparently). make_source is a
            zero-arg callable that creates a fresh generator each call,
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
            gemini_model = settings.gemini_model
            if not _is_configured_model(gemini_model):
                logger.warning(
                    "HybridLLM: Gemini model is not configured; skipping "
                    "Gemini stream tier."
                )
            else:
                try:
                    gemini_config = dict(generation_config)
                    gemini_config.pop("task", None)
                    gemini_config["model"] = gemini_model
                    yield from _run_tier_with_retry(
                        lambda: self.gemini.generate_content_stream(prompt, gemini_config),
                        "Gemini",
                    )
                    return
                except _TierFailedBeforeFirstChunk as e:
                    logger.warning(
                        f"HybridLLM: Gemini stream failed after retries, trying "
                        f"Groq: {e.__cause__}"
                    )

        if self.groq_client:
            groq_model = settings.groq_model
            if not _is_configured_model(groq_model):
                logger.warning(
                    "HybridLLM: Groq model is not configured; skipping "
                    "Groq stream tier."
                )
            else:
                try:
                    groq_max_tokens = min(max_tokens, _GROQ_MAX_OUTPUT_TOKENS_CAP)
                    yield from _run_tier_with_retry(
                        lambda: _openai_compatible_stream(
                            self.groq_client, groq_model, prompt, temperature,
                            groq_max_tokens,
                        ),
                        "Groq",
                    )
                    return
                except _TierFailedBeforeFirstChunk as e:
                    logger.warning(
                        f"HybridLLM: Groq stream failed after retries, trying "
                        f"OpenAI: {e.__cause__}"
                    )

        if self.openai_client:
            openai_model = settings.openai_model
            if not _is_configured_model(openai_model):
                logger.warning(
                    "HybridLLM: OpenAI model is not configured; skipping "
                    "OpenAI stream tier."
                )
            else:
                try:
                    yield from _run_tier_with_retry(
                        lambda: _openai_compatible_stream(
                            self.openai_client, openai_model, prompt, temperature,
                            max_tokens,
                        ),
                        "OpenAI",
                    )
                    return
                except _TierFailedBeforeFirstChunk as e:
                    logger.warning(
                        f"HybridLLM: OpenAI stream failed after retries, trying "
                        f"Anthropic: {e.__cause__}"
                    )

        if self.anthropic_client:
            anthropic_model = settings.anthropic_model
            if not _is_configured_model(anthropic_model):
                logger.warning(
                    "HybridLLM: Anthropic model is not configured; skipping "
                    "Anthropic stream tier."
                )
            else:
                try:
                    yield from _run_tier_with_retry(
                        lambda: self._try_anthropic_stream(
                            prompt, max_tokens, anthropic_model
                        ),
                        "Anthropic",
                    )
                    return
                except _TierFailedBeforeFirstChunk as e:
                    logger.error(
                        f"HybridLLM: Anthropic stream failed after retries: "
                        f"{e.__cause__}"
                    )

        logger.error("HybridLLM: No LLM backend succeeded (streaming)")
        raise RuntimeError(
            "All configured LLM providers are currently unavailable "
            "(Gemini, Groq, OpenAI, and Anthropic all failed or are not configured)."
        )


def get_llm(temperature: float = 0.7) -> HybridLLMClient:
    """Return the singleton hybrid LLM client.

    NOTE: subsequent calls with a different `temperature` return the same
    instance and ignore the new value. Use reload_llm(temperature=...) to
    construct a fresh client with a different sampling temperature.
    """
    global _LLM_INSTANCE
    if _LLM_INSTANCE is None:
        _LLM_INSTANCE = HybridLLMClient(temperature=temperature)
        logger.info("Initialized singleton Hybrid LLM instance")
    return _LLM_INSTANCE


def reload_llm(temperature: Optional[float] = None) -> HybridLLMClient:
    """Force-reload the singleton LLM instance with an optional new temperature."""
    global _LLM_INSTANCE
    _LLM_INSTANCE = HybridLLMClient(temperature=temperature or 0.7)
    logger.info("Reloaded singleton Hybrid LLM instance")
    return _LLM_INSTANCE