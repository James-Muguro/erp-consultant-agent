"""
Unit test for Training Agent - covers the schema-validated happy path
added in Stage 1, including the UserManualField sub-schema fix (the
one bug found live during Stage 1b validation).
"""
from unittest.mock import Mock
from src.agents.training_agent import TrainingAgent


def test_create_training_materials_success():
    mock_response = Mock()
    mock_response.text = """{
        "user_manual": {
            "steps": [
                {
                    "title": "Create Purchase Requisition",
                    "transaction": "ME51N",
                    "instructions": "Navigate to Procurement and create a new requisition.",
                    "fields": [
                        {"name": "Requisitioner", "description": "Employee requesting the item.", "required": "True", "example": "EMP-001"}
                    ],
                    "tips": ["Use F4 search to find material codes."]
                }
            ],
            "tips": ["Save drafts frequently."],
            "faqs": ["What if my requisition is rejected?"]
        },
        "training_guide": {
            "objectives": ["Understand the PR creation process."],
            "agenda": ["Introduction", "Hands-on practice"],
            "exercises": ["Create a sample requisition."]
        },
        "quick_reference": "See the quick reference card for transaction codes.",
        "sop": "Standard operating procedure for requisition creation."
    }"""

    mock_model_instance = Mock()
    mock_model_instance.generate_content.return_value = mock_response

    agent = TrainingAgent()
    agent.model = mock_model_instance

    result = agent.create_training_materials(
        session_id="test_training_session",
        process_name="Procure to Pay",
        user_roles=["Procurement Buyer"],
        solution_design={"configurations": []}
    )

    assert result['success'] is True
    steps = result['training_materials']['user_manual']['steps']
    assert len(steps) == 1
    assert steps[0]['transaction'] == "ME51N"
    # Confirm the UserManualField sub-schema fix - fields must be dicts, not strings
    assert steps[0]['fields'][0]['name'] == "Requisitioner"