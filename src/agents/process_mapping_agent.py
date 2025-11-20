"""
Process Mapping Agent - Creates detailed business process maps
"""
import google.generativeai as genai
from typing import Dict, List, Any, Optional
import time

from src.config.settings import settings, PROCESS_MAPPING_AGENT_CONFIG
from src.utils.logger import AgentLogger, metrics_collector
from src.utils.prompts import PROCESS_MAPPING_SYSTEM_PROMPT, PROCESS_MAPPING_TASK_PROMPT
from src.tools import erp_kb
from src.memory import agent_memory


class ProcessMappingAgent:
    """Agent specialized in creating business process maps"""
    
    def __init__(self):
        self.config = PROCESS_MAPPING_AGENT_CONFIG
        self.logger = AgentLogger(self.config.name)
        
        # Configure Gemini
        genai.configure(api_key=settings.gemini_api_key)
        self.model = genai.GenerativeModel(
            model_name=settings.gemini_model,
            generation_config={
                'temperature': self.config.temperature,
                'max_output_tokens': settings.max_tokens,
            }
        )
        
        self.logger.info(f"{self.config.name} initialized")
    
    def map_process(
        self,
        session_id: str,
        process_name: str,
        requirements: Dict[str, Any],
        current_state: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create detailed business process map
        
        Args:
            session_id: Session identifier
            process_name: Name of the process to map
            requirements: Requirements from previous phase
            current_state: Description of current AS-IS process
            
        Returns:
            Dictionary containing process map and documentation
        """
        start_time = time.time()
        
        self.logger.log_agent_start(
            "map_process",
            {
                'process': process_name,
                'has_current_state': current_state is not None
            }
        )
        
        try:
            # Get standard process flow if available
            standard_flow = erp_kb.get_process_flow(process_name)
            
            # Get module information
            module = requirements.get('module', 'FI')
            module_info = erp_kb.get_module_info(module)
            
            # Get relevant memories
            past_processes = agent_memory.recall({
                'category': 'process_pattern',
                'tags': [process_name.lower(), module.lower()]
            }, limit=3)
            
            # Build context
            context = self._build_context(
                standard_flow,
                module_info,
                past_processes
            )
            
            # Create prompt
            prompt = self._create_prompt(
                process_name,
                requirements,
                current_state or "No current process documented",
                context
            )
            
            # Generate process map using Gemini
            self.logger.info("Calling Gemini API for process mapping")
            response = self.model.generate_content(prompt)
            
            process_map_text = response.text
            
            # Parse and structure the process map
            structured_process = self._parse_process_map(process_map_text)
            
            # Add to conversation memory
            agent_memory.session_service.add_to_conversation(
                session_id,
                'assistant',
                process_map_text,
                self.config.name
            )
            
            # Save to session
            session = agent_memory.session_service.get_session(session_id)
            if session:
                if not session.process_maps:
                    session.process_maps = {}
                session.process_maps[process_name] = {
                    'structured': structured_process,
                    'raw_text': process_map_text,
                    'timestamp': time.time()
                }
                agent_memory.session_service.update_session(
                    session_id,
                    {'process_maps': session.process_maps}
                )
            
            # Log decision
            agent_memory.session_service.log_decision(
                session_id,
                f"Process map created for {process_name}",
                f"Mapped {len(structured_process.get('steps', []))} process steps with {len(structured_process.get('roles', []))} roles",
                self.config.name
            )
            
            duration = time.time() - start_time
            
            self.logger.log_agent_complete(
                "map_process",
                {
                    'process': process_name,
                    'steps_count': len(structured_process.get('steps', []))
                },
                duration
            )
            
            metrics_collector.record_task(self.config.name, True, duration)
            
            return {
                'success': True,
                'process_map': structured_process,
                'raw_text': process_map_text,
                'duration': duration
            }
            
        except Exception as e:
            duration = time.time() - start_time
            self.logger.log_agent_error("map_process", e)
            metrics_collector.record_task(self.config.name, False, duration)
            
            return {
                'success': False,
                'error': str(e),
                'duration': duration
            }
    
    def create_raci_matrix(
        self,
        process_steps: List[Dict[str, Any]],
        roles: List[str]
    ) -> Dict[str, Any]:
        """
        Create RACI matrix for process
        
        Args:
            process_steps: List of process steps
            roles: List of roles involved
            
        Returns:
            RACI matrix
        """
        
        raci_matrix = {
            'roles': roles,
            'steps': []
        }
        
        for step in process_steps:
            step_raci = {
                'step_name': step.get('name', ''),
                'assignments': {}
            }
            
            for role in roles:
                # Default assignment (this would be enhanced with AI)
                step_raci['assignments'][role] = 'I'  # Informed
            
            # Set primary role as Responsible
            if step.get('responsible_role'):
                step_raci['assignments'][step['responsible_role']] = 'R'
            
            raci_matrix['steps'].append(step_raci)
        
        return raci_matrix
    
    def identify_gaps(
        self,
        current_process: Dict[str, Any],
        target_process: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Identify gaps between AS-IS and TO-BE processes
        
        Args:
            current_process: Current AS-IS process
            target_process: Target TO-BE process
            
        Returns:
            List of identified gaps
        """
        
        gaps = []
        
        # Compare steps
        current_steps = set(s.get('name', '') for s in current_process.get('steps', []))
        target_steps = set(s.get('name', '') for s in target_process.get('steps', []))
        
        missing_steps = target_steps - current_steps
        for step in missing_steps:
            gaps.append({
                'type': 'missing_step',
                'description': f"Process step '{step}' is missing in current process",
                'impact': 'Medium',
                'recommendation': f"Add '{step}' to the process flow"
            })
        
        extra_steps = current_steps - target_steps
        for step in extra_steps:
            gaps.append({
                'type': 'extra_step',
                'description': f"Process step '{step}' is not in target process",
                'impact': 'Low',
                'recommendation': f"Evaluate if '{step}' should be removed or standardized"
            })
        
        self.logger.info(
            "Gap analysis completed",
            gaps_found=len(gaps)
        )
        
        return gaps
    
    def _build_context(
        self,
        standard_flow: Optional[Dict],
        module_info: Optional[Dict],
        past_processes: List[Any]
    ) -> str:
        """Build context for the LLM"""
        context_parts = []
        
        if standard_flow:
            context_parts.append(f"""
Standard Process Flow: {standard_flow['name']}
Modules: {', '.join(standard_flow['modules'])}
Steps:
{chr(10).join(standard_flow['steps'])}

Integration Points:
{chr(10).join(f'- {ip}' for ip in standard_flow['integration_points'])}
""")
        
        if module_info:
            context_parts.append(f"""
ERP Module Context:
- Module: {module_info['name']}
- Common Transactions: {', '.join(module_info['common_transactions'][:5])}
""")
        
        if past_processes:
            context_parts.append("""
Similar Process Patterns from Past Projects:
""")
            for process in past_processes:
                context_parts.append(f"- {process.content[:150]}")
        
        return "\n".join(context_parts)
    
    def _create_prompt(
        self,
        process_name: str,
        requirements: Dict[str, Any],
        current_state: str,
        context: str
    ) -> str:
        """Create the full prompt for the LLM"""
        
        # Extract relevant requirements
        requirements_summary = self._summarize_requirements(requirements)
        
        task_prompt = PROCESS_MAPPING_TASK_PROMPT.format(
            process_name=process_name,
            requirements=requirements_summary,
            current_state=current_state
        )
        
        full_prompt = f"""
{PROCESS_MAPPING_SYSTEM_PROMPT}

{context}

{task_prompt}

Please provide a detailed, structured process map that can be used for ERP implementation.
"""
        
        return full_prompt
    
    def _summarize_requirements(self, requirements: Dict[str, Any]) -> str:
        """Summarize requirements for process mapping"""
        summary_parts = []
        
        # Functional requirements
        func_reqs = requirements.get('functional_requirements', {})
        if func_reqs:
            summary_parts.append("Key Functional Requirements:")
            for category, reqs in func_reqs.items():
                for req in reqs[:3]:  # Limit to top 3 per category
                    summary_parts.append(f"- {req.get('description', '')}")
        
        # Integration requirements
        int_reqs = requirements.get('integration_requirements', [])
        if int_reqs:
            summary_parts.append("\nIntegration Points:")
            for req in int_reqs[:3]:
                summary_parts.append(f"- {req.get('description', '')}")
        
        return "\n".join(summary_parts)
    
    def _parse_process_map(self, process_text: str) -> Dict[str, Any]:
        """Parse process map text into structured format"""
        
        structured = {
            'overview': '',
            'scope': '',
            'roles': [],
            'steps': [],
            'decision_points': [],
            'integration_points': [],
            'exceptions': [],
            'improvements': []
        }
        
        current_section = None
        current_step = None
        lines = process_text.split('\n')
        
        for line in lines:
            line_stripped = line.strip()
            line_lower = line_stripped.lower()
            
            # Detect sections
            if 'overview' in line_lower and not line_stripped.startswith('-'):
                current_section = 'overview'
                current_step = None
            elif 'scope' in line_lower and not line_stripped.startswith('-'):
                current_section = 'scope'
                current_step = None
            elif 'roles' in line_lower and 'responsib' in line_lower:
                current_section = 'roles'
                current_step = None
            elif 'process steps' in line_lower or 'detailed steps' in line_lower:
                current_section = 'steps'
                current_step = None
            elif 'decision' in line_lower and 'point' in line_lower:
                current_section = 'decision_points'
                current_step = None
            elif 'integration' in line_lower:
                current_section = 'integration_points'
                current_step = None
            elif 'exception' in line_lower:
                current_section = 'exceptions'
                current_step = None
            elif 'improvement' in line_lower or 'to-be' in line_lower:
                current_section = 'improvements'
                current_step = None
            elif current_section and line_stripped:
                # Add content to current section
                if current_section in ['overview', 'scope']:
                    structured[current_section] += line + '\n'
                elif current_section == 'steps':
                    # Try to identify step number
                    if line_stripped[0].isdigit() or line_stripped.startswith('Step'):
                        if current_step:
                            structured['steps'].append(current_step)
                        current_step = {
                            'number': len(structured['steps']) + 1,
                            'name': line_stripped,
                            'description': '',
                            'transaction': '',
                            'responsible_role': ''
                        }
                    elif current_step and (line_stripped.startswith('-') or line_stripped.startswith('*')):
                        current_step['description'] += line_stripped.strip('- * ') + ' '
                elif isinstance(structured[current_section], list):
                    if line_stripped.startswith('-') or line_stripped.startswith('*') or line_stripped[0].isdigit():
                        structured[current_section].append(line_stripped.strip('- *0123456789. '))
        
        # Add last step if exists
        if current_step:
            structured['steps'].append(current_step)
        
        return structured


# Global process mapping agent instance
process_mapping_agent = ProcessMappingAgent()