"""
Training & Documentation Agent - Creates training materials and user documentation
"""
from src.utils.llm import get_llm
from typing import Dict, List, Any, Optional
import time

from src.config.settings import settings, TRAINING_AGENT_CONFIG
from src.utils.logger import AgentLogger, metrics_collector
from src.utils.prompts import TRAINING_SYSTEM_PROMPT, TRAINING_TASK_PROMPT
from src.tools import doc_generator
from src.memory import agent_memory

from pydantic import ValidationError
from src.models.training_schema import TrainingMaterials


class TrainingAgent:
    """Agent specialized in creating training materials and documentation"""
    
    def __init__(self):
        self.config = TRAINING_AGENT_CONFIG
        self.logger = AgentLogger(self.config.name)
        
        # Get the singleton model instance
        self.model = get_llm()

    def reload_model(self):
        """Reload the LLM model instance for training agent."""
        self.model = get_llm()
        
        self.logger.info(f"{self.config.name} initialized")
    
    def create_training_materials(
        self,
        session_id: str,
        process_name: str,
        user_roles: List[str],
        solution_design: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create comprehensive training materials
        
        Args:
            session_id: Session identifier
            process_name: Name of the process
            user_roles: List of user roles needing training
            solution_design: Solution design from previous phase
            
        Returns:
            Dictionary containing training materials and document paths
        """
        start_time = time.time()
        
        self.logger.log_agent_start(
            "create_training_materials",
            {
                'process': process_name,
                'user_roles': user_roles
            }
        )
        
        try:
            # Get training templates from memory
            training_templates = agent_memory.recall({
                'category': 'requirements_template',  # Using general templates
                'tags': ['training', 'documentation']
            }, limit=2)
            
            # Build context
            context = self._build_context(training_templates)
            
            # Prepare solution design summary
            design_summary = self._summarize_design(solution_design)
            
            # Create prompt
            prompt = self._create_prompt(
                process_name,
                user_roles,
                design_summary,
                context
            )
            
            # Define generation config
            generation_config = {
                'temperature': self.config.temperature,
                'max_output_tokens': settings.max_tokens,
            }
            
            # Generate training materials using Gemini, constrained to our schema
            self.logger.info("Calling Gemini API for training materials generation")
            generation_config = {**generation_config, 'response_schema': TrainingMaterials}
            response = self.model.generate_content(prompt, generation_config=generation_config)
            
            training_text = response.text
            
            # Parse and validate against schema, falling back to the old
            # heuristic parser only if validation ever fails
            try:
                validated = TrainingMaterials.model_validate_json(training_text)
                structured_materials = validated.model_dump()
            except ValidationError as e:
                self.logger.error(f"Schema validation failed, falling back to heuristic parsing: {e}")
                structured_materials = self._parse_training_materials(training_text)
            
            # Add to conversation memory
            agent_memory.session_service.add_to_conversation(
                session_id,
                'assistant',
                training_text,
                self.config.name
            )
            
            # Get project info
            session = agent_memory.session_service.get_session(session_id)
            module = session.module if session else "ERP"
            
            # Generate documents
            documents = {}
            
            # User Manual
            if structured_materials.get('user_manual'):
                user_manual_path = doc_generator.generate_user_manual(
                    process_name=process_name,
                    module=module,
                    process_steps=structured_materials['user_manual'].get('steps', [])
                )
                documents['user_manual'] = user_manual_path
            
            # Save to session
            agent_memory.save_phase_output(
                session_id,
                'training',
                {
                    'training_materials': structured_materials,
                    'documents': documents,
                    'raw_text': training_text
                }
            )
            
            # Log decision
            agent_memory.session_service.log_decision(
                session_id,
                f"Training materials created for {process_name}",
                f"Generated materials for {len(user_roles)} user roles including manuals and guides",
                self.config.name
            )
            
            duration = time.time() - start_time
            
            self.logger.log_agent_complete(
                "create_training_materials",
                {
                    'documents_created': len(documents),
                    'user_roles': len(user_roles)
                },
                duration
            )
            
            metrics_collector.record_task(self.config.name, True, duration)
            
            return {
                'success': True,
                'training_materials': structured_materials,
                'documents': documents,
                'raw_text': training_text,
                'duration': duration
            }
            
        except Exception as e:
            duration = time.time() - start_time
            self.logger.log_agent_error("create_training_materials", e)
            metrics_collector.record_task(self.config.name, False, duration)
            
            return {
                'success': False,
                'error': str(e),
                'duration': duration
            }
    
    def create_quick_reference_guide(
        self,
        process_name: str,
        key_transactions: List[str],
        tips: List[str]
    ) -> str:
        """
        Create a quick reference guide (1-2 pages)
        
        Args:
            process_name: Name of the process
            key_transactions: List of key transaction codes
            tips: List of tips and best practices
            
        Returns:
            Quick reference guide content
        """
        
        guide = f"""# Quick Reference Guide: {process_name}

## Key Transaction Codes

"""
        for transaction in key_transactions:
            guide += f"- **{transaction}**\n"
        
        guide += """
## Step-by-Step Guide

1. Log into the system
2. Navigate to the relevant module
3. Execute the transaction
4. Complete required fields
5. Save and verify

## Tips and Best Practices

"""
        for tip in tips:
            guide += f"- {tip}\n"
        
        guide += """
## Common Issues

| Issue | Solution |
|-------|----------|
| Field not editable | Check authorization |
| Error message | Verify data validity |

## Support Contacts

For assistance, contact your system administrator or helpdesk.
"""
        
        self.logger.info(
            "Quick reference guide created",
            process=process_name
        )
        
        return guide
    
    def _build_context(self, templates: List[Any]) -> str:
        """Build context for the LLM"""
        context_parts = []
        
        if templates:
            context_parts.append("Training Documentation Best Practices:")
            for template in templates:
                context_parts.append(f"- {template.content[:150]}")
        
        context_parts.append("""
Key Principles for Training Materials:
- Use clear, simple language
- Include step-by-step instructions
- Provide real-world examples
- Make content searchable and organized
- Include screenshots placeholders
- Add troubleshooting sections
""")
        
        return "\n".join(context_parts)
    
    def _create_prompt(
        self,
        process_name: str,
        user_roles: List[str],
        solution_design: str,
        context: str
    ) -> str:
        """Create the full prompt for the LLM"""
        
        task_prompt = TRAINING_TASK_PROMPT.format(
            process_name=process_name,
            user_roles=', '.join(user_roles),
            solution_design=solution_design
        )
        
        full_prompt = f"""
{TRAINING_SYSTEM_PROMPT}

{context}

{task_prompt}

Create comprehensive, user-friendly training materials that enable end users to confidently use the ERP system.
"""
        
        return full_prompt
    
    def _summarize_design(self, design: Dict[str, Any]) -> str:
        """Summarize solution design for training"""
        summary_parts = ["Solution Overview:"]
        
        configs = design.get('configurations', [])
        if configs:
            summary_parts.append("\nKey System Features:")
            for config in configs[:3]:
                summary_parts.append(f"- {config.get('component', '')}")
        
        return "\n".join(summary_parts)
    
    def _parse_training_materials(self, text: str) -> Dict[str, Any]:
        """Parse training materials text into structured format"""
        
        materials = {
            'user_manual': {
                'steps': [],
                'tips': [],
                'faqs': []
            },
            'training_guide': {
                'objectives': [],
                'agenda': [],
                'exercises': []
            },
            'quick_reference': '',
            'sop': ''
        }
        
        current_section = None
        current_step = None
        lines = text.split('\n')
        
        for line in lines:
            line_stripped = line.strip()
            line_lower = line_stripped.lower()
            
            # Detect sections
            if 'user manual' in line_lower:
                current_section = 'user_manual'
            elif 'training guide' in line_lower:
                current_section = 'training_guide'
            elif 'quick reference' in line_lower:
                current_section = 'quick_reference'
            elif 'sop' in line_lower or 'standard operating procedure' in line_lower:
                current_section = 'sop'
            elif current_section and line_stripped:
                # Parse content based on section
                if current_section == 'user_manual':
                    if 'step' in line_lower and (':' in line_stripped or line_stripped.startswith('###')):
                        if current_step:
                            materials['user_manual']['steps'].append(current_step)
                        
                        current_step = {
                            'title': line_stripped.split(':')[-1].strip() if ':' in line_stripped else line_stripped.strip('# '),
                            'transaction': '',
                            'instructions': '',
                            'fields': [],
                            'tips': []
                        }
                    elif current_step and line_stripped:
                        current_step['instructions'] += line_stripped + ' '
                    elif 'tip' in line_lower and (line_stripped.startswith('-') or line_stripped.startswith('*')):
                        materials['user_manual']['tips'].append(line_stripped.strip('- * '))
                elif current_section == 'training_guide':
                    if 'objective' in line_lower:
                        pass  # Next lines will be objectives
                    elif line_stripped.startswith('-') or line_stripped.startswith('*'):
                        materials['training_guide']['objectives'].append(line_stripped.strip('- * '))
                elif current_section in ['quick_reference', 'sop']:
                    materials[current_section] += line + '\n'
        
        # Add last step if exists
        if current_step:
            materials['user_manual']['steps'].append(current_step)
        
        return materials


# Global training agent instance
training_agent = TrainingAgent()