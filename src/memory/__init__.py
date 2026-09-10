
"""
Unified memory interface for ERP Consultant Agent
"""
import uuid
from typing import Optional
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
from .project_memory import ProjectMemoryStore, project_memory_store

__all__ = [
    'SessionState',
    'InMemorySessionService',
    'session_service',
    'MemoryEntry',
    'MemoryBank',
    'memory_bank',
    'ProjectMemoryStore',
    'project_memory_store',
    'AgentMemory'
]


class AgentMemory:
    """
    Unified memory interface that combines session management and
    per-project long-term memory (see project_memory.py - every memory
    operation below is scoped to a specific session_id; there is no
    cross-project recall).
    """
    
    def __init__(self):
        self.session_service = session_service
        self.memory_bank = memory_bank
        self.project_memory = project_memory_store
    
    def create_project(
        self,
        project_name: str,
        module: str,
        erp_system: str = "SAP S/4HANA",
        user_id: Optional[str] = None,
        is_casual: bool = False
    ) -> str:
        """Create a new project session"""
        slug = project_name.lower().replace(' ', '_')[:30]
        session_id = f"prj_{slug}_{uuid.uuid4().hex[:8]}"
        session = self.session_service.create_session(
            session_id=session_id,
            project_name=project_name,
            module=module,
            erp_system=erp_system,
            user_id=user_id,
            is_casual=is_casual
        )
        # Casual (no-explicit-project) sessions don't need the full
        # requirements/design/testing template scaffolding - only real
        # projects that will actually run phases do.
        if not is_casual:
            self.project_memory.seed_defaults(session_id)
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
    
    # Memory operations - all scoped to session_id, see project_memory.py
    def remember(
        self,
        session_id: str,
        key: str,
        content: str,
        category: str,
        tags: list = None,
        importance: float = 1.0
    ):
        """Store something in this project's long-term memory"""
        self.project_memory.store_memory(
            session_id=session_id,
            entry_id=key,
            category=category,
            content=content,
            tags=tags or [],
            importance=importance
        )
    
    def recall(self, session_id: str, context: dict, limit: int = 5):
        """Recall memories relevant to the given context, scoped to this
        project only - never returns another project's entries."""
        return self.project_memory.get_relevant_memories(session_id, context, limit)
    
    def get_template(self, session_id: str, template_type: str):
        """Get a template from this project's memory"""
        memories = self.project_memory.search_by_category(
            session_id,
            f"{template_type}_template",
            limit=1
        )
        return memories[0].content if memories else None
    
    def get_best_practices(self, session_id: str, tags: list = None):
        """Get best practices from this project's memory"""
        if tags:
            return self.project_memory.search_by_tags(
                session_id,
                tags=['best-practice'] + tags,
                limit=10
            )
        else:
            return self.project_memory.search_by_category(
                session_id,
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
            self.project_memory.store_memory(
                session_id=session_id,
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
    
    def get_memory_stats(self, session_id: str) -> dict:
        """Get statistics about one project's memory usage. Requires a
        session_id now that memory is per-project rather than global -
        there's no longer a single pool to summarize across everyone."""
        categories: dict = {}
        for cat in ('requirements_template', 'process_pattern', 'solution_pattern',
                    'test_case_template', 'best_practice', 'lesson_learned',
                    'common_issue', 'erp_knowledge'):
            entries = self.project_memory.search_by_category(session_id, cat)
            if entries:
                categories[cat] = len(entries)
        return {
            'sessions': {
                'active': len(self.session_service.list_sessions()),
                'sessions': self.session_service.list_sessions()
            },
            'project_memory': {
                'session_id': session_id,
                'total_memories': sum(categories.values()),
                'categories': categories,
            }
        }


# Global unified memory instance
agent_memory = AgentMemory()