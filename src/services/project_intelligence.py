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
"""
import uuid
from typing import Dict, List, Any, Optional

from src.db.base import SessionLocal
from src.db.models import (
    RequirementItemRecord,
    ProcessStepRecord,
    SolutionDecision,
    TestCaseRecord,
    TrainingStepRecord,
    ProjectIssue,
    ReviewAction,
    TraceLink,
)

def sync_requirements_from_structured(session_id: str, structured_requirements: Dict[str, Any]) -> List[str]:
    """Converts the existing structured_requirements dict (as produced by
    RequirementsDocument.to_legacy_dict()) into real RequirementItemRecord
    rows. Returns the list of new requirement IDs created."""
    db = SessionLocal()
    created_ids = []
    try:
        functional = structured_requirements.get("functional_requirements", {}) or {}
        for category, reqs in functional.items():
            for req in reqs:
                rid = uuid.uuid4().hex
                db.add(RequirementItemRecord(
                    id=rid,
                    session_id=session_id,
                    category=category,
                    description=req.get("description", ""),
                    priority=req.get("priority", "Medium"),
                    req_type=req.get("type", "Functional"),
                    acceptance_criteria=req.get("acceptance_criteria"),
                ))
                created_ids.append(rid)

        for bucket, category_label in (
            ("technical_requirements", "Technical"),
            ("integration_requirements", "Integration"),
            ("reporting_requirements", "Reporting"),
        ):
            for req in structured_requirements.get(bucket, []) or []:
                desc = req.get("description", req) if isinstance(req, dict) else req
                rid = uuid.uuid4().hex
                db.add(RequirementItemRecord(
                    id=rid,
                    session_id=session_id,
                    category=category_label,
                    description=desc,
                    priority=req.get("priority", "Medium") if isinstance(req, dict) else "Medium",
                    req_type=category_label,
                ))
                created_ids.append(rid)

        db.commit()
    finally:
        db.close()
    return created_ids


def get_requirements(session_id: str) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        rows = db.query(RequirementItemRecord).filter(
            RequirementItemRecord.session_id == session_id
        ).order_by(RequirementItemRecord.category, RequirementItemRecord.created_at).all()
        return [{
            "id": r.id, "category": r.category, "description": r.description,
            "priority": r.priority, "type": r.req_type,
            "acceptance_criteria": r.acceptance_criteria, "status": r.status,
        } for r in rows]
    finally:
        db.close()


def record_review_action(session_id: str, user_id: str, object_type: str, object_id: str,
                          action: str, note: Optional[str] = None) -> str:
    """Records an approve/reject/correct action and, for requirements,
    updates the underlying row's status to match - the concrete
    validation-and-review workflow foundation."""
    db = SessionLocal()
    try:
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
    finally:
        db.close()


def create_issue(session_id: str, issue_type: str, description: str, severity: str = "medium",
                  related_object_type: Optional[str] = None, related_object_id: Optional[str] = None) -> str:
    db = SessionLocal()
    try:
        iid = uuid.uuid4().hex
        db.add(ProjectIssue(
            id=iid, session_id=session_id, issue_type=issue_type, severity=severity,
            description=description, related_object_type=related_object_type,
            related_object_id=related_object_id,
        ))
        db.commit()
        return iid
    finally:
        db.close()


def get_issues(session_id: str, status: Optional[str] = "open") -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        q = db.query(ProjectIssue).filter(ProjectIssue.session_id == session_id)
        if status:
            q = q.filter(ProjectIssue.status == status)
        rows = q.order_by(ProjectIssue.created_at.desc()).all()
        return [{
            "id": r.id, "issue_type": r.issue_type, "severity": r.severity,
            "description": r.description, "status": r.status,
            "related_object_type": r.related_object_type, "related_object_id": r.related_object_id,
        } for r in rows]
    finally:
        db.close()


def add_trace_link(session_id: str, source_type: str, source_id: str,
                    target_type: str, target_id: str, relationship: str = "covers") -> str:
    db = SessionLocal()
    try:
        lid = uuid.uuid4().hex
        db.add(TraceLink(
            id=lid, session_id=session_id, source_type=source_type, source_id=source_id,
            target_type=target_type, target_id=target_id, relationship=relationship,
        ))
        db.commit()
        return lid
    finally:
        db.close()


def get_project_health(session_id: str) -> Dict[str, Any]:
    """Coarse project-level health summary: requirement counts by status,
    open issue counts by severity, and a naive coverage percentage
    (requirements with at least one 'covers' trace link pointing at
    them). Deliberately simple - a real coverage-gap engine is a
    follow-up, not built here."""
    db = SessionLocal()
    try:
        requirements = db.query(RequirementItemRecord).filter(
            RequirementItemRecord.session_id == session_id).all()
        issues = db.query(ProjectIssue).filter(
            ProjectIssue.session_id == session_id, ProjectIssue.status == "open").all()
        covered_ids = {
            l.target_id for l in db.query(TraceLink).filter(
                TraceLink.session_id == session_id, TraceLink.relationship == "covers"
            ).all()
        }

        req_by_status = {"draft": 0, "approved": 0, "rejected": 0}
        for r in requirements:
            req_by_status[r.status] = req_by_status.get(r.status, 0) + 1

        issues_by_severity = {"low": 0, "medium": 0, "high": 0}
        for i in issues:
            issues_by_severity[i.severity] = issues_by_severity.get(i.severity, 0) + 1

        total = len(requirements)
        covered = sum(1 for r in requirements if r.id in covered_ids)

        return {
            "requirements_total": total,
            "requirements_by_status": req_by_status,
            "requirements_coverage_pct": round((covered / total * 100), 1) if total else 0.0,
            "open_issues_total": len(issues),
            "open_issues_by_severity": issues_by_severity,
        }
    finally:
        db.close()

def sync_process_steps_from_structured(session_id: str, process_name: str,
                                        structured_process: Dict[str, Any]) -> List[str]:
    """Converts a ProcessMap's steps into real ProcessStepRecord rows.
    requirement_id is left null here - process_mapping_agent's current
    output doesn't identify which specific requirement drove which step,
    and fabricating that link would violate the 'deterministic validation,
    not LLM assumption' principle. Wire this once the agent/schema
    reports it explicitly."""
    db = SessionLocal()
    created_ids = []
    try:
        for step in structured_process.get("steps", []) or []:
            sid = uuid.uuid4().hex
            db.add(ProcessStepRecord(
                id=sid,
                session_id=session_id,
                process_name=process_name,
                step_number=step.get("number", len(created_ids) + 1),
                name=step.get("name", ""),
                description=step.get("description"),
                responsible_role=step.get("responsible_role"),
            ))
            created_ids.append(sid)
        db.commit()
    finally:
        db.close()
    return created_ids


def get_process_steps(session_id: str, process_name: Optional[str] = None) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        q = db.query(ProcessStepRecord).filter(ProcessStepRecord.session_id == session_id)
        if process_name:
            q = q.filter(ProcessStepRecord.process_name == process_name)
        rows = q.order_by(ProcessStepRecord.process_name, ProcessStepRecord.step_number).all()
        return [{
            "id": r.id, "process_name": r.process_name, "step_number": r.step_number,
            "name": r.name, "description": r.description,
            "responsible_role": r.responsible_role, "requirement_id": r.requirement_id,
        } for r in rows]
    finally:
        db.close()


def sync_solution_decisions_from_structured(session_id: str, structured_design: Dict[str, Any]) -> List[str]:
    """Converts a SolutionDesign's configurations, customizations, and
    integrations into real SolutionDecision rows, resolving each item's
    self-reported related_requirement_ids into validated TraceLinks - a
    code that doesn't match a real requirement is never fabricated into
    a link; it's filed as a ProjectIssue instead (see
    resolve_requirement_codes)."""
    db = SessionLocal()
    created_ids = []
    pending_links = []  # (decision_id, codes) - resolved after commit so IDs exist
    try:
        for config in structured_design.get("configurations", []) or []:
            did = uuid.uuid4().hex
            db.add(SolutionDecision(
                id=did,
                session_id=session_id,
                decision_type="module_config",
                component=config.get("component"),
                description=config.get("description", ""),
                rationale=None,
            ))
            created_ids.append(did)
            pending_links.append((did, "solution_decision", config.get("related_requirement_ids") or []))

        for custom in structured_design.get("customizations", []) or []:
            did = uuid.uuid4().hex
            db.add(SolutionDecision(
                id=did,
                session_id=session_id,
                decision_type="customization",
                component=custom.get("component"),
                description=custom.get("description", ""),
                rationale=custom.get("justification"),
            ))
            created_ids.append(did)
            pending_links.append((did, "solution_decision", custom.get("related_requirement_ids") or []))

        for integ in structured_design.get("integrations", []) or []:
            did = uuid.uuid4().hex
            db.add(SolutionDecision(
                id=did,
                session_id=session_id,
                decision_type="integration",
                component=integ.get("name"),
                description=integ.get("description", ""),
                rationale=None,
            ))
            created_ids.append(did)
            pending_links.append((did, "solution_decision", integ.get("related_requirement_ids") or []))

        db.commit()
    finally:
        db.close()

    for decision_id, source_type, codes in pending_links:
        if codes:
            link_requirements(session_id, source_type, decision_id, codes)

    return created_ids


def get_solution_decisions(session_id: str, decision_type: Optional[str] = None) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        q = db.query(SolutionDecision).filter(SolutionDecision.session_id == session_id)
        if decision_type:
            q = q.filter(SolutionDecision.decision_type == decision_type)
        rows = q.order_by(SolutionDecision.created_at).all()
        return [{
            "id": r.id, "decision_type": r.decision_type, "component": r.component,
            "description": r.description, "rationale": r.rationale,
            "requirement_id": r.requirement_id, "status": r.status,
        } for r in rows]
    finally:
        db.close()

def sync_requirements_from_structured(session_id: str, structured_requirements: Dict[str, Any]) -> List[str]:
    db = SessionLocal()
    created_ids = []
    try:
        functional = structured_requirements.get("functional_requirements", {}) or {}
        for category, reqs in functional.items():
            for req in reqs:
                rid = uuid.uuid4().hex
                db.add(RequirementItemRecord(
                    id=rid,
                    session_id=session_id,
                    category=category,
                    description=req.get("description", ""),
                    priority=req.get("priority", "Medium"),
                    req_type=req.get("type", "Functional"),
                    acceptance_criteria=req.get("acceptance_criteria"),
                    external_code=req.get("id"),
                ))
                created_ids.append(rid)

        for bucket, category_label in (
            ("technical_requirements", "Technical"),
            ("integration_requirements", "Integration"),
            ("reporting_requirements", "Reporting"),
        ):
            for req in structured_requirements.get(bucket, []) or []:
                desc = req.get("description", req) if isinstance(req, dict) else req
                rid = uuid.uuid4().hex
                db.add(RequirementItemRecord(
                    id=rid,
                    session_id=session_id,
                    category=category_label,
                    description=desc,
                    priority=req.get("priority", "Medium") if isinstance(req, dict) else "Medium",
                    req_type=category_label,
                    external_code=req.get("id") if isinstance(req, dict) else None,
                ))
                created_ids.append(rid)

        db.commit()
    finally:
        db.close()
    return created_ids


def resolve_requirement_codes(session_id: str, codes: List[str]) -> Dict[str, str]:
    """Maps model-reported requirement codes (e.g. 'REQ-001') to real
    RequirementItemRecord UUIDs - the deterministic validation step.
    Codes that don't match any stored requirement are silently excluded
    from the result (never fabricated) and logged as a ProjectIssue so
    the mismatch is visible instead of disappearing."""
    if not codes:
        return {}
    db = SessionLocal()
    try:
        rows = db.query(RequirementItemRecord).filter(
            RequirementItemRecord.session_id == session_id,
            RequirementItemRecord.external_code.in_(codes),
        ).all()
        resolved = {r.external_code: r.id for r in rows}
        unresolved = set(codes) - set(resolved.keys())
        for code in unresolved:
            create_issue(
                session_id, "missing_info",
                f"Referenced requirement code '{code}' does not match any stored requirement.",
                severity="low",
            )
        return resolved
    finally:
        db.close()


def link_requirements(session_id: str, source_type: str, source_id: str,
                       requirement_codes: List[str]) -> List[str]:
    """Resolves requirement codes and creates 'covers' TraceLinks for
    each valid match. Returns the list of TraceLink IDs created."""
    resolved = resolve_requirement_codes(session_id, requirement_codes)
    return [
        add_trace_link(session_id, source_type, source_id, "requirement", req_uuid)
        for req_uuid in resolved.values()
    ]

def sync_test_cases_from_structured(session_id: str, test_type: str,
                                     structured_test_cases: List[Dict[str, Any]]) -> List[str]:
    db = SessionLocal()
    created_ids = []
    pending_links = []
    try:
        for tc in structured_test_cases:
            tid = uuid.uuid4().hex
            db.add(TestCaseRecord(
                id=tid,
                session_id=session_id,
                test_type=test_type,
                external_code=tc.get("id"),
                scenario=tc.get("scenario", ""),
                priority=tc.get("priority", "Medium"),
                expected_result=tc.get("expected_result"),
            ))
            created_ids.append(tid)
            pending_links.append((tid, tc.get("related_requirement_ids") or []))
        db.commit()
    finally:
        db.close()

    for tc_id, codes in pending_links:
        if codes:
            link_requirements(session_id, "test_case", tc_id, codes)

    return created_ids


def sync_training_steps_from_structured(session_id: str, structured_materials: Dict[str, Any]) -> List[str]:
    db = SessionLocal()
    created_ids = []
    pending_links = []
    try:
        steps = (structured_materials.get("user_manual") or {}).get("steps", [])
        for step in steps:
            sid = uuid.uuid4().hex
            db.add(TrainingStepRecord(
                id=sid,
                session_id=session_id,
                title=step.get("title", ""),
                instructions=step.get("instructions"),
            ))
            created_ids.append(sid)
            pending_links.append((sid, step.get("related_requirement_ids") or []))
        db.commit()
    finally:
        db.close()

    for step_id, codes in pending_links:
        if codes:
            link_requirements(session_id, "training_step", step_id, codes)

    return created_ids


def get_test_cases(session_id: str, test_type: Optional[str] = None) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        q = db.query(TestCaseRecord).filter(TestCaseRecord.session_id == session_id)
        if test_type:
            q = q.filter(TestCaseRecord.test_type == test_type)
        rows = q.order_by(TestCaseRecord.created_at).all()
        return [{
            "id": r.id, "test_type": r.test_type, "external_code": r.external_code,
            "scenario": r.scenario, "priority": r.priority, "expected_result": r.expected_result,
        } for r in rows]
    finally:
        db.close()


def get_training_steps(session_id: str) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        rows = db.query(TrainingStepRecord).filter(
            TrainingStepRecord.session_id == session_id
        ).order_by(TrainingStepRecord.created_at).all()
        return [{"id": r.id, "title": r.title, "instructions": r.instructions} for r in rows]
    finally:
        db.close()