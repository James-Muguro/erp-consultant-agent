"""
Requirements Gathering Agent - Analyzes stakeholder inputs and generates requirement documents
"""
from src.utils.llm import get_llm
from typing import Dict, List, Any, Optional
import time

from pydantic import ValidationError

from src.config.settings import settings, REQUIREMENTS_AGENT_CONFIG
from src.utils.logger import AgentLogger, metrics_collector
from src.utils.prompts import REQUIREMENTS_SYSTEM_PROMPT, REQUIREMENTS_TASK_PROMPT
from src.tools import erp_kb, doc_generator
from src.memory import agent_memory
from src.models.requirements_schema import RequirementsDocument


class RequirementsAgent:
    """Agent specialized in gathering and documenting requirements"""
    
    def __init__(self):
        self.config = REQUIREMENTS_AGENT_CONFIG
        self.logger = AgentLogger(self.config.name)
        
        # Get the singleton model instance (no args allowed in get_llm)
        self.model = get_llm()

        # Store generation configuration for Gemini API calls
        self.generation_config = {
            'temperature': self.config.temperature,
            'max_output_tokens': settings.max_tokens,
        }

    def reload_model(self):
        """Reload the GenAI model instance (used when provider changes)."""
        self.model = get_llm()
        self.logger.info(f"{self.config.name} model reloaded")

    def gather_requirements(
        self,
        session_id: str,
        project_name: str,
        module: str,
        stakeholder_input: str,
        erp_system: str = "SAP S/4HANA"
    ) -> Dict[str, Any]:
        """
        Gather and document requirements based on stakeholder input
        """
        start_time = time.time()
        
        self.logger.log_agent_start(
            "gather_requirements",
            {
                'project': project_name,
                'module': module,
                'erp_system': erp_system
            }
        )
        
        try:
            # Get relevant knowledge from ERP KB
            module_info = erp_kb.get_module_info(module, erp_system)
            best_practices = erp_kb.get_best_practices(module, erp_system)
            
            # Get templates from memory
            template = agent_memory.get_template('requirements')
            past_learnings = agent_memory.recall({
                'category': 'requirements_template',
                'tags': [module.lower(), 'requirements']
            }, limit=3)

            # Build context for the LLM
            context = self._build_context(
                module_info,
                best_practices,
                template,
                past_learnings
            )
            
            # Create prompt
            prompt = self._create_prompt(
                project_name,
                module,
                stakeholder_input,
                erp_system,
                context
            )
            
            # Generate requirements using Gemini, constrained to our schema
            self.logger.info("Calling Gemini API for requirements generation")
            response = self.model.generate_content(
                prompt,
                generation_config={**self.generation_config, 'response_schema': RequirementsDocument}
            )
            
            requirements_text = response.text
            
            # Parse and validate requirements against schema, with the old
            # heuristic parser as a fallback if validation ever fails
            try:
                validated = RequirementsDocument.model_validate_json(requirements_text)
                structured_requirements = validated.to_legacy_dict()
            except ValidationError as e:
                self.logger.error(f"Schema validation failed, falling back to heuristic parsing: {e}")
                structured_requirements = self._parse_requirements(requirements_text)
            
            # Generate formatted document
            doc_path = doc_generator.generate_requirements_document(
                project_name=project_name,
                module=module,
                requirements=structured_requirements,
                metadata={'erp_system': erp_system, 'session_id': session_id}
            )
            
            # Save to session
            agent_memory.save_phase_output(
                session_id,
                'requirements_gathering',
                {
                    'structured_requirements': structured_requirements,
                    'document_path': doc_path,
                    'raw_text': requirements_text
                }
            )
            
            # Log decision
            agent_memory.session_service.log_decision(
                session_id,
                f"Requirements gathered for {module} module",
                f"Identified {len(structured_requirements.get('functional_requirements', {}))} functional requirement categories",
                self.config.name
            )
            
            duration = time.time() - start_time
            
            self.logger.log_agent_complete(
                "gather_requirements",
                {
                    'document_path': doc_path,
                    'requirements_count': len(structured_requirements.get('functional_requirements', {}))
                },
                duration
            )
            
            metrics_collector.record_task(self.config.name, True, duration)
            
            return {
                'success': True,
                'requirements': structured_requirements,
                'document_path': doc_path,
                'raw_text': requirements_text,
                'duration': duration
            }
            
        except Exception as e:
            duration = time.time() - start_time
            self.logger.log_agent_error("gather_requirements", e)
            metrics_collector.record_task(self.config.name, False, duration)
            
            return {
                'success': False,
                'error': str(e),
                'duration': duration
            }

    def generate_requirements_template(
        self,
        project_name: str,
        module: str,
        erp_system: str,
        context: Dict[str, str]
    ) -> Dict[str, Any]:
        """Generate a requirements-gathering questionnaire from intake context."""
        start_time = time.time()
        try:
            doc_path = doc_generator.generate_requirements_template(
                project_name=project_name,
                module=module,
                erp_system=erp_system,
                context=context
            )
            duration = time.time() - start_time
            return {'success': True, 'document_path': doc_path, 'duration': duration}
        except Exception as e:
            duration = time.time() - start_time
            self.logger.log_agent_error("generate_requirements_template", e)
            return {'success': False, 'error': str(e), 'duration': duration}
    
    def _build_context(
        self,
        module_info: Optional[Dict],
        best_practices: List[str],
        template: Optional[str],
        past_learnings: List[Any]
    ) -> str:
        """Build context for the LLM"""
        context_parts = []
        
        if module_info:
            context_parts.append(f"""
Module Information:
- Name: {module_info['name']}
- Description: {module_info['description']}
- Sub-modules: {', '.join(module_info['sub_modules'])}
- Common Transactions: {', '.join(module_info['common_transactions'][:5])}
""")
        
        if best_practices:
            context_parts.append(f"""
Module Best Practices:
{chr(10).join(f'- {bp}' for bp in best_practices[:5])}
""")
        
        if template:
            context_parts.append(f"""
Requirements Document Template:
{template}
""")
        
        if past_learnings:
            context_parts.append("""
Relevant Past Learnings:
""")
            for learning in past_learnings:
                context_parts.append(f"- {learning.content[:200]}")
        
        return "\n".join(context_parts)
    
    def _create_prompt(
        self,
        project_name: str,
        module: str,
        stakeholder_input: str,
        erp_system: str,
        context: str
    ) -> str:
        """Create the full prompt for the LLM"""
        
        task_prompt = REQUIREMENTS_TASK_PROMPT.format(
            project_name=project_name,
            module=module,
            stakeholder_input=stakeholder_input,
            erp_system=erp_system
        )
        
        full_prompt = f"""
{REQUIREMENTS_SYSTEM_PROMPT}

{context}

{task_prompt}

Please provide a comprehensive requirements document with clear structure and ERP-specific terminology.
"""
        
        return full_prompt
    
    def _parse_requirements(self, requirements_text: str) -> Dict[str, Any]:
        """Parse requirements text into structured format"""
        
        structured = {
            'executive_summary': '',
            'business_context': '',
            'objectives': [],
            'functional_requirements': {},
            'technical_requirements': [],
            'integration_requirements': [],
            'reporting_requirements': [],
            'dependencies': [],
            'constraints': [],
            'assumptions': []
        }
        
        current_section = None
        lines = requirements_text.split('\n')
        
        for line in lines:
            line_lower = line.lower().strip()
            
            if 'executive summary' in line_lower:
                current_section = 'executive_summary'
            elif 'business context' in line_lower or 'business objectives' in line_lower:
                current_section = 'business_context'
            elif 'functional requirement' in line_lower:
                current_section = 'functional_requirements'
            elif 'technical requirement' in line_lower:
                current_section = 'technical_requirements'
            elif 'integration requirement' in line_lower:
                current_section = 'integration_requirements'
            elif 'reporting requirement' in line_lower:
                current_section = 'reporting_requirements'
            elif 'dependencies' in line_lower or 'dependency' in line_lower:
                current_section = 'dependencies'
            elif 'constraint' in line_lower:
                current_section = 'constraints'
            elif 'assumption' in line_lower:
                current_section = 'assumptions'
            elif current_section and line.strip():
                if current_section in ['executive_summary', 'business_context']:
                    structured[current_section] += line + '\n'
                elif current_section == 'functional_requirements':
                    if line.startswith('-') or line.startswith('*') or line[0].isdigit():
                        if 'general' not in structured['functional_requirements']:
                            structured['functional_requirements']['general'] = []
                        structured['functional_requirements']['general'].append({
                            'id': f'REQ-{len(structured["functional_requirements"].get("general", [])) + 1:03d}',
                            'description': line.strip('- *0123456789. '),
                            'priority': 'Medium',
                            'type': 'Functional'
                        })
                elif isinstance(structured[current_section], list):
                    if line.startswith('-') or line.startswith('*'):
                        structured[current_section].append(line.strip('- * '))
        
        return structured
    
    def validate_requirements(
        self,
        requirements: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate completeness and quality of requirements"""
        
        validation_result = {
            'is_valid': True,
            'issues': [],
            'warnings': [],
            'completeness_score': 0.0
        }
        
        required_sections = [
            'executive_summary',
            'business_context',
            'functional_requirements'
        ]
        
        for section in required_sections:
            if not requirements.get(section):
                validation_result['issues'].append(f"Missing required section: {section}")
                validation_result['is_valid'] = False
        
        total_sections = 10
        completed_sections = sum(1 for k, v in requirements.items() if v)
        validation_result['completeness_score'] = (completed_sections / total_sections) * 100
        
        func_reqs = requirements.get('functional_requirements', {})
        if func_reqs:
            total_reqs = sum(len(reqs) for reqs in func_reqs.values())
            if total_reqs == 0:
                validation_result['warnings'].append("No functional requirements defined")
            elif total_reqs < 5:
                validation_result['warnings'].append(f"Only {total_reqs} functional requirements defined - consider if this is sufficient")
        
        self.logger.info(
            "Requirements validated",
            completeness_score=validation_result['completeness_score'],
            is_valid=validation_result['is_valid']
        )
        
        return validation_result


# Global requirements agent instance
requirements_agent = RequirementsAgent()