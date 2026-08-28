"""
Unit test for Solution Design Agent - covers the schema-validated
happy path added in Stage 1, including the master_data/technical_specs
dict-reshaping in to_legacy_dict().
"""
from unittest.mock import Mock
from src.agents.solution_design_agent import SolutionDesignAgent


def test_design_solution_success():
    mock_response = Mock()
    mock_response.text = """{
        "executive_summary": "Solution uses standard SAP MM functionality.",
        "architecture_overview": "Single-instance S/4HANA deployment.",
        "configurations": [
            {"component": "PO Approval Workflow", "description": "Workflow config.", "steps": ["Define approval limits", "Assign approvers"]}
        ],
        "master_data": [
            {"data_type": "Vendor Master", "details": "Standard vendor master with tax fields."}
        ],
        "integrations": [
            {"name": "Vendor Portal", "type": "Real-time", "source": "S/4HANA", "target": "Vendor Portal", "description": "PO dispatch integration."}
        ],
        "security": {"overview": "RBAC via SoD matrix."},
        "customizations": [
            {"type": "Enhancement", "component": "PO Form", "description": "Custom PO layout.", "justification": "Regulatory requirement."}
        ],
        "migration": {"strategy": "Phased cutover by plant."},
        "technical_specs": [
            {"name": "Uptime SLA", "value": "99.9%"}
        ]
    }"""

    mock_model_instance = Mock()
    mock_model_instance.generate_content.return_value = mock_response

    agent = SolutionDesignAgent()
    agent.model = mock_model_instance

    result = agent.design_solution(
        session_id="test_solution_design_session",
        requirements={"module": "MM", "functional_requirements": {}, "integration_requirements": []},
        process_maps={},
        erp_system="SAP S/4HANA"
    )

    assert result['success'] is True
    design = result['design']
    assert len(design['configurations']) == 1
    # Confirm the arbitrary-key dict reshaping worked correctly
    assert design['master_data'] == {"Vendor Master": "Standard vendor master with tax fields."}
    assert design['technical_specs'] == {"Uptime SLA": "99.9%"}