"""ERP User artifact status assembly.

FRD staleness is computed by comparing the specific GeneratedDocument
revision that was signed (ReviewAction.object_id with object_type =
'frd_signoff') against the current revision (GeneratedDocument with
is_current=True, phase='frd', label='frd'). No parallel FRD table.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from src.db.models import (
    GeneratedDocument,
    ReviewAction,
    SessionStakeholderSubmission,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_current_frd_revision(
    db: Session, session_id: str,
) -> Optional[GeneratedDocument]:
    return (
        db.query(GeneratedDocument)
        .filter(
            GeneratedDocument.session_id == session_id,
            GeneratedDocument.phase == "frd",
            GeneratedDocument.label == "frd",
            GeneratedDocument.is_current.is_(True),
        )
        .first()
    )


def get_latest_frd_signoff(
    db: Session, session_id: str,
) -> Optional[ReviewAction]:
    return (
        db.query(ReviewAction)
        .filter(
            ReviewAction.session_id == session_id,
            ReviewAction.object_type == "frd_signoff",
        )
        .order_by(ReviewAction.created_at.desc())
        .first()
    )


def build_frd_status(db: Session, session_id: str) -> Dict[str, Any]:
    current = get_current_frd_revision(db, session_id)
    latest = get_latest_frd_signoff(db, session_id)

    signed_rev_id = latest.object_id if latest is not None else None
    signoff_stale = bool(
        signed_rev_id is not None
        and (current is None or current.id != signed_rev_id)
    )

    return {
        "current_revision_id": current.id if current else None,
        "current_filename": current.filename if current else None,
        "current_generated_at": (
            current.created_at.isoformat() if current and current.created_at else None
        ),
        "signed_revision_id": signed_rev_id,
        "signed_action": latest.action if latest else None,
        "signed_at": (
            latest.created_at.isoformat() if latest and latest.created_at else None
        ),
        "signed_by_user_id": latest.user_id if latest else None,
        "signed_note": latest.note if latest else None,
        "signoff_stale": signoff_stale,
    }


def record_submission(
    db: Session,
    session_id: str,
    submitted_by_user_id: str,
    answers: str,
) -> SessionStakeholderSubmission:
    row = SessionStakeholderSubmission(
        id=uuid.uuid4().hex,
        session_id=session_id,
        submitted_by_user_id=submitted_by_user_id,
        answers=answers,
        submitted_at=_utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def latest_submission_for_user(
    db: Session, session_id: str, user_id: str,
) -> Optional[SessionStakeholderSubmission]:
    return (
        db.query(SessionStakeholderSubmission)
        .filter(
            SessionStakeholderSubmission.session_id == session_id,
            SessionStakeholderSubmission.submitted_by_user_id == user_id,
        )
        .order_by(SessionStakeholderSubmission.submitted_at.desc())
        .first()
    )


def list_submissions(db: Session, session_id: str):
    return (
        db.query(SessionStakeholderSubmission)
        .filter(SessionStakeholderSubmission.session_id == session_id)
        .order_by(SessionStakeholderSubmission.submitted_at.desc())
        .all()
    )