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

Design notes on this revision:

  * Idempotency: findings are filed with create_issue(dedupe=True), so
    re-running the check against unchanged data does not produce a
    second copy of the same issue. The previous version documented this
    as a known limitation and asked callers to only invoke on
    state-changing events. Since the descriptions the checker produces
    are fully deterministic (no timestamps, no generated ids), dedupe
    by description is a safe and correct fix - the caller no longer
    has to reason about when to run the check.

  * Vendor detection is order-independent. The previous rule returned
    the first vendor name found in KNOWN_ERP_VENDORS's list order,
    which meant behavior depended on list ordering rather than content.
    The rule now collects every vendor mentioned in the text, treats
    the project's own vendor as authoritative, and only flags when the
    project's vendor is NOT mentioned and another vendor IS.

  * Vendor aliases: common abbreviations (s4hana, s/4hana, d365,
    fusion) are recognized and mapped to their canonical vendor, so a
    decision referring to "S/4HANA" is detected the same way as one
    referring to "SAP".

Explicitly out of scope for this pass:
  - Checks that would require inferring meaning from free-text
    categories. Those would be heuristic guesses dressed up as
    deterministic rules.
  - Checks that depend on requirement_id links, which are populated
    only when an agent explicitly supplies related_requirement_ids
    (see sync_process_steps_from_structured / sync_solution_decisions_
    from_structured in project_intelligence.py). Adding them now would
    flag every requirement as a false "gap" simply because linking
    doesn't exist yet.
"""
from __future__ import annotations

from typing import Any, Dict, List, Set

from src.db.base import SessionLocal
from src.db.models import SolutionDecision
from src.memory import session_service
from src.services.project_intelligence import create_issue
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Vendor recognition
# ---------------------------------------------------------------------------
# Canonical vendor names, plus the aliases users type. Matched as
# substrings of lowercased text, so "s/4hana" matches "sap s/4hana" or
# "sap s4hana" or "s/4hana private cloud".
#
# When two canonical vendors would both match a single substring (not
# currently possible — the strings are distinct), the alias map's dict
# ordering determines which one wins. Keep the canonical names as keys
# and aliases as values.
_VENDOR_ALIASES: Dict[str, str] = {
    # SAP
    "sap": "sap",
    "s/4hana": "sap",
    "s4hana": "sap",
    "sap ecc": "sap",
    # Oracle
    "oracle": "oracle",
    "oracle fusion": "oracle",
    "fusion cloud": "oracle",
    # Microsoft
    "dynamics": "dynamics",
    "dynamics 365": "dynamics",
    "d365": "dynamics",
    "business central": "dynamics",
    # Others
    "netsuite": "netsuite",
    "odoo": "odoo",
    "infor": "infor",
    "workday": "workday",
}

# Deduplicated canonical vendor set for iteration. Exposed for
# consistency-checker tests and any future rule that needs the same list.
KNOWN_ERP_VENDORS: List[str] = sorted(set(_VENDOR_ALIASES.values()))


def _mentioned_vendors(text: str) -> Set[str]:
    """Return the set of canonical vendors mentioned in `text`.

    Substring matching, case-insensitive. A decision mentioning both SAP
    and Oracle returns {'sap', 'oracle'}. An empty or None text returns
    an empty set.

    Order-independent — this is the whole point of the function
    compared to the previous first-match-wins version. A caller can
    reason about the result without knowing the order of any list."""
    if not text:
        return set()
    lowered = text.lower()
    return {
        canonical for alias, canonical in _VENDOR_ALIASES.items()
        if alias in lowered
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def run_consistency_checks(session_id: str) -> List[Dict[str, Any]]:
    """Runs every check below against the current state of one project
    and records a ProjectIssue for each finding.

    Safe to call repeatedly: findings are filed with dedupe=True, so
    re-running against unchanged data does not produce duplicate issues.
    A previously-resolved issue will NOT be reopened by a subsequent
    run — the caller decides when a past finding has been addressed.

    Returns the list of findings produced by this run, each as
    {issue_type, severity, description, ...}. Note the return value is
    the findings *produced* (before dedupe), not the issues *created*:
    a finding that dedupe skips still appears in the return value, so
    callers see the current state of contradictions regardless of
    whether a matching open issue already existed.
    """
    findings: List[Dict[str, Any]] = []

    session = session_service.get_session(session_id)
    if not session:
        return findings

    db = SessionLocal()
    try:
        decisions = (
            db.query(SolutionDecision)
            .filter(SolutionDecision.session_id == session_id)
            .all()
        )
    finally:
        db.close()

    findings.extend(_check_erp_system_mismatch(session.erp_system, decisions))
    findings.extend(_check_conflicting_component_decisions(decisions))
    findings.extend(_check_customizations_missing_rationale(decisions))

    for f in findings:
        # dedupe=True skips filing when an open issue with the same
        # (session, issue_type, description) already exists. The
        # descriptions this module produces are deterministic, so the
        # match is exact and safe.
        create_issue(
            session_id=session_id,
            issue_type=f["issue_type"],
            description=f["description"],
            severity=f["severity"],
            related_object_type=f.get("related_object_type"),
            related_object_id=f.get("related_object_id"),
            dedupe=True,
        )

    # One structured line per run. Feeds the same diagnostic stream the
    # phase-completion callers will eventually log against.
    logger.info(
        "Consistency check completed",
        session_id=session_id,
        decisions_scanned=len(decisions),
        findings_count=len(findings),
        finding_types=sorted({f["issue_type"] for f in findings}),
    )

    return findings


# ---------------------------------------------------------------------------
# Rule 1 — ERP system mismatch
# ---------------------------------------------------------------------------
def _check_erp_system_mismatch(
    project_erp_system: str,
    decisions: List[SolutionDecision],
) -> List[Dict[str, Any]]:
    """A solution decision naming a vendor other than the project's own
    erp_system field is a contradiction — the project's erp_system is
    the declared ground truth.

    Order-independent and multi-vendor-aware:
      - Extract every vendor mentioned in the decision text.
      - If the project's vendor is among them, no finding. A decision
        that references the current vendor, even alongside others
        ("Compare SAP to Oracle"; "Our SAP solution beats Workday"),
        is not a contradiction of the current vendor.
      - Only when the project's vendor is NOT mentioned and at least
        one other vendor IS does the rule fire.

    This is stricter than a substring search but more precise. A
    decision is only flagged when it commits to a different platform
    without acknowledging the current one."""
    project_vendors = _mentioned_vendors(project_erp_system)
    if not project_vendors:
        # The configured erp_system field doesn't name a vendor we
        # recognize. Nothing to compare against — skipping is the
        # conservative choice.
        return []

    # If the project's erp_system names multiple vendors (unusual, but
    # possible if someone writes "SAP or Oracle" in the field), any of
    # them counts as "the current vendor" for exclusion purposes.
    findings: List[Dict[str, Any]] = []
    for d in decisions:
        text = f"{d.component or ''} {d.description or ''}"
        mentioned = _mentioned_vendors(text)
        if not mentioned:
            continue
        if mentioned & project_vendors:
            # The current vendor is acknowledged in the text.
            continue

        other_vendors = sorted(mentioned - project_vendors)
        findings.append({
            "issue_type": "contradiction",
            "severity": "high",
            "description": (
                f"Solution decision mentions "
                f"'{', '.join(v.upper() for v in other_vendors)}' but this "
                f"project's ERP system is '{project_erp_system}': "
                f"{d.description}"
            ),
            "related_object_type": "solution_decision",
            "related_object_id": d.id,
        })
    return findings


# ---------------------------------------------------------------------------
# Rule 2 — conflicting same-component decisions
# ---------------------------------------------------------------------------
def _check_conflicting_component_decisions(
    decisions: List[SolutionDecision],
) -> List[Dict[str, Any]]:
    """Two decisions of the same type, naming the same component, with
    different descriptions — a real conflict (two different things were
    decided about the same component), not a heuristic guess.

    Component comparison is case-insensitive and whitespace-stripped.
    Description comparison uses the stripped string as-is; case and
    whitespace differences between decisions are treated as the same
    description, since they don't represent different decisions."""
    by_key: Dict[tuple, List[SolutionDecision]] = {}
    for d in decisions:
        if not d.component:
            continue
        key = (d.decision_type, d.component.strip().lower())
        by_key.setdefault(key, []).append(d)

    findings: List[Dict[str, Any]] = []
    for (decision_type, _component_key), group in by_key.items():
        distinct_descriptions = {
            d.description.strip().lower()
            for d in group
            if d.description and d.description.strip()
        }
        if len(distinct_descriptions) > 1:
            original_component = group[0].component
            findings.append({
                "issue_type": "contradiction",
                "severity": "high",
                "description": (
                    f"Multiple conflicting '{decision_type}' decisions "
                    f"recorded for component '{original_component}': "
                    + " | ".join(sorted(distinct_descriptions))
                ),
                "related_object_type": "solution_decision",
                "related_object_id": group[0].id,
            })
    return findings


# ---------------------------------------------------------------------------
# Rule 3 — customizations missing a rationale
# ---------------------------------------------------------------------------
def _check_customizations_missing_rationale(
    decisions: List[SolutionDecision],
) -> List[Dict[str, Any]]:
    """A customization with no stated rationale is a completeness gap,
    not a contradiction — flagged as missing_info at medium severity.
    Matches the best-practice guidance seeded into every project's
    memory ("minimize customizations... ensure decisions have
    rationale").

    A rationale that is None, empty, or whitespace-only is treated as
    missing — a field that contains " " is not an answer."""
    findings: List[Dict[str, Any]] = []
    for d in decisions:
        if d.decision_type != "customization":
            continue
        if d.rationale and d.rationale.strip():
            continue
        findings.append({
            "issue_type": "missing_info",
            "severity": "medium",
            "description": (
                f"Customization has no stated rationale: {d.description}"
            ),
            "related_object_type": "solution_decision",
            "related_object_id": d.id,
        })
    return findings