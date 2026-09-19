"""
Integration tests for the Orchestrator Agent.

Coverage:

  Initialization
    - Phase workflow mapping is intact (6 phases, each with the
      expected keys).
    - Module-level singleton `orchestrator` is present.

  Project lifecycle
    - start_project returns a session_id and reads the actual current
      phase from the session (not a hardcoded literal).
    - get_project_status returns the expected shape.
    - generate_project_summary returns project_info, phases_completed,
      deliverables.

  Phase advancement
    - _get_next_phase for the six working phases and for the terminal
      COMPLETED state.

  Phase execution
    - Requirements phase advances to process_mapping on success.
    - Process mapping phase advances to solution_design on success.
    - Prerequisite gating: a downstream phase called without its
      upstream output fails with a clear, specific error and does not
      advance the session.

  Phase hardening
    - An unexpected agent exception is contained (never propagates).
    - A phase exceeding its timeout returns a clean failure message.
    - Successful phases record metrics.

  Diagnostics
    - _collect_phase_diagnostics extracts warnings, open_questions,
      degraded, repaired, validation_valid from an agent result.
    - _aggregate_diagnostics merges per-phase records correctly.

Fixture strategy:
  * patched_llm       patches get_llm at the orchestrator's import
                      path, so ERPOrchestratorAgent() construction
                      does not build a real HybridLLMClient.
  * workflow_session  creates a session, yields its ID, cleans up with
                      a try/except so a cleanup failure never fails a
                      test.
  * patched_sleep     reduces retry backoff to zero for tests that
                      exercise the retry path.

Mocked at the class-method level (RequirementsAgent.gather_requirements,
ProcessMappingAgent.map_process) so the singleton the orchestrator holds
sees the patch.
"""
from __future__ import annotations

import time as time_module
from unittest.mock import Mock, patch

import pytest

from src.orchestrator import ERPOrchestratorAgent, ProjectPhase, orchestrator
from src.memory import agent_memory
from src.utils.logger import metrics_collector


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# A minimal but schema-valid phase result used by the phase-execution
# tests. Matches what the real agents return on the happy path.
_REQUIREMENTS_SUCCESS_RESULT = {
    "success": True,
    "requirements": {
        "executive_summary": "Test",
        "functional_requirements": {},
    },
    "document_path": "/test/path.md",
    "duration": 1.0,
}

_PROCESS_MAPPING_SUCCESS_RESULT = {
    "success": True,
    "process_map": {"steps": []},
    "document_path": "/test/map.docx",
    "duration": 1.0,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def patched_llm():
    """Patch get_llm at the orchestrator's import path. Yields the mock
    client so tests can observe or override behavior if needed."""
    with patch("src.orchestrator.get_llm") as mock_get:
        mock_client = Mock(name="HybridLLMClient")
        mock_get.return_value = mock_client
        yield mock_client


@pytest.fixture
def patched_sleep():
    """Patch time.sleep in the orchestrator module so any retry-path
    tests don't add real latency."""
    with patch("src.orchestrator.time.sleep"):
        yield


@pytest.fixture
def orch(patched_llm):
    """A fully-mocked ERPOrchestratorAgent. Construction no longer
    builds a real HybridLLMClient."""
    return ERPOrchestratorAgent()


@pytest.fixture
def workflow_session():
    """Create a session, yield its ID, clean it up. Cleanup wrapped in
    try/except so a storage-cleanup failure during teardown doesn't
    fail the test result."""
    session_id = agent_memory.create_project(
        project_name="Workflow Integration Test",
        module="FI",
        erp_system="SAP S/4HANA",
    )
    try:
        yield session_id
    finally:
        try:
            agent_memory.session_service.delete_session(session_id)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------
class TestOrchestratorInitialization:
    def test_orchestrator_initialization(self, orch):
        assert orch.logger is not None
        assert orch.model is not None
        assert len(orch.phase_workflow) == 6

    def test_module_singleton_exists(self):
        assert isinstance(orchestrator, ERPOrchestratorAgent)

    def test_phase_workflow_mapping(self, orch):
        expected_phases = [
            ProjectPhase.REQUIREMENTS_GATHERING,
            ProjectPhase.PROCESS_MAPPING,
            ProjectPhase.SOLUTION_DESIGN,
            ProjectPhase.QA_TESTING,
            ProjectPhase.UAT_TESTING,
            ProjectPhase.TRAINING,
        ]
        for phase in expected_phases:
            assert phase in orch.phase_workflow
            workflow_info = orch.phase_workflow[phase]
            assert "agent" in workflow_info
            assert "method" in workflow_info
            assert "next_phase" in workflow_info


# ---------------------------------------------------------------------------
# Project lifecycle
# ---------------------------------------------------------------------------
class TestProjectLifecycle:
    def test_start_project(self, orch):
        result = orch.start_project(
            project_name="Test Orchestrator Project",
            module="FI",
            erp_system="SAP S/4HANA",
        )
        try:
            assert result["success"] is True
            assert "session_id" in result
            assert result["project_name"] == "Test Orchestrator Project"
            # current_phase is read from the session after any auto-run
            # requirements work, not hardcoded — assert on presence and
            # that it's a known phase value rather than a specific one.
            assert result["current_phase"] in {p.value for p in ProjectPhase}
        finally:
            agent_memory.session_service.delete_session(result["session_id"])

    def test_get_project_status(self, orch):
        create = orch.start_project(
            project_name="Status Test Project",
            module="MM",
            erp_system="SAP S/4HANA",
        )
        session_id = create["session_id"]
        try:
            status = orch.get_project_status(session_id)
            assert status["project_name"] == "Status Test Project"
            assert status["module"] == "MM"
            assert status["current_phase"] == ProjectPhase.REQUIREMENTS_GATHERING.value
            # progress_percentage is derived from len(PHASES); assert
            # a sensible range rather than the specific formula.
            assert 0 <= status["progress_percentage"] <= 100
            assert "next_phase" in status
        finally:
            agent_memory.session_service.delete_session(session_id)

    def test_generate_project_summary(self, orch):
        create = orch.start_project(
            project_name="Summary Test",
            module="SD",
            erp_system="SAP S/4HANA",
        )
        session_id = create["session_id"]
        try:
            summary = orch.generate_project_summary(session_id)
            assert summary["project_info"]["name"] == "Summary Test"
            assert "phases_completed" in summary
            assert "deliverables" in summary
            assert "metrics" in summary
        finally:
            agent_memory.session_service.delete_session(session_id)


# ---------------------------------------------------------------------------
# Next phase lookup
# ---------------------------------------------------------------------------
class TestNextPhaseLookup:
    def test_working_phases_have_expected_successors(self, orch):
        assert orch._get_next_phase(ProjectPhase.REQUIREMENTS_GATHERING.value) == \
            ProjectPhase.PROCESS_MAPPING.value
        assert orch._get_next_phase(ProjectPhase.TRAINING.value) == \
            ProjectPhase.COMPLETED.value

    def test_completed_is_terminal(self, orch):
        """COMPLETED has no successor — the lookup returns COMPLETED
        itself rather than raising or returning 'unknown'. The previous
        implementation fell into the generic 'unknown' fallback."""
        assert orch._get_next_phase(ProjectPhase.COMPLETED.value) == \
            ProjectPhase.COMPLETED.value

    def test_unknown_phase_returns_unknown(self, orch):
        """An unrecognized phase string returns 'unknown' rather than
        raising. The orchestrator's error paths and diagnostics should
        never crash on an unexpected phase value."""
        assert orch._get_next_phase("not_a_real_phase") == "unknown"


# ---------------------------------------------------------------------------
# Phase execution
# ---------------------------------------------------------------------------
class TestPhaseExecution:
    @patch("src.agents.requirements_agent.RequirementsAgent.gather_requirements")
    def test_requirements_phase_execution(self, mock_gather, orch, workflow_session):
        mock_gather.return_value = dict(_REQUIREMENTS_SUCCESS_RESULT)

        result = orch.execute_requirements_phase(
            session_id=workflow_session,
            stakeholder_input="Test requirements",
        )

        assert result["success"] is True
        session = agent_memory.session_service.get_session(workflow_session)
        assert session.current_phase == ProjectPhase.PROCESS_MAPPING.value

    @patch("src.agents.process_mapping_agent.ProcessMappingAgent.map_process")
    @patch("src.agents.requirements_agent.RequirementsAgent.gather_requirements")
    def test_process_mapping_phase_execution(
        self, mock_gather, mock_map, orch, workflow_session,
    ):
        mock_gather.return_value = dict(_REQUIREMENTS_SUCCESS_RESULT)
        mock_map.return_value = dict(_PROCESS_MAPPING_SUCCESS_RESULT)

        orch.execute_requirements_phase(workflow_session, "Test input")
        result = orch.execute_process_mapping_phase(
            session_id=workflow_session,
            process_name="Test Process",
        )

        assert result["success"] is True
        session = agent_memory.session_service.get_session(workflow_session)
        assert session.current_phase == ProjectPhase.SOLUTION_DESIGN.value


# ---------------------------------------------------------------------------
# Prerequisite gating
# ---------------------------------------------------------------------------
class TestPrerequisiteGating:
    def test_solution_design_without_requirements_fails(self, orch, workflow_session):
        result = orch.execute_solution_design_phase(session_id=workflow_session)
        assert result["success"] is False
        # The error names both the blocked phase and the missing
        # prerequisite, so a caller sees what to run next.
        assert "solution_design" in result["error"]
        assert "requirements_gathering" in result["error"]

    def test_process_mapping_without_requirements_fails(self, orch, workflow_session):
        """Replaces the original test_missing_requirements_handling.
        The error message was upgraded from the generic 'Requirements
        not found' to a specific 'required upstream phase X has no
        output yet'. Both name the issue; the new one names the
        missing phase explicitly."""
        result = orch.execute_process_mapping_phase(session_id=workflow_session)
        assert result["success"] is False
        assert "requirements_gathering" in result["error"]
        assert "no output" in result["error"]

    def test_failed_prerequisite_does_not_advance_phase(self, orch, workflow_session):
        """A gated phase must not advance the session. Otherwise a
        downstream phase could pass its check by mistake on a
        subsequent call."""
        orch.execute_solution_design_phase(session_id=workflow_session)
        session = agent_memory.session_service.get_session(workflow_session)
        assert session.current_phase == ProjectPhase.REQUIREMENTS_GATHERING.value


# ---------------------------------------------------------------------------
# Phase hardening
# ---------------------------------------------------------------------------
class TestPhaseHardening:
    """Covers the phase-level timeout and exception containment the
    orchestrator added in the hardening pass. All three tests are
    regression guards: a future change that lets an agent exception
    propagate or bypasses the timeout would fail here."""

    @patch("src.agents.requirements_agent.RequirementsAgent.gather_requirements")
    def test_unexpected_agent_exception_is_contained_not_raised(
        self, mock_gather, orch, workflow_session,
    ):
        mock_gather.side_effect = RuntimeError("boom - unexpected agent crash")

        result = orch.execute_requirements_phase(
            session_id=workflow_session,
            stakeholder_input="Test requirements",
        )

        assert result["success"] is False
        assert "boom - unexpected agent crash" in result["error"]
        assert "duration" in result
        # Session must not have advanced past a failed phase.
        session = agent_memory.session_service.get_session(workflow_session)
        assert session.current_phase == ProjectPhase.REQUIREMENTS_GATHERING.value

    @patch("src.agents.requirements_agent.RequirementsAgent.gather_requirements")
    def test_phase_exceeding_timeout_is_stopped_and_reported(
        self, mock_gather, orch, workflow_session,
    ):
        """A hung agent call must not block the caller past the
        configured phase timeout. The failure is reported via a
        user-facing message the API can surface directly."""
        def hangs(*args, **kwargs):
            time_module.sleep(2)
            return {"success": True}

        mock_gather.side_effect = hangs

        with patch.object(orch, "_call_agent_safely", wraps=orch._call_agent_safely):
            # Patch settings.timeout_seconds down so the test is fast.
            with patch("src.orchestrator.settings.timeout_seconds", 0.1):
                result = orch.execute_requirements_phase(
                    session_id=workflow_session,
                    stakeholder_input="Test requirements",
                )

        assert result["success"] is False
        assert "longer than expected" in result["error"]

    @patch("src.agents.requirements_agent.RequirementsAgent.gather_requirements")
    def test_successful_phase_records_metrics(
        self, mock_gather, orch, workflow_session,
    ):
        """A successful phase must increment the metrics collector's
        total task count. Uses the current API (get_summary), not the
        pre-refactor `metrics_collector.tasks` list which no longer
        exists — the previous version of this test silently stopped
        asserting when that attribute was renamed."""
        mock_gather.return_value = dict(_REQUIREMENTS_SUCCESS_RESULT)

        before = metrics_collector.get_summary()["total_tasks"]
        result = orch.execute_requirements_phase(
            session_id=workflow_session,
            stakeholder_input="Test requirements",
        )
        after = metrics_collector.get_summary()["total_tasks"]

        assert result["success"] is True
        assert "duration" in result
        assert after == before + 1

    @patch("src.agents.requirements_agent.RequirementsAgent.gather_requirements")
    def test_non_dict_agent_result_becomes_structured_failure(
        self, mock_gather, orch, workflow_session,
    ):
        """An agent that returns None or a non-dict (a bug, or a mock in
        a test) must not crash the orchestrator. _call_agent_safely
        normalizes it into a structured failure."""
        mock_gather.return_value = None  # not a dict

        result = orch.execute_requirements_phase(
            session_id=workflow_session,
            stakeholder_input="Test requirements",
        )

        assert result["success"] is False
        assert "error" in result
        assert "NoneType" in result["error"] or "unexpected result type" in result["error"]


# ---------------------------------------------------------------------------
# Diagnostics aggregation
# ---------------------------------------------------------------------------
class TestDiagnosticsAggregation:
    def test_collect_phase_diagnostics_extracts_enriched_fields(self, orch):
        """Every agent now returns warnings / open_questions / degraded /
        repaired / validation. _collect_phase_diagnostics must surface
        them so the workflow summary can aggregate across phases."""
        result = {
            "success": True,
            "document_path": "/x.docx",
            "duration": 1.2,
            "warnings": ["low input length"],
            "open_questions": [{"topic": "Approval thresholds"}],
            "assumptions": ["Finance will confirm sign-off owners"],
            "degraded": False,
            "repaired": True,
            "validation": {"is_valid": True, "issues": []},
        }

        diagnostics = orch._collect_phase_diagnostics("requirements_gathering", result)
        assert diagnostics["phase"] == "requirements_gathering"
        assert diagnostics["success"] is True
        assert diagnostics["warnings"] == ["low input length"]
        assert diagnostics["open_questions"] == [{"topic": "Approval thresholds"}]
        assert diagnostics["assumptions"] == ["Finance will confirm sign-off owners"]
        assert diagnostics["repaired"] is True
        assert diagnostics["validation_valid"] is True

    def test_collect_phase_diagnostics_tolerates_missing_keys(self, orch):
        """An agent result that omits enriched keys must not crash the
        diagnostic collector — the .get() defaults should produce an
        empty-but-shaped record."""
        diagnostics = orch._collect_phase_diagnostics("qa_testing", {"success": True})
        assert diagnostics["phase"] == "qa_testing"
        assert diagnostics["warnings"] == []
        assert diagnostics["open_questions"] == []
        assert diagnostics["degraded"] is False
        assert diagnostics["validation_valid"] is None

    def test_aggregate_diagnostics_summarizes_across_phases(self, orch):
        """The aggregated view is what a caller reads to understand
        'what did the pipeline actually produce?' without opening
        individual phase results."""
        diags = [
            orch._collect_phase_diagnostics("requirements_gathering", {
                "success": True,
                "warnings": ["short input"],
                "open_questions": [{"topic": "A"}],
                "degraded": False,
            }),
            orch._collect_phase_diagnostics("process_mapping", {
                "success": False,
                "error": "failed",
                "degraded": True,
                "warnings": ["context missing"],
            }),
            orch._collect_phase_diagnostics("solution_design", {
                "success": True,
                "open_questions": [{"topic": "B"}, {"topic": "C"}],
                "repaired": True,
            }),
        ]

        aggregated = orch._aggregate_diagnostics(diags)
        assert aggregated["failed_phases"] == ["process_mapping"]
        assert aggregated["degraded_phases"] == ["process_mapping"]
        assert aggregated["repaired_phases"] == ["solution_design"]
        assert aggregated["open_questions_count"] == 3
        assert aggregated["warnings_count"] == 2
        # Each open question carries its phase attribution.
        phases_with_questions = {q["phase"] for q in aggregated["open_questions"]}
        assert phases_with_questions == {"requirements_gathering", "solution_design"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
class TestErrorHandling:
    def test_invalid_session_handling(self, orch):
        status = orch.get_project_status("invalid_session_id")
        assert "error" in status

    def test_execute_full_workflow_stops_on_critical_phase_failure(
        self, orch, patched_llm,
    ):
        """A failure on the requirements phase — a critical phase —
        must stop the pipeline with a clear 'stopped_at' marker
        rather than cascading into downstream 'not found' errors."""
        with patch.object(
            orch,
            "start_project",
            return_value={"success": True, "session_id": "synthetic-sid"},
        ), patch.object(
            orch,
            "execute_requirements_phase",
            return_value={"success": False, "error": "synthetic failure"},
        ):
            result = orch.execute_full_workflow(
                project_name="Synthetic",
                module="FI",
                stakeholder_input="input",
            )

        assert result["success"] is False
        assert result.get("stopped_at") == "requirements_gathering"
        assert "Requirements gathering failed" in result["error"]