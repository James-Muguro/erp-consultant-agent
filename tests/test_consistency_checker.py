import pytest

from src.db.base import SessionLocal
from src.db.models import SolutionDecision
from src.memory import agent_memory
from src.services.consistency_checker import run_consistency_checks
from src.services.project_intelligence import get_issues


@pytest.fixture
def project():
    session_id = agent_memory.create_project("Consistency Test", "FI", erp_system="SAP S/4HANA")
    yield session_id
    from src.memory import session_service
    session_service.delete_session(session_id)


def _add_decision(session_id, decision_type, component, description, rationale=None):
    db = SessionLocal()
    try:
        import uuid
        d = SolutionDecision(
            id=uuid.uuid4().hex,
            session_id=session_id,
            lineage_id=uuid.uuid4().hex,
            decision_type=decision_type,
            component=component,
            description=description,
            rationale=rationale,
        )
        db.add(d)
        db.commit()
        return d.id
    finally:
        db.close()


class TestErpSystemMismatch:
    def test_flags_a_decision_naming_a_different_erp_vendor(self, project):
        _add_decision(project, "erp_selection", "core", "Recommend Oracle Fusion for this project")

        findings = run_consistency_checks(project)

        contradictions = [f for f in findings if f["issue_type"] == "contradiction"]
        assert len(contradictions) == 1
        assert "ORACLE" in contradictions[0]["description"]
        assert "SAP S/4HANA" in contradictions[0]["description"]

    def test_does_not_flag_a_decision_matching_the_project_erp_system(self, project):
        _add_decision(project, "erp_selection", "core", "Confirm SAP S/4HANA as target platform")

        findings = run_consistency_checks(project)

        assert findings == []

    def test_does_not_flag_decisions_with_no_vendor_mentioned(self, project):
        _add_decision(project, "module_config", "GL", "Enable multi-currency ledger")

        findings = run_consistency_checks(project)

        assert findings == []

    def test_findings_are_persisted_as_real_issues(self, project):
        _add_decision(project, "erp_selection", "core", "Recommend Oracle Fusion for this project")
        run_consistency_checks(project)

        issues = get_issues(project, status=None)
        assert any(i["issue_type"] == "contradiction" for i in issues)


class TestConflictingComponentDecisions:
    def test_flags_two_different_decisions_for_the_same_component(self, project):
        _add_decision(project, "module_config", "GL", "Use 10-segment chart of accounts")
        _add_decision(project, "module_config", "GL", "Use 12-segment chart of accounts")

        findings = run_consistency_checks(project)

        contradictions = [f for f in findings if "conflicting" in f["description"].lower()]
        assert len(contradictions) == 1
        assert "GL" in contradictions[0]["description"]

    def test_does_not_flag_identical_repeated_decisions(self, project):
        _add_decision(project, "module_config", "GL", "Use 12-segment chart of accounts")
        _add_decision(project, "module_config", "GL", "Use 12-segment chart of accounts")

        findings = run_consistency_checks(project)

        assert not any("conflicting" in f["description"].lower() for f in findings)

    def test_does_not_flag_same_component_across_different_decision_types(self, project):
        """Same component name, different decision_type - not a real
        conflict (e.g. a config decision and a customization decision
        can both legitimately reference 'GL')."""
        _add_decision(project, "module_config", "GL", "Enable multi-currency")
        _add_decision(project, "customization", "GL", "Custom validation rule", rationale="Client requirement")

        findings = run_consistency_checks(project)

        assert not any("conflicting" in f["description"].lower() for f in findings)


class TestCustomizationRationale:
    def test_flags_customization_with_no_rationale(self, project):
        _add_decision(project, "customization", "PO Approval", "Add custom approval matrix")

        findings = run_consistency_checks(project)

        missing_info = [f for f in findings if f["issue_type"] == "missing_info"]
        assert len(missing_info) == 1

    def test_does_not_flag_customization_with_rationale(self, project):
        _add_decision(project, "customization", "PO Approval", "Add custom approval matrix",
                       rationale="Client's existing approval policy requires 3 sign-off levels")

        findings = run_consistency_checks(project)

        assert not any(f["issue_type"] == "missing_info" for f in findings)

    def test_does_not_flag_non_customization_decisions_for_missing_rationale(self, project):
        _add_decision(project, "module_config", "GL", "Enable multi-currency ledger")

        findings = run_consistency_checks(project)

        assert not any(f["issue_type"] == "missing_info" for f in findings)


def test_returns_empty_for_a_project_with_no_decisions_or_requirements(project):
    findings = run_consistency_checks(project)
    assert findings == []


def test_returns_empty_for_a_nonexistent_session():
    findings = run_consistency_checks("prj_does_not_exist")
    assert findings == []
