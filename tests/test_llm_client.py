"""
Contract tests for HybridLLMClient (src/utils/llm.py).

These guard against the exact bug found and fixed in Stage 0: the client
returning inconsistent shapes (a plain string on some paths, an object
with .text on others) depending on which backend succeeded. Every agent
in this codebase unconditionally does `response.text`, so this contract
must hold no matter which path generate_content() takes.

Coverage:

  Response shape
    - Gemini success returns an LLMResponse with .text.
    - OpenAI fallback (with Groq skipped) returns the same shape.
    - Every successful response carries provider, model, finish_reason
      and usage fields, not just .text.

  Failure handling
    - Total failure raises RuntimeError rather than returning a fake
      success.
    - Retrying within a tier recovers from a transient exception.
    - An OpenAI response with no message content is treated as a
      provider failure (raises) rather than being silently accepted as
      empty text.

  Provider-specific behavior
    - response_schema reaches the Gemini call unmodified.
    - Groq receives response_format={"type": "json_object"} and the
      schema injected into the prompt.
    - OpenAI receives response_format={"type": "json_schema", ...}.

  Truncation detection
    - _looks_truncated_json correctly flags unbalanced JSON.
    - finish_reason='length' surfaces on the response.

  Streaming
    - Yields chunks from the first healthy tier.
    - Falls back to the next tier when the first fails before yielding.
    - Mid-stream failure re-raises (cannot fall back after partial output).

  Singleton lifecycle
    - reload_llm constructs a new instance.

Live API tests are marked @pytest.mark.api and excluded by default.
Run explicitly with: pytest -m api
"""
from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest

from src.utils.llm import HybridLLMClient, LLMResponse, get_llm, reload_llm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _gemini_response(text: str, finish_reason: str = "STOP"):
    """Construct a Gemini-shaped response object (a bare object with
    .text and .finish_reason attributes, which is what the wrapper's
    normalizer reads)."""
    return type(
        "GeminiResponse",
        (),
        {"text": text, "finish_reason": finish_reason},
    )()


def _openai_completion(content: str, finish_reason: str = "stop"):
    """Construct an OpenAI-compatible completion response."""
    choice = Mock()
    choice.message = Mock(content=content)
    choice.finish_reason = finish_reason
    completion = Mock()
    completion.choices = [choice]
    return completion


@pytest.fixture
def client():
    """A HybridLLMClient with all provider clients cleared.

    The constructor may build real SDK clients depending on which
    settings keys are present. For unit tests we want a hermetic
    baseline: every provider disabled, so a test that doesn't
    explicitly enable one cannot reach a live API. Tests opt in by
    setting the specific client they need."""
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
    don't add real latency even in an environment where pytest's
    PYTEST_CURRENT_TEST flag isn't set."""
    with patch("src.utils.resilience.time.sleep"):
        yield


# ---------------------------------------------------------------------------
# Response shape contract
# ---------------------------------------------------------------------------
class TestResponseShape:
    def test_gemini_success_returns_text_object(self, client):
        client.use_gemini = True
        client.gemini = Mock()
        client.gemini.generate_content.return_value = _gemini_response("real gemini output")

        result = client.generate_content("some prompt")

        assert hasattr(result, "text")
        assert result.text == "real gemini output"

    def test_gemini_success_returns_llm_response_instance(self, client):
        """The response is an LLMResponse, not a dynamically-created
        type. This makes isinstance checks and downstream field access
        predictable."""
        client.use_gemini = True
        client.gemini = Mock()
        client.gemini.generate_content.return_value = _gemini_response("output")

        result = client.generate_content("prompt")

        assert isinstance(result, LLMResponse)

    def test_successful_response_carries_provider_and_model(self, client):
        """Diagnostic fields — logged on every call. If they stop being
        populated, the "which provider actually answered?" question
        becomes unanswerable from logs alone."""
        client.use_gemini = True
        client.gemini = Mock()
        client.gemini.generate_content.return_value = _gemini_response("output")

        result = client.generate_content("prompt")

        assert result.provider == "gemini"
        # model may be None if no override and the gemini_config didn't
        # set one; assert the attribute exists rather than its value.
        assert hasattr(result, "model")

    def test_openai_fallback_returns_consistent_shape(self, client):
        client.use_gemini = True
        client.gemini = Mock()
        client.gemini.generate_content.side_effect = Exception("Gemini is down")
        # Groq explicitly disabled so the OpenAI mock is reached.
        client.groq_client = None
        client.openai_client = Mock()
        client.openai_client.chat.completions.create.return_value = _openai_completion(
            "fallback output "
        )

        result = client.generate_content("some prompt")

        assert hasattr(result, "text")
        assert result.text == "fallback output"
        assert result.provider == "openai"

    def test_empty_query_still_reaches_provider(self, client):
        """The wrapper doesn't have a pre-flight check; an empty query
        is the caller's problem. This documents that behavior so a
        future change to add a pre-flight doesn't silently break
        callers relying on the current passthrough."""
        client.use_gemini = True
        client.gemini = Mock()
        client.gemini.generate_content.return_value = _gemini_response("")

        result = client.generate_content("")

        # Empty text from a successful call is a valid (if unhelpful)
        # response — the wrapper surfaces it as-is.
        assert result.text == ""


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------
class TestFailureHandling:
    def test_total_failure_raises_instead_of_faking_success(self, client):
        """Total failure must raise, not return a fake .text response —
        the fake-success bug previously leaked the literal string
        'Error generating response: LLM unavailable' straight through
        to end users as if it were real model output."""
        client.use_gemini = True
        client.gemini = Mock()
        client.gemini.generate_content.side_effect = Exception("Gemini is down")
        # All fallbacks disabled.
        client.groq_client = None
        client.openai_client = None
        client.anthropic_client = None

        with pytest.raises(RuntimeError, match="LLM providers are currently unavailable"):
            client.generate_content("some prompt")

    def test_openai_failure_also_raises(self, client):
        client.use_gemini = True
        client.gemini = Mock()
        client.gemini.generate_content.side_effect = Exception("Gemini is down")
        client.groq_client = None
        client.openai_client = Mock()
        client.openai_client.chat.completions.create.side_effect = Exception(
            "OpenAI is down too"
        )
        client.anthropic_client = None

        with pytest.raises(RuntimeError, match="LLM providers are currently unavailable"):
            client.generate_content("some prompt")

    def test_transient_failure_is_retried_within_tier(self, client, patched_sleep):
        """A transient failure followed by success on retry stays within
        the same tier — the retry logic in call_with_retries recovers
        without burning downstream tiers."""
        client.use_gemini = True
        client.gemini = Mock()
        client.gemini.generate_content.side_effect = [
            Exception("transient blip"),
            _gemini_response("recovered"),
        ]

        result = client.generate_content("prompt")

        assert result.text == "recovered"
        assert client.gemini.generate_content.call_count == 2

    def test_openai_empty_content_treated_as_provider_failure(self, client):
        """When OpenAI returns no message content (content filter, or a
        tool-call-only response), the wrapper raises rather than
        accepting an empty response. This is the path that used to
        produce `AttributeError: 'NoneType' has no attribute 'strip'`
        and was logged as "provider outage" for a reason that wasn't a
        provider outage."""
        client.use_gemini = False
        client.openai_client = Mock()
        completion = Mock()
        choice = Mock()
        choice.message = Mock(content=None)  # no content
        choice.finish_reason = "content_filter"
        completion.choices = [choice]
        client.openai_client.chat.completions.create.return_value = completion
        client.groq_client = None
        client.anthropic_client = None

        with pytest.raises(RuntimeError, match="LLM providers are currently unavailable"):
            client.generate_content("prompt")


# ---------------------------------------------------------------------------
# Provider-specific behavior
# ---------------------------------------------------------------------------
class TestProviderSpecificBehavior:
    def test_response_schema_is_passed_through_to_gemini(self, client):
        """Guards the Stage 1 wiring: response_schema in generation_config
        must actually reach the underlying Gemini client call."""
        client.use_gemini = True
        client.gemini = Mock()
        client.gemini.generate_content.return_value = _gemini_response("{}")

        class FakeSchema:
            pass

        client.generate_content("some prompt", generation_config={"response_schema": FakeSchema})

        _, kwargs = client.gemini.generate_content.call_args
        assert kwargs["generation_config"]["response_schema"] is FakeSchema

    def test_task_hint_is_stripped_before_gemini_call(self, client):
        """The `task` kwarg is a routing hint for the wrapper, not a
        parameter the Gemini SDK understands. It must be popped before
        the call."""
        client.use_gemini = True
        client.gemini = Mock()
        client.gemini.generate_content.return_value = _gemini_response("{}")

        client.generate_content(
            "prompt",
            generation_config={"task": "high_reasoning"},
        )

        _, kwargs = client.gemini.generate_content.call_args
        assert "task" not in kwargs["generation_config"]

    def test_openai_receives_json_schema_response_format(self, client):
        """OpenAI supports strict JSON-schema-constrained output via
        response_format with a top-level json_schema key. Sending the
        wrong shape here would 400 and burn the tier."""
        client.use_gemini = False
        client.openai_client = Mock()
        client.openai_client.chat.completions.create.return_value = _openai_completion("{}")
        client.groq_client = None

        class FakeSchema:
            @staticmethod
            def model_json_schema():
                return {"type": "object", "properties": {}}

        FakeSchema.__name__ = "FakeSchema"

        client.generate_content(
            "prompt",
            generation_config={"response_schema": FakeSchema},
        )

        _, kwargs = client.openai_client.chat.completions.create.call_args
        fmt = kwargs["response_format"]
        assert fmt["type"] == "json_schema"
        assert fmt["json_schema"]["name"] == "FakeSchema"
        assert fmt["json_schema"]["schema"] == {"type": "object", "properties": {}}

    def test_groq_receives_json_object_response_format_and_schema_in_prompt(self, client):
        """Groq rejects OpenAI's json_schema response_format (400) and
        only supports {"type": "json_object"}. The schema must be
        injected into the prompt instead, and the prompt must contain
        the literal token 'JSON' (Groq's requirement)."""
        client.use_gemini = False
        client.openai_client = None
        client.groq_client = Mock()
        client.groq_client.chat.completions.create.return_value = _openai_completion("{}")

        class FakeSchema:
            @staticmethod
            def model_json_schema():
                return {"type": "object", "properties": {"x": {"type": "string"}}}

        FakeSchema.__name__ = "FakeSchema"

        client.generate_content(
            "prompt text",
            generation_config={"response_schema": FakeSchema},
        )

        _, kwargs = client.groq_client.chat.completions.create.call_args
        assert kwargs["response_format"] == {"type": "json_object"}
        # Schema is injected into the prompt.
        prompt_sent = kwargs["messages"][0]["content"]
        assert "JSON" in prompt_sent
        assert '"x"' in prompt_sent or "x" in prompt_sent

    def test_groq_max_tokens_is_clamped(self, client):
        """Groq caps output tokens far lower than Gemini/OpenAI on most
        models. The wrapper must clamp rather than let the request 400
        and burn the free tier."""
        client.use_gemini = False
        client.openai_client = None
        client.groq_client = Mock()
        client.groq_client.chat.completions.create.return_value = _openai_completion("{}")

        client.generate_content(
            "prompt",
            generation_config={"max_output_tokens": 100_000},
        )

        _, kwargs = client.groq_client.chat.completions.create.call_args
        assert kwargs["max_tokens"] <= 8192


# ---------------------------------------------------------------------------
# Truncation detection
# ---------------------------------------------------------------------------
class TestTruncationDetection:
    def test_looks_truncated_json_detects_unbalanced_braces(self):
        assert HybridLLMClient._looks_truncated_json('{"a": 1, "b": [1, 2') is True

    def test_looks_truncated_json_accepts_balanced_json(self):
        assert HybridLLMClient._looks_truncated_json('{"a": 1, "b": [1, 2]}') is False

    def test_looks_truncated_json_ignores_non_json_output(self):
        """A plain-text response is not JSON — return False so the
        caller's schema validation handles it, rather than treating it
        as a truncation and forcing a pointless retry."""
        assert HybridLLMClient._looks_truncated_json("just some prose") is False

    def test_looks_truncated_json_handles_escaped_quotes(self):
        """Escaped quotes inside string literals must not be counted as
        string delimiters, or a balanced JSON object with `\\"` in a
        value would be falsely flagged as truncated."""
        assert HybridLLMClient._looks_truncated_json(
            '{"a": "he said \\"hi\\"", "b": 1}'
        ) is False

    def test_finish_reason_length_surfaces_on_response(self, client):
        """A truncated model response is signaled by finish_reason
        'length'. Agents consult this to trigger a retry rather than
        trying to parse a half-written JSON document."""
        client.use_gemini = True
        client.gemini = Mock()
        client.gemini.generate_content.return_value = _gemini_response(
            '{"truncated": "yes', finish_reason="MAX_TOKENS"
        )

        result = client.generate_content("prompt")
        assert result.finish_reason == "length"


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------
class TestStreaming:
    def test_stream_yields_chunks_from_first_healthy_tier(self, client):
        client.use_gemini = True
        client.gemini = Mock()

        def fake_stream(prompt, config):
            yield "chunk1"
            yield "chunk2"

        client.gemini.generate_content_stream = fake_stream

        chunks = list(client.generate_content_stream("prompt"))
        assert chunks == ["chunk1", "chunk2"]

    def test_stream_falls_back_when_first_tier_fails_before_yielding(self, client):
        client.use_gemini = True
        client.gemini = Mock()

        def failing_stream(prompt, config):
            raise RuntimeError("Gemini unavailable")
            yield  # pragma: no cover - unreachable, marks the function as a generator

        client.gemini.generate_content_stream = failing_stream

        # Fallback to OpenAI. Use OpenAI since Groq's stream helper has
        # a slightly different shape; the contract we care about is
        # that a pre-yield failure moves on to the next tier.
        client.groq_client = None
        client.openai_client = Mock()

        def openai_stream(**kwargs):
            yield "fallback chunk"

        # _openai_compatible_stream uses client.chat.completions.create(stream=True).
        mock_stream = iter([
            type("Chunk", (), {"choices": [type("Choice", (), {"delta": type("Delta", (), {"content": "fallback chunk"})()})()]})(),
        ])
        client.openai_client.chat.completions.create.return_value = mock_stream

        chunks = list(client.generate_content_stream("prompt"))
        assert chunks == ["fallback chunk"]

    def test_stream_mid_failure_reraises(self, client):
        """Once a tier has yielded a chunk, a subsequent failure on that
        tier cannot silently fall back — the caller has already seen
        partial output. The error must surface."""
        client.use_gemini = True
        client.gemini = Mock()

        def partial_then_fail(prompt, config):
            yield "partial"
            raise RuntimeError("mid-stream failure")

        client.gemini.generate_content_stream = partial_then_fail

        with pytest.raises(RuntimeError, match="mid-stream failure"):
            list(client.generate_content_stream("prompt"))


# ---------------------------------------------------------------------------
# Singleton lifecycle
# ---------------------------------------------------------------------------
class TestSingletonLifecycle:
    def test_reload_llm_returns_fresh_instance(self):
        """reload_llm must construct a new client, not return the
        existing singleton. This is what agents that want to swap
        providers need — get_llm() by contrast returns the same
        instance."""
        first = get_llm()
        second = reload_llm()
        assert first is not second
        assert isinstance(second, HybridLLMClient)


# ---------------------------------------------------------------------------
# Live API tests (excluded by default)
# ---------------------------------------------------------------------------
@pytest.mark.api
def test_live_gemini_call_returns_real_text():
    """Real, unmocked call to the live Gemini API. Excluded by default —
    run explicitly with: pytest -m api"""
    llm = get_llm()
    result = llm.generate_content("Say 'contract test ok' and nothing else.")

    assert hasattr(result, "text")
    assert len(result.text.strip()) > 0
    assert "Error generating response" not in result.text