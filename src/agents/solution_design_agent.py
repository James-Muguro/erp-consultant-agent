"""
Solution Design Agent - Designs ERP solutions based on requirements
"""
import google.generativeai as genai
from typing import Dict, List, Any, Optional
import time

from src.config.settings import settings, SOLUTION_DESIGN_AGENT_CONFIG
from src.utils.logger import AgentLogger, metrics_collector
from src.utils.prompts import SOLUTION_DESIGN_SYSTEM_PROMPT, SOLUTION_DESIGN_TASK_PROMPT
from src.tools import erp_kb, doc_generator
from src.memory import agent_memory


class SolutionDesignAgent:
    """Agent specialized in designing ERP solutions"""
    
    def __init__(self):
        self.config = SOLUTION_DESIGN_AGENT_CONFIG
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
    
    def design_solution(
        self,
        session_id: str,
        requirements: Dict[str, Any],
        process_maps: Dict[str, Any],
        erp_system: str = "SAP S/4HANA"
    ) -> Dict[str, Any]:
        """
        Design ERP solution based on requirements and process maps
        
        Args:
            session_id: Session identifier
            requirements: Requirements from requirements phase
            process_maps: Process maps from process mapping phase
            erp_system: Target ERP system
            
        Returns:
            Dictionary containing solution design and document path
        """
        start_time = time.time()
        
        self.logger.log_agent_start(
            "design_solution",
            {
                'erp_system': erp_system,
                'process_count': len(process_maps) if isinstance(process_maps, dict) else 0
            }
        )
        
        try:
            # Get module information
            module = requirements.get('module', 'FI')
            module_info = erp_kb.get_module_info(module)
            best_practices = erp_kb.get_best_practices(module)
            integration_points = erp_kb.get_integration_points(module)
            
            # Get relevant design patterns from memory
            design_patterns = agent_memory.recall({
                'category': 'solution_pattern',
                'tags': [module.lower(), 'design']
            }, limit=3)
            
            # Build context
            context = self._build_context(
                module_info,
                best_practices,
                integration_points,
                design_patterns
            )
            
            # Prepare requirements and process maps summary
            req_summary = self._summarize_requirements(requirements)
            process_summary = self._summarize_process_maps(process_maps)
            
            # Create prompt
            prompt = self._create_prompt(
                req_summary,
                process_summary,
                erp_system,
                context
            )
            
            # Generate solution design using Gemini
            self.logger.info("Calling Gemini API for solution design")
            response = self.model.generate_content(prompt)
            
            design_text = response.text
            
            # Parse and structure the design
            structured_design = self._parse_design(design_text)
            
            # Add to conversation memory
            agent_memory.session_service.add_to_conversation(
                session_id,
                'assistant',
                design_text,
                self.config.name
            )
            
            # Get project info for document generation
            session = agent_memory.session_service.get_session(session_id)
            project_name = session.project_name if session else "ERP Project"
            
            # Generate formatted document
            doc_path = doc_generator.generate_solution_design(
                project_name=project_name,
                module=module,
                design=structured_design
            )
            
            # Save to session
            agent_memory.save_phase_output(
                session_id,
                'solution_design',
                {
                    'structured_design': structured_design,
                    'document_path': doc_path,
                    'raw_text': design_text
                }
            )
            
            # Log decision
            customization_count = len(structured_design.get('customizations', []))
            agent_memory.session_service.log_decision(
                session_id,
                "Solution design completed",
                f"Designed solution with {customization_count} customizations, prioritizing standard ERP functionality",
                self.config.name
            )
            
            duration = time.time() - start_time
            
            self.logger.log_agent_complete(
                "design_solution",
                {
                    'document_path': doc_path,
                    'customizations': customization_count
                },
                duration
            )
            
            metrics_collector.record_task(self.config.name, True, duration)
            
            return {
                'success': True,
                'design': structured_design,
                'document_path': doc_path,
                'raw_text': design_text,
                'duration': duration
            }
            
        except Exception as e:
            duration = time.time() - start_time
            self.logger.log_agent_error("design_solution", e)
            metrics_collector.record_task(self.config.name, False, duration)
            
            return {
                'success': False,
                'error': str(e),
                'duration': duration
            }
    
    def evaluate_customization_need(
        self,
        requirement: str,
        standard_functionality: List[str]
    ) -> Dict[str, Any]:
        """
        Evaluate if a customization is needed or if standard functionality suffices
        
        Args:
            requirement: The requirement to evaluate
            standard_functionality: List of available standard features
            
        Returns:
            Evaluation result with recommendation
        """
        
        # Simple evaluation logic (would be enhanced with AI)
        evaluation = {
            'requirement': requirement,
            'needs_customization': False,
            'standard_solution': None,
            'customization_justification': None,
            'recommendation': ''
        }
        
        # Check if any standard functionality matches
        for func in standard_functionality:
            if any(word in func.lower() for word in requirement.lower().split()):
                evaluation['standard_solution'] = func
                evaluation['recommendation'] = f"Use standard functionality: {func}"
                return evaluation
        
        # If no match, might need customization
        evaluation['needs_customization'] = True
        evaluation['customization_justification'] = "No standard functionality found that meets this requirement"
        evaluation['recommendation'] = "Consider customization or alternative approach"
        
        return evaluation
    
    def _build_context(
        self,
        module_info: Optional[Dict],
        best_practices: List[str],
        integration_points: List[str],
        design_patterns: List[Any]
    ) -> str:
        """Build context for the LLM"""
        context_parts = []
        
        if module_info:
            context_parts.append(f"""
ERP Module Information:
- Name: {module_info['name']}
- Description: {module_info['description']}
- Key Transactions: {', '.join(module_info['common_transactions'][:5])}
""")
        
        if best_practices:
            context_parts.append(f"""
ERP Best Practices:
{chr(10).join(f'- {bp}' for bp in best_practices[:5])}
""")
        
        if integration_points:
            context_parts.append(f"""
Standard Integration Points:
{chr(10).join(f'- {ip}' for ip in integration_points[:5])}
""")
        
        if design_patterns:
            context_parts.append("""
Relevant Design Patterns from Past Projects:
""")
            for pattern in design_patterns:
                context_parts.append(f"- {pattern.content[:150]}")
        
        return "\n".join(context_parts)
    
    def _create_prompt(
        self,
        requirements: str,
        process_maps: str,
        erp_system: str,
        context: str
    ) -> str:
        """Create the full prompt for the LLM"""
        
        task_prompt = SOLUTION_DESIGN_TASK_PROMPT.format(
            requirements=requirements,
            process_maps=process_maps,
            erp_system=erp_system
        )
        
        full_prompt = f"""
{SOLUTION_DESIGN_SYSTEM_PROMPT}

{context}

{task_prompt}

Important: Prioritize standard ERP functionality over customizations. Only recommend customizations when absolutely necessary and provide clear justification.
"""
        
        return full_prompt
    
    def _summarize_requirements(self, requirements: Dict[str, Any]) -> str:
        """Summarize requirements for solution design"""
        summary_parts = ["Key Requirements:"]
        
        # Functional requirements
        func_reqs = requirements.get('functional_requirements', {})
        for category, reqs in func_reqs.items():
            summary_parts.append(f"\n{category}:")
            for req in reqs[:5]:  # Top 5 per category
                summary_parts.append(f"- {req.get('description', '')} (Priority: {req.get('priority', 'Medium')})")
        
        # Integration requirements
        int_reqs = requirements.get('integration_requirements', [])
        if int_reqs:
            summary_parts.append("\nIntegration Requirements:")
            for req in int_reqs[:3]:
                summary_parts.append(f"- {req.get('description', '')}")
        
        return "\n".join(summary_parts)
    
    def _summarize_process_maps(self, process_maps: Dict[str, Any]) -> str:
        """Summarize process maps for solution design"""
        if not process_maps:
            return "No process maps available"
        
        summary_parts = ["Process Maps Overview:"]
        
        for process_name, process_data in process_maps.items():
            structured = process_data.get('structured', {})
            steps = structured.get('steps', [])
            
            summary_parts.append(f"\nProcess: {process_name}")
            summary_parts.append(f"- Steps: {len(steps)}")
            summary_parts.append(f"- Integration Points: {len(structured.get('integration_points', []))}")
            
            if steps:
                summary_parts.append("Key Steps:")
                for step in steps[:3]:  # Top 3 steps
                    summary_parts.append(f"  - {step.get('name', '')}")
        
        return "\n".join(summary_parts)
    
    def _parse_design(self, design_text: str) -> Dict[str, Any]:
        """Parse design text into structured format"""
        
        structured = {
            'executive_summary': '',
            'architecture_overview': '',
            'configurations': [],
            'master_data': {},
            'integrations': [],
            'security': {},
            'customizations': [],
            'migration': {},
            'technical_specs': {}
        }
        
        current_section = None
        current_item = None
        lines = design_text.split('\n')
        
        for line in lines:
            line_stripped = line.strip()
            line_lower = line_stripped.lower()
            
            # Detect sections
            if 'executive summary' in line_lower:
                current_section = 'executive_summary'
            elif 'architecture' in line_lower and 'overview' in line_lower:
                current_section = 'architecture_overview'
            elif 'configuration' in line_lower or 'module config' in line_lower:
                current_section = 'configurations'
            elif 'master data' in line_lower:
                current_section = 'master_data'
            elif 'integration' in line_lower:
                current_section = 'integrations'
            elif 'security' in line_lower or 'authorization' in line_lower:
                current_section = 'security'
            elif 'customization' in line_lower:
                current_section = 'customizations'
            elif 'migration' in line_lower:
                current_section = 'migration'
            elif 'technical spec' in line_lower:
                current_section = 'technical_specs'
            elif current_section and line_stripped:
                # Add content to current section
                if current_section in ['executive_summary', 'architecture_overview']:
                    structured[current_section] += line + '\n'
                elif current_section == 'configurations':
                    if line_stripped.startswith('###') or (line_stripped and not line_stripped.startswith('-')):
                        if current_item:
                            structured['configurations'].append(current_item)
                        current_item = {
                            'component': line_stripped.strip('# '),
                            'description': '',
                            'steps': []
                        }
                    elif current_item and (line_stripped.startswith('-') or line_stripped.startswith('*')):
                        current_item['steps'].append(line_stripped.strip('- * '))
                elif current_section == 'integrations':
                    if line_stripped.startswith('###') or (line_stripped and ':' in line_stripped):
                        if current_item:
                            structured['integrations'].append(current_item)
                        current_item = {
                            'name': line_stripped.strip('# '),
                            'type': '',
                            'source': '',
                            'target': '',
                            'description': ''
                        }
                    elif current_item:
                        current_item['description'] += line_stripped + ' '
                elif current_section == 'customizations':
                    if line_stripped.startswith('-') or line_stripped.startswith('*') or '|' in line_stripped:
                        parts = [p.strip() for p in line_stripped.strip('- * |').split('|')]
                        if len(parts) >= 3:
                            structured['customizations'].append({
                                'type': parts[0] if len(parts) > 0 else '',
                                'component': parts[1] if len(parts) > 1 else '',
                                'description': parts[2] if len(parts) > 2 else '',
                                'justification': parts[3] if len(parts) > 3 else ''
                            })
                elif current_section in ['security', 'migration', 'technical_specs']:
                    if isinstance(structured[current_section], dict):
                        if 'overview' not in structured[current_section]:
                            structured[current_section]['overview'] = ''
                        structured[current_section]['overview'] += line + '\n'
        
        # Add last item if exists
        if current_item and current_section == 'configurations':
            structured['configurations'].append(current_item)
        elif current_item and current_section == 'integrations':
            structured['integrations'].append(current_item)
        
        return structured


# Global solution design agent instance
solution_design_agent = SolutionDesignAgent()