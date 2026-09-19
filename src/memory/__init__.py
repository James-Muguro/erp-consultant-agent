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
# The canonical ERP delivery phase sequence, in order. This tuple is the
# single source of truth for:
#   - the phase -> session-field mapping used by save_phase_output
#   - the progress percentage in get_project_state
#   - the phase validation in advance_phase

# Defensive assertion at import time. If PHASES and _PHASE_FIELD_MAP ever
# drift (a phase added in one place but not the other), fail loudly at
# startup rather than at the moment an agent tries to save phase output.
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
# The underlying ProjectMemoryStore returns rows from SQLAlchemy, which
# are ORM objects with a `.content` attribute. But there are several
# plausible futures where they become plain dicts (a serialization layer,
# a different backend, a mock in tests). Every entry-consuming method
# in this file goes through _entry_content so a shape change doesn't
# cause an AttributeError deep inside an agent's context builder.
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
    per-project long-term memory (see project_memory.py - every memory
    operation below is scoped to a specific session_id; there is no
    cross-project recall).
    """

    def __init__(self):
        self.session_service = session_service
        self.memory_bank = memory_bank
        self.project_memory = project_memory_store

    # ------------------------------------------------------------------ #
    # Project lifecycle
    # ------------------------------------------------------------------ #
    def create_project(
        self,
        project_name: str,
        module: str,
        erp_system: str = "SAP S/4HANA",
        user_id: Optional[str] = None,
        is_casual: bool = False,
    ) -> str:
        """Create a new project session and, for real (non-casual)
        projects, seed the requirements/design/testing template memories.
        If seeding fails, the session is deleted before re-raising — a
        half-created project without its seeded templates would silently
        produce agent output with thinner context than expected."""
        slug = project_name.lower().replace(' ', '_')[:30] or "project"
        session_id = f"prj_{slug}_{uuid.uuid4().hex[:8]}"

        self.session_service.create_session(
            session_id=session_id,
            project_name=project_name,
            module=module,
            erp_system=erp_system,
            user_id=user_id,
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
                # Best-effort rollback. If delete_session itself fails,
                # log it but don't mask the original seeding exception.
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
        )
        return session_id

    def get_project_state(self, session_id: str) -> Dict[str, Any]:
        """Return a summary of a project's current state. Returns an empty
        dict if the session doesn't exist (matches the previous behavior,
        which callers rely on)."""
        session = self.session_service.get_session(session_id)
        if not session:
            return {}

        completed = getattr(session, 'completed_phases', None) or []
        total = len(PHASES) or 1  # guard against a future empty-tuple bug
        progress = round(len(completed) / total * 100, 1)

        return {
            'project_name': session.project_name,
            'module': session.module,
            'erp_system': session.erp_system,
            'current_phase': session.current_phase,
            'completed_phases': completed,
            'progress': progress,
        }

    # ------------------------------------------------------------------ #
    # Phase output
    # ------------------------------------------------------------------ #
    def save_phase_output(
        self,
        session_id: str,
        phase: str,
        output: Any,
    ) -> bool:
        """Persist the structured output of a phase on the session.

        Returns True if the output was stored, False if the phase is not
        recognized. Previously this returned None on both paths — a typo
        in the phase name silently dropped the output, and the calling
        agent's `success: True` made it look saved. Now the caller can
        distinguish the two cases, and unknown phases are logged as a
        warning so they surface in production."""
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
        """Retrieve the stored output for a phase, or None if the phase
        hasn't run or isn't recognized."""
        return self.session_service.get_phase_output(session_id, phase)

    def advance_phase(self, session_id: str, new_phase: str) -> bool:
        """Move the session to a new phase.

        Now rejects phase names that aren't in PHASES, and refuses to
        move backwards through the sequence — an ERP pipeline that
        accepts 'training' before 'solution_design' is one regression
        away from producing training material for a solution that
        doesn't exist. Returns True if the phase was advanced, False if
        the target was rejected. The underlying session_manager may
        still track additional metadata (timestamps, etc.); this wrapper
        adds the ordering discipline the memory layer needs.

        Note: re-entering the *current* phase is idempotent and returns
        True (some callers re-set the phase after a retry)."""
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

    # ------------------------------------------------------------------ #
    # Long-term memory
    # ------------------------------------------------------------------ #
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
        """Store something in this project's long-term memory.

        `metadata` was previously accepted only by `learn_from_project`,
        which meant any caller who wanted to attach structured metadata
        had to bypass this method. It's now a first-class argument that
        is forwarded to the underlying store. Accepting it here keeps
        the two call sites consistent — previously one used it and one
        silently didn't have access to it."""
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
        """Recall memories relevant to the given context, scoped to this
        project only - never returns another project's entries."""
        return self.project_memory.get_relevant_memories(session_id, context, limit)

    def get_template(
        self,
        session_id: str,
        template_type: str,
    ) -> Optional[str]:
        """Get a template from this project's memory. Returns the content
        string, or None if no template of that type exists.

        Defensive about entry shape: `search_by_category` may return ORM
        rows (the current case), dicts (a serialization layer), or
        anything else with a `.content` attribute or a `'content'` key."""
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
        """Get best practices from this project's memory, optionally
        filtered by additional tags on top of the 'best-practice'
        category tag."""
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
        """Extract learnings from a partially or fully completed project.

        The threshold is 'at least half the phases completed' — computed
        from PHASES rather than a hardcoded 4, so adding or removing a
        phase doesn't silently make this fire too early or never fire at
        all. Metadata and tags are forwarded via `remember`, which now
        accepts them consistently."""
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

        # Tags used for later recall. Filter empties so a session with an
        # unusual module name doesn't produce tags like ['', 'sap s/4hana'].
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

    # ------------------------------------------------------------------ #
    # Stats
    # ------------------------------------------------------------------ #
    def get_memory_stats(self, session_id: str) -> Dict[str, Any]:
        """Statistics about one project's memory usage. Session-scoped —
        returns the count of that session's own memories by category.

        Note on session enumeration: this method deliberately does NOT
        return the list of session IDs on the platform. That list would
        be a cross-tenant leak (every user's project IDs exposed to any
        caller of this method), and contradicts the "no cross-project
        read path, by design" rule stated in project_memory.py. If a
        caller genuinely needs an admin view of all sessions, that
        belongs on an admin-scoped endpoint with its own authorization,
        not on the project memory facade.
        """
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


# Global unified memory instance
agent_memory = AgentMemory()