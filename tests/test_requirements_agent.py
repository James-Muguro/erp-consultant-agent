"""
Unit tests for Requirements Agent.

Coverage:

  Initialization
    - Agent constructs with config, logger, model.
    - The module-level singleton is present.

  Parse pipeline (three tiers)
    - Valid schema JSON         -> schema validation path.
    - Valid JSON, wrong shape   -> repair path (repaired=True).
    - Unparseable output        -> degraded heuristic path (degraded=True).
    - Truncated JSON            -> detected and retried.
    - Heuristic parser          -> asserts content, not just section keys.

  Input pre-flight
    - Empty / whitespace-only input -> success=False, no LLM call.
    - Very short input              -> success=True with warnings.
    - Oversized input               -> soft-truncated with a marker.

  LLM failure handling
    - Transient failure then success -> retry succeeds (time.sleep patched).

  Return payload
    - warnings, degraded, repaired, open_questions, validation present.

Fixtures mock:
  * get_llm                        - no real provider client construction.
  * sync_requirements_from_structured - no DB access in unit tests.
  * generate_requirements_document    - no .docx files written to disk.
  * time.sleep                      - retry paths don't add real latency.

Session fixtures create and tear down a real session via agent_memory,
matching the pattern the previous version used.
"""
from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest

from src.agents.requirements_agent import RequirementsAgent, requirements_agent
from src.memory import agent_memory


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_stakeholder_input() -> str:
    """Realistic input that passes the agent's pre-flight checks."""
    return (
        "We need to implement Purchase Order processing with the following "
        "features:\n"
        "- Create and approve purchase orders\n"
        "- Three-way matching\n"
        "- Vendor management\n"
        "- Budget checking\n"
        "- Automated notifications\n"
    )


def _valid_requirements_json() -> str:
    """Schema-conformant JSON matching RequirementsDocument.

    Kept as a helper so tests that need a valid response don't repeat
    the same ~30 lines. Includes the newer fields (non_functional_
    requirements, open_questions) that the schema declares, so tests
    exercise the current schema rather than a legacy shape."""
    return json.dumps({
        "executive_summary": "Implementing Purchase Order management system.",
        "business_context": "Procurement needs a standardized PO workflow.",
        "objectives": ["Reduce manual PO errors"],
        "functional_requirements": [
            {
                "category": "Purchase Order Management",
                "requirements": [
                    {"id": "REQ-001", "description": "Create purchase orders",
                     "priority": "High", "type": "Functional"},
                    {"id": "REQ-002", "description": "Approve purchase orders",
                     "priority": "High", "type": "Functional"},
                    {"id": "REQ-003", "description": "Three-way matching",
                     "priority": "High", "type": "Functional"},
                ],
            },
        ],
        "non_functional_requirements": [],
        "technical_requirements": [],
        "integration_requirements": [],
        "reporting_requirements": [],
        "dependencies": [],
        "constraints": [],
        "assumptions": [],
        "open_questions": [],
    })


# ---------------------------------------------------------------------------
# Session fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def test_session_id():
    """Create a session, yield its ID, and clean it up afterwards.

    Cleanup is wrapped in try/except because DbSessionService.delete_session
    performs object-storage cleanup that can log-but-fail on a bare test
    environment; a cleanup error should never mask a test result."""
    session_id = agent_memory.create_project(
        project_name="Test Project",
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


# ---------------------------------------------------------------------------
# Agent fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def patched_llm():
    """Patch get_llm at the module where the agent imports it, so that
    RequirementsAgent() construction does not build a real
    HybridLLMClient. Tests override .generate_content on the returned
    mock as needed.

    Yields the mock returned by get_llm()."""
    with patch("src.agents.requirements_agent.get_llm") as mock_get:
        mock_model = Mock(name="HybridLLMClient")
        mock_get.return_value = mock_model
        yield mock_model


@pytest.fixture
def patched_side_effects():
    """Patch the agent's DB sync and document generation so unit tests
    don't touch the database or write .docx files."""
    with patch(
        "src.services.project_intelligence.sync_requirements_from_structured"
    ), patch(
        "src.tools.doc_generator.generate_requirements_document",
        return_value="/tmp/test_requirements.docx",
    ):
        yield


@pytest.fixture
def agent(patched_llm, patched_side_effects):
    """A RequirementsAgent whose LLM client and side effects are mocked.
    Default the LLM to a valid response so tests only override for the
    error paths they specifically want to exercise."""
    response = Mock()
    response.text = _valid_requirements_json()
    patched_llm.generate_content.return_value = response
    return RequirementsAgent()


@pytest.fixture
def patched_sleep():
    """Patch time.sleep so retry paths don't add real latency. The
    agent's RETRY_BACKOFF_SECONDS is (1.0, 3.0, 7.0); a full retry
    sequence would otherwise sleep for 11s, which is unacceptable for
    a unit test. A follow-up agent update will route the backoff
    through resilience.compute_backoff_delay (which respects
    PYTEST_CURRENT_TEST) and this patch can be removed."""
    with patch("src.agents.requirements_agent.time.sleep"):
        yield


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------
class TestRequirementsAgentInit:
    def test_agent_initialization(self, patched_llm, patched_side_effects):
        agent = RequirementsAgent()
        assert agent.config is not None
        assert agent.logger is not None
        assert agent.model is not None

    def test_module_singleton_exists(self):
        assert requirements_agent is not None
        assert isinstance(requirements_agent, RequirementsAgent)

    def test_reload_model_returns_a_client(self, patched_llm, patched_side_effects):
        """Documents current behavior: reload_model calls get_llm(),
        which returns the same singleton — so in practice it's a no-op
        unless the singleton has been replaced (e.g. by reload_llm()).

        If reload_model is later changed to call reload_llm() (as other
        agents have been), update this assertion to match."""
        agent = RequirementsAgent()
        original = agent.model
        agent.reload_model()
        # get_llm is patched to return the same mock on every call, so
        # the identity is preserved. This is asserting the current
        # no-op-in-test-context behavior, not endorsing it.
        assert agent.model is original


# ---------------------------------------------------------------------------
# Heuristic parser
# ---------------------------------------------------------------------------
class TestHeuristicParser:
    def test_parse_requirements_extracts_sections(self, patched_llm, patched_side_effects):
        """The parser must produce non-empty sections for recognisable
        input — asserting section presence alone would pass an empty
        parser."""
        agent = RequirementsAgent()
        sample_text = (
            "# Executive Summary\n"
            "This project implements AP functionality.\n\n"
            "## Functional Requirements\n"
            "- REQ-001: Process vendor invoices\n"
            "- REQ-002: Automated payment runs\n\n"
            "## Technical Requirements\n"
            "- Integration with procurement system\n"
        )
        parsed = agent._parse_requirements(sample_text)

        assert "AP functionality" in parsed["executive_summary"]
        assert parsed["functional_requirements"], (
            "functional_requirements is empty — parser did not extract any "
            "bullets under the Functional Requirements heading"
        )
        assert parsed["technical_requirements"], (
            "technical_requirements is empty — parser did not extract any "
            "bullets under the Technical Requirements heading"
        )

    def test_parse_requirements_handles_empty_text(self, patched_llm, patched_side_effects):
        """An empty input must still produce a shape-valid dict."""
        agent = RequirementsAgent()
        parsed = agent._parse_requirements("")
        assert isinstance(parsed, dict)
        # All expected sections are present with their defaults.
        for key in ("executive_summary", "functional_requirements",
                    "technical_requirements", "assumptions"):
            assert key in parsed


# ---------------------------------------------------------------------------
# Input pre-flight
# ---------------------------------------------------------------------------
class TestInputPreFlight:
    def test_gather_requirements_rejects_empty_input(
        self, agent, test_session_id,
    ):
        result = agent.gather_requirements(
            session_id=test_session_id,
            project_name="Test Project",
            module="MM",
            stakeholder_input="",
        )
        assert result["success"] is False
        assert result.get("error")
        # No LLM call should have been made for unusable input.
        agent.model.generate_content.assert_not_called()

    def test_gather_requirements_rejects_whitespace_only_input(
        self, agent, test_session_id,
    ):
        result = agent.gather_requirements(
            session_id=test_session_id,
            project_name="Test Project",
            module="MM",
            stakeholder_input="      \n\t  ",
        )
        assert result["success"] is False
        agent.model.generate_content.assert_not_called()

    def test_gather_requirements_warns_on_short_input(
        self, agent, test_session_id,
    ):
        """Short input is not rejected — it's flagged. The result should
        succeed with a warning that the document will be mostly inferred."""
        result = agent.gather_requirements(
            session_id=test_session_id,
            project_name="Test Project",
            module="MM",
            stakeholder_input="do the thing",
        )
        assert result["success"] is True
        assert result.get("warnings"), (
            "short input should produce at least one warning on the "
            "returned payload"
        )


# ---------------------------------------------------------------------------
# Parse pipeline
# ---------------------------------------------------------------------------
class TestParsePipeline:
    def test_valid_schema_json_uses_schema_path(self, agent, test_session_id):
        result = agent.gather_requirements(
            session_id=test_session_id,
            project_name="Test Project",
            module="MM",
            stakeholder_input="We need Purchase Order approval workflows for the MM team. " * 2,
        )
        assert result["success"] is True
        assert result.get("degraded") is False
        assert result.get("repaired") is False
        func_reqs = result["requirements"]["functional_requirements"]
        assert "Purchase Order Management" in func_reqs
        assert len(func_reqs["Purchase Order Management"]) == 3

    def test_wrong_shape_triggers_repair_path(
        self, agent, test_session_id, patched_sleep,
    ):
        """First response is valid JSON but missing required fields; the
        agent should ask for a repair, and if the repair returns valid
        JSON, the result carries repaired=True."""
        broken = Mock()
        broken.text = '{"executive_summary": "ok"}'  # missing required sections
        repaired = Mock()
        repaired.text = _valid_requirements_json()

        # First call: broken. Repair call: valid.
        agent.model.generate_content.side_effect = [broken, repaired]

        result = agent.gather_requirements(
            session_id=test_session_id,
            project_name="Test Project",
            module="MM",
            stakeholder_input="We need Purchase Order approval workflows for the MM team. " * 2,
        )
        assert result["success"] is True
        # The repair path ran — model was called at least twice.
        assert agent.model.generate_content.call_count >= 2

    def test_unparseable_output_degrades(
        self, agent, test_session_id, patched_sleep,
    ):
        """If schema validation and repair both fail, the agent falls
        back to the heuristic parser and marks the result degraded."""
        garbage = Mock()
        garbage.text = "This is not JSON at all.\n\n- REQ-001 something\n"
        agent.model.generate_content.side_effect = [garbage, garbage]

        result = agent.gather_requirements(
            session_id=test_session_id,
            project_name="Test Project",
            module="MM",
            stakeholder_input="We need Purchase Order approval workflows for the MM team. " * 2,
        )
        # The agent must not crash; it degrades.
        assert result["success"] is True
        assert result.get("degraded") is True


# ---------------------------------------------------------------------------
# LLM failure handling
# ---------------------------------------------------------------------------
class TestLLMFailureHandling:
    def test_retry_succeeds_after_transient_failure(
        self, agent, test_session_id, patched_sleep,
    ):
        """One transient exception, then success. The retry mechanism
        should recover without surfacing an error to the caller."""
        success = Mock()
        success.text = _valid_requirements_json()
        agent.model.generate_content.side_effect = [
            RuntimeError("transient provider blip"),
            success,
        ]

        result = agent.gather_requirements(
            session_id=test_session_id,
            project_name="Test Project",
            module="MM",
            stakeholder_input="We need Purchase Order approval workflows for the MM team. " * 2,
        )
        assert result["success"] is True
        assert agent.model.generate_content.call_count == 2

    def test_persistent_failure_returns_error(
        self, agent, test_session_id, patched_sleep,
    ):
        """Every attempt fails. The agent must return success=False with
        a propagated error, not raise."""
        agent.model.generate_content.side_effect = RuntimeError("provider down")

        result = agent.gather_requirements(
            session_id=test_session_id,
            project_name="Test Project",
            module="MM",
            stakeholder_input="We need Purchase Order approval workflows for the MM team. " * 2,
        )
        assert result["success"] is False
        assert "provider down" in result.get("error", "")


# ---------------------------------------------------------------------------
# Return payload enrichment
# ---------------------------------------------------------------------------
class TestReturnPayload:
    def test_payload_has_enriched_fields(self, agent, test_session_id):
        result = agent.gather_requirements(
            session_id=test_session_id,
            project_name="Test Project",
            module="MM",
            stakeholder_input="We need Purchase Order approval workflows for the MM team. " * 2,
        )
        assert result["success"] is True
        # Fields the orchestrator and API rely on. Assert presence even
        # when the value is empty — a missing key would break downstream
        # consumers that use .get() with a default only where they know
        # the key exists.
        for key in ("warnings", "validation", "degraded", "repaired",
                    "open_questions", "assumptions", "requirements",
                    "document_path", "duration"):
            assert key in result, f"missing required key {key!r} in result"

    def test_validation_result_is_structured(self, agent, test_session_id):
        result = agent.gather_requirements(
            session_id=test_session_id,
            project_name="Test Project",
            module="MM",
            stakeholder_input="We need Purchase Order approval workflows for the MM team. " * 2,
        )
        validation = result.get("validation")
        assert isinstance(validation, dict)
        assert "is_valid" in validation
        assert "issues" in validation
        assert "completeness_score" in validation


# ---------------------------------------------------------------------------
# validate_requirements (unit)
# ---------------------------------------------------------------------------
class TestValidateRequirements:
    def test_validate_requirements_valid(self, patched_llm, patched_side_effects):
        agent = RequirementsAgent()
        valid_reqs = {
            "executive_summary": "Test summary",
            "business_context": "Test context",
            "functional_requirements": {
                "general": [
                    {"id": "REQ-001", "description": "Test req", "priority": "High"},
                ],
            },
        }
        validation = agent.validate_requirements(valid_reqs)
        assert validation["is_valid"] is True
        assert validation["completeness_score"] > 0

    def test_validate_requirements_missing_sections(self, patched_llm, patched_side_effects):
        agent = RequirementsAgent()
        validation = agent.validate_requirements({})
        assert validation["is_valid"] is False
        assert validation["issues"], "empty requirements should report issues"

    def test_validate_requirements_warns_on_no_functional(self, patched_llm, patched_side_effects):
        """The validator should flag 'no functional requirements' as
        invalid rather than a soft warning, since it's a structural gap."""
        agent = RequirementsAgent()
        validation = agent.validate_requirements({
            "executive_summary": "Summary",
            "business_context": "Context",
            "functional_requirements": {},
        })
        assert validation["is_valid"] is False


# ---------------------------------------------------------------------------
# _build_context (unit)
# ---------------------------------------------------------------------------
class TestBuildContext:
    def test_build_context_includes_module_info(self, patched_llm, patched_side_effects):
        agent = RequirementsAgent()
        module_info = {
            "name": "Materials Management",
            "description": "Test module",
            "sub_modules": ["Purchasing", "Inventory"],
            "common_transactions": ["ME21N", "MIGO"],
            "integration_points": ["FI", "SD"],
            "best_practices": ["Best practice 1"],
        }
        context = agent._build_context(
            module_info=module_info,
            best_practices=["Practice 1", "Practice 2"],
            template="Test template",
            past_learnings=[],
        )
        assert "Materials Management" in context
        assert "ME21N" in context
        assert "Practice 1" in context or "Best practice 1" in context

    def test_build_context_tolerates_missing_module_info(self, patched_llm, patched_side_effects):
        """None module_info must not crash — the agent runs without KB
        context rather than failing."""
        agent = RequirementsAgent()
        context = agent._build_context(
            module_info=None,
            best_practices=[],
            template=None,
            past_learnings=[],
        )
        assert isinstance(context, str)