"""
Orchestrator Agent - Coordinates all specialized agents and manages workflow
"""
from src.utils.llm import get_llm
from typing import Dict, List, Any, Optional
import time
from enum import Enum

from src.config.settings import settings
from src.utils.logger import AgentLogger, metrics_collector
from src.utils.prompts import ORCHESTRATOR_SYSTEM_PROMPT
from src.memory import agent_memory
from src.agents import (
    requirements_agent,
    process_mapping_agent,
    solution_design_agent,
    qa_testing_agent,
    uat_testing_agent,
    training_agent
)


class ProjectPhase(Enum):
    """ERP project phases"""
    REQUIREMENTS_GATHERING = "requirements_gathering"
    PROCESS_MAPPING = "process_mapping"
    SOLUTION_DESIGN = "solution_design"
    QA_TESTING = "qa_testing"
    UAT_TESTING = "uat_testing"
    TRAINING = "training"
    COMPLETED = "completed"


class ERPOrchestratorAgent:
    """
    Orchestrator agent that manages the complete ERP consulting workflow
    """
    
    def __init__(self):
        self.logger = AgentLogger("OrchestratorAgent")
        
        # Get the singleton model instance
        self.model = get_llm()
        
        # Phase workflow mapping
        self.phase_workflow = {
            ProjectPhase.REQUIREMENTS_GATHERING: {
                'agent': requirements_agent,
                'method': 'gather_requirements',
                'next_phase': ProjectPhase.PROCESS_MAPPING,
                'description': 'Gather and document requirements'
            },
            ProjectPhase.PROCESS_MAPPING: {
                'agent': process_mapping_agent,
                'method': 'map_process',
                'next_phase': ProjectPhase.SOLUTION_DESIGN,
                'description': 'Create business process maps'
            },
            ProjectPhase.SOLUTION_DESIGN: {
                'agent': solution_design_agent,
                'method': 'design_solution',
                'next_phase': ProjectPhase.QA_TESTING,
                'description': 'Design ERP solution'
            },
            ProjectPhase.QA_TESTING: {
                'agent': qa_testing_agent,
                'method': 'generate_test_cases',
                'next_phase': ProjectPhase.UAT_TESTING,
                'description': 'Generate QA test cases'
            },
            ProjectPhase.UAT_TESTING: {
                'agent': uat_testing_agent,
                'method': 'generate_uat_scenarios',
                'next_phase': ProjectPhase.TRAINING,
                'description': 'Create UAT scenarios'
            },
            ProjectPhase.TRAINING: {
                'agent': training_agent,
                'method': 'create_training_materials',
                'next_phase': ProjectPhase.COMPLETED,
                'description': 'Generate training materials'
            }
        }
        
        self.logger.info("Orchestrator Agent initialized")
    
    def start_project(
        self,
        project_name: str,
        module: str,
        erp_system: str = "SAP S/4HANA",
        initial_input: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Start a new ERP consulting project
        
        Args:
            project_name: Name of the project
            module: ERP module (e.g., 'FI', 'MM', 'SD')
            erp_system: Target ERP system
            initial_input: Initial stakeholder input
            user_id: Owning user's id (None for CLI/no-auth callers)
            
        Returns:
            Project summary with session ID
        """
        start_time = time.time()
        
        self.logger.log_agent_start(
            "start_project",
            {
                'project': project_name,
                'module': module,
                'erp_system': erp_system
            }
        )
        
        try:
            # Create new session
            session_id = agent_memory.create_project(
                project_name=project_name,
                module=module,
                erp_system=erp_system,
                user_id=user_id
            )
            
            self.logger.info(
                "Project created",
                session_id=session_id,
                project=project_name
            )
            
            # If initial input provided, start requirements gathering
            result = {'session_id': session_id, 'project_name': project_name}
            
            if initial_input:
                req_result = self.execute_requirements_phase(
                    session_id=session_id,
                    stakeholder_input=initial_input
                )
                result['requirements_result'] = req_result
            
            duration = time.time() - start_time
            metrics_collector.record_task("OrchestratorAgent", True, duration)
            
            return {
                'success': True,
                'session_id': session_id,
                'project_name': project_name,
                'module': module,
                'current_phase': ProjectPhase.REQUIREMENTS_GATHERING.value,
                'duration': duration,
                **result
            }
            
        except Exception as e:
            duration = time.time() - start_time
            self.logger.log_agent_error("start_project", e)
            metrics_collector.record_task("OrchestratorAgent", False, duration)
            
            return {
                'success': False,
                'error': str(e),
                'duration': duration
            }
    
    def execute_requirements_phase(
        self,
        session_id: str,
        stakeholder_input: str
    ) -> Dict[str, Any]:
        """Execute requirements gathering phase"""
        
        self.logger.info("Executing requirements phase", session_id=session_id)
        
        session = agent_memory.session_service.get_session(session_id)
        if not session:
            return {'success': False, 'error': 'Session not found'}
        
        # Execute requirements agent
        result = requirements_agent.gather_requirements(
            session_id=session_id,
            project_name=session.project_name,
            module=session.module,
            stakeholder_input=stakeholder_input,
            erp_system=session.erp_system
        )
        
        if result['success']:
            # Persist phase output if agent did not write it to memory (helpful for mocked tests)
            phase_output = agent_memory.get_phase_output(session_id, 'requirements_gathering')
            if not phase_output:
                structured = result.get('requirements') or result.get('structured_requirements') or {}
                doc_path = result.get('document_path')
                agent_memory.save_phase_output(
                    session_id,
                    'requirements_gathering',
                    {
                        'structured_requirements': structured,
                        'document_path': doc_path,
                        'raw_text': result.get('raw_text', '')
                    }
                )

            # Advance phase
            agent_memory.advance_phase(session_id, ProjectPhase.PROCESS_MAPPING.value)
            self.logger.info("Requirements phase completed", session_id=session_id)
        
        return result
    
    def execute_process_mapping_phase(
        self,
        session_id: str,
        process_name: Optional[str] = None,
        current_state: Optional[str] = None
    ) -> Dict[str, Any]:
        """Execute process mapping phase"""
        
        self.logger.info("Executing process mapping phase", session_id=session_id)
        
        session = agent_memory.session_service.get_session(session_id)
        if not session:
            return {'success': False, 'error': 'Session not found'}
        
        # Get requirements from previous phase
        requirements_output = agent_memory.get_phase_output(session_id, 'requirements_gathering')
        if not requirements_output:
            return {'success': False, 'error': 'Requirements not found. Complete requirements phase first.'}
        
        requirements = requirements_output.get('structured_requirements', {})
        
        # Use module name as process if not provided
        if not process_name:
            process_name = f"{session.module} Standard Process"
        
        # Execute process mapping agent
        result = process_mapping_agent.map_process(
            session_id=session_id,
            process_name=process_name,
            requirements=requirements,
            current_state=current_state,
            module=session.module,
            erp_system=session.erp_system
        )
        
        if result['success']:
            # Advance phase
            agent_memory.advance_phase(session_id, ProjectPhase.SOLUTION_DESIGN.value)
            self.logger.info("Process mapping phase completed", session_id=session_id)
        
        return result
    
    def execute_solution_design_phase(
        self,
        session_id: str
    ) -> Dict[str, Any]:
        """Execute solution design phase"""
        
        self.logger.info("Executing solution design phase", session_id=session_id)
        
        session = agent_memory.session_service.get_session(session_id)
        if not session:
            return {'success': False, 'error': 'Session not found'}
        
        # Get requirements and process maps
        requirements_output = agent_memory.get_phase_output(session_id, 'requirements_gathering')
        if not requirements_output:
            return {'success': False, 'error': 'Requirements not found'}
        
        requirements = requirements_output.get('structured_requirements', {})
        requirements['module'] = session.module
        
        process_maps = session.process_maps or {}
        
        # Execute solution design agent
        result = solution_design_agent.design_solution(
            session_id=session_id,
            requirements=requirements,
            process_maps=process_maps,
            erp_system=session.erp_system
        )
        
        if result['success']:
            # Advance phase
            agent_memory.advance_phase(session_id, ProjectPhase.QA_TESTING.value)
            self.logger.info("Solution design phase completed", session_id=session_id)
        
        return result
    
    def execute_qa_testing_phase(
        self,
        session_id: str,
        scope: str = "comprehensive"
    ) -> Dict[str, Any]:
        """Execute QA testing phase"""
        
        self.logger.info("Executing QA testing phase", session_id=session_id)
        
        session = agent_memory.session_service.get_session(session_id)
        if not session:
            return {'success': False, 'error': 'Session not found'}
        
        # Get solution design
        design_output = agent_memory.get_phase_output(session_id, 'solution_design')
        if not design_output:
            return {'success': False, 'error': 'Solution design not found'}
        
        solution_design = design_output.get('structured_design', {})
        
        # Execute QA testing agent
        result = qa_testing_agent.generate_test_cases(
            session_id=session_id,
            solution_design=solution_design,
            module=session.module,
            scope=scope
        )
        
        if result['success']:
            # Advance phase
            agent_memory.advance_phase(session_id, ProjectPhase.UAT_TESTING.value)
            self.logger.info("QA testing phase completed", session_id=session_id)
        
        return result
    
    def execute_uat_testing_phase(
        self,
        session_id: str,
        user_roles: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Execute UAT testing phase"""
        
        self.logger.info("Executing UAT testing phase", session_id=session_id)
        
        session = agent_memory.session_service.get_session(session_id)
        if not session:
            return {'success': False, 'error': 'Session not found'}
        
        # Get process maps
        process_maps = session.process_maps or {}
        
        # Default user roles if not provided
        if not user_roles:
            user_roles = ["Business User", "Power User", "Administrator"]
        
        # Execute UAT testing agent
        result = uat_testing_agent.generate_uat_scenarios(
            session_id=session_id,
            business_processes=process_maps,
            user_roles=user_roles
        )
        
        if result['success']:
            # Advance phase
            agent_memory.advance_phase(session_id, ProjectPhase.TRAINING.value)
            self.logger.info("UAT testing phase completed", session_id=session_id)
        
        return result
    
    def execute_training_phase(
        self,
        session_id: str,
        process_name: Optional[str] = None,
        user_roles: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Execute training and documentation phase"""
        
        self.logger.info("Executing training phase", session_id=session_id)
        
        session = agent_memory.session_service.get_session(session_id)
        if not session:
            return {'success': False, 'error': 'Session not found'}
        
        # Get solution design
        design_output = agent_memory.get_phase_output(session_id, 'solution_design')
        solution_design = design_output.get('structured_design', {}) if design_output else {}
        
        # Default values
        if not process_name:
            process_name = f"{session.module} Business Process"
        
        if not user_roles:
            user_roles = ["End User", "Process Owner", "System Administrator"]
        
        # Execute training agent
        result = training_agent.create_training_materials(
            session_id=session_id,
            process_name=process_name,
            user_roles=user_roles,
            solution_design=solution_design
        )
        
        if result['success']:
            # Mark project as completed
            agent_memory.advance_phase(session_id, ProjectPhase.COMPLETED.value)
            self.logger.info("Training phase completed - Project finished!", session_id=session_id)
            
            # Learn from this project
            agent_memory.learn_from_project(session_id)
        
        return result
    
    def execute_full_workflow(
        self,
        project_name: str,
        module: str,
        stakeholder_input: str,
        erp_system: str = "SAP S/4HANA",
        process_name: Optional[str] = None,
        user_roles: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Execute complete ERP consulting workflow from start to finish
        
        Args:
            project_name: Name of the project
            module: ERP module
            stakeholder_input: Initial requirements input
            erp_system: Target ERP system
            process_name: Business process name
            user_roles: List of user roles
            
        Returns:
            Complete workflow results
        """
        start_time = time.time()
        
        self.logger.info(
            "Starting full workflow execution",
            project=project_name,
            module=module
        )
        
        workflow_results = {
            'project_name': project_name,
            'module': module,
            'phases': {}
        }
        
        try:
            # 1. Start Project (without auto-running requirements)
            self.logger.info("Phase 1/6: Requirements Gathering")
            project_result = self.start_project(
                project_name=project_name,
                module=module,
                erp_system=erp_system,
                initial_input=None  # Do NOT auto-run requirements here
            )
            
            if not project_result['success']:
                return project_result
            
            session_id = project_result['session_id']
            workflow_results['session_id'] = session_id
            
            # Execute requirements phase explicitly once
            req_result = self.execute_requirements_phase(
                session_id=session_id,
                stakeholder_input=stakeholder_input
            )
            workflow_results['phases']['requirements'] = req_result
            
            # 2. Process Mapping
            self.logger.info("Phase 2/6: Process Mapping")
            process_result = self.execute_process_mapping_phase(
                session_id=session_id,
                process_name=process_name
            )
            workflow_results['phases']['process_mapping'] = process_result
            
            if not process_result['success']:
                self.logger.warning("Process mapping failed, continuing with available data")
            
            # 3. Solution Design
            self.logger.info("Phase 3/6: Solution Design")
            design_result = self.execute_solution_design_phase(session_id=session_id)
            workflow_results['phases']['solution_design'] = design_result
            
            if not design_result['success']:
                self.logger.warning("Solution design failed, continuing")
            
            # 4. QA Testing
            self.logger.info("Phase 4/6: QA Testing")
            qa_result = self.execute_qa_testing_phase(session_id=session_id)
            workflow_results['phases']['qa_testing'] = qa_result
            
            # 5. UAT Testing
            self.logger.info("Phase 5/6: UAT Testing")
            uat_result = self.execute_uat_testing_phase(
                session_id=session_id,
                user_roles=user_roles
            )
            workflow_results['phases']['uat_testing'] = uat_result
            
            # 6. Training
            self.logger.info("Phase 6/6: Training & Documentation")
            training_result = self.execute_training_phase(
                session_id=session_id,
                process_name=process_name,
                user_roles=user_roles
            )
            workflow_results['phases']['training'] = training_result
            
            duration = time.time() - start_time
            
            # Generate final summary
            summary = self.generate_project_summary(session_id)
            
            self.logger.info(
                "Full workflow completed",
                session_id=session_id,
                duration=duration
            )
            
            return {
                'success': True,
                'session_id': session_id,
                'workflow_results': workflow_results,
                'summary': summary,
                'total_duration': duration,
                'metrics': metrics_collector.get_summary()
            }
            
        except Exception as e:
            duration = time.time() - start_time
            self.logger.log_agent_error("execute_full_workflow", e)
            
            return {
                'success': False,
                'error': str(e),
                'partial_results': workflow_results,
                'duration': duration
            }
    
    def generate_project_summary(self, session_id: str) -> Dict[str, Any]:
        """Generate comprehensive project summary"""
        
        session = agent_memory.session_service.get_session(session_id)
        if not session:
            return {}
        
        summary = {
            'project_info': {
                'name': session.project_name,
                'module': session.module,
                'erp_system': session.erp_system,
                'created_at': session.created_at.isoformat(),
                'completed_at': session.updated_at.isoformat()
            },
            'phases_completed': session.completed_phases,
            'deliverables': {},
            'metrics': {}
        }
        
        # Collect deliverables
        for phase in session.completed_phases:
            phase_output = agent_memory.get_phase_output(session_id, phase)
            if phase_output:
                doc_path = phase_output.get('document_path')
                if doc_path:
                    summary['deliverables'][phase] = doc_path
        
        # Add metrics
        summary['metrics'] = metrics_collector.get_metrics()
        
        return summary
    
    def get_project_status(self, session_id: str) -> Dict[str, Any]:
        """Get current project status"""
        
        session = agent_memory.session_service.get_session(session_id)
        if not session:
            return {'error': 'Session not found'}
        
        return {
            'session_id': session_id,
            'project_name': session.project_name,
            'module': session.module,
            'current_phase': session.current_phase,
            'completed_phases': session.completed_phases,
            'progress_percentage': len(session.completed_phases) / 6 * 100,
            'next_phase': self._get_next_phase(session.current_phase),
            'created_at': session.created_at.isoformat(),
            'last_updated': session.updated_at.isoformat()
        }
    
    def _get_next_phase(self, current_phase: str) -> str:
        """Get next phase in workflow"""
        try:
            phase_enum = ProjectPhase(current_phase)
            workflow_info = self.phase_workflow.get(phase_enum)
            if workflow_info:
                return workflow_info['next_phase'].value
        except Exception:
            pass
        return "unknown"


# Global orchestrator instance
orchestrator = ERPOrchestratorAgent()