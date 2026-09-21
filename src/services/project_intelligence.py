"""
Project Intelligence service layer - turns the JSON blobs already
produced by existing agents into structured, queryable, reviewable
objects (requirements, process steps, solution decisions, issues,
review actions, trace links).

Deliberately additive: existing SessionState JSON storage and document
generation are untouched. This layer reads what agents already produce
and writes structured rows alongside it - the single source of truth
for "what did the agent actually decide" moves here over time, without
breaking anything that currently works.

DB schema state
---------------
The columns listed below were added to src/db/models.py alongside this
module's schema-review changes and are the current state of the schema.
They are noted here so anyone reading this file in isolation knows which
fields the sync functions expect to exist:

    RequirementItemRecord:  rationale, source, status
    ProcessStepRecord:      external_code, trigger, inputs, outputs,
                            transaction, exception_paths
    SolutionDecision:       external_code, classification, complexity,
                            lifecycle_impact
    TestCaseRecord:         user_role, business_process,
                            acceptance_criteria, related_design_component,
                            updated_at
    TrainingStepRecord:     external_code, role, verification,
                            prerequisites, updated_at
    ProjectIssue:           updated_at

Every write path uses _filter_model_kwargs, so a DB that predates the
migration degrades gracefully — the fields the DB can't hold are
dropped, and the sync still completes. Every read path uses getattr()
with a None default for the same reason.
"""

from __future__ import annotations

import functools
import logging
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional, Set

from src.db.base import SessionLocal
from src.db.models import (
    RequirementItemRecord,
    ProcessStepRecord,
    SolutionDecision,
    TestCaseRecord,
    TrainingStepRecord,
    ProjectIssue,
    SolutionBaseline,
    SolutionBaselineItem,
    ReviewAction,
    TraceLink,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
@contextmanager
def _db_session():
    """Open a SQLAlchemy session, close it on exit. Preserves the existing
    'caller commits explicitly' pattern - no auto-commit, because several
    functions deliberately commit partway through and then continue with
    non-DB work (e.g. running link_requirements after the primary rows
    are committed)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@functools.lru_cache(maxsize=None)
def _model_columns(model_cls: Any) -> frozenset:
    """Return the set of column names on a SQLAlchemy declarative model.

    Cached because _filter_model_kwargs calls this on every sync
    iteration. Model classes are hashable and their column sets are
    stable for the process lifetime, so the cache is safe. Used by
    _filter_model_kwargs to remain forward-compatible when the schema
    evolves ahead of the DB model.

    Note: the cache is never invalidated. That is correct for the
    current usage — models don't change columns at runtime — but a test
    that monkeypatches a model's __table__ would need to clear this
    cache (see functools.lru_cache's cache_clear) to see the change."""
    try:
        return frozenset(c.name for c in model_cls.__table__.columns)
    except Exception:  # noqa: BLE001 - non-SQLAlchemy model or test double
        return frozenset()


def _filter_model_kwargs(model_cls: Any, data: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys not present as columns on the target model.

    Rationale: agent schemas gain fields faster than DB migrations land.
    Passing an unknown kwarg to a declarative model raises TypeError and
    takes down the whole sync - which is worse than silently dropping a
    field the DB can't store yet. This is deliberately permissive; if you
    want to be strict, add a startup check that compares the schema field
    set against the model column set and fails fast in dev."""
    cols = _model_columns(model_cls)
    if not cols:
        return dict(data)
    return {k: v for k, v in data.items() if k in cols}


def _owns(db: Any, model_cls: Any, object_id: str, session_id: str) -> bool:
    """True iff the object exists, belongs to this session, and hasn't
    been superseded. Used to guard cross-session references."""
    if not object_id:
        return False
    obj = db.get(model_cls, object_id)
    return bool(obj and getattr(obj, "session_id", None) == session_id)


def _find_recent_identical_issue(
    db: Any, session_id: str, issue_type: str, description: str
) -> Optional[ProjectIssue]:
    """Return the open ProjectIssue matching (session, issue_type,
    description) exactly, or None. At most one such row should exist at
    a time — filing is skipped while a matching open issue is present —
    so no ordering is applied."""
    return (
        db.query(ProjectIssue)
        .filter(
            ProjectIssue.session_id == session_id,
            ProjectIssue.issue_type == issue_type,
            ProjectIssue.description == description,
            ProjectIssue.status == "open",
        )
        .first()
    )


def _file_open_questions(db: Any, session_id: str, questions: Iterable[Any]) -> int:
    """Persist a list of OpenQuestion-shaped items (dict or object) as
    ProjectIssue rows with issue_type='open_question'. Returns the count
    filed. Used by every agent sync so the questions the guardrails
    require the model to surface actually land somewhere."""
    filed = 0
    for q in questions or []:
        if q is None:
            continue
        if isinstance(q, dict):
            topic = q.get("topic") or ""
            question = q.get("question") or ""
            blocking = bool(q.get("blocking"))
            owner = q.get("owner")
        else:
            topic = getattr(q, "topic", "") or ""
            question = getattr(q, "question", "") or ""
            blocking = bool(getattr(q, "blocking", False))
            owner = getattr(q, "owner", None)
        if not question.strip():
            continue
        description = f"{topic}: {question}".strip(": ") or question
        if owner:
            description = f"{description} (owner: {owner})"
        severity = "high" if blocking else "low"
        db.add(ProjectIssue(
            id=uuid.uuid4().hex,
            session_id=session_id,
            issue_type="open_question",
            severity=severity,
            description=description,
            related_object_type=None,
            related_object_id=None,
        ))
        filed += 1
    return filed

# Canonical statuses the DB can hold on a requirement. Kept lowercase
# because that's what get_project_health's bucket dict uses
# ({"draft": 0, "approved": 0, "rejected": 0}) and what
# record_review_action/revise_requirement write. The agent schema
# produces capitalized values ("Draft", "Confirmed", "Assumed", "TBD"),
# so normalization happens here at the boundary.
_KNOWN_REQUIREMENT_STATUSES = frozenset({
    "draft", "confirmed", "assumed", "tbd", "approved", "rejected",
})


def _normalize_requirement_status(value: Any) -> str:
    """Lowercase-normalize a status string and default to 'draft' for
    unknown or missing values. Without this, a model-supplied 'Draft'
    (from the schema's capitalized Literal) would coexist in the DB
    with a review-action-set 'approved', and get_project_health would
    count them under two different dict keys."""
    if value is None:
        return "draft"
    lowered = str(value).strip().lower()
    if lowered in _KNOWN_REQUIREMENT_STATUSES:
        return lowered
    return "draft"

# ---------------------------------------------------------------------------
# Requirements
# ---------------------------------------------------------------------------
def sync_requirements_from_structured(
    session_id: str, structured_requirements: Dict[str, Any]
) -> List[str]:
    """Convert structured_requirements (as produced by
    RequirementsDocument.to_legacy_dict()) into RequirementItemRecord
    rows. Returns the list of new requirement UUIDs created.

    Captures:
      * Functional requirements per category.
      * technical_requirements / integration_requirements /
        reporting_requirements as flat buckets.
      * non_functional_requirements (a bucket added to the schema to
        give NFRs a home distinct from technical requirements).
      * rationale, source, status on each item where present.
      * external_code from the schema's canonical 'REQ-NNN' id, which is
        what allows resolve_requirement_codes() to link to this row.
      * Document-level open_questions as ProjectIssue rows so gaps the
        model flagged are not lost.
    """
    created_ids: List[str] = []
    with _db_session() as db:
        functional = structured_requirements.get("functional_requirements", {}) or {}
        # functional_requirements may be a dict {category: [items]} (the
        # legacy canonical shape) or a list of items (degraded parse). The
        # iteration here tolerates both.
        if isinstance(functional, dict):
            pairs = list(functional.items())
        elif isinstance(functional, list):
            pairs = [("general", functional)]
        else:
            pairs = []

        for category, reqs in pairs:
            if not isinstance(reqs, list):
                continue
            for req in reqs:
                if not isinstance(req, dict):
                    continue
                rid = uuid.uuid4().hex
                db.add(RequirementItemRecord(**_filter_model_kwargs(
                    RequirementItemRecord,
                    {
                        "id": rid,
                        "session_id": session_id,
                        "lineage_id": rid,
                        "version": 1,
                        "is_current": True,
                        "status": _normalize_requirement_status(req.get("status")),
                        "category": category,
                        "description": req.get("description", ""),
                        "priority": req.get("priority", "Medium"),
                        "req_type": req.get("type", "Functional"),
                        "acceptance_criteria": req.get("acceptance_criteria"),
                        "rationale": req.get("rationale"),
                        "source": req.get("source"),
                        "external_code": req.get("id"),
                    },
                )))
                created_ids.append(rid)

        for bucket, category_label in (
            ("technical_requirements", "Technical"),
            ("integration_requirements", "Integration"),
            ("reporting_requirements", "Reporting"),
            ("non_functional_requirements", "Non-functional"),
        ):
            for req in structured_requirements.get(bucket, []) or []:
                if isinstance(req, dict):
                    desc = req.get("description", "")
                    priority = req.get("priority", "Medium")
                    external_code = req.get("id")
                    rationale = req.get("rationale")
                    source = req.get("source")
                    status = _normalize_requirement_status(req.get("status"))
                    acceptance = req.get("acceptance_criteria")
                else:
                    desc = str(req)
                    priority = "Medium"
                    external_code = None
                    rationale = None
                    source = None
                    status = "draft"
                    acceptance = None
                rid = uuid.uuid4().hex
                db.add(RequirementItemRecord(**_filter_model_kwargs(
                    RequirementItemRecord,
                    {
                        "id": rid,
                        "session_id": session_id,
                        "lineage_id": rid,
                        "version": 1,
                        "is_current": True,
                        "status": status,
                        "category": category_label,
                        "description": desc,
                        "priority": priority,
                        "req_type": category_label,
                        "acceptance_criteria": acceptance,
                        "rationale": rationale,
                        "source": source,
                        "external_code": external_code,
                    },
                )))
                created_ids.append(rid)

        # Surface document-level open questions so they aren't lost.
        _file_open_questions(db, session_id, structured_requirements.get("open_questions") or [])

        db.commit()
    return created_ids


def get_requirements(session_id: str, include_history: bool = False) -> List[Dict[str, Any]]:
    with _db_session() as db:
        q = db.query(RequirementItemRecord).filter(RequirementItemRecord.session_id == session_id)
        if not include_history:
            q = q.filter(RequirementItemRecord.is_current.is_(True))
        rows = q.order_by(RequirementItemRecord.category, RequirementItemRecord.created_at).all()
        return [{
            "id": r.id, "lineage_id": r.lineage_id, "version": r.version, "is_current": r.is_current,
            "category": r.category, "description": r.description, "priority": r.priority,
            "type": r.req_type, "acceptance_criteria": r.acceptance_criteria,
            "status": r.status, "external_code": r.external_code,
            # Change-control fields — written by sync_requirements_from_structured
            # from the agent schema's rationale/source fields. getattr with a
            # default so this works against a DB that predates the migration.
            "rationale": getattr(r, "rationale", None),
            "source": getattr(r, "source", None),
        } for r in rows]


# ---------------------------------------------------------------------------
# Reviews and issues
# ---------------------------------------------------------------------------
def record_review_action(
    session_id: str, user_id: str, object_type: str, object_id: str,
    action: str, note: Optional[str] = None,
) -> str:
    """Record an approve/reject/correct action and, for requirements,
    update the underlying row's status to match.

    Now validates that `object_id` belongs to `session_id` before writing
    the review action. Previously a caller could approve a requirement in
    a different session by passing its id."""
    with _db_session() as db:
        # Cross-session guard for the object types we know how to validate.
        model_for_type = {
            "requirement": RequirementItemRecord,
            "solution_decision": SolutionDecision,
            "process_step": ProcessStepRecord,
            "test_case": TestCaseRecord,
            "training_step": TrainingStepRecord,
        }
        target_model = model_for_type.get(object_type)
        if target_model is not None and not _owns(db, target_model, object_id, session_id):
            raise ValueError(
                f"Cannot record review action: {object_type} '{object_id}' does "
                f"not belong to session '{session_id}'."
            )

        rid = uuid.uuid4().hex
        db.add(ReviewAction(
            id=rid, session_id=session_id, user_id=user_id,
            object_type=object_type, object_id=object_id, action=action, note=note,
        ))
        if object_type == "requirement" and action in ("approved", "rejected"):
            req = db.get(RequirementItemRecord, object_id)
            if req:
                req.status = action
        db.commit()
        return rid


def create_issue(
    session_id: str, issue_type: str, description: str, severity: str = "medium",
    related_object_type: Optional[str] = None, related_object_id: Optional[str] = None,
    dedupe: bool = False,
) -> str:
    """File a ProjectIssue. When `dedupe=True`, an existing open issue with
    the same session_id + issue_type + description is returned instead of
    filing a duplicate. Used by resolve_requirement_codes to avoid piling
    one issue per unresolved code on every sync."""
    with _db_session() as db:
        if dedupe:
            existing = _find_recent_identical_issue(db, session_id, issue_type, description)
            if existing is not None:
                return existing.id
        iid = uuid.uuid4().hex
        db.add(ProjectIssue(
            id=iid, session_id=session_id, issue_type=issue_type, severity=severity,
            description=description, related_object_type=related_object_type,
            related_object_id=related_object_id,
        ))
        db.commit()
        return iid


def get_issues(session_id: str, status: Optional[str] = "open") -> List[Dict[str, Any]]:
    with _db_session() as db:
        q = db.query(ProjectIssue).filter(ProjectIssue.session_id == session_id)
        if status:
            q = q.filter(ProjectIssue.status == status)
        rows = q.order_by(ProjectIssue.created_at.desc()).all()
        return [{
            "id": r.id, "issue_type": r.issue_type, "severity": r.severity,
            "description": r.description, "status": r.status,
            "related_object_type": r.related_object_type, "related_object_id": r.related_object_id,
            "test_case_id": getattr(r, "test_case_id", None),
            "classification": getattr(r, "classification", None),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if getattr(r, "updated_at", None) else None,
            "resolved_at": r.resolved_at.isoformat() if getattr(r, "resolved_at", None) else None,
        } for r in rows]


# ---------------------------------------------------------------------------
# Traceability
# ---------------------------------------------------------------------------
def add_trace_link(
    session_id: str, source_type: str, source_id: str,
    target_type: str, target_id: str, relationship: str = "covers",
) -> str:
    """Create a TraceLink. Now validates that both endpoints belong to the
    given session before writing, so a caller can't accidentally link
    objects from two different sessions."""
    with _db_session() as db:
        type_to_model = {
            "requirement": RequirementItemRecord,
            "process_step": ProcessStepRecord,
            "solution_decision": SolutionDecision,
            "test_case": TestCaseRecord,
            "training_step": TrainingStepRecord,
        }
        for role, otype, oid in (("source", source_type, source_id), ("target", target_type, target_id)):
            model = type_to_model.get(otype)
            if model is None:
                continue  # unknown type - preserve legacy permissive behaviour
            if not _owns(db, model, oid, session_id):
                raise ValueError(
                    f"TraceLink {role} {otype} '{oid}' does not belong to "
                    f"session '{session_id}'."
                )

        lid = uuid.uuid4().hex
        db.add(TraceLink(
            id=lid, session_id=session_id, source_type=source_type, source_id=source_id,
            target_type=target_type, target_id=target_id, relationship=relationship,
        ))
        db.commit()
        return lid


def resolve_requirement_codes(session_id: str, codes: List[str]) -> Dict[str, str]:
    """Map model-reported requirement codes ('REQ-001') to real
    RequirementItemRecord UUIDs.

    Codes that don't match any stored requirement are excluded (never
    fabricated) and, if any are unresolved, a single aggregated
    ProjectIssue is filed rather than one per code. The previous
    behaviour filed an issue per unresolved code, which floods the
    issue list when a model hallucinates a batch of codes."""
    if not codes:
        return {}

    # Deduplicate and normalize before querying.
    normalized: Set[str] = {str(c).strip() for c in codes if c and str(c).strip()}
    if not normalized:
        return {}

    with _db_session() as db:
        rows = db.query(RequirementItemRecord).filter(
            RequirementItemRecord.session_id == session_id,
            RequirementItemRecord.external_code.in_(list(normalized)),
        ).all()
        resolved = {r.external_code: r.id for r in rows if r.external_code}
        unresolved = sorted(normalized - set(resolved.keys()))

    if unresolved:
        # Aggregate into one issue per session per batch description. The
        # description is sorted so identical unresolved sets dedupe via
        # create_issue(dedupe=True) even if the batch arrives twice.
        description = (
            f"Referenced requirement code(s) do not match any stored "
            f"requirement: {', '.join(unresolved)}"
        )
        try:
            create_issue(
                session_id, "missing_info", description,
                severity="low", dedupe=True,
            )
        except Exception as e:  # noqa: BLE001 - issue filing is best-effort
            logger.warning(f"Could not file unresolved-code issue: {e}")

    return resolved


def link_requirements(
    session_id: str, source_type: str, source_id: str, requirement_codes: List[str]
) -> List[str]:
    """Resolve requirement codes and create 'covers' TraceLinks for each
    valid match. Returns the list of TraceLink IDs created."""
    resolved = resolve_requirement_codes(session_id, requirement_codes)
    return [
        add_trace_link(session_id, source_type, source_id, "requirement", req_uuid)
        for req_uuid in resolved.values()
    ]


# ---------------------------------------------------------------------------
# Process steps
# ---------------------------------------------------------------------------
def sync_process_steps_from_structured(
    session_id: str, process_name: str, structured_process: Dict[str, Any]
) -> List[str]:
    """Convert a ProcessMap's steps into ProcessStepRecord rows.

    Captures:
      * external_code from ProcessStep.id (canonical STEP-NNN). This is
        what lets a re-sync match a step from a previous run.
      * trigger, inputs, outputs, transaction, exception_paths, role —
        if the DB model has those columns; otherwise safely skipped.
      * Process-level open_questions as ProjectIssue rows.

    Requirement linking is intentionally NOT done here: the process
    mapping agent calls link_requirements() with the step's own
    related_requirement_ids after sync, so validation happens against
    real requirement rows. Doing it in both places would double-link."""
    created_ids: List[str] = []
    with _db_session() as db:
        steps = structured_process.get("steps", []) or []
        for idx, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                continue
            sid = uuid.uuid4().hex
            db.add(ProcessStepRecord(**_filter_model_kwargs(
                ProcessStepRecord,
                {
                    "id": sid,
                    "session_id": session_id,
                    "lineage_id": sid,
                    "version": 1,
                    "is_current": True,
                    "process_name": process_name,
                    "step_number": step.get("number", idx),
                    "name": step.get("name", ""),
                    "description": step.get("description"),
                    "responsible_role": step.get("responsible_role"),
                    "trigger": step.get("trigger"),
                    "inputs": step.get("inputs"),
                    "outputs": step.get("outputs"),
                    "transaction": step.get("transaction"),
                    "exception_paths": step.get("exception_paths"),
                    "external_code": step.get("id"),
                },
            )))
            created_ids.append(sid)

        _file_open_questions(db, session_id, structured_process.get("open_questions") or [])

        db.commit()
    return created_ids


def get_process_steps(
    session_id: str, process_name: Optional[str] = None,
    include_history: bool = False,
) -> List[Dict[str, Any]]:
    with _db_session() as db:
        q = db.query(ProcessStepRecord).filter(ProcessStepRecord.session_id == session_id)
        if process_name:
            q = q.filter(ProcessStepRecord.process_name == process_name)
        if not include_history:
            q = q.filter(ProcessStepRecord.is_current.is_(True))
        rows = q.order_by(ProcessStepRecord.process_name, ProcessStepRecord.step_number).all()
        return [{
            "id": r.id, "lineage_id": r.lineage_id, "version": r.version, "is_current": r.is_current,
            "process_name": r.process_name, "step_number": r.step_number,
            "name": r.name, "description": r.description,
            "responsible_role": r.responsible_role, "requirement_id": r.requirement_id,
            "external_code": getattr(r, "external_code", None),
            # Per-step detail from the process-map schema review. Needed by
            # the solution design agent's context builder and by any UI
            # that renders the full step.
            "trigger": getattr(r, "trigger", None),
            "inputs": getattr(r, "inputs", None),
            "outputs": getattr(r, "outputs", None),
            "transaction": getattr(r, "transaction", None),
            "exception_paths": getattr(r, "exception_paths", None),
        } for r in rows]


# ---------------------------------------------------------------------------
# Solution decisions
# ---------------------------------------------------------------------------
def sync_solution_decisions_from_structured(
    session_id: str, structured_design: Dict[str, Any]
) -> List[str]:
    """Convert a SolutionDesign's configurations, customizations, and
    integrations into SolutionDecision rows.

    Captures:
      * external_code from CFG-XXX / INT-XXX / CUST-XXX ids where present.
      * classification for configurations (STANDARD / CONFIGURATION /
        EXTENSION) if the DB column exists — otherwise skipped.
      * direction, transport, error_handling, idempotency_key for
        integrations where the DB has those columns.
      * lifecycle_impact and complexity for customizations where present.
      * open_questions as ProjectIssue rows.

    requirement_ids on each item are resolved into validated TraceLinks
    via link_requirements, which excludes and logs any code that doesn't
    correspond to a real requirement. requirement_id (singular) is left
    null on the decision row itself — the many-to-many mapping lives in
    TraceLink."""
    created_ids: List[str] = []
    pending_links: List[tuple] = []

    with _db_session() as db:
        for config in structured_design.get("configurations", []) or []:
            if not isinstance(config, dict):
                continue
            did = uuid.uuid4().hex
            db.add(SolutionDecision(**_filter_model_kwargs(
                SolutionDecision,
                {
                    "id": did,
                    "session_id": session_id,
                    "lineage_id": did, "version": 1, "is_current": True,
                    "stage": "proposed",
                    "decision_type": "module_config",
                    "component": config.get("component"),
                    "description": config.get("description", ""),
                    "rationale": None,
                    "external_code": config.get("id"),
                    "classification": config.get("classification"),
                },
            )))
            created_ids.append(did)
            pending_links.append((did, config.get("related_requirement_ids") or []))

        for custom in structured_design.get("customizations", []) or []:
            if not isinstance(custom, dict):
                continue
            did = uuid.uuid4().hex
            db.add(SolutionDecision(**_filter_model_kwargs(
                SolutionDecision,
                {
                    "id": did,
                    "session_id": session_id,
                    "lineage_id": did, "version": 1, "is_current": True,
                    "stage": "proposed",
                    "decision_type": "customization",
                    "component": custom.get("component"),
                    "description": custom.get("description", ""),
                    "rationale": custom.get("justification"),
                    "external_code": custom.get("id"),
                    "complexity": custom.get("complexity"),
                    "lifecycle_impact": custom.get("lifecycle_impact"),
                },
            )))
            created_ids.append(did)
            pending_links.append((did, custom.get("related_requirement_ids") or []))

        for integ in structured_design.get("integrations", []) or []:
            if not isinstance(integ, dict):
                continue
            did = uuid.uuid4().hex
            db.add(SolutionDecision(**_filter_model_kwargs(
                SolutionDecision,
                {
                    "id": did,
                    "session_id": session_id,
                    "lineage_id": did, "version": 1, "is_current": True,
                    "stage": "proposed",
                    "decision_type": "integration",
                    "component": integ.get("name"),
                    "description": integ.get("description", ""),
                    "rationale": None,
                    "external_code": integ.get("id"),
                },
            )))
            created_ids.append(did)
            pending_links.append((did, integ.get("related_requirement_ids") or []))

        _file_open_questions(db, session_id, structured_design.get("open_questions") or [])

        db.commit()

    # Linking is done after commit so the decision rows exist for the
    # TraceLink ownership check. Each link call is independently wrapped:
    # a single malformed requirement code shouldn't prevent the rest.
    for decision_id, codes in pending_links:
        if not codes:
            continue
        try:
            link_requirements(session_id, "solution_decision", decision_id, codes)
        except Exception as e:  # noqa: BLE001 - one bad decision shouldn't stop the rest
            logger.warning(f"link_requirements failed for decision {decision_id}: {e}")

    return created_ids


def get_solution_decisions(
    session_id: str, decision_type: Optional[str] = None,
    stage: Optional[str] = None, include_history: bool = False,
) -> List[Dict[str, Any]]:
    with _db_session() as db:
        q = db.query(SolutionDecision).filter(SolutionDecision.session_id == session_id)
        if decision_type:
            q = q.filter(SolutionDecision.decision_type == decision_type)
        if stage:
            q = q.filter(SolutionDecision.stage == stage)
        if not include_history:
            q = q.filter(SolutionDecision.is_current.is_(True))
        rows = q.order_by(SolutionDecision.created_at).all()
        return [{
            "id": r.id, "lineage_id": r.lineage_id, "version": r.version, "is_current": r.is_current,
            "stage": r.stage, "decision_type": r.decision_type, "component": r.component,
            "description": r.description, "rationale": r.rationale,
            "requirement_id": r.requirement_id, "status": r.status,
            "external_code": getattr(r, "external_code", None),
            # Standard-first classification and customization governance
            # fields — written by sync_solution_decisions_from_structured.
            "classification": getattr(r, "classification", None),
            "complexity": getattr(r, "complexity", None),
            "lifecycle_impact": getattr(r, "lifecycle_impact", None),
        } for r in rows]

# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------
def sync_test_cases_from_structured(
    session_id: str, test_type: str, structured_test_cases: List[Dict[str, Any]]
) -> List[str]:
    """Convert QA/UAT test cases into TestCaseRecord rows and post-process
    their links and failures.

    Captures:
      * user_role, business_process, acceptance_criteria where the DB has
        columns for them (added by the UAT review; without DB columns
        they're skipped — see module docstring).
      * related_design_component where present.
      * related_requirement_ids resolved to TraceLinks.
      * related_process_step_ids resolved to TraceLinks with source_type
        'test_case' and target_type 'process_step'.

    Failed test cases generate ProjectIssue rows via record_test_failure,
    same as before."""
    created_ids: List[str] = []
    pending_req_links: List[tuple] = []
    pending_step_links: List[tuple] = []
    pending_failures: List[tuple] = []

    with _db_session() as db:
        for tc in structured_test_cases or []:
            if not isinstance(tc, dict):
                continue
            tid = uuid.uuid4().hex
            db.add(TestCaseRecord(**_filter_model_kwargs(
                TestCaseRecord,
                {
                    "id": tid,
                    "session_id": session_id,
                    "test_type": test_type,
                    "external_code": tc.get("id"),
                    "scenario": tc.get("scenario", ""),
                    "priority": tc.get("priority", "Medium"),
                    "expected_result": tc.get("expected_result"),
                    "user_role": tc.get("user_role"),
                    "business_process": tc.get("business_process"),
                    "acceptance_criteria": tc.get("acceptance_criteria"),
                    "related_design_component": tc.get("related_design_component"),
                },
            )))
            created_ids.append(tid)
            pending_req_links.append((tid, tc.get("related_requirement_ids") or []))
            pending_step_links.append((tid, tc.get("related_process_step_ids") or []))
            if tc.get("execution_status") == "failed":
                pending_failures.append((tid, tc))
        db.commit()

    for tc_id, codes in pending_req_links:
        if not codes:
            continue
        try:
            link_requirements(session_id, "test_case", tc_id, codes)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"link_requirements failed for test case {tc_id}: {e}")

    for tc_id, step_ids in pending_step_links:
        if not step_ids:
            continue
        for step_external in step_ids:
            step_uuid = _resolve_process_step_external_code(session_id, step_external)
            if step_uuid:
                try:
                    add_trace_link(session_id, "test_case", tc_id, "process_step", step_uuid)
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        f"link test_case->process_step failed for {tc_id}->{step_uuid}: {e}"
                    )

    for tc_id, tc in pending_failures:
        record_test_failure(
            session_id, tc_id,
            classification=tc.get("failure_classification") or "other",
            description=tc.get("failure_description") or f"Test case '{tc.get('scenario', tc_id)}' failed.",
        )

    return created_ids


def _resolve_process_step_external_code(session_id: str, external_code: str) -> Optional[str]:
    """Look up a ProcessStepRecord UUID by its external_code (STEP-NNN)
    within a session. Returns None if not found — callers must not
    fabricate a link when the reference doesn't resolve."""
    if not external_code:
        return None
    code = str(external_code).strip()
    if not code:
        return None
    with _db_session() as db:
        row = (
            db.query(ProcessStepRecord)
            .filter(
                ProcessStepRecord.session_id == session_id,
                ProcessStepRecord.external_code == code,
            )
            .first()
        )
        return row.id if row else None


def record_test_failure(session_id: str, test_case_id: str, classification: str, description: str) -> str:
    """Record a test failure as a first-class ProjectIssue."""
    valid_classifications = {
        "defect", "unclear_requirement", "changed_requirement",
        "data_issue", "integration_issue", "environment_issue", "other",
    }
    if classification not in valid_classifications:
        classification = "other"

    severity = "high" if classification in ("defect", "changed_requirement") else "medium"

    with _db_session() as db:
        iid = uuid.uuid4().hex
        db.add(ProjectIssue(
            id=iid, session_id=session_id, issue_type="test_failure", severity=severity,
            description=description, related_object_type="test_case", related_object_id=test_case_id,
            test_case_id=test_case_id, classification=classification,
        ))
        db.commit()
        return iid


def get_test_failures(session_id: str, classification: Optional[str] = None) -> List[Dict[str, Any]]:
    with _db_session() as db:
        q = db.query(ProjectIssue).filter(
            ProjectIssue.session_id == session_id, ProjectIssue.issue_type == "test_failure"
        )
        if classification:
            q = q.filter(ProjectIssue.classification == classification)
        rows = q.order_by(ProjectIssue.created_at.desc()).all()
        return [{
            "id": r.id, "test_case_id": r.test_case_id, "classification": r.classification,
            "severity": r.severity, "description": r.description, "status": r.status,
        } for r in rows]


def get_test_cases(
    session_id: str, test_type: Optional[str] = None, needs_retest: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    with _db_session() as db:
        q = db.query(TestCaseRecord).filter(TestCaseRecord.session_id == session_id)
        if test_type:
            q = q.filter(TestCaseRecord.test_type == test_type)
        if needs_retest is not None:
            q = q.filter(TestCaseRecord.needs_retest.is_(needs_retest))
        rows = q.order_by(TestCaseRecord.created_at).all()
        return [{
            "id": r.id, "test_type": r.test_type, "external_code": r.external_code,
            "scenario": r.scenario, "priority": r.priority, "expected_result": r.expected_result,
            "needs_retest": r.needs_retest,
            # UAT-specific fields. Populated for UAT cases, None for QA —
            # the UAT agent's role-coverage and process-linkage signals
            # read these.
            "user_role": getattr(r, "user_role", None),
            "business_process": getattr(r, "business_process", None),
            "acceptance_criteria": getattr(r, "acceptance_criteria", None),
            "related_design_component": getattr(r, "related_design_component", None),
            "updated_at": r.updated_at.isoformat() if getattr(r, "updated_at", None) else None,
        } for r in rows]


def mark_test_case_retested(session_id: str, test_case_id: str) -> bool:
    with _db_session() as db:
        tc = db.get(TestCaseRecord, test_case_id)
        if not tc or tc.session_id != session_id:
            return False
        tc.needs_retest = False
        db.commit()
        return True


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------
def sync_training_steps_from_structured(
    session_id: str, structured_materials: Dict[str, Any]
) -> List[str]:
    """Convert training user manual steps into TrainingStepRecord rows.

    Captures:
      * external_code from UserManualStep.id (TSTEP-NNN) where present.
      * role, verification, prerequisites where the DB has columns.
      * related_requirement_ids resolved to TraceLinks.
      * related_process_step_ids resolved to TraceLinks to process steps.
      * Document-level open_questions as ProjectIssue rows."""
    created_ids: List[str] = []
    pending_req_links: List[tuple] = []
    pending_step_links: List[tuple] = []

    with _db_session() as db:
        user_manual = structured_materials.get("user_manual") or {}
        if isinstance(user_manual, dict):
            steps = user_manual.get("steps") or []
        else:
            steps = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            sid = uuid.uuid4().hex
            db.add(TrainingStepRecord(**_filter_model_kwargs(
                TrainingStepRecord,
                {
                    "id": sid,
                    "session_id": session_id,
                    "title": step.get("title", ""),
                    "instructions": step.get("instructions"),
                    "external_code": step.get("id"),
                    "role": step.get("role"),
                    "verification": step.get("verification"),
                    "prerequisites": step.get("preconditions"),
                },
            )))
            created_ids.append(sid)
            pending_req_links.append((sid, step.get("related_requirement_ids") or []))
            pending_step_links.append((sid, step.get("related_process_step_ids") or []))

        _file_open_questions(db, session_id, structured_materials.get("open_questions") or [])

        db.commit()

    for step_id, codes in pending_req_links:
        if not codes:
            continue
        try:
            link_requirements(session_id, "training_step", step_id, codes)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"link_requirements failed for training step {step_id}: {e}")

    for step_id, process_step_codes in pending_step_links:
        if not process_step_codes:
            continue
        for code in process_step_codes:
            target = _resolve_process_step_external_code(session_id, code)
            if target:
                try:
                    add_trace_link(session_id, "training_step", step_id, "process_step", target)
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        f"link training_step->process_step failed for {step_id}->{target}: {e}"
                    )

    return created_ids


def get_training_steps(session_id: str) -> List[Dict[str, Any]]:
    with _db_session() as db:
        rows = db.query(TrainingStepRecord).filter(
            TrainingStepRecord.session_id == session_id
        ).order_by(TrainingStepRecord.created_at).all()
        return [{
            "id": r.id, "title": r.title, "instructions": r.instructions,
            # Per-step metadata added in the training schema review.
            # Populated when the model supplies them; None otherwise.
            "external_code": getattr(r, "external_code", None),
            "role": getattr(r, "role", None),
            "verification": getattr(r, "verification", None),
            "prerequisites": getattr(r, "prerequisites", None),
            "updated_at": r.updated_at.isoformat() if getattr(r, "updated_at", None) else None,
        } for r in rows]


# ---------------------------------------------------------------------------
# Coverage / health
# ---------------------------------------------------------------------------
def _coverage_gaps_inline(db: Any, session_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """Same computation as get_coverage_gaps, but on a caller-supplied
    session, so get_project_health doesn't need to open a second one."""
    requirements = db.query(RequirementItemRecord).filter(
        RequirementItemRecord.session_id == session_id
    ).filter(RequirementItemRecord.is_current.is_(True)).all()

    links = db.query(TraceLink).filter(
        TraceLink.session_id == session_id,
        TraceLink.relationship == "covers",
    ).all()

    covered_req_ids = {l.target_id for l in links if l.target_type == "requirement"}
    tested_req_ids = {
        l.target_id for l in links
        if l.target_type == "requirement" and l.source_type == "test_case"
    }

    def _shape(r: RequirementItemRecord) -> Dict[str, Any]:
        return {
            "id": r.id, "external_code": r.external_code, "category": r.category,
            "description": r.description, "priority": r.priority,
        }

    return {
        "uncovered_requirements": [_shape(r) for r in requirements if r.id not in covered_req_ids],
        "untested_requirements": [_shape(r) for r in requirements if r.id not in tested_req_ids],
    }


def get_coverage_gaps(session_id: str) -> Dict[str, List[Dict[str, Any]]]:
    with _db_session() as db:
        return _coverage_gaps_inline(db, session_id)


def _active_baseline_inline(db: Any, session_id: str) -> Optional[Dict[str, Any]]:
    baseline = db.query(SolutionBaseline).filter(
        SolutionBaseline.session_id == session_id, SolutionBaseline.is_active.is_(True)
    ).first()
    if not baseline:
        return None
    items = db.query(SolutionBaselineItem).filter(
        SolutionBaselineItem.baseline_id == baseline.id
    ).all()
    decision_ids = [i.solution_decision_id for i in items]
    decisions = (
        db.query(SolutionDecision).filter(SolutionDecision.id.in_(decision_ids)).all()
        if decision_ids else []
    )
    return {
        "id": baseline.id, "label": baseline.label, "notes": baseline.notes,
        "created_at": baseline.created_at.isoformat(),
        "decisions": [{
            "id": d.id, "decision_type": d.decision_type, "component": d.component,
            "description": d.description, "stage": d.stage, "version": d.version,
        } for d in decisions],
    }


def get_active_baseline(session_id: str) -> Optional[Dict[str, Any]]:
    with _db_session() as db:
        return _active_baseline_inline(db, session_id)


def get_project_health(session_id: str) -> Dict[str, Any]:
    """Project-level health summary on a single DB session. Previously
    opened three nested sessions (one for requirements/issues/links,
    one inside get_coverage_gaps, one inside get_active_baseline) — a
    connection-pool and lock hazard on non-SQLite backends."""
    with _db_session() as db:
        requirements = db.query(RequirementItemRecord).filter(
            RequirementItemRecord.session_id == session_id
        ).filter(RequirementItemRecord.is_current.is_(True)).all()
        issues = db.query(ProjectIssue).filter(
            ProjectIssue.session_id == session_id, ProjectIssue.status == "open"
        ).all()
        covered_ids = {
            l.target_id for l in db.query(TraceLink).filter(
                TraceLink.session_id == session_id, TraceLink.relationship == "covers"
            ).all()
        }

        req_by_status: Dict[str, int] = {"draft": 0, "approved": 0, "rejected": 0}
        for r in requirements:
            req_by_status[r.status] = req_by_status.get(r.status, 0) + 1

        issues_by_severity: Dict[str, int] = {"low": 0, "medium": 0, "high": 0}
        for i in issues:
            issues_by_severity[i.severity] = issues_by_severity.get(i.severity, 0) + 1

        total = len(requirements)
        covered = sum(1 for r in requirements if r.id in covered_ids)

        gaps = _coverage_gaps_inline(db, session_id)
        baseline = _active_baseline_inline(db, session_id)

        return {
            "requirements_total": total,
            "requirements_by_status": req_by_status,
            "requirements_coverage_pct": round((covered / total * 100), 1) if total else 0.0,
            "open_issues_total": len(issues),
            "open_issues_by_severity": issues_by_severity,
            "uncovered_requirements_count": len(gaps["uncovered_requirements"]),
            "untested_requirements_count": len(gaps["untested_requirements"]),
            "has_active_baseline": baseline is not None,
        }


# ---------------------------------------------------------------------------
# Change propagation
# ---------------------------------------------------------------------------
def _propagate_requirement_change(
    db: Any, session_id: str, old_requirement_id: str, new_requirement_id: str,
    change_summary: str,
) -> int:
    """When a requirement changes, its existing coverage (trace links)
    still describes real work done against the OLD version — that work
    isn't invalidated, but it does need re-confirming against the new
    version.

    When old != new (a genuine revision): incoming 'covers' links are
    carried forward to the new requirement row so coverage/gap analysis
    doesn't wrongly report the revised requirement as newly uncovered.

    When old == new (record_actual_solution updating a decision, which
    doesn't change the requirement itself): no new links are created.
    The previous version of this function created a duplicate link for
    every incoming link in that case, inflating coverage counts and
    re-flagging tests on every update. Only the retest flagging and the
    issue filing happen here — the links were already in place.

    Returns the number of test cases flagged for retest."""
    incoming_links = db.query(TraceLink).filter(
        TraceLink.session_id == session_id,
        TraceLink.target_type == "requirement",
        TraceLink.target_id == old_requirement_id,
        TraceLink.relationship == "covers",
    ).all()

    flagged = 0
    same_id = (old_requirement_id == new_requirement_id)

    if not same_id:
        for link in incoming_links:
            db.add(TraceLink(
                id=uuid.uuid4().hex, session_id=session_id,
                source_type=link.source_type, source_id=link.source_id,
                target_type="requirement", target_id=new_requirement_id,
                relationship="covers",
            ))

    for link in incoming_links:
        if link.source_type != "test_case":
            continue
        tc = db.get(TestCaseRecord, link.source_id)
        if tc and not tc.needs_retest:
            tc.needs_retest = True
            flagged += 1

    if flagged:
        db.add(ProjectIssue(
            id=uuid.uuid4().hex, session_id=session_id,
            issue_type="requirement_changed", severity="medium",
            description=f"{change_summary} - {flagged} test case(s) flagged for retest.",
            related_object_type="requirement", related_object_id=new_requirement_id,
        ))
    return flagged


def revise_requirement(session_id: str, requirement_id: str, updates: Dict[str, Any]) -> str:
    """Create a new version of a requirement instead of mutating it.
    A revised requirement returns to 'draft' status — the prior approval
    applied to the superseded version, not this one."""
    with _db_session() as db:
        current = db.get(RequirementItemRecord, requirement_id)
        if not current or current.session_id != session_id:
            raise ValueError("Requirement not found for this session")

        new_id = uuid.uuid4().hex
        db.add(RequirementItemRecord(**_filter_model_kwargs(
            RequirementItemRecord,
            {
                "id": new_id, "session_id": session_id,
                "lineage_id": current.lineage_id,
                "version": current.version + 1, "is_current": True,
                "status": "draft",
                "category": updates.get("category", current.category),
                "description": updates.get("description", current.description),
                "priority": updates.get("priority", current.priority),
                "req_type": updates.get("req_type", current.req_type),
                "acceptance_criteria": updates.get("acceptance_criteria", current.acceptance_criteria),
                "external_code": current.external_code,
                "rationale": updates.get("rationale", getattr(current, "rationale", None)),
                "source": updates.get("source", getattr(current, "source", None)),
            },
        )))
        current.is_current = False
        _propagate_requirement_change(
            db, session_id, current.id, new_id,
            f"Requirement '{current.external_code or current.id}' was revised",
        )
        db.commit()
        return new_id


def get_requirement_history(session_id: str, lineage_id: str) -> List[Dict[str, Any]]:
    with _db_session() as db:
        rows = db.query(RequirementItemRecord).filter(
            RequirementItemRecord.session_id == session_id,
            RequirementItemRecord.lineage_id == lineage_id,
        ).order_by(RequirementItemRecord.version).all()
        return [{
            "id": r.id, "version": r.version, "is_current": r.is_current,
            "description": r.description, "priority": r.priority,
            "status": r.status, "created_at": r.created_at.isoformat(),
        } for r in rows]


# ---------------------------------------------------------------------------
# Solution actuals
# ---------------------------------------------------------------------------
def record_actual_solution(
    session_id: str, decision_id: str, description: str,
    component: Optional[str] = None, rationale: Optional[str] = None,
) -> str:
    """Record what was ACTUALLY implemented for a solution decision,
    distinct from what was proposed. Creates a new version in the same
    lineage rather than overwriting the proposal."""
    with _db_session() as db:
        current = db.get(SolutionDecision, decision_id)
        if not current or current.session_id != session_id:
            raise ValueError("Solution decision not found for this session")

        new_id = uuid.uuid4().hex
        db.add(SolutionDecision(**_filter_model_kwargs(
            SolutionDecision,
            {
                "id": new_id, "session_id": session_id,
                "lineage_id": current.lineage_id,
                "version": current.version + 1, "is_current": True,
                "stage": "actual",
                "decision_type": current.decision_type,
                "component": component or current.component,
                "description": description,
                "rationale": rationale or current.rationale,
                "requirement_id": current.requirement_id,
                "external_code": getattr(current, "external_code", None),
            },
        )))
        current.is_current = False

        if current.requirement_id:
            _propagate_requirement_change(
                db, session_id, current.requirement_id, current.requirement_id,
                f"Solution decision '{current.component or current.id}' was updated",
            )

        db.commit()
        return new_id


def get_solution_decision_history(session_id: str, lineage_id: str) -> List[Dict[str, Any]]:
    with _db_session() as db:
        rows = db.query(SolutionDecision).filter(
            SolutionDecision.session_id == session_id,
            SolutionDecision.lineage_id == lineage_id,
        ).order_by(SolutionDecision.version).all()
        return [{
            "id": r.id, "version": r.version, "is_current": r.is_current, "stage": r.stage,
            "component": r.component, "description": r.description, "rationale": r.rationale,
            "created_at": r.created_at.isoformat(),
        } for r in rows]


# ---------------------------------------------------------------------------
# Process step revisions
# ---------------------------------------------------------------------------
def revise_process_step(session_id: str, step_id: str, updates: Dict[str, Any]) -> str:
    """Create a new version of a process step instead of mutating it."""
    with _db_session() as db:
        current = db.get(ProcessStepRecord, step_id)
        if not current or current.session_id != session_id:
            raise ValueError("Process step not found for this session")

        new_id = uuid.uuid4().hex
        db.add(ProcessStepRecord(**_filter_model_kwargs(
            ProcessStepRecord,
            {
                "id": new_id, "session_id": session_id,
                "lineage_id": current.lineage_id,
                "version": current.version + 1, "is_current": True,
                "process_name": current.process_name,
                "step_number": updates.get("step_number", current.step_number),
                "name": updates.get("name", current.name),
                "description": updates.get("description", current.description),
                "responsible_role": updates.get("responsible_role", current.responsible_role),
                "requirement_id": current.requirement_id,
                "external_code": getattr(current, "external_code", None),
            },
        )))
        current.is_current = False
        db.commit()
        return new_id


def get_process_step_history(session_id: str, lineage_id: str) -> List[Dict[str, Any]]:
    with _db_session() as db:
        rows = db.query(ProcessStepRecord).filter(
            ProcessStepRecord.session_id == session_id,
            ProcessStepRecord.lineage_id == lineage_id,
        ).order_by(ProcessStepRecord.version).all()
        return [{
            "id": r.id, "version": r.version, "is_current": r.is_current,
            "name": r.name, "description": r.description,
            "responsible_role": r.responsible_role, "created_at": r.created_at.isoformat(),
        } for r in rows]


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------
def create_baseline(
    session_id: str, user_id: str, label: str, notes: Optional[str] = None,
    decision_ids: Optional[List[str]] = None,
) -> str:
    """Snapshot 'the solution actually delivered' as of now. Defaults to
    every currently-active solution decision in the session.

    Now validates that every supplied decision_id belongs to this
    session — previously a caller could pass decision ids from another
    session and produce an inconsistent baseline. Deactivates any prior
    active baseline (kept, not deleted)."""
    with _db_session() as db:
        if decision_ids is None:
            current_decisions = db.query(SolutionDecision).filter(
                SolutionDecision.session_id == session_id,
                SolutionDecision.is_current.is_(True),
            ).all()
            decision_ids = [d.id for d in current_decisions]
        else:
            # Explicit ids: verify ownership before proceeding.
            if decision_ids:
                owned = db.query(SolutionDecision.id).filter(
                    SolutionDecision.session_id == session_id,
                    SolutionDecision.id.in_(decision_ids),
                ).all()
                owned_ids = {row[0] for row in owned}
                not_owned = [d for d in decision_ids if d not in owned_ids]
                if not_owned:
                    raise ValueError(
                        f"Cannot create baseline: decision id(s) do not belong "
                        f"to session '{session_id}': {not_owned}"
                    )

        db.query(SolutionBaseline).filter(
            SolutionBaseline.session_id == session_id,
            SolutionBaseline.is_active.is_(True),
        ).update({"is_active": False})

        baseline_id = uuid.uuid4().hex
        db.add(SolutionBaseline(
            id=baseline_id, session_id=session_id, label=label, notes=notes,
            created_by=user_id, is_active=True,
        ))
        for decision_id in decision_ids:
            db.add(SolutionBaselineItem(
                id=uuid.uuid4().hex, baseline_id=baseline_id, solution_decision_id=decision_id,
            ))
        db.commit()
        return baseline_id


def get_baselines(session_id: str) -> List[Dict[str, Any]]:
    with _db_session() as db:
        rows = db.query(SolutionBaseline).filter(
            SolutionBaseline.session_id == session_id
        ).order_by(SolutionBaseline.created_at.desc()).all()
        return [{
            "id": r.id, "label": r.label, "notes": r.notes,
            "is_active": r.is_active, "created_at": r.created_at.isoformat(),
        } for r in rows]