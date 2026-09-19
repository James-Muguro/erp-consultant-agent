"""
Unit tests for QA and UAT Testing Agents.

Coverage:

  Happy path
    - Schema-valid LLM output is parsed via the structured path.
    - The UAT regression guard from Stage 1b: real LLM output is used,
      not a fabricated placeholder.
    - test_data is flattened on the return path (schema list -> dict).

  Hard-failure modes (new in the improved agents)
    - Zero usable test cases triggers a hard failure with success=False
      rather than falling back to fabricated generic test cases. This is
      the current regression guard for the class of bug Stage 1b fixed -
      stronger than the original, because the fallback path no longer
      exists at all.

  Input pre-flight
    - Empty module -> success=False, no LLM call.
    - Empty solution_design / business_processes -> success=False.
    - Thin solution_design -> success=True with a warning.

  Return payload
    - warnings, validation, degraded, repaired present on every result.
    - UAT-specific fields (user_role, business_process, acceptance_criteria)
      survive the return path.

Fixtures mock:
  * get_llm                            - no real provider client construction.
  * sync_test_cases_from_structured    - no DB access in unit tests.
  * generate_test_case_document        - no .docx files written to disk.
  * time.sleep                         - retry paths don't add real latency.
"""
from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest

from src.agents.testing_agents import QATestingAgent, UATTestingAgent
from src.memory import agent_memory


# ---------------------------------------------------------------------------
# Sample responses
# ---------------------------------------------------------------------------
def _sample_test_cases_json(*, include_uat_fields: bool = False) -> str:
    """Schema-conformant response matching TestCasesDocument.

    When include_uat_fields is True, adds user_role / business_process /
    acceptance_criteria so UAT-specific behavior can be tested without
    a second constant."""
    test_case: dict = {
        "id": "TC-001",
        "scenario": "Create and approve Purchase Order",
        "priority": "High",
        "type": "Functional",
        "objective": "Verify PO creation and approval flow.",
        "preconditions": ["User has Procurement role"],
        "steps": ["Navigate to Purchase Orders", "Create new PO", "Submit for approval"],
        "test_data": [{"key": "vendor_id", "value": "VEND-001"}],
        "expected_result": "PO status changes to Approved.",
    }
    if include_uat_fields:
        test_case["user_role"] = "Procurement Buyer"
        test_case["business_process"] = "Procure to Pay"
        test_case["acceptance_criteria"] = (
            "Finance can confirm the PO matches the approved requisition."
        )
    return json.dumps({"test_cases": [test_case]})


SAMPLE_TEST_CASES_JSON = _sample_test_cases_json()
SAMPLE_UAT_JSON = _sample_test_cases_json(include_uat_fields=True)

# A response with zero test cases. Schema-valid (the list can be empty),
# so schema validation succeeds and the agent's own hard-failure check
# is what produces the failure. This is the path we want to test.
EMPTY_TEST_CASES_JSON = json.dumps({"test_cases": []})

# Sufficiently long to pass MIN_STAKEHOLDER_ANSWER_LENGTH-style checks
# in the shared validators (no such check exists on the QA/UAT agents
# today, but keeping it non-trivial makes the intent obvious).
VALID_SOLUTION_DESIGN = {
    "executive_summary": "PO workflow automation.",
    "configurations": [
        {"component": "Release strategy", "description": "Two-step approval"},
    ],
    "integrations": [
        {"name": "Vendor sync", "source": "MDM", "target": "SAP"},
    ],
}

VALID_BUSINESS_PROCESSES = {
    "Procure to Pay": {
        "structured": {
            "steps": [{"name": "Create PO"}, {"name": "Approve PO"}],
            "roles": ["Procurement Buyer", "Approver"],
        }
    }
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def test_session_id():
    """Create a session, yield its ID, clean up afterwards. Cleanup is
    wrapped in try/except so a storage-cleanup failure during teardown
    never fails the test result."""
    session_id = agent_memory.create_project(
        project_name="Testing Agent Test",
        module="MM",
        erp_system="SAP S/4HANA",
    )
    try:
        yield session_id
    finally:
        try:
            agent_memory.session_service.delete_session(session_id)
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture
def patched_llm():
    """Patch get_llm at the module path the testing agents import it
    from. Yields the mock so tests can set generate_content's
    return_value / side_effect."""
    with patch("src.agents.testing_agents.get_llm") as mock_get:
        mock_model = Mock(name="HybridLLMClient")
        mock_get.return_value = mock_model
        yield mock_model


@pytest.fixture
def patched_side_effects():
    """Patch DB sync and document generation so unit tests don't touch
    the database or write .docx files."""
    with patch(
        "src.services.project_intelligence.sync_test_cases_from_structured"
    ), patch(
        "src.tools.doc_generator.generate_test_case_document",
        return_value="/tmp/test_cases.docx",
    ):
        yield


@pytest.fixture
def patched_sleep():
    """Patch time.sleep so retry paths don't add real latency. The
    testing agents use RETRY_BACKOFF_SECONDS = (1.0, 3.0, 7.0); a full
    retry sequence would otherwise sleep ~11s."""
    with patch("src.agents.testing_agents.time.sleep"):
        yield


@pytest.fixture
def qa_agent(patched_llm, patched_side_effects):
    """A QATestingAgent with mocked LLM and side effects. Default LLM
    response is a valid one-test-case document; tests override for
    failure paths."""
    response = Mock()
    response.text = SAMPLE_TEST_CASES_JSON
    patched_llm.generate_content.return_value = response
    return QATestingAgent()


@pytest.fixture
def uat_agent(patched_llm, patched_side_effects):
    """A UATTestingAgent with mocked LLM and side effects. Default LLM
    response includes UAT-specific fields (user_role, business_process,
    acceptance_criteria)."""
    response = Mock()
    response.text = SAMPLE_UAT_JSON
    patched_llm.generate_content.return_value = response
    return UATTestingAgent()


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------
class TestAgentInitialization:
    def test_qa_agent_initializes(self, patched_llm, patched_side_effects):
        agent = QATestingAgent()
        assert agent.config is not None
        assert agent.logger is not None
        assert agent.model is not None

    def test_uat_agent_initializes(self, patched_llm, patched_side_effects):
        agent = UATTestingAgent()
        assert agent.config is not None
        assert agent.logger is not None
        assert agent.model is not None

    def test_module_singletons_exist(self):
        from src.agents.testing_agents import qa_testing_agent, uat_testing_agent
        assert isinstance(qa_testing_agent, QATestingAgent)
        assert isinstance(uat_testing_agent, UATTestingAgent)


# ---------------------------------------------------------------------------
# QA happy path (preserved from the original test)
# ---------------------------------------------------------------------------
class TestQAHappyPath:
    def test_qa_generate_test_cases_success(self, qa_agent, test_session_id):
        result = qa_agent.generate_test_cases(
            session_id=test_session_id,
            solution_design=VALID_SOLUTION_DESIGN,
            module="MM",
            scope="comprehensive",
        )

        assert result["success"] is True
        assert len(result["test_cases"]) == 1
        assert result["test_cases"][0]["scenario"] == "Create and approve Purchase Order"
        # test_data is flattened from the schema's list form to a dict
        # by TestCase.to_legacy_dict(). The schema-internal shape is
        # [{"key": ..., "value": ...}]; the return shape is {key: value}.
        assert result["test_cases"][0]["test_data"] == {"vendor_id": "VEND-001"}


# ---------------------------------------------------------------------------
# UAT happy path (regression guard from the original test)
# ---------------------------------------------------------------------------
class TestUATHappyPath:
    def test_uat_generate_scenarios_uses_real_llm_output_not_generic_fallback(
        self, uat_agent, test_session_id,
    ):
        """Regression guard for the Stage 1b bug: UAT scenarios must come
        from the actual LLM response, not a hardcoded placeholder."""
        result = uat_agent.generate_uat_scenarios(
            session_id=test_session_id,
            business_processes=VALID_BUSINESS_PROCESSES,
            user_roles=["Procurement Buyer"],
        )

        assert result["success"] is True
        scenarios = result["uat_scenarios"]
        assert len(scenarios) == 1
        assert scenarios[0]["scenario"] == "Create and approve Purchase Order"
        assert "Log into the system" not in scenarios[0]["steps"]

    def test_uat_scenario_preserves_role_and_process_fields(
        self, uat_agent, test_session_id,
    ):
        """The UAT-specific fields added in the schema review must
        survive the return path. Without them, the role-coverage and
        process-linkage validators have nothing to read."""
        result = uat_agent.generate_uat_scenarios(
            session_id=test_session_id,
            business_processes=VALID_BUSINESS_PROCESSES,
            user_roles=["Procurement Buyer"],
        )
        scenario = result["uat_scenarios"][0]
        assert scenario.get("user_role") == "Procurement Buyer"
        assert scenario.get("business_process") == "Procure to Pay"
        assert scenario.get("acceptance_criteria")


# ---------------------------------------------------------------------------
# Hard-failure modes (newer behavior; the core regression guard)
# ---------------------------------------------------------------------------
class TestQAEmptyOutputHardFails:
    def test_qa_returns_failure_when_no_test_cases(
        self, qa_agent, test_session_id, patched_sleep,
    ):
        """If the model returns zero test cases, the agent must NOT
        substitute fabricated generic cases. It returns success=False
        with a descriptive error.

        This is the current regression guard for the class of bug
        Stage 1b fixed - stronger than the original because the
        fabricated-fallback path no longer exists in the codebase."""
        empty = Mock()
        empty.text = EMPTY_TEST_CASES_JSON
        qa_agent.model.generate_content.return_value = empty

        result = qa_agent.generate_test_cases(
            session_id=test_session_id,
            solution_design=VALID_SOLUTION_DESIGN,
            module="MM",
        )

        assert result["success"] is False
        assert result.get("error"), "empty output must produce an error message"

    def test_qa_does_not_persist_when_refusing_to_emit(
        self, qa_agent, test_session_id, patched_sleep,
    ):
        """When the agent refuses to emit, it should not have written a
        phase output or document. Verified by asserting the doc
        generator was not called for this path."""
        empty = Mock()
        empty.text = EMPTY_TEST_CASES_JSON
        qa_agent.model.generate_content.return_value = empty

        with patch(
            "src.tools.doc_generator.generate_test_case_document"
        ) as mock_doc_gen:
            result = qa_agent.generate_test_cases(
                session_id=test_session_id,
                solution_design=VALID_SOLUTION_DESIGN,
                module="MM",
            )
            assert result["success"] is False
            mock_doc_gen.assert_not_called()


class TestUATEmptyOutputHardFails:
    def test_uat_returns_failure_when_no_scenarios(
        self, uat_agent, test_session_id, patched_sleep,
    ):
        empty = Mock()
        empty.text = EMPTY_TEST_CASES_JSON
        uat_agent.model.generate_content.return_value = empty

        result = uat_agent.generate_uat_scenarios(
            session_id=test_session_id,
            business_processes=VALID_BUSINESS_PROCESSES,
            user_roles=["Procurement Buyer"],
        )

        assert result["success"] is False
        assert result.get("error")


# ---------------------------------------------------------------------------
# Input pre-flight
# ---------------------------------------------------------------------------
class TestInputPreFlight:
    def test_qa_rejects_empty_module(self, qa_agent, test_session_id):
        result = qa_agent.generate_test_cases(
            session_id=test_session_id,
            solution_design=VALID_SOLUTION_DESIGN,
            module="",
        )
        assert result["success"] is False
        qa_agent.model.generate_content.assert_not_called()

    def test_qa_rejects_empty_solution_design(self, qa_agent, test_session_id):
        result = qa_agent.generate_test_cases(
            session_id=test_session_id,
            solution_design={},
            module="MM",
        )
        assert result["success"] is False
        qa_agent.model.generate_content.assert_not_called()

    def test_uat_rejects_empty_business_processes(self, uat_agent, test_session_id):
        result = uat_agent.generate_uat_scenarios(
            session_id=test_session_id,
            business_processes={},
            user_roles=["Procurement Buyer"],
        )
        assert result["success"] is False
        uat_agent.model.generate_content.assert_not_called()

    def test_qa_warns_on_thin_solution_design(self, qa_agent, test_session_id):
        """A solution_design dict with only empty lists triggers a
        warning but does not refuse - the design may legitimately be
        empty at design time, and the agent should proceed with a flag."""
        result = qa_agent.generate_test_cases(
            session_id=test_session_id,
            solution_design={"configurations": [], "integrations": []},
            module="MM",
        )
        assert result["success"] is True
        assert result.get("warnings"), (
            "thin solution_design should produce at least one warning"
        )


# ---------------------------------------------------------------------------
# Return payload
# ---------------------------------------------------------------------------
class TestReturnPayload:
    def test_qa_payload_has_enriched_fields(self, qa_agent, test_session_id):
        result = qa_agent.generate_test_cases(
            session_id=test_session_id,
            solution_design=VALID_SOLUTION_DESIGN,
            module="MM",
        )
        assert result["success"] is True
        for key in ("test_cases", "document_path", "raw_text", "validation",
                    "warnings", "degraded", "repaired", "duration"):
            assert key in result, f"missing required key {key!r}"

    def test_uat_payload_has_enriched_fields(self, uat_agent, test_session_id):
        result = uat_agent.generate_uat_scenarios(
            session_id=test_session_id,
            business_processes=VALID_BUSINESS_PROCESSES,
            user_roles=["Procurement Buyer"],
        )
        assert result["success"] is True
        for key in ("uat_scenarios", "document_path", "raw_text", "validation",
                    "warnings", "degraded", "repaired", "duration"):
            assert key in result, f"missing required key {key!r}"


# ---------------------------------------------------------------------------
# LLM failure handling
# ---------------------------------------------------------------------------
class TestLLMFailureHandling:
    def test_qa_retry_succeeds_after_transient_failure(
        self, qa_agent, test_session_id, patched_sleep,
    ):
        success = Mock()
        success.text = SAMPLE_TEST_CASES_JSON
        qa_agent.model.generate_content.side_effect = [
            RuntimeError("transient provider blip"),
            success,
        ]
        result = qa_agent.generate_test_cases(
            session_id=test_session_id,
            solution_design=VALID_SOLUTION_DESIGN,
            module="MM",
        )
        assert result["success"] is True
        assert qa_agent.model.generate_content.call_count == 2

    def test_qa_persistent_failure_returns_error(
        self, qa_agent, test_session_id, patched_sleep,
    ):
        qa_agent.model.generate_content.side_effect = RuntimeError("provider down")
        result = qa_agent.generate_test_cases(
            session_id=test_session_id,
            solution_design=VALID_SOLUTION_DESIGN,
            module="MM",
        )
        assert result["success"] is False
        assert "provider down" in result.get("error", "")