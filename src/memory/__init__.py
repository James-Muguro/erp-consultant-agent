"""
Unified memory interface for ERP Consultant Agent.
"""
from __future__ import annotations

from src.utils.logger import get_logger
import uuid
from typing import Any, Dict, List, Optional

from .session_manager import PHASES, PHASE_FIELD_MAP

from .session_manager import (
    SessionState,
    InMemorySessionService,
    session_service,
)
from .memory_bank import (
    MemoryEntry,
    MemoryBank,
    memory_bank,
)
from .project_memory import ProjectMemoryStore, project_memory_store

logger = get_logger(__name__)

__all__ = [
    'SessionState',
    'InMemorySessionService',
    'session_service',
    'MemoryEntry',
    'MemoryBank',
    'memory_bank',
    'ProjectMemoryStore',
    'project_memory_store',
    'AgentMemory',
    'agent_memory',
]


# ---------------------------------------------------------------------------
# Phase definitions
# ---------------------------------------------------------------------------
_missing = set(PHASES) - set(PHASE_FIELD_MAP.keys())
_extra = set(PHASE_FIELD_MAP.keys()) - set(PHASES)
if _missing or _extra:
    raise RuntimeError(
        f"PHASES/PHASE_FIELD_MAP mismatch. Missing mapping: {sorted(_missing)}. "
        f"Unknown keys in mapping: {sorted(_extra)}."
    )


# ---------------------------------------------------------------------------
# Shape-normalization helpers
# ---------------------------------------------------------------------------
def _entry_content(entry: Any) -> Optional[str]:
    if entry is None:
        return None
    if isinstance(entry, dict):
        return entry.get('content')
    return getattr(entry, 'content', None)


def _entry_field(entry: Any, field: str, default: Any = None) -> Any:
    if entry is None:
        return default
    if isinstance(entry, dict):
        return entry.get(field, default)
    return getattr(entry, field, default)


class AgentMemory:
    """
    Unified memory interface that combines session management and
    per-project long-term memory.
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
        organization_id: Optional[str] = None,
        is_casual: bool = False,
    ) -> str:
        """Create a new project session and, for real (non-casual)
        projects, seed the requirements/design/testing template memories.
        If seeding fails, the session is deleted before re-raising.

        organization_id is the tenant context: None for a personal
        project, an Organization id for an org-owned one. Callers are
        responsible for verifying that the user is authorized to create
        a project in that organization BEFORE calling this method; this
        function does not perform that check. The API route that drives
        this path (POST /api/projects/start) enforces the boundary.
        """
        slug = project_name.lower().replace(' ', '_')[:30] or "project"
        session_id = f"prj_{slug}_{uuid.uuid4().hex[:8]}"

        self.session_service.create_session(
            session_id=session_id,
            project_name=project_name,
            module=module,
            erp_system=erp_system,
            user_id=user_id,
            organization_id=organization_id,
            is_casual=is_casual,
        )

        if not is_casual:
            try:
                self.project_memory.seed_defaults(session_id)
            except Exception:
                logger.exception(
                    "seed_defaults failed for session %s; rolling back session",
                    session_id,
                )
                try:
                    self.session_service.delete_session(session_id)
                except Exception:
                    logger.exception(
                        "Rollback (delete_session) also failed for %s", session_id
                    )
                raise

        logger.info(
            "Created project session",
            session_id=session_id,
            module=module,
            is_casual=is_casual,
            organization_id=organization_id,
        )
        return session_id

    def get_project_state(self, session_id: str) -> Dict[str, Any]:
        session = self.session_service.get_session(session_id)
        if not session:
            return {}

        completed = getattr(session, 'completed_phases', None) or []
        total = len(PHASES) or 1
        progress = round(len(completed) / total * 100, 1)

        return {
            'project_name': session.project_name,
            'module': session.module,
            'erp_system': session.erp_system,
            'current_phase': session.current_phase,
            'completed_phases': completed,
            'progress': progress,
        }

    def save_phase_output(
        self,
        session_id: str,
        phase: str,
        output: Any,
    ) -> bool:
        field_name = PHASE_FIELD_MAP.get(phase)
        if not field_name:
            logger.warning(
                "save_phase_output called with unknown phase %r for session %s; "
                "no output was saved. Valid phases: %s",
                phase, session_id, PHASES,
            )
            return False

        self.session_service.update_session(session_id, {field_name: output})
        logger.info(
            "Saved phase output",
            session_id=session_id,
            phase=phase,
            field=field_name,
        )
        return True

    def get_phase_output(self, session_id: str, phase: str) -> Any:
        return self.session_service.get_phase_output(session_id, phase)

    def advance_phase(self, session_id: str, new_phase: str) -> bool:
        if new_phase not in PHASES:
            logger.warning(
                "advance_phase called with unknown phase %r for session %s",
                new_phase, session_id,
            )
            return False

        session = self.session_service.get_session(session_id)
        if not session:
            logger.warning(
                "advance_phase called for missing session %s", session_id
            )
            return False

        current = getattr(session, 'current_phase', None)
        if current in PHASES and current != new_phase:
            if PHASES.index(new_phase) < PHASES.index(current):
                logger.warning(
                    "advance_phase refuses backwards move: session %s is at "
                    "%r, caller asked for %r",
                    session_id, current, new_phase,
                )
                return False

        self.session_service.advance_phase(session_id, new_phase)
        logger.info(
            "Advanced session phase",
            session_id=session_id,
            from_phase=current,
            to_phase=new_phase,
        )
        return True

    def remember(
        self,
        session_id: str,
        key: str,
        content: str,
        category: str,
        tags: Optional[List[str]] = None,
        importance: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.project_memory.store_memory(
            session_id=session_id,
            entry_id=key,
            category=category,
            content=content,
            tags=tags or [],
            importance=importance,
            metadata=metadata,
        )

    def recall(
        self,
        session_id: str,
        context: Dict[str, Any],
        limit: int = 5,
    ) -> List[Any]:
        return self.project_memory.get_relevant_memories(session_id, context, limit)

    def get_template(
        self,
        session_id: str,
        template_type: str,
    ) -> Optional[str]:
        memories = self.project_memory.search_by_category(
            session_id, f"{template_type}_template", limit=1,
        )
        if not memories:
            return None
        return _entry_content(memories[0])

    def get_best_practices(
        self,
        session_id: str,
        tags: Optional[List[str]] = None,
    ) -> List[Any]:
        if tags:
            return self.project_memory.search_by_tags(
                session_id,
                tags=['best-practice'] + list(tags),
                limit=10,
            )
        return self.project_memory.search_by_category(
            session_id, 'best_practice', limit=10,
        )

    def learn_from_project(self, session_id: str) -> None:
        session = self.session_service.get_session(session_id)
        if not session:
            logger.warning(
                "learn_from_project called for missing session %s", session_id
            )
            return

        completed = getattr(session, 'completed_phases', None) or []
        threshold = max(1, len(PHASES) // 2)
        if len(completed) < threshold:
            logger.debug(
                "Skipping learn_from_project for %s: %d of %d phases complete",
                session_id, len(completed), len(PHASES),
            )
            return

        tags = [
            str(session.module or '').lower(),
            str(session.erp_system or '').lower(),
        ]
        tags = [t for t in tags if t]

        self.remember(
            session_id=session_id,
            key=f"lesson_{session_id}",
            content=f"Project: {session.project_name}, Module: {session.module}",
            category='lesson_learned',
            tags=tags,
            importance=0.8,
            metadata={
                'project_name': session.project_name,
                'module': session.module,
                'erp_system': session.erp_system,
                'completed_phases': list(completed),
            },
        )

    def get_memory_stats(self, session_id: str) -> Dict[str, Any]:
        categories: Dict[str, int] = {}
        for cat in (
            'requirements_template', 'process_pattern', 'solution_pattern',
            'test_case_template', 'best_practice', 'lesson_learned',
            'common_issue', 'erp_knowledge',
        ):
            entries = self.project_memory.search_by_category(session_id, cat)
            if entries:
                categories[cat] = len(entries)

        return {
            'session_id': session_id,
            'total_memories': sum(categories.values()),
            'categories': categories,
        }


agent_memory = AgentMemory()