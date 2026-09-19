"""
Tests for src/services/consistency_checker.run_consistency_checks.

The checker runs deterministic cross-document consistency rules (no LLM
calls) and records findings as ProjectIssue rows. Three rules are
exercised here:

  1. ERP mismatch
       An `erp_selection` decision naming a vendor different from the
       session's configured erp_system produces a `contradiction`
       finding.

  2. Conflicting same-component decisions
       Two decisions of the same decision_type that reference the same
       component with different descriptions produce a `contradiction`
       finding.

  3. Missing customization rationale
       A `customization` decision with no rationale produces a
       `missing_info` finding.

Coverage note — idempotency:
  The most consequential test here is
  TestIdempotency.test_running_twice_produces_one_issue_not_two. If the
  checker files a new issue on every run, wiring it into phase
  completion (which the API's docstring names as a future step) would
  flood the issue list. The project_intelligence layer exposes
  create_issue(dedupe=True) for exactly this; the test asserts the
  checker uses it (or some equivalent).

Coverage note — rule semantics:
  Several tests pin the exact matching behavior that the checker
  currently has, particularly around the ERP vendor match (case
  handling, multiple vendors in one decision, current vendor alongside
  others). If any of those fails against the current implementation,
  it means the current behavior is a surprise, and either the test or
  the checker should change — but not silently.

Fixtures:
  * project  creates a session configured for SAP S/4HANA, yields its
             id, and cleans up on teardown with a guarded delete.

DB helper:
  _add_decision  inserts a SolutionDecision row directly. Direct
                 insertion (rather than going through the sync layer)
                 keeps the tests focused on the checker's rules without
                 pulling in trace-link side effects.
"""
from __future__ import annotations

import uuid

import pytest

from src.db.base import SessionLocal
from src.db.models import SolutionDecision
from src.memory import agent_memory, session_service
from src.services.consistency_checker import run_consistency_checks
from src.services.project_intelligence import get_issues


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------
@pytest.fixture
def project():
    """A session configured for SAP S/4HANA. Cleanup is wrapped in
    try/except so a storage-cleanup failure during teardown never
    fails the test result."""
    session_id = agent_memory.create_project(
        "Consistency Test", "FI", erp_system="SAP S/4HANA",
    )
    try:
        yield session_id
    finally:
        try:
            session_service.delete_session(session_id)
        except Exception:  # noqa: BLE001
            pass


def _add_decision(
    session_id: str,
    decision_type: str,
    component: str,
    description: str,
    rationale: str | None = None,
) -> str:
    """Insert a SolutionDecision row and return its id.

    Session lifecycle is guarded by try/finally so a failed commit
    doesn't leak the session. is_current is set explicitly rather than
    relying on the ORM default — a schema change to the default would
    otherwise silently make these tests exercise the wrong rows."""
    decision_id = uuid.uuid4().hex
    db = SessionLocal()
    try:
        db.add(SolutionDecision(
            id=decision_id,
            session_id=session_id,
            lineage_id=uuid.uuid4().hex,
            version=1,
            is_current=True,
            decision_type=decision_type,
            component=component,
            description=description,
            rationale=rationale,
        ))
        db.commit()
        return decision_id
    finally:
        db.close()


def _open_issues(session_id: str) -> list:
    return get_issues(session_id, status=None)


# ===========================================================================
# Rule 1 — ERP mismatch
# ===========================================================================
class TestErpSystemMismatch:
    def test_flags_a_decision_naming_a_different_erp_vendor(self, project):
        _add_decision(
            project, "erp_selection", "core",
            "Recommend Oracle Fusion for this project",
        )

        findings = run_consistency_checks(project)

        contradictions = [f for f in findings if f["issue_type"] == "contradiction"]
        assert len(contradictions) == 1
        assert "ORACLE" in contradictions[0]["description"]
        assert "SAP S/4HANA" in contradictions[0]["description"]

    def test_flags_lowercase_vendor_mention(self, project):
        """The vendor match is case-insensitive — 'oracle' in the input
        is the same as 'Oracle'. Without this, a decision written in
        lowercase would slip past the rule."""
        _add_decision(
            project, "erp_selection", "core",
            "recommend oracle fusion as the platform",
        )
        findings = run_consistency_checks(project)
        assert any(f["issue_type"] == "contradiction" for f in findings)

    def test_does_not_flag_a_decision_matching_the_project_erp_system(self, project):
        _add_decision(
            project, "erp_selection", "core",
            "Confirm SAP S/4HANA as target platform",
        )
        findings = run_consistency_checks(project)
        assert findings == []

    def test_does_not_flag_decisions_with_no_vendor_mentioned(self, project):
        _add_decision(
            project, "module_config", "GL",
            "Enable multi-currency ledger",
        )
        findings = run_consistency_checks(project)
        assert findings == []

    def test_decision_mentioning_current_vendor_alongside_others_is_not_flagged(
        self, project,
    ):
        """A decision that names the current vendor among others is a
        comparison, not a contradiction. 'Our SAP solution beats
        Oracle and Workday' is a legitimate statement on an
        SAP-configured session. Flagging it would be a false positive.

        If the current implementation flags this, it's a bug: the rule
        should fire only when the decision recommends a *different*
        platform without acknowledging the current one."""
        _add_decision(
            project, "erp_selection", "core",
            "Our SAP S/4HANA solution beats Oracle and Workday on TCO",
        )
        findings = run_consistency_checks(project)
        contradictions = [f for f in findings if f["issue_type"] == "contradiction"]
        assert contradictions == [], (
            f"a decision naming the current vendor alongside others was "
            f"flagged as a contradiction: {contradictions}"
        )

    def test_skips_decisions_with_empty_description(self, project):
        """An empty description has no vendor to match against. The
        checker must not crash and must not flag it."""
        _add_decision(project, "erp_selection", "core", "")
        findings = run_consistency_checks(project)
        # No contradiction (nothing to contradict); no crash.
        assert not any(f["issue_type"] == "contradiction" for f in findings)

    def test_each_conflicting_decision_produces_its_own_finding(self, project):
        """Two decisions each naming a different wrong vendor are two
        distinct problems and should produce two findings, not one
        aggregate finding that hides the second."""
        _add_decision(
            project, "erp_selection", "core_a",
            "Recommend Oracle Fusion",
        )
        _add_decision(
            project, "erp_selection", "core_b",
            "Recommend Workday for HCM",
        )
        findings = run_consistency_checks(project)
        contradictions = [f for f in findings if f["issue_type"] == "contradiction"]
        assert len(contradictions) == 2


# ===========================================================================
# Rule 2 — Conflicting same-component decisions
# ===========================================================================
class TestConflictingComponentDecisions:
    def test_flags_two_different_decisions_for_the_same_component(self, project):
        _add_decision(project, "module_config", "GL", "Use 10-segment chart of accounts")
        _add_decision(project, "module_config", "GL", "Use 12-segment chart of accounts")

        findings = run_consistency_checks(project)

        conflicts = [f for f in findings if "conflicting" in f["description"].lower()]
        assert len(conflicts) == 1
        assert "GL" in conflicts[0]["description"]

    def test_does_not_flag_identical_repeated_decisions(self, project):
        _add_decision(project, "module_config", "GL", "Use 12-segment chart of accounts")
        _add_decision(project, "module_config", "GL", "Use 12-segment chart of accounts")
        findings = run_consistency_checks(project)
        assert not any("conflicting" in f["description"].lower() for f in findings)

    def test_does_not_flag_descriptions_that_differ_only_in_case(self, project):
        """'Use 12-segment chart' and 'use 12-segment chart' describe
        the same decision. The comparison should be case-insensitive;
        flagging them would be a false positive on a common data-entry
        variance."""
        _add_decision(project, "module_config", "GL", "Use 12-segment chart of accounts")
        _add_decision(project, "module_config", "GL", "use 12-SEGMENT chart of accounts")
        findings = run_consistency_checks(project)
        assert not any("conflicting" in f["description"].lower() for f in findings), (
            "case-only differences should not be flagged as conflicts"
        )

    def test_does_not_flag_descriptions_that_differ_only_in_whitespace(self, project):
        """Trailing/leading whitespace differences are a common
        copy-paste artifact; they don't represent different decisions."""
        _add_decision(project, "module_config", "GL", "Use 12-segment chart of accounts")
        _add_decision(project, "module_config", "GL", "  Use 12-segment chart of accounts  ")
        findings = run_consistency_checks(project)
        assert not any("conflicting" in f["description"].lower() for f in findings)

    def test_does_not_flag_same_component_across_different_decision_types(self, project):
        """Same component name, different decision_type — not a real
        conflict (e.g. a config decision and a customization decision
        can both legitimately reference 'GL')."""
        _add_decision(project, "module_config", "GL", "Enable multi-currency")
        _add_decision(
            project, "customization", "GL",
            "Custom validation rule",
            rationale="Client requirement",
        )
        findings = run_consistency_checks(project)
        assert not any("conflicting" in f["description"].lower() for f in findings)

    def test_three_way_conflict_is_detected(self, project):
        """Three decisions on the same component with three different
        descriptions is still a conflict — the rule fires on the group,
        not just on a pairwise comparison. At least one finding is
        expected."""
        _add_decision(project, "module_config", "GL", "Use 8-segment chart of accounts")
        _add_decision(project, "module_config", "GL", "Use 10-segment chart of accounts")
        _add_decision(project, "module_config", "GL", "Use 12-segment chart of accounts")

        findings = run_consistency_checks(project)
        assert any("conflicting" in f["description"].lower() for f in findings), (
            "three different decisions on the same component were not "
            "flagged as a conflict"
        )

    def test_two_conflicting_groups_produce_two_findings(self, project):
        """Conflicts on two different components are two distinct
        problems and should be reported separately."""
        _add_decision(project, "module_config", "GL", "Use 10-segment chart")
        _add_decision(project, "module_config", "GL", "Use 12-segment chart")
        _add_decision(project, "module_config", "AR", "Net 30 terms")
        _add_decision(project, "module_config", "AR", "Net 45 terms")

        findings = run_consistency_checks(project)
        conflicts = [f for f in findings if "conflicting" in f["description"].lower()]
        assert len(conflicts) == 2


# ===========================================================================
# Rule 3 — Customization rationale
# ===========================================================================
class TestCustomizationRationale:
    def test_flags_customization_with_no_rationale(self, project):
        _add_decision(project, "customization", "PO Approval", "Add custom approval matrix")
        findings = run_consistency_checks(project)
        missing_info = [f for f in findings if f["issue_type"] == "missing_info"]
        assert len(missing_info) == 1

    def test_flags_customization_with_empty_string_rationale(self, project):
        """A rationale field set to an empty string is not a rationale.
        The rule should treat '' the same as None."""
        _add_decision(
            project, "customization", "PO Approval",
            "Add custom approval matrix", rationale="",
        )
        findings = run_consistency_checks(project)
        assert any(f["issue_type"] == "missing_info" for f in findings)

    def test_flags_customization_with_whitespace_only_rationale(self, project):
        """'   ' is not a rationale either. If the rule only checks for
        None, this test fails and the fix is to strip before comparing."""
        _add_decision(
            project, "customization", "PO Approval",
            "Add custom approval matrix", rationale="     ",
        )
        findings = run_consistency_checks(project)
        assert any(f["issue_type"] == "missing_info" for f in findings), (
            "whitespace-only rationale should be treated as missing"
        )

    def test_does_not_flag_customization_with_rationale(self, project):
        _add_decision(
            project, "customization", "PO Approval",
            "Add custom approval matrix",
            rationale="Client's existing approval policy requires 3 sign-off levels",
        )
        findings = run_consistency_checks(project)
        assert not any(f["issue_type"] == "missing_info" for f in findings)

    def test_does_not_flag_non_customization_decisions_for_missing_rationale(self, project):
        _add_decision(project, "module_config", "GL", "Enable multi-currency ledger")
        findings = run_consistency_checks(project)
        assert not any(f["issue_type"] == "missing_info" for f in findings)

    def test_flags_each_customization_without_rationale(self, project):
        """Two unjustified customizations are two separate missing-info
        findings — the reviewer needs to chase both."""
        _add_decision(project, "customization", "PO Approval", "Custom approval matrix")
        _add_decision(project, "customization", "Vendor Form", "Custom vendor screen")
        findings = run_consistency_checks(project)
        missing = [f for f in findings if f["issue_type"] == "missing_info"]
        assert len(missing) == 2


# ===========================================================================
# Idempotency and persistence
# ===========================================================================
class TestIdempotency:
    """The most consequential class in this file. Without dedupe, wiring
    the checker into phase completion (per the API docstring) would
    flood the issue list on every run."""

    def test_running_twice_produces_one_issue_not_two(self, project):
        _add_decision(
            project, "erp_selection", "core",
            "Recommend Oracle Fusion for this project",
        )

        run_consistency_checks(project)
        run_consistency_checks(project)

        issues = _open_issues(project)
        contradictions = [i for i in issues if i["issue_type"] == "contradiction"]
        assert len(contradictions) == 1, (
            f"running the checker twice filed {len(contradictions)} "
            "contradiction issues; a duplicate-filing bug would flood "
            "the issue list once this is wired into phase completion"
        )

    def test_findings_are_persisted_as_real_issues(self, project):
        _add_decision(
            project, "erp_selection", "core",
            "Recommend Oracle Fusion for this project",
        )
        run_consistency_checks(project)

        issues = _open_issues(project)
        assert any(i["issue_type"] == "contradiction" for i in issues)

    def test_returned_findings_count_matches_persisted_issues(self, project):
        """The endpoint returns findings_count from the return value
        and separately relies on the issues being queryable. The two
        must agree, or the SPA's "N findings, view issues" flow is
        inconsistent."""
        _add_decision(
            project, "erp_selection", "core",
            "Recommend Oracle Fusion for this project",
        )
        findings = run_consistency_checks(project)

        issues = _open_issues(project)
        # Only this rule produced a finding, so counts should match.
        assert len(issues) == len(findings)


# ===========================================================================
# Empty / edge inputs
# ===========================================================================
def test_returns_empty_for_a_project_with_no_decisions_or_requirements(project):
    findings = run_consistency_checks(project)
    assert findings == []
    # And no issues were filed.
    assert _open_issues(project) == []


def test_returns_empty_for_a_nonexistent_session():
    """A nonexistent session returns [] rather than raising. In the API
    path this is unreachable because _get_owned_session returns 404
    first, but the checker is defensive against a direct caller."""
    findings = run_consistency_checks("prj_does_not_exist")
    assert findings == []


def test_finding_shape_is_stable(project):
    """Each finding carries at least issue_type and description. The
    API returns findings as-is; if a consumer starts reading a new
    field (severity, related_object_type), the finding dict must
    already have it, and this test pins the shape."""
    _add_decision(
        project, "erp_selection", "core",
        "Recommend Oracle Fusion for this project",
    )
    findings = run_consistency_checks(project)
    assert findings, "expected at least one finding"
    finding = findings[0]
    assert "issue_type" in finding
    assert "description" in finding
    # Description is non-empty — an empty description would be useless
    # in the issue list.
    assert finding["description"].strip()