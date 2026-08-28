"""
Unit tests for QA and UAT Testing Agents - covers the schema-validated
happy path added in Stage 1. The UAT test in particular guards against
the bug found and fixed in Stage 1b, where real Gemini output was
previously discarded and replaced with hardcoded generic scenarios.
"""
from unittest.mock import Mock
from src.agents.testing_agents import QATestingAgent, UATTestingAgent


SAMPLE_TEST_CASES_JSON = """{
    "test_cases": [
        {
            "id": "TC-001",
            "scenario": "Create and approve Purchase Order",
            "priority": "High",
            "type": "Functional",
            "objective": "Verify PO creation and approval flow.",
            "preconditions": ["User has Procurement role"],
            "steps": ["Navigate to Purchase Orders", "Create new PO", "Submit for approval"],
            "test_data": [{"key": "vendor_id", "value": "VEND-001"}],
            "expected_result": "PO status changes to Approved."
        }
    ]
}"""


def test_qa_generate_test_cases_success():
    mock_response = Mock()
    mock_response.text = SAMPLE_TEST_CASES_JSON

    mock_model_instance = Mock()
    mock_model_instance.generate_content.return_value = mock_response

    agent = QATestingAgent()
    agent.model = mock_model_instance

    result = agent.generate_test_cases(
        session_id="test_qa_session",
        solution_design={"configurations": [], "integrations": []},
        module="MM",
        scope="comprehensive"
    )

    assert result['success'] is True
    assert len(result['test_cases']) == 1
    assert result['test_cases'][0]['scenario'] == "Create and approve Purchase Order"
    assert result['test_cases'][0]['test_data'] == {"vendor_id": "VEND-001"}


def test_uat_generate_scenarios_uses_real_llm_output_not_generic_fallback():
    """This is the regression guard for the Stage 1b bug: UAT scenarios
    must come from the actual Gemini response, not the hardcoded
    'Log into the system / Navigate to the module' placeholder."""
    mock_response = Mock()
    mock_response.text = SAMPLE_TEST_CASES_JSON

    mock_model_instance = Mock()
    mock_model_instance.generate_content.return_value = mock_response

    agent = UATTestingAgent()
    agent.model = mock_model_instance

    result = agent.generate_uat_scenarios(
        session_id="test_uat_session",
        business_processes={"Procure to Pay": {"structured": {"steps": [{"name": "Create PO"}]}}},
        user_roles=["Procurement Buyer"]
    )

    assert result['success'] is True
    scenarios = result['uat_scenarios']
    assert len(scenarios) == 1
    # This is the real Gemini-derived scenario, not the generic placeholder
    assert scenarios[0]['scenario'] == "Create and approve Purchase Order"
    assert "Log into the system" not in scenarios[0]['steps']