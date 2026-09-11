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
    RequirementItemRecord, ProcessStepRecord, SolutionDecision,
    ProjectIssue, ReviewAction, TraceLink,
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