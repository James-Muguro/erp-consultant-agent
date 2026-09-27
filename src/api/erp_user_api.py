"""ERP User artifact endpoints.

Access chain for every route:
  1. authenticate (Depends(get_current_user))
  2. tenant boundary — project membership (is_project_member)
  3. artifact grant — user_has_artifact_access(artifact_type)
  4. designation where required — user_is_frd_signatory / user_is_uat_participant

All failures return 404 to preserve the enumeration-resistant pattern.
No route relies on frontend gating.
"""
from __future__ import annotations

from typing import Any, Dict
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.db.models import SessionRecord  # extend the existing models import
from src.services import erp_user_requests as erp_user_requests_svc

from src.auth.dependencies import get_current_user, get_db
from src.auth.project_access import (
    ArtifactType,
    is_project_member,
    user_has_artifact_access,
    user_is_frd_signatory,
    user_is_uat_participant,
)
from src.db.models import GeneratedDocument, User
from src.services import erp_user_artifacts as artifacts_svc
from src.services import project_intelligence


router = APIRouter(
    prefix="/api/projects/{session_id}/erp-user",
    tags=["erp-user"],
)


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------
def _require_member(db: Session, session_id: str, user_id: str) -> None:
    if not is_project_member(db, session_id, user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")


def _require_artifact(
    db: Session, session_id: str, user_id: str, artifact_type: ArtifactType,
) -> None:
    if not user_has_artifact_access(db, session_id, user_id, artifact_type):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")


# ---------------------------------------------------------------------------
# 1. Artifact grant summary
# ---------------------------------------------------------------------------
@router.get("/artifacts")
def get_artifacts(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _require_member(db, session_id, current_user.id)
    grants = []
    for artifact in ArtifactType:
        if user_has_artifact_access(db, session_id, current_user.id, artifact):
            grants.append({
                "artifact_type": artifact.value,
                "is_signatory": (
                    artifact == ArtifactType.FRD
                    and user_is_frd_signatory(db, session_id, current_user.id)
                ),
                "is_uat_participant": (
                    artifact == ArtifactType.UAT_SCENARIOS
                    and user_is_uat_participant(db, session_id, current_user.id)
                ),
            })
    return {"session_id": session_id, "grants": grants}


# ---------------------------------------------------------------------------
# 2. Questionnaire
# ---------------------------------------------------------------------------
@router.get("/questionnaire")
def get_questionnaire(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _require_member(db, session_id, current_user.id)
    _require_artifact(
        db, session_id, current_user.id,
        ArtifactType.REQUIREMENTS_QUESTIONNAIRE,
    )
    last = artifacts_svc.latest_submission_for_user(
        db, session_id, current_user.id,
    )
    # The template is served by our own authorized download route; the
    # existing documents:read route is not relaxed.
    template = (
        db.query(GeneratedDocument)
        .filter(
            GeneratedDocument.session_id == session_id,
            GeneratedDocument.phase == "requirements_template",
            GeneratedDocument.label == "requirements_template",
            GeneratedDocument.is_current.is_(True),
        )
        .first()
    )
    return {
        "submitted": last is not None,
        "last_submission": (
            {
                "id": last.id,
                "answers": last.answers,
                "submitted_at": last.submitted_at.isoformat(),
            }
            if last else None
        ),
        "template_available": template is not None,
        "template_download_path": (
            f"/api/projects/{session_id}/erp-user/questionnaire/template/download"
            if template else None
        ),
    }


@router.get("/questionnaire/template/download")
def download_questionnaire_template(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_member(db, session_id, current_user.id)
    _require_artifact(
        db, session_id, current_user.id,
        ArtifactType.REQUIREMENTS_QUESTIONNAIRE,
    )
    template = (
        db.query(GeneratedDocument)
        .filter(
            GeneratedDocument.session_id == session_id,
            GeneratedDocument.phase == "requirements_template",
            GeneratedDocument.label == "requirements_template",
            GeneratedDocument.is_current.is_(True),
        )
        .first()
    )
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return Response(
        content=template.content,
        media_type=template.content_type,
        headers=_attachment_headers(template.filename),
    )


class SubmitAnswersBody(BaseModel):
    answers: str = Field(min_length=1)


@router.post("/questionnaire/submit")
def submit_questionnaire(
    session_id: str,
    body: SubmitAnswersBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _require_member(db, session_id, current_user.id)
    _require_artifact(
        db, session_id, current_user.id,
        ArtifactType.REQUIREMENTS_QUESTIONNAIRE,
    )
    row = artifacts_svc.record_submission(
        db, session_id, current_user.id, body.answers,
    )
    submission_id = row.id
    submitted_at_iso = row.submitted_at.isoformat()
    db.commit()
    return {
        "id": submission_id,
        "submitted_at": submitted_at_iso,
        "note": (
            "Your answers have been recorded and are available to the "
            "functional consultant for review. They are not yet part of "
            "the structured requirements register."
        ),
    }

# ---------------------------------------------------------------------------
# 3. FRD
# ---------------------------------------------------------------------------
@router.get("/frd")
def get_frd(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _require_member(db, session_id, current_user.id)
    _require_artifact(db, session_id, current_user.id, ArtifactType.FRD)
    status_info = artifacts_svc.build_frd_status(db, session_id)
    is_signatory = user_is_frd_signatory(db, session_id, current_user.id)
    return {
        **status_info,
        "can_sign_off": bool(
            is_signatory
            and status_info["current_revision_id"] is not None
        ),
        "is_signatory": is_signatory,
    }


@router.get("/frd/download")
def download_frd(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_member(db, session_id, current_user.id)
    _require_artifact(db, session_id, current_user.id, ArtifactType.FRD)
    current = artifacts_svc.get_current_frd_revision(db, session_id)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return Response(
        content=current.content,
        media_type=current.content_type,
        headers=_attachment_headers(current.filename),
    )


class SignOffBody(BaseModel):
    decision: str  # "confirm" | "request_changes"
    revision_id: str
    note: str | None = None


@router.post("/frd/sign-off")
def sign_off_frd(
    session_id: str,
    body: SignOffBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _require_member(db, session_id, current_user.id)
    _require_artifact(db, session_id, current_user.id, ArtifactType.FRD)
    if not user_is_frd_signatory(db, session_id, current_user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    if body.decision not in ("confirm", "request_changes"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "decision must be 'confirm' or 'request_changes'",
        )
    current = artifacts_svc.get_current_frd_revision(db, session_id)
    if current is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "No FRD available to sign.")
    if body.revision_id != current.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The revision being signed is not the current FRD revision. "
            "Refresh and sign the current revision.",
        )
    internal_action = (
        "approved" if body.decision == "confirm" else "rejected"
    )
    project_intelligence.record_review_action(
        session_id,
        current_user.id,
        "frd_signoff",
        current.id,
        internal_action,
        body.note,
    )
    return {
        "signed_revision_id": current.id,
        "action": internal_action,
        "signoff_stale": False,
    }


# ---------------------------------------------------------------------------
# 4. UAT scenarios (read-only)
# ---------------------------------------------------------------------------
@router.get("/uat-scenarios")
def get_uat_scenarios(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _require_member(db, session_id, current_user.id)
    _require_artifact(
        db, session_id, current_user.id, ArtifactType.UAT_SCENARIOS,
    )
    is_participant = user_is_uat_participant(db, session_id, current_user.id)
    cases = project_intelligence.get_test_cases(session_id, test_type="uat") or []
    return {
        "is_uat_participant": is_participant,
        "scenarios": cases,
    }


# ---------------------------------------------------------------------------
# 5. Training materials (read-only)
# ---------------------------------------------------------------------------
@router.get("/training-materials")
def get_training_materials(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _require_member(db, session_id, current_user.id)
    _require_artifact(
        db, session_id, current_user.id, ArtifactType.TRAINING_MATERIALS,
    )
    steps = project_intelligence.get_training_steps(session_id) or []
    docs = (
        db.query(GeneratedDocument)
        .filter(
            GeneratedDocument.session_id == session_id,
            GeneratedDocument.phase == "training",
            GeneratedDocument.is_current.is_(True),
        )
        .all()
    )
    return {
        "steps": steps,
        "documents": [
            {
                "label": d.label,
                "filename": d.filename,
                "generated_at": d.created_at.isoformat() if d.created_at else None,
                "download_path": (
                    f"/api/projects/{session_id}/erp-user/training-materials/"
                    f"documents/{d.id}/download"
                ),
            }
            for d in docs
        ],
    }

def _attachment_headers(filename: str) -> Dict[str, str]:
    raw = filename or "document"
    ascii_name = "".join(
        c if 32 <= ord(c) < 127 and c != '"' else "_" for c in raw
    )
    if not ascii_name:
        ascii_name = "document"
    encoded = quote(raw, safe="")
    return {
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{encoded}"
        ),
    }

# ---------------------------------------------------------------------------
# 6. Support requests
# ---------------------------------------------------------------------------
class CreateRequestBody(BaseModel):
    request_type: str = Field(min_length=1, max_length=32)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10_000)


@router.get("/requests")
def list_my_requests(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _require_member(db, session_id, current_user.id)
    # A request is available to any ERP User with an active artifact
    # grant on the project; see the D3 recipient policy. Require at
    # least one grant, matching the Support tab's own gate.
    any_grant = any(
        user_has_artifact_access(db, session_id, current_user.id, artifact)
        for artifact in ArtifactType
    )
    if not any_grant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    rows = erp_user_requests_svc.list_for_user(
        db, session_id, current_user.id,
    )
    return {
        "requests": [
            {
                "id": r.id,
                "request_type": r.request_type,
                "subject": r.subject,
                "body": r.body,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
            }
            for r in rows
        ],
    }


@router.post("/requests")
def create_request(
    session_id: str,
    body: CreateRequestBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _require_member(db, session_id, current_user.id)
    any_grant = any(
        user_has_artifact_access(db, session_id, current_user.id, artifact)
        for artifact in ArtifactType
    )
    if not any_grant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    session = db.get(SessionRecord, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    try:
        row = erp_user_requests_svc.create_request(
            db,
            session=session,
            created_by_user_id=current_user.id,
            request_type=body.request_type,
            subject=body.subject,
            body=body.body,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))

    payload = {
        "id": row.id,
        "request_type": row.request_type,
        "subject": row.subject,
        "body": row.body,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "resolved_at": None,
    }
    db.commit()
    return payload

@router.get("/training-materials/documents/{document_id}/download")
def download_training_document(
    session_id: str,
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_member(db, session_id, current_user.id)
    _require_artifact(
        db, session_id, current_user.id, ArtifactType.TRAINING_MATERIALS,
    )
    doc = (
        db.query(GeneratedDocument)
        .filter(
            GeneratedDocument.id == document_id,
            GeneratedDocument.session_id == session_id,
            GeneratedDocument.phase == "training",
            GeneratedDocument.is_current.is_(True),
        )
        .first()
    )
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return Response(
        content=doc.content,
        media_type=doc.content_type,
        headers=_attachment_headers(doc.filename),
    )