"""
Cross-document consistency checking - deterministic, rule-based checks
across the structured project-intelligence objects (RequirementItemRecord,
SolutionDecision), never an LLM judgment call. This is the concrete
"AI reliability: move business logic away from unsupported LLM
assumptions, use deterministic validation" principle - every check here
is a plain comparison a human could verify by eye, not a model asking
"does this seem contradictory?".

Deliberately a small, precise rule set rather than a large one: a false
positive here (flagging something as a contradiction that isn't) erodes
trust in every future flag, so each check only fires on an unambiguous
signal. Findings become ProjectIssue rows (issue_type='contradiction' or
'missing_info') - visible on the existing /issues and /health endpoints,
nothing new to build there.

Explicitly out of scope for this pass (see docstrings on individual
checks, and the module-level TODO at the bottom): checks that would
require inferring meaning from free-text categories, or that depend on
requirement_id links which aren't populated anywhere yet (see
sync_process_steps_from_structured / sync_solution_decisions_from_structured
in project_intelligence.py) - adding those checks now would either be a
heuristic guess dressed up as a deterministic rule, or would flag every
requirement as a false "gap" simply because linking doesn't exist yet.
Both would be noise, not signal.
"""
from typing import Dict, List, Any

from src.db.base import SessionLocal
from src.db.models import SolutionDecision, RequirementItemRecord
from src.memory import session_service
from src.services.project_intelligence import create_issue

# Vendor names checked against the project's own erp_system field. Matching
# is a plain case-insensitive substring check, not fuzzy/semantic - "SAP"
# only matches decision text that actually contains "sap".
KNOWN_ERP_VENDORS = ["sap", "oracle", "dynamics", "netsuite", "odoo", "infor", "workday"]


def _mentioned_vendor(text: str) -> str | None:
    lowered = text.lower()
    for vendor in KNOWN_ERP_VENDORS:
        if vendor in lowered:
            return vendor
    return None


def run_consistency_checks(session_id: str) -> List[Dict[str, Any]]:
    """Runs every check below against the current state of one project and
    records a ProjectIssue for each finding. Safe to call repeatedly
    (e.g. after every phase completes) - it does not deduplicate against
    previously-created issues itself, so calling it many times without any
    underlying data changing will create repeat issues. Wire it to actual
    state-changing events (a phase completing), not a polling loop, until
    that's addressed.

    Returns the list of findings created, each as
    {issue_type, severity, description}.
    """
    findings: List[Dict[str, Any]] = []

    session = session_service.get_session(session_id)
    if not session:
        return findings

    db = SessionLocal()
    try:
        decisions = db.query(SolutionDecision).filter(SolutionDecision.session_id == session_id).all()
        requirements = db.query(RequirementItemRecord).filter(
            RequirementItemRecord.session_id == session_id
        ).all()
    finally:
        db.close()

    findings.extend(_check_erp_system_mismatch(session_id, session.erp_system, decisions))
    findings.extend(_check_conflicting_component_decisions(session_id, decisions))
    findings.extend(_check_customizations_missing_rationale(session_id, decisions))

    for f in findings:
        create_issue(
            session_id=session_id,
            issue_type=f["issue_type"],
            description=f["description"],
            severity=f["severity"],
            related_object_type=f.get("related_object_type"),
            related_object_id=f.get("related_object_id"),
        )

    return findings


def _check_erp_system_mismatch(session_id: str, project_erp_system: str,
                                decisions: List[SolutionDecision]) -> List[Dict[str, Any]]:
    """A solution decision naming a different ERP vendor than the project's
    own erp_system field is an unambiguous contradiction - not a judgment
    call, since the project's erp_system is the declared ground truth."""
    project_vendor = _mentioned_vendor(project_erp_system)
    if not project_vendor:
        return []  # Can't compare against an erp_system we don't recognize

    findings = []
    for d in decisions:
        text = f"{d.component or ''} {d.description or ''}"
        mentioned = _mentioned_vendor(text)
        if mentioned and mentioned != project_vendor:
            findings.append({
                "issue_type": "contradiction",
                "severity": "high",
                "description": (
                    f"Solution decision mentions '{mentioned.upper()}' but this project's "
                    f"ERP system is '{project_erp_system}': {d.description}"
                ),
                "related_object_type": "solution_decision",
                "related_object_id": d.id,
            })
    return findings


def _check_conflicting_component_decisions(session_id: str,
                                            decisions: List[SolutionDecision]) -> List[Dict[str, Any]]:
    """Two decisions of the same type, naming the same component, with
    different descriptions - a real conflict (two different things were
    decided about the same component), not a heuristic guess."""
    by_key: Dict[tuple, List[SolutionDecision]] = {}
    for d in decisions:
        if not d.component:
            continue
        key = (d.decision_type, d.component.strip().lower())
        by_key.setdefault(key, []).append(d)

    findings = []
    for (decision_type, component_key), group in by_key.items():
        distinct_descriptions = {d.description.strip() for d in group if d.description}
        if len(distinct_descriptions) > 1:
            original_component = group[0].component
            findings.append({
                "issue_type": "contradiction",
                "severity": "high",
                "description": (
                    f"Multiple conflicting '{decision_type}' decisions recorded for "
                    f"component '{original_component}': " + " | ".join(sorted(distinct_descriptions))
                ),
                "related_object_type": "solution_decision",
                "related_object_id": group[0].id,
            })
    return findings


def _check_customizations_missing_rationale(session_id: str,
                                             decisions: List[SolutionDecision]) -> List[Dict[str, Any]]:
    """A customization with no stated rationale is a completeness gap, not
    a contradiction - flagged as missing_info at medium severity. Matches
    the existing best-practice guidance already seeded into every
    project's memory ('minimize customizations... ensure decisions have
    rationale')."""
    findings = []
    for d in decisions:
        if d.decision_type == "customization" and not (d.rationale and d.rationale.strip()):
            findings.append({
                "issue_type": "missing_info",
                "severity": "medium",
                "description": f"Customization has no stated rationale: {d.description}",
                "related_object_type": "solution_decision",
                "related_object_id": d.id,
            })
    return findings
