"""
Session management for maintaining state across agent interactions.

Timestamp convention: every datetime stored on a session is timezone-aware
and UTC. Sessions created before this change have naive ISO strings
on disk; SessionState.from_dict normalizes both vintages to UTC-aware.

Tenancy: SessionState.organization_id is NULL for personal projects and
non-NULL for organization-owned projects. Personal projects use the
existing ownership rule (session.user_id == current_user.id).
Organization-owned projects use an active OrganizationMembership for
the owning organization (enforced at the API layer, not here).

Listing semantics (Round 3a correction):
  * list_project_summaries_for_user returns BOTH the user's personal
    projects AND every project belonging to an organization the user
    is an active member of. This is the discoverability half of the
    tenant boundary: without it, an org member could only reach org
    projects by already knowing their session_id.
  * list_sessions_for_user returns ONLY personal projects. It is the
    deletion path used by account deletion, which must not destroy
    org-owned project data when the creator deletes their personal
    account. Org-owned sessions survive via the FK's ON DELETE SET NULL
    on sessions.user_id; only the attribution is removed.
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

if set(PHASES) != set(PHASE_FIELD_MAP.keys()):
    raise RuntimeError(
        "PHASES and PHASE_FIELD_MAP are out of sync. "
        f"PHASES={PHASES}, PHASE_FIELD_MAP keys={sorted(PHASE_FIELD_MAP.keys())}"
    )


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return _utcnow()
    else:
        return _utcnow()

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class SessionState:
    """Represents the state of a session.

    The object is shared and mutable: get_session() returns the cached
    instance, not a copy. Callers may mutate it directly and then call
    update_session() (or _save_session) to persist.
    """
    session_id: str
    project_name: str
    module: str
    erp_system: str
    user_id: Optional[str] = None
    organization_id: Optional[str] = None
    is_casual: bool = False
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    current_phase: str = "requirements_gathering"
    completed_phases: List[str] = field(default_factory=list)

    requirements_document: Optional[str] = None
    process_maps: Optional[Dict[str, Any]] = None
    solution_design: Optional[str] = None
    qa_test_cases: Optional[List[Dict]] = None
    uat_test_cases: Optional[List[Dict]] = None
    training_materials: Optional[Dict[str, Any]] = None

    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    decisions_log: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'session_id': self.session_id,
            'project_name': self.project_name,
            'module': self.module,
            'erp_system': self.erp_system,
            'user_id': self.user_id,
            'organization_id': self.organization_id,
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

        Unknown keys are filtered rather than raising TypeError, so a
        field added on the dataclass or removed from it doesn't break
        loading older/newer records. Pre-Round-3a blobs have no
        'organization_id' key and load with the dataclass default None."""
        if not isinstance(data, dict):
            raise TypeError(f"from_dict expected dict, got {type(data).__name__}")

        safe = dict(data)
        safe['created_at'] = _parse_datetime(safe.get('created_at'))
        safe['updated_at'] = _parse_datetime(safe.get('updated_at'))

        valid_fields = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in safe.items() if k in valid_fields}
        return cls(**filtered)


class InMemorySessionService:
    """In-memory session management service (file-backed).

    Kept for reference and as a fallback; production uses DbSessionService
    at the bottom of this module."""

    def __init__(self):
        self.sessions: Dict[str, SessionState] = {}
        self.logger = AgentLogger("SessionManager")
        self.persistence_dir = Path(settings.output_dir) / "sessions"
        self.persistence_dir.mkdir(parents=True, exist_ok=True)
        self._save_lock = threading.Lock()

    def create_session(
        self,
        session_id: str,
        project_name: str,
        module: str,
        erp_system: str = "SAP S/4HANA",
        metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        is_casual: bool = False,
    ) -> SessionState:
        if session_id in self.sessions:
            self.logger.warning(f"Session {session_id} already exists")
            return self.sessions[session_id]

        session = SessionState(
            session_id=session_id,
            project_name=project_name,
            module=module,
            erp_system=erp_system,
            user_id=user_id,
            organization_id=organization_id,
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
        if session_id in self.sessions:
            return self.sessions[session_id]
        return self._load_session(session_id)

    def update_session(
        self,
        session_id: str,
        updates: Dict[str, Any],
    ) -> Optional[SessionState]:
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

    def add_to_conversation(
        self,
        session_id: str,
        role: str,
        content: str,
        agent_name: Optional[str] = None,
    ) -> None:
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

    def advance_phase(self, session_id: str, new_phase: str) -> None:
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

    def list_sessions(self) -> List[str]:
        return list(self.sessions.keys())

    def delete_session(self, session_id: str) -> bool:
        if session_id in self.sessions:
            del self.sessions[session_id]

            session_file = self.persistence_dir / f"{session_id}.json"
            if session_file.exists():
                session_file.unlink()

            self.logger.info("Session deleted", session_id=session_id)
            return True

        return False

    def _save_session(self, session: SessionState) -> None:
        session_file = self.persistence_dir / f"{session.session_id}.json"
        tmp_file = self.persistence_dir / f"{session.session_id}.json.tmp"
        with self._save_lock:
            with open(tmp_file, 'w') as f:
                json.dump(session.to_dict(), f, indent=2, default=str)
            os.replace(tmp_file, session_file)

    def _load_session(self, session_id: str) -> Optional[SessionState]:
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

    Reuses every method from InMemorySessionService unchanged - only the
    storage primitives are overridden."""

    def __init__(self):
        self.sessions: Dict[str, SessionState] = {}
        self.logger = AgentLogger("SessionManager")
        self._save_lock = threading.Lock()

        from src.db.base import init_db, SessionLocal, engine
        if engine.dialect.name == "sqlite":
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
                record.organization_id = session.organization_id
                record.is_casual = session.is_casual
                record.current_phase = session.current_phase
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
        """List PERSONAL project session IDs owned by a specific user.

        Round 3a correction: this method is the deletion path used by
        account deletion, and it deliberately excludes organization-
        owned sessions. Deleting a personal account must not destroy an
        organization's projects; org-owned sessions keep their
        organization_id and lose only their user_id attribution
        (ON DELETE SET NULL on sessions.user_id). The alternative -
        deleting everything a user created - would silently destroy
        project history that other organization members still need.

        For discoverability (what the user can see), use
        list_project_summaries_for_user instead; it also returns org
        projects the user has access to via membership.
        """
        from src.db.models import SessionRecord
        from sqlalchemy import select

        db = self._db_session_factory()
        try:
            query = select(SessionRecord.session_id).where(
                SessionRecord.user_id == user_id,
                SessionRecord.organization_id.is_(None),
            )
            if not include_archived:
                query = query.where(SessionRecord.archived_at.is_(None))
            rows = db.execute(
                query.order_by(SessionRecord.updated_at.desc())
            ).all()
            return [row[0] for row in rows]
        finally:
            db.close()

    def list_project_summaries_for_user(
        self, user_id: str, include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        """Return per-project summary dicts for every project the user
        can access, in a single query.

        Discoverability half of the tenant boundary. The user can see:

          * their personal projects (organization_id IS NULL AND
            user_id == user_id)
          * every project belonging to an organization where they hold
            an active membership (organization_id IN (their org ids))

        This matches the agreed architecture: organization-owned
        projects are accessible to active organization members, and
        access does not depend on already knowing the session_id.
        Before this correction, an org member who did not personally
        create a project could only reach it if someone handed them the
        session_id - which is not a discoverable UX.

        Records whose stored JSON cannot be deserialized are skipped
        with a logged error, matching the previous behavior which
        filtered falsy summaries out rather than failing the listing.

        A single SQL query is used (with a correlated subquery for the
        user's org ids) so the operation stays O(1) round trips. No
        per-project or per-org query is issued.
        """
        from src.db.models import SessionRecord, OrganizationMembership
        from sqlalchemy import select, or_, and_

        db = self._db_session_factory()
        try:
            # Subquery: every organization the user currently belongs to.
            # Correlated execution is fine here - the planner will treat
            # it as a semi-join against the unique index on
            # (organization_id, user_id).
            user_org_ids_subq = (
                select(OrganizationMembership.organization_id)
                .where(OrganizationMembership.user_id == user_id)
                .scalar_subquery()
            )

            query = select(SessionRecord).where(
                or_(
                    # Personal projects: owned by the user, no org context.
                    and_(
                        SessionRecord.organization_id.is_(None),
                        SessionRecord.user_id == user_id,
                    ),
                    # Organization-owned projects: any org the user
                    # belongs to. session.user_id is deliberately NOT
                    # consulted - the org owns the project.
                    SessionRecord.organization_id.in_(user_org_ids_subq),
                )
            )
            if not include_archived:
                query = query.where(SessionRecord.archived_at.is_(None))

            records = db.execute(
                query.order_by(SessionRecord.updated_at.desc())
            ).scalars().all()
        finally:
            db.close()

        summaries: List[Dict[str, Any]] = []
        for record in records:
            try:
                session = SessionState.from_dict(record.data)
            except Exception as e:  # noqa: BLE001
                self.logger.error(
                    f"Failed to deserialize session {record.session_id}: {e}"
                )
                continue
            summaries.append({
                'session_id': session.session_id,
                'project_name': session.project_name,
                'module': session.module,
                'erp_system': session.erp_system,
                'is_casual': session.is_casual,
                'is_archived': record.archived_at is not None,
                'current_phase': session.current_phase,
                'completed_phases': session.completed_phases,
                'phases_completed': len(session.completed_phases),
                'total_conversations': len(session.conversation_history),
                'total_decisions': len(session.decisions_log),
                'created_at': session.created_at.isoformat(),
                'last_updated': session.updated_at.isoformat(),
            })
        return summaries

    def rename_session(
        self, session_id: str, new_project_name: str,
    ) -> Optional[SessionState]:
        session = self.get_session(session_id)
        if not session:
            return None
        session.project_name = new_project_name
        session.updated_at = _utcnow()
        self._save_session(session)
        return session

    def archive_session(self, session_id: str) -> bool:
        from src.db.models import SessionRecord

        db = self._db_session_factory()
        try:
            record = db.get(SessionRecord, session_id)
            if record is None or record.archived_at is not None:
                return False
            record.archived_at = _utcnow()
            db.commit()
            return True
        finally:
            db.close()

    def is_archived(self, session_id: str) -> Optional[bool]:
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
        """Hard-delete a session and every persisted artifact that
        references it. Child-before-parent ordering; object-storage
        cleanup outside the DB transaction. No behavior changes in the
        Round 3a correction - organization-owned sessions are deleted
        through this same path when the caller explicitly asks for it."""
        from src.db.models import SessionRecord, ProjectMemory, Feedback, ProjectDocument

        try:
            from src.storage import object_storage
        except Exception:  # noqa: BLE001
            object_storage = None

        db = self._db_session_factory()
        try:
            record = db.get(SessionRecord, session_id)
            if record is None:
                return False

            storage_failures: List[str] = []
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
                    except Exception as e:  # noqa: BLE001
                        storage_failures.append(storage_key)
                        self.logger.warning(
                            "Failed to delete project document from object storage",
                            session_id=session_id,
                            storage_key=storage_key,
                            error=str(e),
                        )

            db.query(ProjectDocument).filter(
                ProjectDocument.session_id == session_id
            ).delete(synchronize_session=False)
            db.query(ProjectMemory).filter(
                ProjectMemory.session_id == session_id
            ).delete(synchronize_session=False)
            db.query(Feedback).filter(
                Feedback.session_id == session_id
            ).delete(synchronize_session=False)

            db.delete(record)
            db.commit()

            self.sessions.pop(session_id, None)

            if storage_failures:
                self.logger.warning(
                    "Session deleted with residual storage objects",
                    session_id=session_id,
                    storage_failures=len(storage_failures),
                )
            else:
                self.logger.info("Session deleted", session_id=session_id)
            return True
        except Exception:
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            db.close()


session_service = DbSessionService()