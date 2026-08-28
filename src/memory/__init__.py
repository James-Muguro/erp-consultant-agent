
"""
Unified memory interface for ERP Consultant Agent
"""
import uuid
from .session_manager import (
    SessionState,
    InMemorySessionService,
    session_service
)
from .memory_bank import (
    MemoryEntry,
    MemoryBank,
    memory_bank
)

__all__ = [
    'SessionState',
    'InMemorySessionService',
    'session_service',
    'MemoryEntry',
    'MemoryBank',
    'memory_bank',
    'AgentMemory'
]


class AgentMemory:
    """
    Unified memory interface that combines session management and long-term memory
    """
    
    def __init__(self):
        self.session_service = session_service
        self.memory_bank = memory_bank
    
    def create_project(
        self,
        project_name: str,
        module: str,
        erp_system: str = "SAP S/4HANA"
    ) -> str:
        """Create a new project session"""
        slug = project_name.lower().replace(' ', '_')[:30]
        session_id = f"prj_{slug}_{uuid.uuid4().hex[:8]}"
        session = self.session_service.create_session(
            session_id=session_id,
            project_name=project_name,
            module=module,
            erp_system=erp_system
        )
        return session_id
    
    def get_project_state(self, session_id: str) -> dict:
        """Get current project state"""
        session = self.session_service.get_session(session_id)
        if not session:
            return {}
        
        return {
            'project_name': session.project_name,
            'module': session.module,
            'erp_system': session.erp_system,
            'current_phase': session.current_phase,
            'completed_phases': session.completed_phases,
            'progress': len(session.completed_phases) / 6 * 100  # 6 total phases
        }
    
    def save_phase_output(
        self,
        session_id: str,
        phase: str,
        output: any
    ):
        """Save output from a phase"""
        phase_mapping = {
            'requirements_gathering': 'requirements_document',
            'process_mapping': 'process_maps',
            'solution_design': 'solution_design',
            'qa_testing': 'qa_test_cases',
            'uat_testing': 'uat_test_cases',
            'training': 'training_materials'
        }
        
        field_name = phase_mapping.get(phase)
        if field_name:
            self.session_service.update_session(
                session_id,
                {field_name: output}
            )
    
    def get_phase_output(self, session_id: str, phase: str):
        """Get output from a specific phase"""
        return self.session_service.get_phase_output(session_id, phase)
    
    def advance_phase(self, session_id: str, new_phase: str):
        """Move to next phase"""
        self.session_service.advance_phase(session_id, new_phase)
    
    # Memory operations
    def remember(
        self,
        key: str,
        content: str,
        category: str,
        tags: list = None,
        importance: float = 1.0
    ):
        """Store something in long-term memory"""
        self.memory_bank.store_memory(
            entry_id=key,
            category=category,
            content=content,
            tags=tags or [],
            importance=importance
        )
    
    def recall(self, context: dict, limit: int = 5):
        """Recall relevant memories for current context"""
        return self.memory_bank.get_relevant_memories(context, limit)
    
    def get_template(self, template_type: str):
        """Get a template from memory"""
        memories = self.memory_bank.search_by_category(
            f"{template_type}_template",
            limit=1
        )
        return memories[0].content if memories else None
    
    def get_best_practices(self, tags: list = None):
        """Get best practices from memory"""
        if tags:
            return self.memory_bank.search_by_tags(
                tags=['best-practice'] + tags,
                limit=10
            )
        else:
            return self.memory_bank.search_by_category(
                'best_practice',
                limit=10
            )
    
    def learn_from_project(self, session_id: str):
        """Extract learnings from a completed project"""
        session = self.session_service.get_session(session_id)
        if not session:
            return
        
        # Store successful patterns as memories
        if len(session.completed_phases) >= 4:  # At least partially complete
            learning_id = f"lesson_{session_id}"
            self.memory_bank.store_memory(
                entry_id=learning_id,
                category='lesson_learned',
                content=f"Project: {session.project_name}, Module: {session.module}",
                metadata={
                    'project_name': session.project_name,
                    'module': session.module,
                    'erp_system': session.erp_system,
                    'completed_phases': session.completed_phases
                },
                tags=[session.module.lower(), session.erp_system.lower()],
                importance=0.8
            )
    
    def get_memory_stats(self) -> dict:
        """Get statistics about memory usage"""
        return {
            'sessions': {
                'active': len(self.session_service.list_sessions()),
                'sessions': self.session_service.list_sessions()
            },
            'memory_bank': self.memory_bank.get_statistics()
        }


# Global unified memory instance
agent_memory = AgentMemory()