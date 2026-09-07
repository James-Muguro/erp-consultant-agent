"""
Tests for orchestration-hardening's retry behavior actually retrying (not
just falling through), and for the token-usage/latency observability added
alongside it in the same stage.
"""
from unittest.mock import Mock, patch
import pytest

from src.utils.llm import HybridLLMClient, _openai_compatible_call, _anthropic_usage, _to_response
from src.utils.llm_client import LLMClient as GeminiLLMClient


@pytest.fixture
def client():
    return HybridLLMClient()


class TestRetryActuallyRetries:
    def test_gemini_retries_within_the_same_tier_before_falling_back(self, client):
        """A transient failure on attempt 1 should succeed on attempt 2
        of the SAME tier, never reaching Groq/OpenAI/Anthropic at all -
        this is the whole point of retry-before-fallback."""
        client.use_gemini = True
        client.gemini = Mock()
        client.gemini.generate_content.side_effect = [
            Exception("transient blip"),
            type("LLMResponse", (), {"text": "recovered on retry", "usage": None})(),
        ]
        client.groq_client = Mock()  # would prove a bug if this got called

        result = client.generate_content("some prompt")

        assert result.text == "recovered on retry"
        assert client.gemini.generate_content.call_count == 2
        client.groq_client.chat.completions.create.assert_not_called()

    def test_exhausting_retries_on_one_tier_falls_through_to_the_next(self, client):
        client.use_gemini = True
        client.gemini = Mock()
        client.gemini.generate_content.side_effect = Exception("permanently down")
        client.groq_client = None

        fake_completion = Mock()
        fake_completion.choices = [Mock(message=Mock(content="openai answered"))]
        fake_completion.usage = None
        client.openai_client = Mock()
        client.openai_client.chat.completions.create.return_value = fake_completion

        result = client.generate_content("some prompt")

        assert result.text == "openai answered"
        # settings.llm_retry_attempts default is 2 - both attempts on the
        # dead Gemini tier should have been used before falling through.
        assert client.gemini.generate_content.call_count == 2


class TestTokenUsageCapture:
    def test_openai_compatible_call_extracts_usage(self):
        fake_completion = Mock()
        fake_completion.choices = [Mock(message=Mock(content="hello"))]
        fake_completion.usage = Mock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        fake_client = Mock()
        fake_client.chat.completions.create.return_value = fake_completion

        result = _openai_compatible_call(fake_client, "gpt-4o", "prompt", 0.7, 100, None)

        assert result.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    def test_openai_compatible_call_handles_missing_usage_gracefully(self):
        fake_completion = Mock()
        fake_completion.choices = [Mock(message=Mock(content="hello"))]
        fake_completion.usage = None
        fake_client = Mock()
        fake_client.chat.completions.create.return_value = fake_completion

        result = _openai_compatible_call(fake_client, "gpt-4o", "prompt", 0.7, 100, None)

        assert result.usage is None

    def test_anthropic_usage_maps_input_output_to_prompt_completion(self):
        fake_resp = Mock()
        fake_resp.usage = Mock(input_tokens=20, output_tokens=8)

        usage = _anthropic_usage(fake_resp)

        assert usage == {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28}

    def test_anthropic_usage_returns_none_when_absent(self):
        fake_resp = Mock()
        fake_resp.usage = None
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
                prompt_token_count=12, candidates_token_count=6, total_token_count=18
            )
            gemini_client.gemini_client.models.generate_content.return_value = fake_response

            result = gemini_client.generate_content("prompt")

            assert result.text == "hello from gemini"
            assert result.usage == {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18}

    def test_log_llm_call_does_not_crash_when_usage_is_none(self, client):
        """_to_response's default usage=None must be a safe input to the
        logging helper, not an AttributeError waiting to happen."""
        response = _to_response("some text")
        client._log_llm_call("gemini", start_time=0.0, response=response)  # should not raise
