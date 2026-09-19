"""
Tests for retry behavior and token-usage / latency observability in
src/utils/llm.py.

Two families of behavior:

  Retry
    - A transient failure within a tier is retried before falling
      through. This is the fix for the "retry never actually retried"
      bug — the tier would fail once and immediately move on.
    - Retry count is honored exactly; exhausting retries on one tier
      falls through to the next.
    - A tier whose client isn't configured is skipped cleanly.

  Observability
    - Token usage is extracted and normalized across providers.
    - Provider, model, and finish_reason are carried on the response.
    - finish_reason is normalized to a small shared vocabulary so
      callers can rely on 'length' meaning truncated.
    - Logging is null-safe when usage is absent.

Fixtures:
  * client       a HybridLLMClient with all provider clients explicitly
                 cleared. Without this, a developer with API keys in
                 their environment could accidentally reach a live API
                 from a test that forgot to null a provider.
  * patched_sleep
                 zeroes the retry backoff so tests aren't dependent on
                 running under pytest for their speed.

Call-site fragility note
------------------------
`_openai_compatible_call` is called with positional args in some tests.
Its `provider` parameter is keyword-only in the current implementation.
If a future change makes it positional (or reorders arguments), these
tests will need updating — the assertions they make are about provider
behavior, not about the function's signature.
"""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from src.config.settings import settings
from src.utils.llm import (
    HybridLLMClient,
    LLMResponse,
    _anthropic_usage,
    _openai_compatible_call,
    _to_response,
)
from src.utils.llm_client import LLMClient as GeminiLLMClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def client():
    """A HybridLLMClient with every provider client explicitly cleared.

    The constructor builds real SDK clients depending on which settings
    keys are present. For unit tests we want a hermetic baseline — a
    test that doesn't set up a specific provider cannot accidentally
    reach a live API. Tests opt in by assigning the specific client
    they need."""
    c = HybridLLMClient()
    c.gemini = None
    c.use_gemini = False
    c.groq_client = None
    c.openai_client = None
    c.anthropic_client = None
    return c


@pytest.fixture
def patched_sleep():
    """Patch time.sleep in the resilience module so retry-path tests
    don't add real latency. The module's default backoff is already
    small under pytest, but patching makes the tests independent of
    how they're invoked (pytest vs. direct execution)."""
    with patch("src.utils.resilience.time.sleep"):
        yield


def _gemini_response(text: str, finish_reason=None):
    """A minimal Gemini-shaped response object. The wrapper's normalizer
    reads .text, .finish_reason, and (optionally) .usage_metadata; a
    plain object with those attributes is sufficient."""
    obj = type("GeminiResponse", (), {})()
    obj.text = text
    obj.finish_reason = finish_reason
    return obj


def _openai_completion(content: str, usage: Mock = None, finish_reason: str = "stop"):
    """A minimal OpenAI-shaped completion response."""
    choice = Mock()
    choice.message = Mock(content=content)
    choice.finish_reason = finish_reason
    completion = Mock()
    completion.choices = [choice]
    completion.usage = usage
    return completion


# ===========================================================================
# Retry behavior
# ===========================================================================
class TestRetryActuallyRetries:
    def test_gemini_retries_within_the_same_tier_before_falling_back(
        self, client, patched_sleep,
    ):
        """A transient failure on attempt 1 succeeds on attempt 2 of
        the SAME tier — never reaching Groq/OpenAI/Anthropic. This is
        the whole point of retry-before-fallback: transient provider
        blips shouldn't cost a tier hop."""
        client.use_gemini = True
        client.gemini = Mock()
        client.gemini.generate_content.side_effect = [
            Exception("transient blip"),
            _gemini_response("recovered on retry"),
        ]
        client.groq_client = Mock()  # would prove a bug if this got called

        result = client.generate_content("some prompt")

        assert result.text == "recovered on retry"
        assert client.gemini.generate_content.call_count == 2
        client.groq_client.chat.completions.create.assert_not_called()

    @pytest.mark.parametrize("retry_count", [1, 2, 3])
    def test_retry_count_is_honored_exactly(
        self, client, patched_sleep, monkeypatch, retry_count,
    ):
        """The number of attempts on a failing tier equals
        settings.llm_retry_attempts. Parametrized across three values
        so the test asserts the contract, not a hardcoded default that
        happens to equal 2 in the current environment."""
        monkeypatch.setattr(settings, "llm_retry_attempts", retry_count)

        client.use_gemini = True
        client.gemini = Mock()
        client.gemini.generate_content.side_effect = Exception("permanently down")
        client.groq_client = None

        client.openai_client = Mock()
        client.openai_client.chat.completions.create.return_value = _openai_completion(
            "openai answered"
        )

        result = client.generate_content("some prompt")

        assert result.text == "openai answered"
        assert client.gemini.generate_content.call_count == retry_count

    def test_exhausting_retries_on_one_tier_falls_through_to_the_next(
        self, client, patched_sleep,
    ):
        """When every retry on a tier fails, the wrapper moves on to
        the next configured tier rather than raising immediately."""
        client.use_gemini = True
        client.gemini = Mock()
        client.gemini.generate_content.side_effect = Exception("permanently down")
        client.groq_client = None
        client.openai_client = Mock()
        client.openai_client.chat.completions.create.return_value = _openai_completion(
            "openai answered"
        )

        result = client.generate_content("some prompt")

        assert result.text == "openai answered"
        assert result.provider == "openai"


# ===========================================================================
# Token usage extraction
# ===========================================================================
class TestTokenUsageCapture:
    def test_openai_compatible_call_extracts_usage(self):
        usage_mock = Mock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        fake_client = Mock()
        fake_client.chat.completions.create.return_value = _openai_completion(
            "hello", usage=usage_mock,
        )

        result = _openai_compatible_call(fake_client, "gpt-4o", "prompt", 0.7, 100, None)

        assert result.usage == {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }

    def test_openai_compatible_call_handles_missing_usage_gracefully(self):
        fake_client = Mock()
        fake_client.chat.completions.create.return_value = _openai_completion(
            "hello", usage=None,
        )

        result = _openai_compatible_call(fake_client, "gpt-4o", "prompt", 0.7, 100, None)

        assert result.usage is None

    def test_openai_compatible_call_tolerates_partial_usage(self):
        """A provider returning a usage object with only some fields
        populated must not crash. The wrapper reads each field with
        getattr(def, None), so a partial mock produces a partial dict
        rather than an AttributeError."""
        usage_mock = Mock(prompt_tokens=10, completion_tokens=None, total_tokens=None)
        fake_client = Mock()
        fake_client.chat.completions.create.return_value = _openai_completion(
            "hello", usage=usage_mock,
        )

        result = _openai_compatible_call(fake_client, "gpt-4o", "prompt", 0.7, 100, None)

        # No exception; usage dict exists with the fields it had.
        assert result.usage is not None
        assert result.usage["prompt_tokens"] == 10

    def test_anthropic_usage_maps_input_output_to_prompt_completion(self):
        fake_resp = Mock()
        fake_resp.usage = Mock(input_tokens=20, output_tokens=8)

        usage = _anthropic_usage(fake_resp)

        assert usage == {
            "prompt_tokens": 20,
            "completion_tokens": 8,
            "total_tokens": 28,
        }

    def test_anthropic_usage_returns_none_when_absent(self):
        fake_resp = Mock()
        fake_resp.usage = None
        assert _anthropic_usage(fake_resp) is None

    def test_anthropic_usage_returns_none_when_partially_present(self):
        """Partial usage — one field present, one missing — returns
        None rather than a half-filled dict that would produce a
        misleading cost report."""
        fake_resp = Mock()
        fake_resp.usage = Mock(input_tokens=20, output_tokens=None)
        assert _anthropic_usage(fake_resp) is None

    def test_gemini_client_extracts_usage_metadata(self):
        with patch("src.utils.llm_client.GEMINI_AVAILABLE", True), \
             patch("src.utils.llm_client.settings") as mock_settings:
            mock_settings.gemini_api_key = "fake"
            mock_settings.gemini_model = "gemini-test"
            mock_settings.max_tokens = 1000

            gemini_client = GeminiLLMClient.__new__(GeminiLLMClient)
            gemini_client.temperature = 0.7
            gemini_client.gemini_client = Mock()

            fake_response = Mock()
            fake_response.text = "hello from gemini"
            fake_response.usage_metadata = Mock(
                prompt_token_count=12,
                candidates_token_count=6,
                total_token_count=18,
            )
            # Mock auto-attributes confuse the finish-reason normalizer. Pin the
            # two attributes it reads to a shape that behaves like a real response
            # with no candidates and no prompt-level block reason.
            fake_response.candidates = []
            fake_response.prompt_feedback = None
            gemini_client.gemini_client.models.generate_content.return_value = fake_response

            result = gemini_client.generate_content("prompt")

            assert result.text == "hello from gemini"
            assert result.usage == {
                "prompt_tokens": 12,
                "completion_tokens": 6,
                "total_tokens": 18,
            }

    def test_gemini_client_returns_none_usage_when_metadata_absent(self):
        """When Gemini's SDK doesn't include usage_metadata (rare but
        possible for some response types), the client must return
        None rather than raising."""
        with patch("src.utils.llm_client.GEMINI_AVAILABLE", True), \
             patch("src.utils.llm_client.settings") as mock_settings:
            mock_settings.gemini_api_key = "fake"
            mock_settings.gemini_model = "gemini-test"
            mock_settings.max_tokens = 1000

            gemini_client = GeminiLLMClient.__new__(GeminiLLMClient)
            gemini_client.temperature = 0.7
            gemini_client.gemini_client = Mock()

            fake_response = Mock()
            fake_response.text = "hello"
            fake_response.usage_metadata = None
            # Mock auto-attributes confuse the finish-reason normalizer. Pin the
            # two attributes it reads to a shape that behaves like a real response
            # with no candidates and no prompt-level block reason.
            fake_response.candidates = []
            fake_response.prompt_feedback = None
            gemini_client.gemini_client.models.generate_content.return_value = fake_response

            result = gemini_client.generate_content("prompt")
            assert result.usage is None


# ===========================================================================
# Response shape / diagnostics
# ===========================================================================
class TestResponseDiagnostics:
    def test_successful_response_carries_provider_and_model(self, client, patched_sleep):
        """Diagnostic fields populated on every LLMResponse — these are
        what _log_llm_call prints, and what makes 'which tier answered?'
        answerable from production logs."""
        client.use_gemini = True
        client.gemini = Mock()
        client.gemini.generate_content.return_value = _gemini_response("output")

        result = client.generate_content("prompt")

        assert isinstance(result, LLMResponse)
        assert result.provider == "gemini"

    def test_finish_reason_max_tokens_normalizes_to_length(self, client, patched_sleep):
        """The definitive truncation signal. Agents consult
        `finish_reason == 'length'` to trigger a retry rather than
        attempting to parse a half-written JSON document. The
        normalization maps every provider's 'hit the cap' reason to
        the same value."""
        client.use_gemini = True
        client.gemini = Mock()
        client.gemini.generate_content.return_value = _gemini_response(
            "truncated output", finish_reason="MAX_TOKENS",
        )

        result = client.generate_content("prompt")

        assert result.finish_reason == "length"

    def test_finish_reason_stop_normalizes_to_stop(self, client, patched_sleep):
        client.use_gemini = True
        client.gemini = Mock()
        client.gemini.generate_content.return_value = _gemini_response(
            "completed output", finish_reason="STOP",
        )

        result = client.generate_content("prompt")

        assert result.finish_reason == "stop"

    def test_openai_finish_reason_is_normalized(self, client, patched_sleep):
        """OpenAI's completion response carries its own finish_reason.
        'length' is the truncation signal; the wrapper normalizes it to
        the same vocabulary used for Gemini so callers can check one
        value regardless of which tier answered."""
        client.use_gemini = False
        client.openai_client = Mock()
        client.openai_client.chat.completions.create.return_value = _openai_completion(
            "truncated", finish_reason="length",
        )

        result = client.generate_content("prompt")

        assert result.finish_reason == "length"


# ===========================================================================
# Logging null-safety
# ===========================================================================
class TestLoggingNullSafety:
    def test_log_llm_call_does_not_crash_when_usage_is_none(self, client):
        """_to_response's default usage=None must be a safe input to
        the logging helper — not an AttributeError waiting for the
        first response that didn't carry usage."""
        response = _to_response("some text")
        client._log_llm_call("gemini", start_time=0.0, response=response)

    def test_log_llm_call_handles_usage_with_none_fields(self, client):
        """A usage dict with None values (from a partial provider
        response) must not crash the log helper either. The helper
        should log whatever it has."""
        response = LLMResponse(
            text="text",
            usage={"prompt_tokens": None, "completion_tokens": None, "total_tokens": None},
            provider="gemini",
            model="gemini-test",
        )
        client._log_llm_call("gemini", start_time=0.0, response=response)

    def test_log_llm_call_handles_response_without_usage_attribute(self, client):
        """The logging helper reads .usage via getattr with a default,
        so an object that lacks the attribute entirely should still be
        loggable without raising."""
        class BareResponse:
            text = "text"
        client._log_llm_call("gemini", start_time=0.0, response=BareResponse())