"""
Unit test for Process Mapping Agent - covers the schema-validated
happy path added in Stage 1.
"""
from unittest.mock import Mock
from src.agents.process_mapping_agent import ProcessMappingAgent


def test_map_process_success():
    mock_response = Mock()
    mock_response.text = """{
        "overview": "Standard procure-to-pay process.",
        "scope": "Purchase requisition through vendor payment.",
        "roles": ["Procurement Buyer", "Finance Manager"],
        "steps": [
            {"number": 1, "name": "Create Purchase Requisition", "description": "Requisitioner creates PR.", "transaction": "ME51N", "responsible_role": "Requisitioner"},
            {"number": 2, "name": "Approve Requisition", "description": "Manager approves PR.", "transaction": "ME54N", "responsible_role": "Approver"}
        ],
        "decision_points": ["Requisition approval threshold check"],
        "integration_points": ["Vendor master sync"],
        "exceptions": ["Requisition rejected"],
        "improvements": ["Auto-approval for low-value requisitions"]
    }"""

    mock_model_instance = Mock()
    mock_model_instance.generate_content.return_value = mock_response

    agent = ProcessMappingAgent()
    agent.model = mock_model_instance

    result = agent.map_process(
        session_id="test_process_mapping_session",
        process_name="Procure to Pay",
        requirements={"module": "MM", "functional_requirements": {}, "integration_requirements": []},
        current_state="Manual PO creation"
    )

    assert result['success'] is True
    steps = result['process_map']['steps']
    assert len(steps) == 2
    assert steps[0]['name'] == "Create Purchase Requisition"
    assert result['process_map']['roles'] == ["Procurement Buyer", "Finance Manager"]