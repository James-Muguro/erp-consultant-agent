"""
Testing Agents - QA and UAT Testing
"""
from src.utils.llm import get_llm
from typing import Dict, List, Any, Optional
import time

from src.config.settings import settings, QA_TESTING_AGENT_CONFIG, UAT_TESTING_AGENT_CONFIG
from src.utils.logger import AgentLogger, metrics_collector
from src.utils.prompts import QA_TESTING_SYSTEM_PROMPT, QA_TESTING_TASK_PROMPT, UAT_TESTING_SYSTEM_PROMPT, UAT_TESTING_TASK_PROMPT
from src.tools import test_generator, doc_generator
from src.memory import agent_memory

from pydantic import ValidationError
from src.models.test_case_schema import TestCasesDocument


class QATestingAgent:
    """Agent specialized in generating QA test cases"""
    
    def __init__(self):
        self.config = QA_TESTING_AGENT_CONFIG
        self.logger = AgentLogger(self.config.name)
        
        # Get the singleton model instance
        self.model = get_llm()

    def reload_model(self):
        """Reload the model for QA testing agent."""
        self.model = get_llm()
        
        self.logger.info(f"{self.config.name} initialized")
    
    def generate_test_cases(
        self,
        session_id: str,
        solution_design: Dict[str, Any],
        module: str,
        scope: str = "comprehensive"
    ) -> Dict[str, Any]:
        """
        Generate QA test cases based on solution design
        
        Args:
            session_id: Session identifier
            solution_design: Solution design from previous phase
            module: ERP module
            scope: Testing scope (comprehensive, critical, regression)
            
        Returns:
            Dictionary containing test cases and document path
        """
        start_time = time.time()
        
        self.logger.log_agent_start(
            "generate_test_cases",
            {
                'module': module,
                'scope': scope
            }
        )
        
        try:
            # Get test templates from memory
            test_templates = agent_memory.recall({
                'category': 'test_case_template',
                'tags': ['qa', module.lower()]
            }, limit=3)
            
            # Build context
            context = self._build_context(test_templates)
            
            # Prepare solution design summary
            design_summary = self._summarize_design(solution_design)
            
            # Create prompt
            prompt = self._create_prompt(
                design_summary,
                module,
                scope,
                context
            )
            
            # Define generation config
            generation_config = {
                'temperature': self.config.temperature,
                'max_output_tokens': settings.max_tokens,
            }
            
            # Generate test cases using Gemini, constrained to our schema
            self.logger.info("Calling Gemini API for QA test case generation")
            generation_config = {**generation_config, 'response_schema': TestCasesDocument}
            response = self.model.generate_content(prompt, generation_config=generation_config)
            
            test_cases_text = response.text
            
            # Parse and validate against schema, falling back to the old
            # heuristic parser only if validation ever fails
            try:
                validated = TestCasesDocument.model_validate_json(test_cases_text)
                structured_test_cases = [tc.to_legacy_dict() for tc in validated.test_cases]
            except ValidationError as e:
                self.logger.error(f"Schema validation failed, falling back to heuristic parsing: {e}")
                structured_test_cases = self._parse_test_cases(test_cases_text, module)
            
            # Get project info
            session = agent_memory.session_service.get_session(session_id)
            project_name = session.project_name if session else "ERP Project"
            
            # Generate document
            doc_path = doc_generator.generate_test_case_document(
                project_name=project_name,
                module=module,
                test_cases=structured_test_cases,
                test_type="QA"
            )
            
            # Save to session
            agent_memory.save_phase_output(
                session_id,
                'qa_testing',
                {
                    'test_cases': structured_test_cases,
                    'document_path': doc_path,
                    'raw_text': test_cases_text
                }
            )
            
            # Log decision
            agent_memory.session_service.log_decision(
                session_id,
                f"Generated {len(structured_test_cases)} QA test cases",
                f"Coverage includes functional, integration, and security testing",
                self.config.name
            )
            
            duration = time.time() - start_time
            
            self.logger.log_agent_complete(
                "generate_test_cases",
                {
                    'test_cases_count': len(structured_test_cases),
                    'document_path': doc_path
                },
                duration
            )
            
            metrics_collector.record_task(self.config.name, True, duration)
            
            return {
                'success': True,
                'test_cases': structured_test_cases,
                'document_path': doc_path,
                'raw_text': test_cases_text,
                'duration': duration
            }
            
        except Exception as e:
            duration = time.time() - start_time
            self.logger.log_agent_error("generate_test_cases", e)
            metrics_collector.record_task(self.config.name, False, duration)
            
            return {
                'success': False,
                'error': str(e),
                'duration': duration
            }
    
    def _build_context(self, test_templates: List[Any]) -> str:
        """Build context for the LLM"""
        context_parts = []
        
        if test_templates:
            context_parts.append("Test Case Templates and Best Practices:")
            for template in test_templates:
                context_parts.append(f"- {template.content[:150]}")
        
        return "\n".join(context_parts)
    
    def _create_prompt(
        self,
        solution_design: str,
        module: str,
        scope: str,
        context: str
    ) -> str:
        """Create the full prompt for the LLM"""
        
        task_prompt = QA_TESTING_TASK_PROMPT.format(
            solution_design=solution_design,
            module=module,
            scope=scope
        )
        
        full_prompt = f"""
{QA_TESTING_SYSTEM_PROMPT}

{context}

{task_prompt}

Generate comprehensive, well-structured test cases with clear steps and expected results.
"""
        
        return full_prompt
    
    def _summarize_design(self, design: Dict[str, Any]) -> str:
        """Summarize solution design for testing"""
        summary_parts = ["Solution Design Summary:"]
        
        configs = design.get('configurations', [])
        if configs:
            summary_parts.append("\nKey Configurations:")
            for config in configs[:5]:
                summary_parts.append(f"- {config.get('component', '')}")
        
        integrations = design.get('integrations', [])
        if integrations:
            summary_parts.append("\nIntegrations:")
            for integration in integrations[:3]:
                summary_parts.append(f"- {integration.get('name', '')}")
        
        return "\n".join(summary_parts)
    
    def _parse_test_cases(self, text: str, module: str) -> List[Dict[str, Any]]:
        """Parse test cases text into structured format"""
        test_cases = []
        current_tc = None
        
        lines = text.split('\n')
        
        for line in lines:
            line_stripped = line.strip()
            line_lower = line_stripped.lower()
            
            # Detect new test case
            if 'test case' in line_lower and (':' in line_stripped or line_stripped.startswith('###')):
                if current_tc:
                    test_cases.append(current_tc)
                
                current_tc = {
                    'id': f'TC-{len(test_cases) + 1:03d}',
                    'scenario': line_stripped.split(':')[-1].strip() if ':' in line_stripped else line_stripped.strip('# '),
                    'type': 'Functional',
                    'priority': 'Medium',
                    'steps': [],
                    'test_data': {},
                    'expected_result': '',
                    'preconditions': []
                }
            elif current_tc:
                # Parse test case details
                if 'priority' in line_lower and ':' in line_stripped:
                    priority = line_stripped.split(':')[-1].strip()
                    if any(p in priority for p in ['Critical', 'High', 'Medium', 'Low']):
                        current_tc['priority'] = priority.split()[0]
                elif 'expected result' in line_lower or 'expected outcome' in line_lower:
                    current_tc['expected_result'] = ''
                elif line_stripped.startswith(('-', '*', '1.', '2.', '3.', '4.', '5.')):
                    # Could be step or precondition
                    step_text = line_stripped.strip('- *0123456789. ')
                    if step_text:
                        current_tc['steps'].append(step_text)
        
        if current_tc:
            test_cases.append(current_tc)
        
        # If parsing didn't work well, generate test cases programmatically
        if len(test_cases) < 3:
            test_cases = test_generator.generate_functional_test_cases(
                requirements=[
                    {'id': 'REQ-001', 'description': f'{module} module functionality', 'priority': 'High'}
                ],
                module=module
            )
        
        return test_cases


class UATTestingAgent:
    """Agent specialized in generating UAT test scenarios"""
    
    def __init__(self):
        self.config = UAT_TESTING_AGENT_CONFIG
        self.logger = AgentLogger(self.config.name)
        
        # Get the singleton model instance
        self.model = get_llm()

    def reload_model(self):
        """Reload the model for UAT testing agent."""
        self.model = get_llm()
        
        self.logger.info(f"{self.config.name} initialized")
    
    def generate_uat_scenarios(
        self,
        session_id: str,
        business_processes: Dict[str, Any],
        user_roles: List[str]
    ) -> Dict[str, Any]:
        """
        Generate UAT test scenarios for business users
        
        Args:
            session_id: Session identifier
            business_processes: Process maps from earlier phase
            user_roles: List of user roles to create scenarios for
            
        Returns:
            Dictionary containing UAT scenarios and document path
        """
        start_time = time.time()
        
        self.logger.log_agent_start(
            "generate_uat_scenarios",
            {
                'process_count': len(business_processes) if isinstance(business_processes, dict) else 0,
                'user_roles': user_roles
            }
        )
        
        try:
            # Get UAT templates from memory
            uat_templates = agent_memory.recall({
                'category': 'test_case_template',
                'tags': ['uat', 'user-acceptance']
            }, limit=2)
            
            # Build context
            context = self._build_context(uat_templates)
            
            # Prepare process summary
            process_summary = self._summarize_processes(business_processes)
            
            # Create prompt
            prompt = self._create_prompt(
                process_summary,
                user_roles,
                context
            )
            
            # Define generation config
            generation_config = {
                'temperature': self.config.temperature,
                'max_output_tokens': settings.max_tokens,
            }
            
            # Generate UAT scenarios using Gemini, constrained to our schema
            self.logger.info("Calling Gemini API for UAT scenario generation")
            generation_config = {**generation_config, 'response_schema': TestCasesDocument}
            response = self.model.generate_content(prompt, generation_config=generation_config)
            
            uat_text = response.text
            
            # Parse and validate against schema, so Gemini's real scenarios
            # are actually used. Falls back to the old hardcoded-placeholder
            # generator only if validation ever fails.
            try:
                validated = TestCasesDocument.model_validate_json(uat_text)
                structured_scenarios = [tc.to_legacy_dict() for tc in validated.test_cases]
            except ValidationError as e:
                self.logger.error(f"Schema validation failed, falling back to generic scenarios: {e}")
                structured_scenarios = self._parse_uat_scenarios(uat_text, user_roles)
            
            # Get project info
            session = agent_memory.session_service.get_session(session_id)
            project_name = session.project_name if session else "ERP Project"
            module = session.module if session else "ERP"
            
            # Generate document
            doc_path = doc_generator.generate_test_case_document(
                project_name=project_name,
                module=module,
                test_cases=structured_scenarios,
                test_type="UAT"
            )
            
            # Save to session
            agent_memory.save_phase_output(
                session_id,
                'uat_testing',
                {
                    'uat_scenarios': structured_scenarios,
                    'document_path': doc_path,
                    'raw_text': uat_text
                }
            )
            
            # Log decision
            agent_memory.session_service.log_decision(
                session_id,
                f"Generated {len(structured_scenarios)} UAT scenarios",
                f"Created user-friendly scenarios for {len(user_roles)} user roles",
                self.config.name
            )
            
            duration = time.time() - start_time
            
            self.logger.log_agent_complete(
                "generate_uat_scenarios",
                {
                    'scenarios_count': len(structured_scenarios),
                    'document_path': doc_path
                },
                duration
            )
            
            metrics_collector.record_task(self.config.name, True, duration)
            
            return {
                'success': True,
                'uat_scenarios': structured_scenarios,
                'document_path': doc_path,
                'raw_text': uat_text,
                'duration': duration
            }
            
        except Exception as e:
            duration = time.time() - start_time
            self.logger.log_agent_error("generate_uat_scenarios", e)
            metrics_collector.record_task(self.config.name, False, duration)
            
            return {
                'success': False,
                'error': str(e),
                'duration': duration
            }
    
    def _build_context(self, templates: List[Any]) -> str:
        """Build context for the LLM"""
        context_parts = []
        
        if templates:
            context_parts.append("UAT Best Practices:")
            for template in templates:
                context_parts.append(f"- {template.content[:150]}")
        
        return "\n".join(context_parts)
    
    def _create_prompt(
        self,
        processes: str,
        user_roles: List[str],
        context: str
    ) -> str:
        """Create the full prompt for the LLM"""
        
        scenarios = "End-to-end business scenarios covering all key processes"
        
        task_prompt = UAT_TESTING_TASK_PROMPT.format(
            business_processes=processes,
            user_roles=', '.join(user_roles),
            scenarios=scenarios
        )
        
        full_prompt = f"""
{UAT_TESTING_SYSTEM_PROMPT}

{context}

{task_prompt}

Create user-friendly, business-focused test scenarios that non-technical users can execute.
"""
        
        return full_prompt
    
    def _summarize_processes(self, processes: Dict[str, Any]) -> str:
        """Summarize business processes for UAT"""
        if not processes:
            return "Standard ERP business processes"
        
        summary_parts = ["Business Processes:"]
        
        for process_name, process_data in processes.items():
            summary_parts.append(f"\n{process_name}:")
            
            if isinstance(process_data, dict):
                structured = process_data.get('structured', {})
                steps = structured.get('steps', [])
                
                if steps:
                    summary_parts.append("Key Steps:")
                    for step in steps[:5]:
                        summary_parts.append(f"- {step.get('name', '')}")
        
        return "\n".join(summary_parts)
    
    def _parse_uat_scenarios(self, text: str, user_roles: List[str]) -> List[Dict[str, Any]]:
        """Parse UAT scenarios text into structured format"""
        scenarios = []
        
        # Simple parsing or generate programmatically
        if user_roles and len(user_roles) > 0:
            # Generate scenarios using test generator
            business_processes = [
                {
                    'name': 'End-to-End Business Process',
                    'description': 'Complete business workflow',
                    'user_role': role,
                    'steps': [
                        'Log into the system',
                        'Navigate to the module',
                        'Execute the business process',
                        'Verify results'
                    ],
                    'expected_outcome': 'Process completes successfully'
                }
                for role in user_roles
            ]
            
            scenarios = test_generator.generate_uat_scenarios(business_processes)
        
        return scenarios


# Global agent instances
qa_testing_agent = QATestingAgent()
uat_testing_agent = UATTestingAgent()