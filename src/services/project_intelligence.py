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
    SolutionBaseline, 
    SolutionBaselineItem,
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
                    lineage_id=rid, version=1, is_current=True,
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
                    lineage_id=rid, version=1, is_current=True,
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


def get_requirements(session_id: str, include_history: bool = False) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        q = db.query(RequirementItemRecord).filter(RequirementItemRecord.session_id == session_id)
        if not include_history:
            q = q.filter(RequirementItemRecord.is_current.is_(True))
        rows = q.order_by(RequirementItemRecord.category, RequirementItemRecord.created_at).all()
        return [{
            "id": r.id, "lineage_id": r.lineage_id, "version": r.version, "is_current": r.is_current,
            "category": r.category, "description": r.description, "priority": r.priority,
            "type": r.req_type, "acceptance_criteria": r.acceptance_criteria,
            "status": r.status, "external_code": r.external_code,
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
            RequirementItemRecord.session_id == session_id
        ).filter(RequirementItemRecord.is_current.is_(True)).all()
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

        gaps = get_coverage_gaps(session_id)

        return {
            "requirements_total": total,
            "requirements_by_status": req_by_status,
            "requirements_coverage_pct": round((covered / total * 100), 1) if total else 0.0,
            "open_issues_total": len(issues),
            "open_issues_by_severity": issues_by_severity,
            "uncovered_requirements_count": len(gaps["uncovered_requirements"]),
            "untested_requirements_count": len(gaps["untested_requirements"]),
            "has_active_baseline": get_active_baseline(session_id) is not None,
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
                lineage_id=sid,
                version=1,
                is_current=True,
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


def get_process_steps(session_id: str, process_name: Optional[str] = None,
                       include_history: bool = False) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
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
                lineage_id=did, version=1, is_current=True, stage="proposed",
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
                lineage_id=did, version=1, is_current=True, stage="proposed",
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
                lineage_id=did, version=1, is_current=True, stage="proposed",
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


def get_solution_decisions(session_id: str, decision_type: Optional[str] = None,
                            stage: Optional[str] = None, include_history: bool = False) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
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
                    lineage_id=rid, version=1, is_current=True,
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
                    lineage_id=rid, version=1, is_current=True,
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
    pending_failures = []
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
            if tc.get("execution_status") == "failed":
                pending_failures.append((tid, tc))
        db.commit()
    finally:
        db.close()

    for tc_id, codes in pending_links:
        if codes:
            link_requirements(session_id, "test_case", tc_id, codes)

    for tc_id, tc in pending_failures:
        record_test_failure(
            session_id, tc_id,
            classification=tc.get("failure_classification") or "other",
            description=tc.get("failure_description") or f"Test case '{tc.get('scenario', tc_id)}' failed.",
        )

    return created_ids


def record_test_failure(session_id: str, test_case_id: str, classification: str, description: str) -> str:
    """Records a test failure as a first-class ProjectIssue rather than
    a pass/fail checkbox - the platform's core principle that testing
    generates project knowledge. Severity is derived from classification:
    a defect or changed requirement is high-impact (blocks the affected
    requirement's delivery); everything else defaults to medium."""
    valid_classifications = {
        "defect", "unclear_requirement", "changed_requirement",
        "data_issue", "integration_issue", "environment_issue", "other",
    }
    if classification not in valid_classifications:
        classification = "other"

    severity = "high" if classification in ("defect", "changed_requirement") else "medium"

    db = SessionLocal()
    try:
        iid = uuid.uuid4().hex
        db.add(ProjectIssue(
            id=iid, session_id=session_id, issue_type="test_failure", severity=severity,
            description=description, related_object_type="test_case", related_object_id=test_case_id,
            test_case_id=test_case_id, classification=classification,
        ))
        db.commit()
        return iid
    finally:
        db.close()


def get_test_failures(session_id: str, classification: Optional[str] = None) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
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
    finally:
        db.close()


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


def get_test_cases(session_id: str, test_type: Optional[str] = None,
                    needs_retest: Optional[bool] = None) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
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
        } for r in rows]
    finally:
        db.close()


def mark_test_case_retested(session_id: str, test_case_id: str) -> bool:
    db = SessionLocal()
    try:
        tc = db.get(TestCaseRecord, test_case_id)
        if not tc or tc.session_id != session_id:
            return False
        tc.needs_retest = False
        db.commit()
        return True
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

def get_coverage_gaps(session_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """Identifies objects with zero downstream trace-link coverage -
    the concrete 'gaps' the brief asks for, computed deterministically
    from real TraceLink rows rather than inferred by an LLM.

    Two directions of gap are checked:
    - Requirements with no downstream coverage at all (never referenced
      by any process step, solution decision, test case, or training
      step) - these are requirements nobody has acted on yet.
    - Requirements with functional/technical coverage but no QA/UAT
      test case referencing them - a specific, high-value gap since an
      untested requirement is a real delivery risk.
    """
    db = SessionLocal()
    try:
        requirements = db.query(RequirementItemRecord).filter(
            RequirementItemRecord.session_id == session_id
        ).filter(RequirementItemRecord.is_current.is_(True)).all()

        links = db.query(TraceLink).filter(
            TraceLink.session_id == session_id,
            TraceLink.relationship == "covers",
        ).all()

        covered_req_ids = {l.target_id for l in links if l.target_type == "requirement"}
        # Which requirement IDs are covered specifically by a test_case source
        tested_req_ids = {
            l.target_id for l in links
            if l.target_type == "requirement" and l.source_type == "test_case"
        }

        uncovered = [
            {"id": r.id, "external_code": r.external_code, "category": r.category,
             "description": r.description, "priority": r.priority}
            for r in requirements if r.id not in covered_req_ids
        ]

        untested = [
            {"id": r.id, "external_code": r.external_code, "category": r.category,
             "description": r.description, "priority": r.priority}
            for r in requirements if r.id not in tested_req_ids
        ]

        return {
            "uncovered_requirements": uncovered,
            "untested_requirements": untested,
        }
    finally:
        db.close()


def _propagate_requirement_change(db, session_id: str, old_requirement_id: str, new_requirement_id: str,
                                   change_summary: str) -> int:
    """When a requirement changes, its existing coverage (trace links)
    still describes real work done against the OLD version - that work
    isn't invalidated, but it does need re-confirming against the new
    version. This carries every incoming 'covers' link forward to the
    new requirement row (so coverage/gap analysis, which only looks at
    is_current rows, doesn't wrongly report the revised requirement as
    newly uncovered), flags every test case among them as needing
    retest, and files a visible issue. Returns the number of test cases
    flagged."""
    incoming_links = db.query(TraceLink).filter(
        TraceLink.session_id == session_id,
        TraceLink.target_type == "requirement",
        TraceLink.target_id == old_requirement_id,
        TraceLink.relationship == "covers",
    ).all()

    flagged_count = 0
    for link in incoming_links:
        db.add(TraceLink(
            id=uuid.uuid4().hex, session_id=session_id,
            source_type=link.source_type, source_id=link.source_id,
            target_type="requirement", target_id=new_requirement_id, relationship="covers",
        ))
        if link.source_type == "test_case":
            tc = db.get(TestCaseRecord, link.source_id)
            if tc and not tc.needs_retest:
                tc.needs_retest = True
                flagged_count += 1

    if flagged_count:
        db.add(ProjectIssue(
            id=uuid.uuid4().hex, session_id=session_id, issue_type="requirement_changed",
            severity="medium", description=f"{change_summary} - {flagged_count} test case(s) flagged for retest.",
            related_object_type="requirement", related_object_id=new_requirement_id,
        ))
    return flagged_count

def revise_requirement(session_id: str, requirement_id: str, updates: Dict[str, Any]) -> str:
    """Creates a new version of a requirement instead of mutating it -
    the append-only history the platform's change-tracking model
    depends on. A revised requirement returns to 'draft' status - the
    prior approval applied to the superseded version, not this one."""
    db = SessionLocal()
    try:
        current = db.get(RequirementItemRecord, requirement_id)
        if not current or current.session_id != session_id:
            raise ValueError("Requirement not found for this session")

        new_id = uuid.uuid4().hex
        db.add(RequirementItemRecord(
            id=new_id, session_id=session_id, lineage_id=current.lineage_id,
            version=current.version + 1, is_current=True, status="draft",
            category=updates.get("category", current.category),
            description=updates.get("description", current.description),
            priority=updates.get("priority", current.priority),
            req_type=updates.get("req_type", current.req_type),
            acceptance_criteria=updates.get("acceptance_criteria", current.acceptance_criteria),
            external_code=current.external_code,
        ))
        current.is_current = False
        _propagate_requirement_change(
            db, session_id, current.id, new_id,
            f"Requirement '{current.external_code or current.id}' was revised"
        )
        db.commit()
        return new_id
    finally:
        db.close()


def get_requirement_history(session_id: str, lineage_id: str) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        rows = db.query(RequirementItemRecord).filter(
            RequirementItemRecord.session_id == session_id,
            RequirementItemRecord.lineage_id == lineage_id,
        ).order_by(RequirementItemRecord.version).all()
        return [{
            "id": r.id, "version": r.version, "is_current": r.is_current,
            "description": r.description, "priority": r.priority,
            "status": r.status, "created_at": r.created_at.isoformat(),
        } for r in rows]
    finally:
        db.close()


def record_actual_solution(session_id: str, decision_id: str, description: str,
                            component: Optional[str] = None, rationale: Optional[str] = None) -> str:
    """Records what was ACTUALLY implemented for a solution decision,
    distinct from what was originally proposed - creates a new version
    in the same lineage rather than overwriting the proposal, so the
    original design remains visible in history."""
    db = SessionLocal()
    try:
        current = db.get(SolutionDecision, decision_id)
        if not current or current.session_id != session_id:
            raise ValueError("Solution decision not found for this session")

        new_id = uuid.uuid4().hex
        db.add(SolutionDecision(
            id=new_id, session_id=session_id, lineage_id=current.lineage_id,
            version=current.version + 1, is_current=True, stage="actual",
            decision_type=current.decision_type,
            component=component or current.component,
            description=description,
            rationale=rationale or current.rationale,
            requirement_id=current.requirement_id,
        ))
        current.is_current = False

        if current.requirement_id:
            # This decision's requirement didn't itself change, but the
            # implementation behind it did - the same 'existing coverage
            # needs re-confirming' logic applies, scoped to the one
            # requirement this decision is linked to.
            _propagate_requirement_change(
                db, session_id, current.requirement_id, current.requirement_id,
                f"Solution decision '{current.component or current.id}' was updated to reflect the actual implementation"
            )

        db.commit()
        return new_id
    finally:
        db.close()


def get_solution_decision_history(session_id: str, lineage_id: str) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        rows = db.query(SolutionDecision).filter(
            SolutionDecision.session_id == session_id,
            SolutionDecision.lineage_id == lineage_id,
        ).order_by(SolutionDecision.version).all()
        return [{
            "id": r.id, "version": r.version, "is_current": r.is_current, "stage": r.stage,
            "component": r.component, "description": r.description, "rationale": r.rationale,
            "created_at": r.created_at.isoformat(),
        } for r in rows]
    finally:
        db.close()

def revise_process_step(session_id: str, step_id: str, updates: Dict[str, Any]) -> str:
    """Creates a new version of a process step instead of mutating it -
    e.g. when a solution change (record_actual_solution) requires the
    business process itself to change. Preserves the original step in
    full history rather than silently overwriting it."""
    db = SessionLocal()
    try:
        current = db.get(ProcessStepRecord, step_id)
        if not current or current.session_id != session_id:
            raise ValueError("Process step not found for this session")

        new_id = uuid.uuid4().hex
        db.add(ProcessStepRecord(
            id=new_id, session_id=session_id, lineage_id=current.lineage_id,
            version=current.version + 1, is_current=True,
            process_name=current.process_name,
            step_number=updates.get("step_number", current.step_number),
            name=updates.get("name", current.name),
            description=updates.get("description", current.description),
            responsible_role=updates.get("responsible_role", current.responsible_role),
            requirement_id=current.requirement_id,
        ))
        current.is_current = False
        db.commit()
        return new_id
    finally:
        db.close()


def get_process_step_history(session_id: str, lineage_id: str) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        rows = db.query(ProcessStepRecord).filter(
            ProcessStepRecord.session_id == session_id,
            ProcessStepRecord.lineage_id == lineage_id,
        ).order_by(ProcessStepRecord.version).all()
        return [{
            "id": r.id, "version": r.version, "is_current": r.is_current,
            "name": r.name, "description": r.description,
            "responsible_role": r.responsible_role, "created_at": r.created_at.isoformat(),
        } for r in rows]
    finally:
        db.close()

def create_baseline(session_id: str, user_id: str, label: str, notes: Optional[str] = None,
                     decision_ids: Optional[List[str]] = None) -> str:
    """Snapshots 'the solution actually delivered' as of now. Defaults to
    every currently-active solution decision in the session if no
    explicit decision_ids are given - the common case of 'baseline
    whatever is live right now'. Deactivates any prior active baseline
    (kept, not deleted - full baseline history remains queryable)."""
    db = SessionLocal()
    try:
        if decision_ids is None:
            current_decisions = db.query(SolutionDecision).filter(
                SolutionDecision.session_id == session_id,
                SolutionDecision.is_current.is_(True),
            ).all()
            decision_ids = [d.id for d in current_decisions]

        db.query(SolutionBaseline).filter(
            SolutionBaseline.session_id == session_id, SolutionBaseline.is_active.is_(True)
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
    finally:
        db.close()


def get_active_baseline(session_id: str) -> Optional[Dict[str, Any]]:
    db = SessionLocal()
    try:
        baseline = db.query(SolutionBaseline).filter(
            SolutionBaseline.session_id == session_id, SolutionBaseline.is_active.is_(True)
        ).first()
        if not baseline:
            return None

        items = db.query(SolutionBaselineItem).filter(
            SolutionBaselineItem.baseline_id == baseline.id
        ).all()
        decision_ids = [i.solution_decision_id for i in items]
        decisions = db.query(SolutionDecision).filter(SolutionDecision.id.in_(decision_ids)).all() if decision_ids else []

        return {
            "id": baseline.id, "label": baseline.label, "notes": baseline.notes,
            "created_at": baseline.created_at.isoformat(),
            "decisions": [{
                "id": d.id, "decision_type": d.decision_type, "component": d.component,
                "description": d.description, "stage": d.stage, "version": d.version,
            } for d in decisions],
        }
    finally:
        db.close()


def get_baselines(session_id: str) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        rows = db.query(SolutionBaseline).filter(
            SolutionBaseline.session_id == session_id
        ).order_by(SolutionBaseline.created_at.desc()).all()
        return [{
            "id": r.id, "label": r.label, "notes": r.notes,
            "is_active": r.is_active, "created_at": r.created_at.isoformat(),
        } for r in rows]
    finally:
        db.close()