"""Opportunity / TOR workflow service.

Owns every state transition for the pre-award container. The atomic
Mark-as-Won transaction lives here. All methods take an explicit
`db: Session` unless they manage their own transaction; mark_won
manages its own because it must be a single commit.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.config.settings import settings
from src.db.base import SessionLocal
from src.db.models import (
    Opportunity,
    OpportunityDocument,
    OpportunityGeneratedDocument,
    OpportunityRequirement,
    OrganizationMembership,
    RequirementItemRecord,
    SessionRecord,
    UserRoleRecord,
)
from src.models.tender_response_schema import (
    FIT_RESPONSE_VALUES,
    LLMFitDraft,
)
from src.services import attention_service, firm_knowledge, tor_extraction
from src.utils.llm import get_llm
from src.utils.model_selection import TaskCategory


logger = logging.getLogger(__name__)


OPPORTUNITY_STATUS_DRAFT = "draft"
OPPORTUNITY_STATUS_TOR_FINALIZED = "tor_finalized"
OPPORTUNITY_STATUS_WON = "won"
OPPORTUNITY_STATUS_LOST = "lost"
OPPORTUNITY_STATUS_ARCHIVED = "archived"

AI_PENDING = "pending"
AI_DRAFTED = "drafted"
AI_FINALIZED = "finalized"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------
def list_for_organization(
    db: Session, organization_id: str,
) -> List[Opportunity]:
    return (
        db.query(Opportunity)
        .filter(Opportunity.organization_id == organization_id)
        .order_by(Opportunity.updated_at.desc())
        .all()
    )


def get_opportunity(
    db: Session, opportunity_id: str,
) -> Optional[Opportunity]:
    return db.get(Opportunity, opportunity_id)


def get_requirement(
    db: Session, opportunity_id: str, requirement_id: str,
) -> Optional[OpportunityRequirement]:
    row = db.get(OpportunityRequirement, requirement_id)
    if row is None or row.opportunity_id != opportunity_id:
        return None
    return row


def list_requirements(
    db: Session, opportunity_id: str,
) -> List[OpportunityRequirement]:
    return (
        db.query(OpportunityRequirement)
        .filter(OpportunityRequirement.opportunity_id == opportunity_id)
        .order_by(OpportunityRequirement.created_at)
        .all()
    )


def list_eligible_consultants(
    db: Session, organization_id: str,
) -> List[Dict[str, Any]]:
    """Org members holding the functional_consultant role. This is the
    single source of truth for 'eligible consultant' - no second
    directory."""
    from src.db.models import User
    rows = (
        db.query(User, OrganizationMembership.role)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .join(UserRoleRecord, UserRoleRecord.user_id == User.id)
        .filter(
            OrganizationMembership.organization_id == organization_id,
            UserRoleRecord.role == "functional_consultant",
        )
        .order_by(User.email)
        .all()
    )
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for user, org_role in rows:
        if user.id in seen:
            continue
        seen.add(user.id)
        out.append({
            "user_id": user.id,
            "email": user.email,
            "name": user.name,
            "org_role": org_role,
        })
    return out


def is_eligible_consultant(
    db: Session, organization_id: str, user_id: str,
) -> bool:
    return any(
        u["user_id"] == user_id
        for u in list_eligible_consultants(db, organization_id)
    )


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------
def create_opportunity(
    db: Session,
    *,
    organization_id: str,
    created_by_user_id: str,
    title: str,
    client_name: str,
) -> Opportunity:
    opp = Opportunity(
        id=uuid.uuid4().hex,
        organization_id=organization_id,
        created_by_user_id=created_by_user_id,
        owner_user_id=created_by_user_id,
        title=title,
        client_name=client_name,
        status=OPPORTUNITY_STATUS_DRAFT,
    )
    db.add(opp)
    db.flush()
    return opp


def update_opportunity(
    db: Session,
    opp: Opportunity,
    *,
    title: Optional[str] = None,
    client_name: Optional[str] = None,
) -> Opportunity:
    if title is not None:
        opp.title = title
    if client_name is not None:
        opp.client_name = client_name
    return opp


def attach_document(
    db: Session,
    *,
    opp: Opportunity,
    user_id: str,
    filename: str,
    storage_key: str,
    content_type: str,
    size_bytes: int,
    extracted_text_chars: int,
    source_format: str,
) -> OpportunityDocument:
    doc = OpportunityDocument(
        id=uuid.uuid4().hex,
        opportunity_id=opp.id,
        user_id=user_id,
        filename=filename,
        storage_key=storage_key,
        content_type=content_type,
        size_bytes=size_bytes,
        extracted_text_chars=extracted_text_chars,
        source_format=source_format,
    )
    db.add(doc)
    db.flush()
    return doc


def replace_requirements_from_extraction(
    db: Session,
    *,
    opp: Opportunity,
    extracted_rows: List[Dict[str, Any]],
    source_format: str,
) -> int:
    """Replace pending, un-finalized requirements with a fresh
    extraction. Finalized rows are preserved: a re-upload must not
    silently discard the Business Development's work. Returns the number of rows
    added."""
    # Delete rows that are still pending; they are superseded.
    db.query(OpportunityRequirement).filter(
        OpportunityRequirement.opportunity_id == opp.id,
        OpportunityRequirement.ai_draft_status == AI_PENDING,
    ).delete(synchronize_session=False)

    # Determine the highest existing TOR-NNN so codes do not collide.
    existing = (
        db.query(OpportunityRequirement.external_code)
        .filter(OpportunityRequirement.opportunity_id == opp.id)
        .all()
    )
    max_num = 0
    for (code,) in existing:
        if code and code.startswith("TOR-"):
            try:
                max_num = max(max_num, int(code.split("-", 1)[1]))
            except (ValueError, IndexError):
                continue

    added = 0
    source_label = "tor_word" if source_format == "word" else "tor_excel"
    for row in extracted_rows:
        max_num += 1
        code = f"TOR-{max_num:03d}"
        db.add(OpportunityRequirement(
            id=uuid.uuid4().hex,
            opportunity_id=opp.id,
            external_code=code,
            category=row.get("category"),
            description=row["description"],
            priority="Medium",
            req_type="Functional",
            status="draft",
            importance=None,
            fit_response=None,
            fit_response_ai=None,
            fit_response_comment=None,
            fit_response_ai_comment=None,
            ai_draft_status=AI_PENDING,
            source=source_label,
            source_excerpt=row.get("source_excerpt"),
        ))
        added += 1
    return added


def draft_fit_response(
    db: Session,
    *,
    opp: Opportunity,
    requirement: OpportunityRequirement,
    erp_system: Optional[str] = None,
) -> OpportunityRequirement:
    """Produce an AI draft for one requirement. Never sets the final
    fit_response; only the AI fields and ai_draft_status='drafted'."""
    prior = firm_knowledge.retrieve_prior_responses(
        db,
        organization_id=opp.organization_id,
        requirement_text=requirement.description,
        erp_system=erp_system,
    )

    prior_block = ""
    if prior:
        prior_lines = []
        for p in prior:
            kind = p.response_kind or "unknown"
            prior_lines.append(
                f"- [{kind}] {p.requirement_text[:200]}\n"
                f"  past response: {p.response_text[:300]}"
            )
        prior_block = (
            "\n\nPrior similar responses from this organization's past "
            "projects (context only - do NOT copy them; note any "
            "conflicts and justify your recommendation):\n"
            + "\n".join(prior_lines)
        )

    prompt = (
        "You are drafting a fit response for a tender requirement on "
        "behalf of an ERP consulting firm. Choose ONE of:\n"
        "  meets_out_of_the_box - the requirement is satisfied by "
        "standard ERP configuration.\n"
        "  requires_customization - the requirement is achievable but "
        "needs custom development or complex configuration.\n"
        "  not_supported - the ERP does not support the requirement.\n\n"
        "Provide a short justification (1-3 sentences) in the comment "
        "field. Do not invent module names or feature specifics.\n\n"
        f"REQUIREMENT:\n{requirement.description}"
        f"{prior_block}"
    )

    try:
        resp = get_llm().generate_content(
            prompt,
            generation_config={
                "response_schema": LLMFitDraft,
                "temperature": 0.2,
                "task": TaskCategory.HIGH_REASONING,
            },
        )
        draft = LLMFitDraft.model_validate_json(resp.text)
    except Exception as e:  # noqa: BLE001 - surface, do not crash
        logger.warning("Fit-response draft failed: %s", e)
        raise

    if draft.fit_response not in FIT_RESPONSE_VALUES:
        raise ValueError(f"LLM returned unknown fit_response: {draft.fit_response!r}")

    requirement.fit_response_ai = draft.fit_response
    requirement.fit_response_ai_comment = draft.comment
    requirement.ai_draft_status = AI_DRAFTED
    db.flush()
    return requirement


def finalize_requirement(
    db: Session,
    *,
    opp: Opportunity,
    requirement: OpportunityRequirement,
    fit_response: str,
    comment: Optional[str],
) -> OpportunityRequirement:
    """Business Development finalizes a requirement.

    Ingests the finalized response into firm knowledge in the same
    transaction. Does not flip the Opportunity to tor_finalized - that
    is a separate operation so the Business Development can review the full set
    before publishing."""
    if fit_response not in FIT_RESPONSE_VALUES:
        raise ValueError(f"Unknown fit_response: {fit_response!r}")

    requirement.fit_response = fit_response
    requirement.fit_response_comment = (comment or "").strip() or None
    requirement.ai_draft_status = AI_FINALIZED
    db.flush()

    firm_knowledge.ingest_response(
        db,
        organization_id=opp.organization_id,
        requirement_text=requirement.description,
        response_text=requirement.fit_response_comment or "",
        response_kind=fit_response,
        source_opportunity_id=opp.id,
        source_external_code=requirement.external_code,
        category=requirement.category,
        importance=requirement.importance,
        erp_system=None,
        tags=[requirement.category] if requirement.category else [],
    )
    return requirement


def mark_tor_finalized(
    db: Session, opp: Opportunity,
) -> Opportunity:
    """Transition the Opportunity to tor_finalized. Requires every
    requirement to be ai_draft_status='finalized'."""
    pending = (
        db.query(OpportunityRequirement)
        .filter(
            OpportunityRequirement.opportunity_id == opp.id,
            OpportunityRequirement.ai_draft_status != AI_FINALIZED,
        )
        .count()
    )
    if pending:
        raise ValueError(
            f"{pending} requirement(s) still need a finalized fit response "
            "before the TOR can be marked ready."
        )
    opp.status = OPPORTUNITY_STATUS_TOR_FINALIZED
    return opp


def assign_consultant(
    db: Session, opp: Opportunity, consultant_user_id: str,
) -> Opportunity:
    if not is_eligible_consultant(db, opp.organization_id, consultant_user_id):
        raise ValueError(
            "Selected user is not an eligible Functional Consultant in "
            "this organization."
        )
    opp.assigned_consultant_user_id = consultant_user_id
    return opp


# ---------------------------------------------------------------------------
# Mark as Won - atomic
# ---------------------------------------------------------------------------
def mark_won(
    db: Session,
    *,
    opp: Opportunity,
    consultant_user_id: Optional[str],
    erp_system: str = "SAP S/4HANA",
    module: str = "FI",
) -> Dict[str, Any]:
    """Convert an Opportunity to a Project.

    Runs in ONE transaction. Every step is inside the caller's `db`
    session; the caller commits or the whole thing rolls back. The
    email send happens after commit and is best-effort.

    The `sessions.data` JSON blob is produced by constructing a real
    SessionState and calling its .to_dict(). The dataclass is the single
    source of truth for the session shape; do not hand-build this
    dictionary, and do not rely on SessionState.from_dict's key-filter
    behaviour to hide drift. A field added to SessionState must appear
    here for free.

    Returns a dict with the new session_id and the consultant id.
    """
    if opp.status == OPPORTUNITY_STATUS_WON:
        raise ValueError("This opportunity has already been converted.")
    if opp.status != OPPORTUNITY_STATUS_TOR_FINALIZED:
        raise ValueError(
            "Mark as Won requires the TOR to be finalized first."
        )
    if opp.converted_session_id:
        raise ValueError("This opportunity already has a converted session.")

    resolved_consultant = consultant_user_id or opp.assigned_consultant_user_id
    if not resolved_consultant:
        raise ValueError(
            "A Functional Consultant must be selected before marking Won."
        )
    if not is_eligible_consultant(db, opp.organization_id, resolved_consultant):
        raise ValueError(
            "Selected user is not an eligible Functional Consultant in "
            "this organization."
        )

    requirements = (
        db.query(OpportunityRequirement)
        .filter(
            OpportunityRequirement.opportunity_id == opp.id,
            OpportunityRequirement.ai_draft_status == AI_FINALIZED,
        )
        .order_by(OpportunityRequirement.created_at)
        .all()
    )
    if not requirements:
        raise ValueError(
            "No finalized requirements to convert. Finalize the TOR "
            "requirements before marking Won."
        )

    # 1) Create the SessionRecord.
    #
    # The `data` blob is built by constructing a real SessionState and
    # calling .to_dict(). The dataclass is the single source of truth
    # for the session shape; constructing the JSON by hand would drift
    # silently the moment a field is added to SessionState, and
    # SessionState.from_dict's key-filtering would hide the drift
    # rather than surface it. The dataclass instance's timestamps are
    # reused verbatim on the SessionRecord row so the two stay aligned.
    from src.memory.session_manager import SessionState

    session_id = f"prj_{uuid.uuid4().hex[:12]}"
    state = SessionState(
        session_id=session_id,
        project_name=opp.title,
        module=module,
        erp_system=erp_system,
        user_id=resolved_consultant,
        organization_id=opp.organization_id,
        is_casual=False,
        metadata={
            "source_opportunity_id": opp.id,
            "source_opportunity_title": opp.title,
            "source_client_name": opp.client_name,
        },
        current_phase="requirements_gathering",
    )
    session = SessionRecord(
        session_id=session_id,
        user_id=resolved_consultant,
        organization_id=opp.organization_id,
        project_name=opp.title,
        module=module,
        erp_system=erp_system,
        current_phase=state.current_phase,
        created_at=state.created_at,
        updated_at=state.updated_at,
        data=state.to_dict(),
    )
    db.add(session)
    db.flush()

    now = _utcnow()

    # 2) Copy every finalized requirement into RequirementItemRecord.
    for r in requirements:
        new_id = uuid.uuid4().hex
        db.add(RequirementItemRecord(
            id=new_id,
            session_id=session_id,
            lineage_id=new_id,
            version=1,
            is_current=True,
            category=r.category or "General",
            external_code=r.external_code,
            description=r.description,
            priority=r.priority or "Medium",
            req_type=r.req_type or "Functional",
            acceptance_criteria=r.acceptance_criteria,
            status="draft",
            rationale=r.fit_response_comment,
            source=f"TOR ({r.source or 'manual'})",
            source_excerpt=r.source_excerpt,
        ))

    # 3) Update the Opportunity.
    opp.status = OPPORTUNITY_STATUS_WON
    opp.converted_session_id = session_id
    opp.assigned_consultant_user_id = resolved_consultant
    opp.won_at = now

    # 4) Route to the assigned consultant.
    attention_service.create_attention_item(
        db,
        recipient_user_id=resolved_consultant,
        source_type=attention_service.SOURCE_TYPE_BID_WON,
        source_id=opp.id,
        organization_id=opp.organization_id,
        session_id=session_id,
    )

    return {
        "session_id": session_id,
        "consultant_user_id": resolved_consultant,
        "opportunity_id": opp.id,
    }


def send_bid_won_email(
    *, to_email: str, consultant_name: Optional[str],
    opportunity_title: str, client_name: str, session_id: str,
) -> None:
    """Best-effort email notification. Called after the transaction
    commits. On failure, logs and continues.

    Contains an absolute URL to the newly created project workspace so
    the consultant can navigate directly to it. The URL is built from
    the same frontend origin used by the auth flow emails
    (`src.auth.flows._frontend_base_url`), so a single configured origin
    drives both flows - no second configuration mechanism is
    introduced.
    """
    from src.auth.flows import _frontend_base_url
    from src.email.service import send_email

    project_url = f"{_frontend_base_url()}/p/{session_id}"

    subject = f"New project assigned: {opportunity_title}"
    body = (
        f"Hello {consultant_name or 'there'},\n\n"
        f"A tender has been won and assigned to you as the Functional "
        f"Consultant.\n\n"
        f"Client: {client_name}\n"
        f"Project: {opportunity_title}\n"
        f"Session ID: {session_id}\n\n"
        f"The TOR-derived requirements are already in the project, ready "
        f"for you to begin the requirements phase.\n\n"
        f"Open the project:\n{project_url}\n\n"
        f"— Tarzyna"
    )
    send_email(to_email, subject, body)


# ---------------------------------------------------------------------------
# Generated tender response document
# ---------------------------------------------------------------------------
def store_tender_response(
    db: Session, *, opp: Opportunity, filepath: str, content_type: str,
) -> OpportunityGeneratedDocument:
    """Persist a generated tender response to opportunity_generated_documents.
    Flips any prior current row for (phase='tender_response',
    label='tender_response') to is_current=False, mirroring the
    GeneratedDocument partial-unique convention."""
    from pathlib import Path
    from sqlalchemy import update as sa_update

    with open(filepath, "rb") as f:
        content = f.read()

    db.execute(
        sa_update(OpportunityGeneratedDocument)
        .where(
            OpportunityGeneratedDocument.opportunity_id == opp.id,
            OpportunityGeneratedDocument.phase == "tender_response",
            OpportunityGeneratedDocument.label == "tender_response",
            OpportunityGeneratedDocument.is_current.is_(True),
        )
        .values(is_current=False, updated_at=_utcnow())
    )

    doc = OpportunityGeneratedDocument(
        id=uuid.uuid4().hex,
        opportunity_id=opp.id,
        phase="tender_response",
        label="tender_response",
        is_current=True,
        filename=Path(filepath).name,
        content_type=content_type,
        content=content,
    )
    db.add(doc)
    db.flush()
    return doc


def current_tender_response(
    db: Session, opportunity_id: str,
) -> Optional[OpportunityGeneratedDocument]:
    return (
        db.query(OpportunityGeneratedDocument)
        .filter(
            OpportunityGeneratedDocument.opportunity_id == opportunity_id,
            OpportunityGeneratedDocument.phase == "tender_response",
            OpportunityGeneratedDocument.label == "tender_response",
            OpportunityGeneratedDocument.is_current.is_(True),
        )
        .first()
    )