from unittest.mock import Mock, patch
import pytest

from src.tools.info_retriever import retrieve


@pytest.fixture(autouse=True)
def mock_dependencies():
    """Patch every external dependency info_retriever.retrieve touches, so
    each test controls exactly one thing: the reasoning decision, and what
    each source returns."""
    with patch("src.tools.info_retriever.reasoning_tool") as mock_reasoning, \
         patch("src.tools.info_retriever.erp_kb") as mock_kb, \
         patch("src.tools.info_retriever.memory_bank") as mock_memory, \
         patch("src.tools.info_retriever.google_search_tool") as mock_google:
        mock_kb.search_knowledge.return_value = []
        mock_memory.search_by_keywords.return_value = []
        mock_google_instance = Mock(return_value="web search result text")
        mock_google.GoogleSearchTool.return_value = mock_google_instance
        yield {
            "reasoning": mock_reasoning,
            "kb": mock_kb,
            "memory": mock_memory,
            "google": mock_google,
            "google_instance": mock_google_instance,
        }


class TestDecisionRouting:
    def test_kb_decision_only_queries_kb_and_memory_not_web(self, mock_dependencies):
        mock_dependencies["reasoning"].assess_source.return_value = {
            'decision': 'kb', 'confidence': 0.8, 'reasoning': 'internal question'
        }

        result = retrieve("what is a GL account?")

        mock_dependencies["kb"].search_knowledge.assert_called_once()
        mock_dependencies["memory"].search_by_keywords.assert_called_once()
        mock_dependencies["google_instance"].assert_not_called()
        assert result['web_results'] == []

    def test_web_decision_only_queries_web_not_kb(self, mock_dependencies):
        mock_dependencies["reasoning"].assess_source.return_value = {
            'decision': 'web', 'confidence': 0.9, 'reasoning': 'needs current info'
        }

        result = retrieve("latest SAP release date")

        mock_dependencies["kb"].search_knowledge.assert_not_called()
        mock_dependencies["memory"].search_by_keywords.assert_not_called()
        mock_dependencies["google_instance"].assert_called_once()
        assert result['web_results'] == ["web search result text"]

    def test_hybrid_decision_queries_both(self, mock_dependencies):
        mock_dependencies["reasoning"].assess_source.return_value = {
            'decision': 'hybrid', 'confidence': 0.7, 'reasoning': 'mixed'
        }

        retrieve("query")

        mock_dependencies["kb"].search_knowledge.assert_called_once()
        mock_dependencies["google_instance"].assert_called_once()

    def test_prefer_web_bypasses_reasoning_tool_entirely(self, mock_dependencies):
        retrieve("query", prefer_web=True)

        mock_dependencies["reasoning"].assess_source.assert_not_called()
        mock_dependencies["google_instance"].assert_called_once()

    def test_prefer_web_result_decision_is_recorded_as_web(self, mock_dependencies):
        result = retrieve("query", prefer_web=True)
        assert result['decision']['decision'] == 'web'


class TestResultAggregation:
    def test_kb_hits_are_added_to_kb_results_and_sources(self, mock_dependencies):
        mock_dependencies["reasoning"].assess_source.return_value = {'decision': 'kb', 'confidence': 0.8, 'reasoning': 'x'}
        mock_dependencies["kb"].search_knowledge.return_value = [{'title': 'GL Accounts', 'content': '...'}]

        result = retrieve("query")

        assert result['kb_results'] == [{'title': 'GL Accounts', 'content': '...'}]
        assert any(s['type'] == 'kb' for s in result['sources'])

    def test_empty_kb_hits_do_not_add_a_kb_source_entry(self, mock_dependencies):
        """search_knowledge returning [] should not add a misleading empty
        'kb' source entry - only a real hit does."""
        mock_dependencies["reasoning"].assess_source.return_value = {'decision': 'kb', 'confidence': 0.8, 'reasoning': 'x'}
        mock_dependencies["kb"].search_knowledge.return_value = []

        result = retrieve("query")

        assert not any(s['type'] == 'kb' for s in result['sources'])

    def test_memory_hits_are_converted_to_dicts_and_added(self, mock_dependencies):
        mock_dependencies["reasoning"].assess_source.return_value = {'decision': 'kb', 'confidence': 0.8, 'reasoning': 'x'}
        fake_memory_item = Mock()
        fake_memory_item.to_dict.return_value = {'summary': 'a past decision'}
        mock_dependencies["memory"].search_by_keywords.return_value = [fake_memory_item]

        result = retrieve("query")

        assert {'summary': 'a past decision'} in result['kb_results']
        assert any(s['type'] == 'memory' for s in result['sources'])

    def test_web_search_failure_is_caught_and_does_not_propagate(self, mock_dependencies):
        mock_dependencies["reasoning"].assess_source.return_value = {'decision': 'web', 'confidence': 0.9, 'reasoning': 'x'}
        mock_dependencies["google_instance"].side_effect = Exception("search API down")

        result = retrieve("query")  # must not raise

        assert result['web_results'] == []
        assert any(s['type'] == 'web' and s['items'] == [] for s in result['sources'])

    def test_result_includes_the_original_query_and_decision(self, mock_dependencies):
        mock_dependencies["reasoning"].assess_source.return_value = {'decision': 'kb', 'confidence': 0.8, 'reasoning': 'x'}
        result = retrieve("what is a GL account?")
        assert result['query'] == "what is a GL account?"
        assert result['decision']['decision'] == 'kb'

    def test_context_summary_is_passed_through_to_reasoning_tool(self, mock_dependencies):
        mock_dependencies["reasoning"].assess_source.return_value = {'decision': 'kb', 'confidence': 0.8, 'reasoning': 'x'}
        retrieve("query", context={'summary': 'ongoing FI implementation'})
        mock_dependencies["reasoning"].assess_source.assert_called_once_with(
            "query", 'ongoing FI implementation'
        )
