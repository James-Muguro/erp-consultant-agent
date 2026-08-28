
"""
Unit tests for Requirements Agent
"""
import pytest
from unittest.mock import Mock, patch, MagicMock

from src.agents.requirements_agent import RequirementsAgent, requirements_agent
from src.memory import agent_memory


class TestRequirementsAgent:
    """Test suite for Requirements Agent"""
    
    @pytest.fixture
    def sample_stakeholder_input(self):
        """Sample stakeholder input for testing"""
        return """
        We need to implement Purchase Order processing with the following features:
        - Create and approve purchase orders
        - Three-way matching
        - Vendor management
        - Budget checking
        - Automated notifications
        """
    
    @pytest.fixture
    def test_session_id(self):
        """Create test session"""
        session_id = agent_memory.create_project(
            project_name="Test Project",
            module="MM",
            erp_system="SAP S/4HANA"
        )
        yield session_id
        # Cleanup
        agent_memory.session_service.delete_session(session_id)
    
    def test_agent_initialization(self):
        """Test that agent initializes correctly"""
        agent = RequirementsAgent()
        assert agent.config is not None
        assert agent.logger is not None
        assert agent.model is not None
    
    def test_parse_requirements(self):
        """Test requirements parsing"""
        agent = RequirementsAgent()
        
        sample_text = """
        # Executive Summary
        This project implements AP functionality.
        
        ## Functional Requirements
        - REQ-001: Process vendor invoices
        - REQ-002: Automated payment runs
        
        ## Technical Requirements
        - Integration with procurement system
        """
        
        parsed = agent._parse_requirements(sample_text)
        
        assert 'executive_summary' in parsed
        assert 'functional_requirements' in parsed
        assert 'technical_requirements' in parsed
    
    def test_validate_requirements(self):
        """Test requirements validation"""
        agent = RequirementsAgent()
        
        # Valid requirements
        valid_reqs = {
            'executive_summary': 'Test summary',
            'business_context': 'Test context',
            'functional_requirements': {
                'general': [
                    {'id': 'REQ-001', 'description': 'Test req', 'priority': 'High'}
                ]
            }
        }
        
        validation = agent.validate_requirements(valid_reqs)
        assert validation['is_valid'] == True
        assert validation['completeness_score'] > 0
        
        # Invalid requirements (missing required sections)
        invalid_reqs = {}
        validation = agent.validate_requirements(invalid_reqs)
        assert validation['is_valid'] == False
        assert len(validation['issues']) > 0
    
    def test_gather_requirements_success(self, test_session_id, sample_stakeholder_input):
        """Test successful requirements gathering"""
        # Mock the Gemini API response with schema-conformant JSON,
        # matching what the real Gemini structured-output call returns
        mock_response = Mock()
        mock_response.text = """{
            "executive_summary": "Implementing Purchase Order management system.",
            "business_context": "Procurement needs a standardized PO workflow.",
            "objectives": ["Reduce manual PO errors"],
            "functional_requirements": [
                {
                    "category": "Purchase Order Management",
                    "requirements": [
                        {"id": "REQ-001", "description": "Create purchase orders", "priority": "High", "type": "Functional"},
                        {"id": "REQ-002", "description": "Approve purchase orders", "priority": "High", "type": "Functional"},
                        {"id": "REQ-003", "description": "Three-way matching", "priority": "High", "type": "Functional"}
                    ]
                }
            ],
            "technical_requirements": [],
            "integration_requirements": [],
            "reporting_requirements": [],
            "dependencies": [],
            "constraints": [],
            "assumptions": []
        }"""
        
        mock_model_instance = Mock()
        mock_model_instance.generate_content.return_value = mock_response
        
        agent = RequirementsAgent()
        agent.model = mock_model_instance
        
        result = agent.gather_requirements(
            session_id=test_session_id,
            project_name="Test Project",
            module="MM",
            stakeholder_input=sample_stakeholder_input,
            erp_system="SAP S/4HANA"
        )
        
        assert result['success'] == True
        assert 'requirements' in result
        assert 'document_path' in result
        assert result['duration'] >= 0
        # Confirm schema-validated parsing actually ran, not the fallback
        func_reqs = result['requirements']['functional_requirements']
        assert 'Purchase Order Management' in func_reqs
        assert len(func_reqs['Purchase Order Management']) == 3
    
    def test_build_context(self):
        """Test context building"""
        agent = RequirementsAgent()
        
        module_info = {
            'name': 'Materials Management',
            'description': 'Test module',
            'sub_modules': ['Purchasing', 'Inventory'],
            'common_transactions': ['ME21N', 'MIGO'],
            'integration_points': ['FI', 'SD'],
            'best_practices': ['Best practice 1']
        }
        
        context = agent._build_context(
            module_info=module_info,
            best_practices=['Practice 1', 'Practice 2'],
            template='Test template',
            past_learnings=[]
        )
        
        assert 'Materials Management' in context
        assert 'ME21N' in context
        assert 'Best practice' in context or 'Practice' in context


class TestRequirementsIntegration:
    """Integration tests for Requirements Agent"""
    
    @pytest.fixture
    def integration_session_id(self):
        """Create integration test session"""
        session_id = agent_memory.create_project(
            project_name="Integration Test",
            module="FI",
            erp_system="SAP S/4HANA"
        )
        yield session_id
        agent_memory.session_service.delete_session(session_id)
    
    def test_end_to_end_requirements_workflow(self, integration_session_id):
        """Test complete requirements gathering workflow"""
        
        stakeholder_input = """
        We need to automate our Accounts Payable process:
        - Electronic invoice processing
        - Automated approval workflows
        - Payment automation
        - Vendor management
        """
        
        # This would call the real API - comment out if you want to avoid API calls
        # result = requirements_agent.gather_requirements(
        #     session_id=integration_session_id,
        #     project_name="Integration Test",
        #     module="FI",
        #     stakeholder_input=stakeholder_input
        # )
        # 
        # assert result['success'] == True
        
        # For now, just verify the session exists
        session = agent_memory.session_service.get_session(integration_session_id)
        assert session is not None
        assert session.project_name == "Integration Test"


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Setup test environment"""
    from src.utils.logger import setup_logging
    setup_logging()
    yield
    # Cleanup after all tests
