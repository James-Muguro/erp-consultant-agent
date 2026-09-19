"""
Session management for maintaining state across agent interactions.

Timestamp convention: every datetime stored on a session is timezone-aware
and UTC. This was previously naive local time (datetime.now()), which is a
correctness bug on any multi-worker or multi-region deployment — the naive
values are interpreted as server-local time by Postgres when written to the
timestamptz columns, producing inconsistent absolute times for the same
wall-clock event. Sessions created before this change have naive ISO strings
on disk; SessionState.from_dict normalizes both vintages to UTC-aware.
"""
from __future__ import annotations

import dataclasses
import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config.settings import settings
from src.utils.logger import AgentLogger


# ---------------------------------------------------------------------------
# Phase definitions - single source of truth
# ---------------------------------------------------------------------------
# Previously duplicated between this module and src/memory/__init__.py's
# AgentMemory. AgentMemory should import these rather than re-declare them;
# see the note at the end of this module.
PHASES: tuple = (
    'requirements_gathering',
    'process_mapping',
    'solution_design',
    'qa_testing',
    'uat_testing',
    'training',
)

PHASE_FIELD_MAP: Dict[str, str] = {
    'requirements_gathering': 'requirements_document',
    'process_mapping': 'process_maps',
    'solution_design': 'solution_design',
    'qa_testing': 'qa_test_cases',
    'uat_testing': 'uat_test_cases',
    'training': 'training_materials',
}

# Import-time consistency check: if PHASES and PHASE_FIELD_MAP ever drift
# (a phase added to one but not the other), fail loudly at startup.
if set(PHASES) != set(PHASE_FIELD_MAP.keys()):
    raise RuntimeError(
        "PHASES and PHASE_FIELD_MAP are out of sync. "
        f"PHASES={PHASES}, PHASE_FIELD_MAP keys={sorted(PHASE_FIELD_MAP.keys())}"
    )


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def _utcnow() -> datetime:
    """Timezone-aware current time. Everything in this module writes and
    stores datetimes through this helper, so the DB's timestamptz columns
    receive consistent absolute times regardless of which worker wrote
    them."""
    return datetime.now(timezone.utc)


def _parse_datetime(value: Any) -> datetime:
    """Parse a stored datetime value to timezone-aware UTC.

    Handles three input shapes:
      * timezone-aware datetime (modern sessions)
      * naive datetime (older sessions, assumed UTC — matches the new write
        convention, so both vintages end up comparable)
      * ISO string, either with or without an offset (both vintages on disk)
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            # Corrupt or unexpected value — fall back to "now" rather than
            # crashing the load. The load path already logs failures.
            return _utcnow()
    else:
        return _utcnow()

    if dt.tzinfo is None:
        # Naive: assume UTC. This is the convention used by pre-fix sessions
        # and the only choice that keeps them comparable to post-fix ones.
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class SessionState:
    """Represents the state of a session.

    The object is shared and mutable: get_session() returns the cached
    instance, not a copy. Callers may mutate it directly and then call
    update_session() (or _save_session) to persist. See the docstring on
    InMemorySessionService.get_session for the implications.
    """
    session_id: str
    project_name: str
    module: str
    erp_system: str
    # Owning user's id. Optional for backward compatibility with sessions
    # created before per-user auth existed (Stage 2) - every session created
    # from that point on always sets this.
    user_id: Optional[str] = None
    # True for sessions auto-created from a plain question rather than an
    # explicit "start a project" action - see src/db/models.py for why.
    is_casual: bool = False
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Workflow state
    current_phase: str = "requirements_gathering"
    completed_phases: List[str] = field(default_factory=list)

    # Agent outputs
    requirements_document: Optional[str] = None
    process_maps: Optional[Dict[str, Any]] = None
    solution_design: Optional[str] = None
    qa_test_cases: Optional[List[Dict]] = None
    uat_test_cases: Optional[List[Dict]] = None
    training_materials: Optional[Dict[str, Any]] = None

    # Context and history
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    decisions_log: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert session state to dictionary."""
        return {
            'session_id': self.session_id,
            'project_name': self.project_name,
            'module': self.module,
            'erp_system': self.erp_system,
            'user_id': self.user_id,
            'is_casual': self.is_casual,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'metadata': self.metadata,
            'current_phase': self.current_phase,
            'completed_phases': self.completed_phases,
            'requirements_document': self.requirements_document,
            'process_maps': self.process_maps,
            'solution_design': self.solution_design,
            'qa_test_cases': self.qa_test_cases,
            'uat_test_cases': self.uat_test_cases,
            'training_materials': self.training_materials,
            'conversation_history': self.conversation_history,
            'decisions_log': self.decisions_log,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SessionState':
        """Create session state from dictionary.

        Fixes two previous issues:
          * The input dict is copied before modification rather than
            mutated in place.
          * Unknown keys are filtered rather than raising TypeError. This
            makes forward compatibility work: a field added on the dataclass
            or removed from it doesn't break loading older/newer records.
        """
        if not isinstance(data, dict):
            raise TypeError(f"from_dict expected dict, got {type(data).__name__}")

        safe = dict(data)  # never mutate the caller's dict
        safe['created_at'] = _parse_datetime(safe.get('created_at'))
        safe['updated_at'] = _parse_datetime(safe.get('updated_at'))

        valid_fields = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in safe.items() if k in valid_fields}
        return cls(**filtered)


class InMemorySessionService:
    """In-memory session management service (file-backed).

    Kept for reference and as a fallback; production uses DbSessionService
    at the bottom of this module. The two share almost all their logic —
    only the storage primitives (_save_session, _load_session, and the
    enumeration/deletion methods) differ.
    """

    def __init__(self):
        self.sessions: Dict[str, SessionState] = {}
        self.logger = AgentLogger("SessionManager")
        self.persistence_dir = Path(settings.output_dir) / "sessions"
        self.persistence_dir.mkdir(parents=True, exist_ok=True)
        self._save_lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def create_session(
        self,
        session_id: str,
        project_name: str,
        module: str,
        erp_system: str = "SAP S/4HANA",
        metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        is_casual: bool = False,
    ) -> SessionState:
        """Create a new session, or return the existing one if the id is
        already in use. The previous version logged a warning and returned
        the existing session — preserved, since callers rely on the
        idempotent behavior when create_project is retried after a
        transient failure."""
        if session_id in self.sessions:
            self.logger.warning(f"Session {session_id} already exists")
            return self.sessions[session_id]

        session = SessionState(
            session_id=session_id,
            project_name=project_name,
            module=module,
            erp_system=erp_system,
            user_id=user_id,
            is_casual=is_casual,
            metadata=metadata or {},
        )

        self.sessions[session_id] = session
        self.logger.info(
            "Session created",
            session_id=session_id,
            project_name=project_name,
            module=module,
        )

        self._save_session(session)
        return session

    def get_session(self, session_id: str) -> Optional[SessionState]:
        """Get session by ID.

        IMPORTANT — shared-object semantics: the returned object is the
        same instance cached in self.sessions (or, on a cache miss, the
        instance created by _load_session and then cached). Callers may
        mutate it directly and then persist via update_session() or
        _save_session(), but changes made without one of those calls will
        not reach storage. Prefer update_session() for any persistent
        change; mutate-in-place is safe only for transient reads.
        """
        if session_id in self.sessions:
            return self.sessions[session_id]
        return self._load_session(session_id)

    def update_session(
        self,
        session_id: str,
        updates: Dict[str, Any],
    ) -> Optional[SessionState]:
        """Update session state, merging the supplied fields.

        Unknown field names are now logged as warnings rather than silently
        ignored — a typo in a caller-supplied key (e.g. {'pm_processes':
        ...} instead of {'process_maps': ...}) previously dropped the
        update with no signal, and the calling agent's success:True made it
        look saved.
        """
        session = self.get_session(session_id)
        if not session:
            self.logger.error(f"Session {session_id} not found")
            return None

        unknown = [k for k in updates.keys() if not hasattr(session, k)]
        if unknown:
            self.logger.warning(
                "update_session called with unknown field(s); ignored",
                session_id=session_id,
                unknown_fields=unknown,
                valid_fields=sorted(f.name for f in dataclasses.fields(SessionState)),
            )

        for key, value in updates.items():
            if hasattr(session, key):
                setattr(session, key, value)

        session.updated_at = _utcnow()

        self.logger.info(
            "Session updated",
            session_id=session_id,
            updated_fields=list(updates.keys()),
        )

        self._save_session(session)
        return session

    # ------------------------------------------------------------------ #
    # History
    # ------------------------------------------------------------------ #
    def add_to_conversation(
        self,
        session_id: str,
        role: str,
        content: str,
        agent_name: Optional[str] = None,
    ) -> None:
        """Add message to conversation history, trimmed to the configured
        maximum."""
        session = self.get_session(session_id)
        if not session:
            self.logger.warning(
                "add_to_conversation called for missing session", session_id=session_id
            )
            return

        session.conversation_history.append({
            'timestamp': _utcnow().isoformat(),
            'role': role,
            'content': content,
            'agent_name': agent_name,
        })

        max_items = settings.max_conversation_history_items
        if len(session.conversation_history) > max_items:
            session.conversation_history = session.conversation_history[-max_items:]

        session.updated_at = _utcnow()
        self._save_session(session)

    def log_decision(
        self,
        session_id: str,
        decision: str,
        rationale: str,
        agent_name: str,
    ) -> None:
        """Log an important decision.

        Now bumps session.updated_at — a logged decision is a substantive
        change to the session and should move it in 'most recently updated'
        orderings. Previously only add_to_conversation bumped updated_at,
        so decisions were invisible to any UI that sorted by that field.
        """
        session = self.get_session(session_id)
        if not session:
            self.logger.warning(
                "log_decision called for missing session", session_id=session_id
            )
            return

        session.decisions_log.append({
            'timestamp': _utcnow().isoformat(),
            'decision': decision,
            'rationale': rationale,
            'agent_name': agent_name,
        })

        session.updated_at = _utcnow()

        self.logger.log_memory_operation(
            "decision_logged",
            {'session_id': session_id, 'decision': decision},
        )

        self._save_session(session)

    # ------------------------------------------------------------------ #
    # Phase transitions
    # ------------------------------------------------------------------ #
    def advance_phase(self, session_id: str, new_phase: str) -> None:
        """Move session to the next phase.

        Fixes two issues in the previous implementation:

          * The old_phase value logged was read after the assignment, so
            the log line always showed old_phase == new_phase. It is now
            captured before the reassignment.
          * Calling advance_phase() with the current phase (an idempotent
            re-announcement) used to append the current phase to
            completed_phases. That marked a phase completed purely because
            someone restated it. The check now requires that the phase
            actually change before recording the previous one as complete.

        Phase-name validation and backwards-move refusal remain the
        responsibility of AgentMemory.advance_phase, which wraps this
        method. Calls made directly through session_service bypass those
        checks — prefer the AgentMemory wrapper unless you have a reason.
        """
        session = self.get_session(session_id)
        if not session:
            self.logger.warning(
                "advance_phase called for missing session", session_id=session_id
            )
            return

        old_phase = session.current_phase

        if old_phase != new_phase and old_phase not in session.completed_phases:
            session.completed_phases.append(old_phase)

        session.current_phase = new_phase
        session.updated_at = _utcnow()

        self.logger.info(
            "Phase advanced",
            session_id=session_id,
            old_phase=old_phase,
            new_phase=new_phase,
        )

        self._save_session(session)

    def get_phase_output(self, session_id: str, phase: str) -> Optional[Any]:
        """Get output from a specific phase. Uses the shared
        PHASE_FIELD_MAP constant — previously this had its own copy of the
        same six mappings, which is exactly the pattern that drifts."""
        session = self.get_session(session_id)
        if not session:
            return None

        field_name = PHASE_FIELD_MAP.get(phase)
        if field_name:
            return getattr(session, field_name, None)

        self.logger.warning(
            "get_phase_output called with unknown phase",
            session_id=session_id,
            phase=phase,
            valid_phases=PHASES,
        )
        return None

    # ------------------------------------------------------------------ #
    # Enumeration and lifecycle
    # ------------------------------------------------------------------ #
    def list_sessions(self) -> List[str]:
        """List all active session IDs."""
        return list(self.sessions.keys())

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and its on-disk file."""
        if session_id in self.sessions:
            del self.sessions[session_id]

            session_file = self.persistence_dir / f"{session_id}.json"
            if session_file.exists():
                session_file.unlink()

            self.logger.info("Session deleted", session_id=session_id)
            return True

        return False

    # ------------------------------------------------------------------ #
    # Storage primitives (overridden by DbSessionService)
    # ------------------------------------------------------------------ #
    def _save_session(self, session: SessionState) -> None:
        """Save session to disk atomically. Writes to a temp file first,
        then does an atomic rename — a concurrent reader or a crash
        mid-write can never see a partially-written file. The lock
        prevents two threads' writes from interleaving in the temp file
        itself."""
        session_file = self.persistence_dir / f"{session.session_id}.json"
        tmp_file = self.persistence_dir / f"{session.session_id}.json.tmp"
        with self._save_lock:
            with open(tmp_file, 'w') as f:
                json.dump(session.to_dict(), f, indent=2, default=str)
            os.replace(tmp_file, session_file)

    def _load_session(self, session_id: str) -> Optional[SessionState]:
        """Load session from disk."""
        session_file = self.persistence_dir / f"{session_id}.json"

        if not session_file.exists():
            return None

        try:
            with open(session_file, 'r') as f:
                data = json.load(f)

            session = SessionState.from_dict(data)
            self.sessions[session_id] = session
            return session
        except Exception as e:
            self.logger.error(f"Failed to load session {session_id}: {e}")
            return None

    def get_session_summary(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get summary of session state."""
        session = self.get_session(session_id)
        if not session:
            return None

        return {
            'session_id': session.session_id,
            'project_name': session.project_name,
            'module': session.module,
            'erp_system': session.erp_system,
            'is_casual': session.is_casual,
            'current_phase': session.current_phase,
            'completed_phases': session.completed_phases,
            'phases_completed': len(session.completed_phases),
            'total_conversations': len(session.conversation_history),
            'total_decisions': len(session.decisions_log),
            'created_at': session.created_at.isoformat(),
            'last_updated': session.updated_at.isoformat(),
        }


class DbSessionService(InMemorySessionService):
    """Session service backed by a real database instead of per-file JSON.

    Reuses every method from InMemorySessionService unchanged (create/update/
    add_to_conversation/log_decision/advance_phase/get_phase_output all just
    mutate a SessionState object then call self._save_session) — only the
    storage primitives are overridden. Each session is still stored as the
    same to_dict()/from_dict() JSON shape as before; it just lives in a
    database row. This also fixes two pre-existing limitations of the
    file-based service: list_sessions() and delete_session() only ever
    worked for sessions already loaded into this process's memory — here
    both go straight to the database.

    Cascade behavior on delete: sessions have ON DELETE CASCADE on their
    child FKs (see src/db/models.py). Postgres honors it unconditionally.
    SQLite honors it only when PRAGMA foreign_keys=ON, which is a
    per-connection setting — src/db/base.py is responsible for enabling it.
    If it isn't enabled, delete_session() leaves orphaned rows in the
    project_intelligence tables. Verify the pragma is active in any SQLite
    deployment before relying on delete_session to clean up.
    """

    def __init__(self):
        # Skip InMemorySessionService.__init__'s file-directory setup — we
        # don't need a sessions/ directory — but keep the same cache dict,
        # logger, and lock, since inherited methods rely on them.
        self.sessions: Dict[str, SessionState] = {}
        self.logger = AgentLogger("SessionManager")
        self._save_lock = threading.Lock()

        from src.db.base import init_db, SessionLocal, engine
        if engine.dialect.name == "sqlite":
            # SQLite (the zero-setup dev/test default) auto-creates tables
            # on first use for convenience. Postgres deployments run
            # `alembic upgrade head` explicitly.
            init_db()
        self._db_session_factory = SessionLocal

    def _save_session(self, session: SessionState) -> None:
        from src.db.models import SessionRecord

        with self._save_lock:
            db = self._db_session_factory()
            try:
                data = session.to_dict()
                record = db.get(SessionRecord, session.session_id)
                if record is None:
                    record = SessionRecord(session_id=session.session_id)
                    db.add(record)
                record.project_name = session.project_name
                record.module = session.module
                record.erp_system = session.erp_system
                record.user_id = session.user_id
                record.is_casual = session.is_casual
                record.current_phase = session.current_phase
                # Both of these are timezone-aware UTC after the SessionState
                # fix. Assigning them here supersedes the ORM's onupdate;
                # both paths now write the same UTC convention.
                record.created_at = session.created_at
                record.updated_at = session.updated_at
                record.data = data
                db.commit()
            finally:
                db.close()

    def _load_session(self, session_id: str) -> Optional[SessionState]:
        from src.db.models import SessionRecord

        db = self._db_session_factory()
        try:
            record = db.get(SessionRecord, session_id)
            if record is None:
                return None
            try:
                session = SessionState.from_dict(record.data)
            except Exception as e:
                self.logger.error(f"Failed to deserialize session {session_id}: {e}")
                return None
            self.sessions[session_id] = session
            return session
        finally:
            db.close()

    def list_sessions(self) -> List[str]:
        """List all session IDs known to the database (not just the ones
        cached in this process's memory)."""
        from src.db.models import SessionRecord
        from sqlalchemy import select

        db = self._db_session_factory()
        try:
            rows = db.execute(select(SessionRecord.session_id)).all()
            return [row[0] for row in rows]
        finally:
            db.close()

    def list_sessions_for_user(
        self, user_id: str, include_archived: bool = False,
    ) -> List[str]:
        """List session IDs owned by a specific user, most recently
        updated first. Used by the API's conversation-list endpoint —
        list_sessions() above stays unscoped for CLI/admin use."""
        from src.db.models import SessionRecord
        from sqlalchemy import select

        db = self._db_session_factory()
        try:
            query = select(SessionRecord.session_id).where(
                SessionRecord.user_id == user_id
            )
            if not include_archived:
                query = query.where(SessionRecord.archived_at.is_(None))
            rows = db.execute(
                query.order_by(SessionRecord.updated_at.desc())
            ).all()
            return [row[0] for row in rows]
        finally:
            db.close()

    def rename_session(
        self, session_id: str, new_project_name: str,
    ) -> Optional[SessionState]:
        """Rename a session's project_name, in both the indexed column and
        the JSON blob. Goes through the normal get → mutate → save path so
        both stay consistent."""
        session = self.get_session(session_id)
        if not session:
            return None
        session.project_name = new_project_name
        session.updated_at = _utcnow()
        self._save_session(session)
        return session

    def archive_session(self, session_id: str) -> bool:
        """Soft-delete: hide from listings without destroying data. Returns
        False if the session doesn't exist or is already archived."""
        from src.db.models import SessionRecord

        db = self._db_session_factory()
        try:
            record = db.get(SessionRecord, session_id)
            if record is None or record.archived_at is not None:
                return False
            record.archived_at = _utcnow()
            db.commit()
            # Keep the in-memory cache in sync with the archived state; the
            # next _load_session will pick up the new archived_at from the
            # DB, but the currently-cached object should not appear "live"
            # if the caller immediately queries is_archived via the session.
            cached = self.sessions.get(session_id)
            if cached is not None:
                # No archived_at field on SessionState — the session's
                # archived state is authoritative in the DB column. Nothing
                # to update on the cached object itself.
                pass
            return True
        finally:
            db.close()

    def is_archived(self, session_id: str) -> Optional[bool]:
        """Returns None if the session doesn't exist at all."""
        from src.db.models import SessionRecord

        db = self._db_session_factory()
        try:
            record = db.get(SessionRecord, session_id)
            if record is None:
                return None
            return record.archived_at is not None
        finally:
            db.close()

    def delete_session(self, session_id: str) -> bool:
        """Hard-delete a session and its associated objects.

        Explicitly deletes ProjectMemory and Feedback (they carry user-
        attributable data that a caller may want to observe being removed,
        and being explicit here makes the deletion auditable), and relies
        on ON DELETE CASCADE for the project_intelligence tables. On SQLite
        this requires PRAGMA foreign_keys=ON — see class docstring.

        Also removes uploaded project documents from object storage before
        deleting their metadata rows; a failure to delete the storage
        object is logged but does not prevent the DB delete, since leaving
        orphaned storage is preferable to leaving a half-deleted session.
        """
        from src.db.models import SessionRecord, ProjectMemory, Feedback, ProjectDocument

        try:
            from src.storage import object_storage
        except Exception:  # noqa: BLE001 - storage is optional in some envs
            object_storage = None

        db = self._db_session_factory()
        try:
            record = db.get(SessionRecord, session_id)
            if record is None:
                return False

            # 1. Best-effort object storage cleanup.
            if object_storage is not None:
                storage_keys = [
                    row[0]
                    for row in db.query(ProjectDocument.storage_key)
                    .filter(ProjectDocument.session_id == session_id)
                    .all()
                ]
                for storage_key in storage_keys:
                    try:
                        object_storage.delete_object(storage_key)
                    except Exception:
                        self.logger.exception(
                            "Failed to delete project document from object storage",
                            session_id=session_id,
                            storage_key=storage_key,
                        )

            # 2. Explicit user-data cleanup for the tables we don't want to
            #    leave to cascade.
            db.query(ProjectMemory).filter(
                ProjectMemory.session_id == session_id
            ).delete(synchronize_session=False)
            db.query(Feedback).filter(
                Feedback.session_id == session_id
            ).delete(synchronize_session=False)

            # 3. Delete the session; cascade removes project_intelligence
            #    rows if the DB enforces foreign keys.
            db.delete(record)
            db.commit()

            self.sessions.pop(session_id, None)

            self.logger.info("Session deleted", session_id=session_id)
            return True
        finally:
            db.close()


# Global session service instance — database-backed.
session_service = DbSessionService()