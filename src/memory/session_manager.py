"""
Session management for maintaining state across agent interactions
"""
from typing import Any, Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, field
import json
import os
import threading
from pathlib import Path

from src.config.settings import settings
from src.utils.logger import AgentLogger


@dataclass
class SessionState:
    """Represents the state of a session"""
    session_id: str
    project_name: str
    module: str
    erp_system: str
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Workflow state
    current_phase: str = "requirements_gathering"
    completed_phases: List[str] = field(default_factory=list)
    
    # Agent outputs
    requirements_document: Optional[str] = None
    process_maps: Optional[Dict[str, str]] = None
    solution_design: Optional[str] = None
    qa_test_cases: Optional[List[Dict]] = None
    uat_test_cases: Optional[List[Dict]] = None
    training_materials: Optional[Dict[str, str]] = None
    
    # Context and history
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    decisions_log: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert session state to dictionary"""
        return {
            'session_id': self.session_id,
            'project_name': self.project_name,
            'module': self.module,
            'erp_system': self.erp_system,
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
            'decisions_log': self.decisions_log
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SessionState':
        """Create session state from dictionary"""
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        data['updated_at'] = datetime.fromisoformat(data['updated_at'])
        return cls(**data)


class InMemorySessionService:
    """In-memory session management service"""
    
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
        metadata: Optional[Dict[str, Any]] = None
    ) -> SessionState:
        """Create a new session"""
        if session_id in self.sessions:
            self.logger.warning(f"Session {session_id} already exists")
            return self.sessions[session_id]
        
        session = SessionState(
            session_id=session_id,
            project_name=project_name,
            module=module,
            erp_system=erp_system,
            metadata=metadata or {}
        )
        
        self.sessions[session_id] = session
        self.logger.info(
            "Session created",
            session_id=session_id,
            project_name=project_name,
            module=module
        )
        
        self._save_session(session)
        return session
    
    def get_session(self, session_id: str) -> Optional[SessionState]:
        """Get session by ID"""
        if session_id in self.sessions:
            return self.sessions[session_id]
        
        # Try loading from disk
        return self._load_session(session_id)
    
    def update_session(
        self,
        session_id: str,
        updates: Dict[str, Any]
    ) -> Optional[SessionState]:
        """Update session state"""
        session = self.get_session(session_id)
        if not session:
            self.logger.error(f"Session {session_id} not found")
            return None
        
        # Update fields
        for key, value in updates.items():
            if hasattr(session, key):
                setattr(session, key, value)
        
        session.updated_at = datetime.now()
        
        self.logger.info(
            "Session updated",
            session_id=session_id,
            updated_fields=list(updates.keys())
        )
        
        self._save_session(session)
        return session
    
    def add_to_conversation(
        self,
        session_id: str,
        role: str,
        content: str,
        agent_name: Optional[str] = None
    ):
        """Add message to conversation history"""
        session = self.get_session(session_id)
        if not session:
            return
        
        session.conversation_history.append({
            'timestamp': datetime.now().isoformat(),
            'role': role,
            'content': content,
            'agent_name': agent_name
        })

        max_items = settings.max_conversation_history_items
        if len(session.conversation_history) > max_items:
            session.conversation_history = session.conversation_history[-max_items:]

        session.updated_at = datetime.now()
        self._save_session(session)
    
    def log_decision(
        self,
        session_id: str,
        decision: str,
        rationale: str,
        agent_name: str
    ):
        """Log an important decision"""
        session = self.get_session(session_id)
        if not session:
            return
        
        session.decisions_log.append({
            'timestamp': datetime.now().isoformat(),
            'decision': decision,
            'rationale': rationale,
            'agent_name': agent_name
        })
        
        self.logger.log_memory_operation(
            "decision_logged",
            {'session_id': session_id, 'decision': decision}
        )
        
        self._save_session(session)
    
    def advance_phase(self, session_id: str, new_phase: str):
        """Move session to next phase"""
        session = self.get_session(session_id)
        if not session:
            return
        
        if session.current_phase not in session.completed_phases:
            session.completed_phases.append(session.current_phase)
        
        session.current_phase = new_phase
        session.updated_at = datetime.now()
        
        self.logger.info(
            "Phase advanced",
            session_id=session_id,
            old_phase=session.current_phase,
            new_phase=new_phase
        )
        
        self._save_session(session)
    
    def get_phase_output(
        self,
        session_id: str,
        phase: str
    ) -> Optional[Any]:
        """Get output from a specific phase"""
        session = self.get_session(session_id)
        if not session:
            return None
        
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
            return getattr(session, field_name, None)
        
        return None
    
    def list_sessions(self) -> List[str]:
        """List all active session IDs"""
        return list(self.sessions.keys())
    
    def delete_session(self, session_id: str) -> bool:
        """Delete a session"""
        if session_id in self.sessions:
            del self.sessions[session_id]
            
            # Delete from disk
            session_file = self.persistence_dir / f"{session_id}.json"
            if session_file.exists():
                session_file.unlink()
            
            self.logger.info("Session deleted", session_id=session_id)
            return True
        
        return False
    
    def _save_session(self, session: SessionState):
        """Save session to disk atomically. Writes to a temp file first,
        then does an atomic rename - a concurrent reader or a crash
        mid-write can never see a partially-written file. The lock
        prevents two threads' writes from interleaving in the temp
        file itself."""
        session_file = self.persistence_dir / f"{session.session_id}.json"
        tmp_file = self.persistence_dir / f"{session.session_id}.json.tmp"
        with self._save_lock:
            with open(tmp_file, 'w') as f:
                json.dump(session.to_dict(), f, indent=2, default=str)
            os.replace(tmp_file, session_file)
    
    def _load_session(self, session_id: str) -> Optional[SessionState]:
        """Load session from disk"""
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
        """Get summary of session state"""
        session = self.get_session(session_id)
        if not session:
            return None
        
        return {
            'session_id': session.session_id,
            'project_name': session.project_name,
            'module': session.module,
            'erp_system': session.erp_system,
            'current_phase': session.current_phase,
            'completed_phases': session.completed_phases,
            'phases_completed': len(session.completed_phases),
            'total_conversations': len(session.conversation_history),
            'total_decisions': len(session.decisions_log),
            'created_at': session.created_at.isoformat(),
            'last_updated': session.updated_at.isoformat()
        }


class DbSessionService(InMemorySessionService):
    """Session service backed by a real database instead of per-file JSON.

    Reuses every method from InMemorySessionService unchanged (create/update/
    add_to_conversation/log_decision/advance_phase/get_phase_output all just
    mutate a SessionState object then call self._save_session) - only the
    storage primitives are overridden, so the full existing behavior and
    interface are preserved exactly. Each session is still stored as the
    same to_dict()/from_dict() JSON shape as before; it just lives in a
    database row instead of a file on disk. This also fixes two real
    pre-existing limitations of the file-based service: list_sessions() and
    delete_session() only ever worked for sessions already loaded into this
    process's in-memory cache - here both go straight to the database, so
    they see every session regardless of which process wrote it.
    """

    def __init__(self):
        # Skip InMemorySessionService.__init__'s file-directory setup - we
        # don't need a sessions/ directory - but keep the same cache dict,
        # logger, and lock, since inherited methods rely on them.
        self.sessions: Dict[str, SessionState] = {}
        self.logger = AgentLogger("SessionManager")
        self._save_lock = threading.Lock()

        from src.db.base import init_db, SessionLocal
        init_db()
        self._db_session_factory = SessionLocal

    def _save_session(self, session: SessionState):
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

    def delete_session(self, session_id: str) -> bool:
        from src.db.models import SessionRecord

        self.sessions.pop(session_id, None)

        db = self._db_session_factory()
        try:
            record = db.get(SessionRecord, session_id)
            if record is None:
                return False
            db.delete(record)
            db.commit()
            self.logger.info("Session deleted", session_id=session_id)
            return True
        finally:
            db.close()


# Global session service instance - database-backed (see DbSessionService
# above). InMemorySessionService's file-based storage is kept in this module
# only for reference/rollback; it is no longer instantiated anywhere.
session_service = DbSessionService()