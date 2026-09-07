from unittest.mock import Mock, patch
import pytest

from src.tools.reasoning import ReasoningTool


@pytest.fixture
def tool():
    with patch("src.tools.reasoning.get_llm") as mock_get_llm:
        mock_get_llm.return_value = Mock()
        t = ReasoningTool()
        yield t


def _llm_returns(tool, text):
    tool.model.generate_content.return_value = type("LLMResponse", (), {"text": text})()


class TestAssessSource:
    def test_detects_kb_decision(self, tool):
        _llm_returns(tool, "I recommend using the internal kb for this. Confidence: 0.8")
        result = tool.assess_source("what is a GL account?")
        assert result['decision'] == 'kb'

    def test_detects_hybrid_decision_even_when_kb_also_mentioned(self, tool):
        """The prompt asks the model to pick one of kb/web/hybrid, but real
        model output often mentions multiple - hybrid should win when it's
        present since the code checks it last (see assess_source)."""
        _llm_returns(tool, "This could use the kb but a hybrid approach with web is best. 0.7")
        result = tool.assess_source("query")
        assert result['decision'] == 'hybrid'

    def test_defaults_to_web_when_neither_kb_nor_hybrid_mentioned(self, tool):
        _llm_returns(tool, "A web search is best here. 0.9")
        result = tool.assess_source("latest SAP pricing")
        assert result['decision'] == 'web'

    def test_extracts_confidence_float_from_response_text(self, tool):
        _llm_returns(tool, "decision: web reasoning: because 0.65 seems right")
        result = tool.assess_source("query")
        assert result['confidence'] == 0.65

    def test_defaults_confidence_when_no_valid_float_present(self, tool):
        _llm_returns(tool, "web search, no numbers here")
        result = tool.assess_source("query")
        assert result['confidence'] == 0.5

    def test_ignores_out_of_range_numbers_when_extracting_confidence(self, tool):
        """A model might mention '2024' or similar - only a 0-1 float should
        be picked up as the confidence value."""
        _llm_returns(tool, "web search in 2024 confidence 0.3")
        result = tool.assess_source("query")
        assert result['confidence'] == 0.3

    def test_llm_failure_falls_back_to_web_with_low_confidence(self, tool):
        tool.model.generate_content.side_effect = Exception("LLM unavailable")
        result = tool.assess_source("query")
        assert result['decision'] == 'web'
        assert result['confidence'] == 0.4
        assert 'fallback' in result['reasoning']


class TestMakePlan:
    def test_parses_numbered_steps(self, tool):
        _llm_returns(tool, "Steps:\n1. Gather requirements\n2. Map process\n3. Design solution\n\nJustification: logical order")
        result = tool.make_plan("plan an implementation")
        assert result['steps'] == ['Gather requirements', 'Map process', 'Design solution']

    def test_blank_lines_in_response_do_not_crash(self, tool):
        """Regression test for a real bug: a blank line used to raise
        IndexError from `stripped.split()[0]` on an empty list. The
        prompt template itself produces a blank line between the numbered
        steps and the Justification section, so this reproduces reliably
        with normal, well-formed LLM output - not just malformed edge
        cases."""
        _llm_returns(tool, "Steps:\n1. First step\n\n2. Second step\n\nJustification: because")
        result = tool.make_plan("instruction")
        assert result['steps'] == ['First step', 'Second step']

    def test_falls_back_to_first_six_nonblank_lines_when_no_numbered_steps_found(self, tool):
        _llm_returns(tool, "Do this\nThen that\nThen the other thing")
        result = tool.make_plan("instruction")
        assert result['steps'] == ['Do this', 'Then that', 'Then the other thing']

    def test_extracts_justification_section(self, tool):
        _llm_returns(tool, "Steps:\n1. Step one\n\nJustification: this order minimizes risk")
        result = tool.make_plan("instruction")
        assert 'minimizes risk' in result['justification']

    def test_llm_failure_returns_empty_plan_with_fallback_justification(self, tool):
        tool.model.generate_content.side_effect = Exception("LLM unavailable")
        result = tool.make_plan("instruction")
        assert result['steps'] == []
        assert 'fallback' in result['justification']


class TestReloadModel:
    def test_reload_model_refetches_the_llm_singleton(self, tool):
        with patch("src.tools.reasoning.get_llm") as mock_get_llm:
            new_mock = Mock()
            mock_get_llm.return_value = new_mock
            tool.reload_model()
            assert tool.model is new_mock
