"""
Integration tests for Orchestrator Agent
"""
import pytest
from unittest.mock import Mock, patch

from src.orchestrator import ERPOrchestratorAgent, ProjectPhase, orchestrator
from src.memory import agent_memory


class TestOrchestratorAgent:
    """Test suite for Orchestrator Agent"""
    
    def test_orchestrator_initialization(self):
        """Test orchestrator initializes correctly"""
        orch = ERPOrchestratorAgent()
        assert orch.logger is not None
        assert orch.model is not None
        assert len(orch.phase_workflow) == 6
    
    def test_phase_workflow_mapping(self):
        """Test phase workflow is correctly mapped"""
        orch = ERPOrchestratorAgent()
        
        # Check all phases are present
        expected_phases = [
            ProjectPhase.REQUIREMENTS_GATHERING,
            ProjectPhase.PROCESS_MAPPING,
            ProjectPhase.SOLUTION_DESIGN,
            ProjectPhase.QA_TESTING,
            ProjectPhase.UAT_TESTING,
            ProjectPhase.TRAINING
        ]
        
        for phase in expected_phases:
            assert phase in orch.phase_workflow
            workflow_info = orch.phase_workflow[phase]
            assert 'agent' in workflow_info
            assert 'method' in workflow_info
            assert 'next_phase' in workflow_info
    
    def test_start_project(self):
        """Test project creation"""
        orch = ERPOrchestratorAgent()
        
        result = orch.start_project(
            project_name="Test Orchestrator Project",
            module="FI",
            erp_system="SAP S/4HANA"
        )
        
        assert result['success'] == True
        assert 'session_id' in result
        assert result['project_name'] == "Test Orchestrator Project"
        
        # Cleanup
        session_id = result['session_id']
        agent_memory.session_service.delete_session(session_id)
    
    def test_get_project_status(self):
        """Test project status retrieval"""
        orch = ERPOrchestratorAgent()
        
        # Create test project
        result = orch.start_project(
            project_name="Status Test Project",
            module="MM",
            erp_system="SAP S/4HANA"
        )
        
        session_id = result['session_id']
        
        # Get status
        status = orch.get_project_status(session_id)
        
        assert 'session_id' in status
        assert status['project_name'] == "Status Test Project"
        assert status['module'] == "MM"
        assert 'current_phase' in status
        assert 'progress_percentage' in status
        
        # Cleanup
        agent_memory.session_service.delete_session(session_id)
    
    def test_generate_project_summary(self):
        """Test project summary generation"""
        orch = ERPOrchestratorAgent()
        
        # Create test project
        result = orch.start_project(
            project_name="Summary Test",
            module="SD",
            erp_system="SAP S/4HANA"
        )
        
        session_id = result['session_id']
        
        # Generate summary
        summary = orch.generate_project_summary(session_id)
        
        assert 'project_info' in summary
        assert summary['project_info']['name'] == "Summary Test"
        assert 'phases_completed' in summary
        assert 'deliverables' in summary
        
        # Cleanup
        agent_memory.session_service.delete_session(session_id)
    
    def test_get_next_phase(self):
        """Test next phase determination"""
        orch = ERPOrchestratorAgent()
        
        next_phase = orch._get_next_phase(ProjectPhase.REQUIREMENTS_GATHERING.value)
        assert next_phase == ProjectPhase.PROCESS_MAPPING.value
        
        next_phase = orch._get_next_phase(ProjectPhase.TRAINING.value)
        assert next_phase == ProjectPhase.COMPLETED.value


class TestWorkflowIntegration:
    """Integration tests for complete workflow"""
    
    @pytest.fixture
    def workflow_session(self):
        """Create session for workflow testing"""
        session_id = agent_memory.create_project(
            project_name="Workflow Integration Test",
            module="FI",
            erp_system="SAP S/4HANA"
        )
        yield session_id
        agent_memory.session_service.delete_session(session_id)
    
    @patch('src.agents.requirements_agent.RequirementsAgent.gather_requirements')
    def test_requirements_phase_execution(self, mock_gather, workflow_session):
        """Test requirements phase execution"""
        
        # Mock the requirements gathering
        mock_gather.return_value = {
            'success': True,
            'requirements': {
                'executive_summary': 'Test',
                'functional_requirements': {}
            },
            'document_path': '/test/path.md',
            'duration': 1.0
        }
        
        orch = ERPOrchestratorAgent()
        
        result = orch.execute_requirements_phase(
            session_id=workflow_session,
            stakeholder_input="Test requirements"
        )
        
        assert result['success'] == True
        
        # Verify phase advanced
        session = agent_memory.session_service.get_session(workflow_session)
        assert session.current_phase == ProjectPhase.PROCESS_MAPPING.value
    
    @patch('src.agents.process_mapping_agent.ProcessMappingAgent.map_process')
    @patch('src.agents.requirements_agent.RequirementsAgent.gather_requirements')
    def test_process_mapping_phase_execution(self, mock_gather, mock_map, workflow_session):
        """Test process mapping phase execution"""
        
        # Mock requirements
        mock_gather.return_value = {
            'success': True,
            'requirements': {'functional_requirements': {}},
            'document_path': '/test/req.md',
            'duration': 1.0
        }
        
        # Execute requirements first
        orch = ERPOrchestratorAgent()
        orch.execute_requirements_phase(workflow_session, "Test input")
        
        # Mock process mapping
        mock_map.return_value = {
            'success': True,
            'process_map': {'steps': []},
            'duration': 1.0
        }
        
        # Execute process mapping
        result = orch.execute_process_mapping_phase(
            session_id=workflow_session,
            process_name="Test Process"
        )
        
        assert result['success'] == True
        
        # Verify phase advanced
        session = agent_memory.session_service.get_session(workflow_session)
        assert session.current_phase == ProjectPhase.SOLUTION_DESIGN.value
    
    def test_workflow_phase_dependencies(self):
        """Test that phases enforce dependencies"""
        orch = ERPOrchestratorAgent()
        
        # Create new session
        result = orch.start_project(
            project_name="Dependency Test",
            module="MM",
            erp_system="SAP S/4HANA"
        )
        
        session_id = result['session_id']
        
        # Try to execute solution design without requirements
        result = orch.execute_solution_design_phase(session_id)
        
        assert result['success'] == False
        assert 'error' in result
        
        # Cleanup
        agent_memory.session_service.delete_session(session_id)


class TestErrorHandling:
    """Test error handling in orchestrator"""
    
    def test_invalid_session_handling(self):
        """Test handling of invalid session IDs"""
        orch = ERPOrchestratorAgent()
        
        status = orch.get_project_status("invalid_session_id")
        assert 'error' in status
    
    def test_missing_requirements_handling(self):
        """Test handling of missing requirements"""
        orch = ERPOrchestratorAgent()
        
        # Create session without requirements
        session_id = agent_memory.create_project(
            project_name="Error Test",
            module="FI",
            erp_system="SAP S/4HANA"
        )
        
        # Try to execute process mapping without requirements
        result = orch.execute_process_mapping_phase(session_id)
        
        assert result['success'] == False
        assert 'Requirements not found' in result['error']
        
        # Cleanup
        agent_memory.session_service.delete_session(session_id)


@pytest.fixture(scope="module", autouse=True)
def setup_integration_tests():
    """Setup for integration tests"""
    from src.utils.logger import setup_logging
    setup_logging()
    yield


class TestPhaseHardening:
    """Tests for the orchestration-hardening added in this stage: phase
    calls are time-bounded and exceptions are contained instead of
    propagating, and every phase now records execution metrics."""

    @pytest.fixture
    def hardening_session(self):
        session_id = agent_memory.create_project(
            project_name="Hardening Test",
            module="FI",
            erp_system="SAP S/4HANA"
        )
        yield session_id
        agent_memory.session_service.delete_session(session_id)

    @patch('src.agents.requirements_agent.RequirementsAgent.gather_requirements')
    def test_unexpected_agent_exception_is_contained_not_raised(self, mock_gather, hardening_session):
        """An agent raising an unexpected exception (not returning a
        {'success': False} dict, an actual crash) must come back as a
        structured failure, never propagate out of the orchestrator."""
        mock_gather.side_effect = RuntimeError("boom - unexpected agent crash")

        orch = ERPOrchestratorAgent()
        result = orch.execute_requirements_phase(
            session_id=hardening_session,
            stakeholder_input="Test requirements"
        )

        assert result['success'] is False
        assert 'boom - unexpected agent crash' in result['error']
        assert 'duration' in result

        # Session must not have silently advanced past a failed phase
        session = agent_memory.session_service.get_session(hardening_session)
        assert session.current_phase == ProjectPhase.REQUIREMENTS_GATHERING.value

    @patch('src.agents.requirements_agent.RequirementsAgent.gather_requirements')
    def test_phase_exceeding_timeout_is_stopped_and_reported(self, mock_gather, hardening_session):
        """A hung agent call must not block the caller past the configured
        phase timeout - it should come back as a clear, user-facing
        timeout message instead of hanging indefinitely."""
        import time as time_module

        def hangs(*args, **kwargs):
            time_module.sleep(2)
            return {'success': True}

        mock_gather.side_effect = hangs

        orch = ERPOrchestratorAgent()
        with patch('src.orchestrator.settings.timeout_seconds', 0.1):
            result = orch.execute_requirements_phase(
                session_id=hardening_session,
                stakeholder_input="Test requirements"
            )

        assert result['success'] is False
        assert 'longer than expected' in result['error']

    @patch('src.agents.requirements_agent.RequirementsAgent.gather_requirements')
    def test_successful_phase_records_metrics(self, mock_gather, hardening_session):
        from src.utils.logger import metrics_collector

        mock_gather.return_value = {
            'success': True,
            'requirements': {'executive_summary': 'ok'},
            'document_path': '/test/path.md',
        }

        before = len(metrics_collector.tasks) if hasattr(metrics_collector, 'tasks') else None

        orch = ERPOrchestratorAgent()
        result = orch.execute_requirements_phase(
            session_id=hardening_session,
            stakeholder_input="Test requirements"
        )

        assert result['success'] is True
        assert 'duration' in result  # added by _call_agent_safely if the agent didn't set one
        if before is not None:
            assert len(metrics_collector.tasks) == before + 1