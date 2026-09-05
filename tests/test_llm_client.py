"""
Contract tests for HybridLLMClient (src/utils/llm.py).

These guard against the exact bug found and fixed in Stage 0: the client
returning inconsistent shapes (a plain string on some paths, an object
with .text on others) depending on which backend succeeded. Every agent
in this codebase unconditionally does `response.text`, so this contract
must hold no matter which path generate_content() takes.
"""
from unittest.mock import Mock
import pytest

from src.utils.llm import HybridLLMClient


@pytest.fixture
def client():
    """A real HybridLLMClient - __init__ only sets up API clients, it
    doesn't make network calls, so this is safe to construct directly."""
    return HybridLLMClient()


def test_gemini_success_returns_text_object(client):
    client.use_gemini = True
    client.gemini = Mock()
    client.gemini.generate_content.return_value = type("LLMResponse", (), {"text": "real gemini output"})()

    result = client.generate_content("some prompt")

    assert hasattr(result, "text")
    assert result.text == "real gemini output"


def test_gemini_failure_falls_back_to_openai_with_consistent_shape(client):
    client.use_gemini = True
    client.gemini = Mock()
    client.gemini.generate_content.side_effect = Exception("Gemini is down")

    fake_completion = Mock()
    fake_completion.choices = [Mock(message=Mock(content="fallback output "))]
    client.openai_client = Mock()
    client.openai_client.chat.completions.create.return_value = fake_completion

    result = client.generate_content("some prompt")

    assert hasattr(result, "text")
    assert result.text == "fallback output"


def test_total_failure_raises_instead_of_faking_success(client):
    """Total failure must raise, not return a fake .text response - a
    silent fake success previously leaked the literal string 'Error
    generating response: LLM unavailable' straight through to end users
    as if it were real model output. Every caller (all agents, plus the
    chat endpoint) already has a try/except ready to turn this into a
    proper structured error or a friendly fallback message."""
    client.use_gemini = True
    client.gemini = Mock()
    client.gemini.generate_content.side_effect = Exception("Gemini is down")
    client.openai_client = None  # no fallback configured

    with pytest.raises(RuntimeError, match="LLM providers are currently unavailable"):
        client.generate_content("some prompt")


def test_openai_failure_also_raises(client):
    client.use_gemini = True
    client.gemini = Mock()
    client.gemini.generate_content.side_effect = Exception("Gemini is down")
    client.openai_client = Mock()
    client.openai_client.chat.completions.create.side_effect = Exception("OpenAI is down too")

    with pytest.raises(RuntimeError, match="LLM providers are currently unavailable"):
        client.generate_content("some prompt")


def test_response_schema_is_passed_through_to_gemini(client):
    """Guards the Stage 1 wiring: response_schema in generation_config
    must actually reach the underlying Gemini client call."""
    client.use_gemini = True
    client.gemini = Mock()
    client.gemini.generate_content.return_value = type("LLMResponse", (), {"text": "{}"})()

    class FakeSchema:
        pass

    client.generate_content("some prompt", generation_config={"response_schema": FakeSchema})

    _, kwargs = client.gemini.generate_content.call_args
    assert kwargs["generation_config"]["response_schema"] is FakeSchema


@pytest.mark.api
def test_live_gemini_call_returns_real_text():
    """Real, unmocked call to the live Gemini API. Excluded by default -
    run explicitly with: pytest -m api"""
    from src.utils.llm import get_llm

    llm = get_llm()
    result = llm.generate_content("Say 'contract test ok' and nothing else.")

    assert hasattr(result, "text")
    assert len(result.text.strip()) > 0
    assert "Error generating response" not in result.text