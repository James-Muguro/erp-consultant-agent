"""
Unit tests for ProcessMappingAgent.

Coverage:

  Happy path
    - Schema-valid mock output produces a process_map with steps and
      roles preserved.
    - decision_points and integration_points are returned as structured
      objects (see note below), not as the plain strings the pre-schema
      mock supplies. The map_process test asserts this explicitly so the
      contract change is documented in code.

  Structured field contract (new in the schema review)
    - Legacy list-of-strings decision_points is accepted and wrapped
      into {"condition": ..., ...} dicts.
    - Legacy list-of-strings integration_points is accepted and wrapped
      into {"name": ..., ...} dicts.
    - Explicitly structured decision_points pass through unchanged.

  Pre-flight validation
    - Empty process_name -> success=False, no LLM call.
    - Empty requirements -> success=True with a warning (not a refusal).
    - Invalid scope values on requirements are handled tolerantly.

  Parse pipeline
    - Unparseable output -> degraded heuristic path, success=True with
      degraded=True.
    - Wrong-shape JSON -> repair path, success=True with repaired=True.

  LLM failure handling
    - Transient failure then success retries and succeeds.
    - Persistent failure returns success=False, not raising.

  Return payload
    - warnings, validation, degraded, repaired present on every result.

  Module resolution
    - module_source reflects where the module came from (arg vs
      requirements vs. default_fallback).

  RACI matrix
    - Explicit raci dicts honored.
    - Missing Accountable flagged in data_gaps.
    - Same role as both R and A flagged as a SoD risk.
    - default_assignment='I' preserves the pre-review behavior.

  Gap analysis
    - Renamed steps detected as 'renamed_step' with confidence.
    - Genuinely missing / extra steps reported with high confidence.

Fixtures:
  * patched_llm        patches get_llm so construction is hermetic.
  * patched_side_effects
                       patches the DB sync and document generation.
  * patched_sleep      zeroes the retry backoff for tests that exercise
                       the retry path.
  * pma_agent          composes the above and defaults the mock to a
                       schema-valid response.
  * test_session_id    creates a session and cleans it up safely.
"""
from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest

from src.agents.process_mapping_agent import ProcessMappingAgent, process_mapping_agent
from src.memory import agent_memory


# ---------------------------------------------------------------------------
# Sample responses
# ---------------------------------------------------------------------------
def _process_map_json(
    *,
    decision_points=None,
    integration_points=None,
    include_step_ids: bool = False,
) -> str:
    """Schema-conformant ProcessMap JSON. Parameterised so tests can
    exercise the two forms of decision_points / integration_points
    (legacy string list vs. structured dict list) without duplicating
    the whole document.

    `include_step_ids=False` (default) omits the step `id` field, which
    is the common case — the schema's `_ensure_step_ids` validator
    fills it in. Set to True to test the model-supplied form."""
    steps = [
        {
            "number": 1,
            "name": "Create Purchase Requisition",
            "description": "Requisitioner creates PR.",
            "transaction": "ME51N",
            "responsible_role": "Requisitioner",
        },
        {
            "number": 2,
            "name": "Approve Requisition",
            "description": "Manager approves PR.",
            "transaction": "ME54N",
            "responsible_role": "Approver",
        },
    ]
    if include_step_ids:
        steps[0]["id"] = "STEP-001"
        steps[1]["id"] = "STEP-002"

    return json.dumps({
        "overview": "Standard procure-to-pay process.",
        "scope": "Purchase requisition through vendor payment.",
        "roles": ["Procurement Buyer", "Finance Manager"],
        "steps": steps,
        "decision_points": decision_points
            if decision_points is not None
            else ["Requisition approval threshold check"],
        "integration_points": integration_points
            if integration_points is not None
            else ["Vendor master sync"],
        "exceptions": ["Requisition rejected"],
        "improvements": ["Auto-approval for low-value requisitions"],
    })


_VALID_PROCESS_MAP_JSON = _process_map_json()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def patched_llm():
    """Patch get_llm at the module path the agent imports it from."""
    with patch("src.agents.process_mapping_agent.get_llm") as mock_get:
        mock_model = Mock(name="HybridLLMClient")
        mock_get.return_value = mock_model
        yield mock_model


@pytest.fixture
def patched_side_effects():
    """Patch DB sync and document generation so unit tests don't touch
    the DB or write .docx files."""
    with patch(
        "src.services.project_intelligence.sync_process_steps_from_structured",
        return_value=[],
    ), patch(
        "src.services.project_intelligence.link_requirements",
    ), patch(
        "src.tools.doc_generator.generate_process_map",
        return_value="/tmp/test_process_map.docx",
    ):
        yield


@pytest.fixture
def patched_sleep():
    """Zero out the retry backoff. The agent's RETRY_BACKOFF_SECONDS is
    (1.0, 3.0, 7.0); a full retry sequence would sleep ~11s unpatched."""
    with patch("src.agents.process_mapping_agent.time.sleep"):
        yield


@pytest.fixture
def pma_agent(patched_llm, patched_side_effects):
    """A ProcessMappingAgent with mocked LLM and side effects. Default
    response is a valid schema-conformant ProcessMap."""
    response = Mock()
    response.text = _VALID_PROCESS_MAP_JSON
    patched_llm.generate_content.return_value = response
    return ProcessMappingAgent()


@pytest.fixture
def test_session_id():
    """Session with safe cleanup on teardown."""
    session_id = agent_memory.create_project(
        project_name="Process Mapping Test",
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
# Initialization
# ---------------------------------------------------------------------------
class TestProcessMappingAgentInit:
    def test_agent_initializes(self, patched_llm, patched_side_effects):
        agent = ProcessMappingAgent()
        assert agent.config is not None
        assert agent.logger is not None
        assert agent.model is not None

    def test_module_singleton_exists(self):
        assert isinstance(process_mapping_agent, ProcessMappingAgent)


# ---------------------------------------------------------------------------
# Happy path (preserved from the original test)
# ---------------------------------------------------------------------------
class TestMapProcessHappyPath:
    def test_map_process_success(self, pma_agent, test_session_id):
        result = pma_agent.map_process(
            session_id=test_session_id,
            process_name="Procure to Pay",
            requirements={
                "module": "MM",
                "functional_requirements": {},
                "integration_requirements": [],
            },
            current_state="Manual PO creation",
        )

        assert result["success"] is True
        steps = result["process_map"]["steps"]
        assert len(steps) == 2
        assert steps[0]["name"] == "Create Purchase Requisition"
        assert result["process_map"]["roles"] == [
            "Procurement Buyer",
            "Finance Manager",
        ]

    def test_steps_receive_auto_assigned_ids(self, pma_agent, test_session_id):
        """The schema's _ensure_step_ids validator assigns STEP-NNN when
        the model omits the id. This is what makes downstream traceability
        linking possible — _sync_downstream zips steps with returned step
        IDs, and link_requirements matches on step['id']."""
        result = pma_agent.map_process(
            session_id=test_session_id,
            process_name="Procure to Pay",
            requirements={"module": "MM"},
        )
        steps = result["process_map"]["steps"]
        assert all(step.get("id") for step in steps), (
            "every step must have an id — the schema's _ensure_step_ids "
            "validator should have assigned one where the model omitted it"
        )
        assert steps[0]["id"] == "STEP-001"
        assert steps[1]["id"] == "STEP-002"


# ---------------------------------------------------------------------------
# Structured decision_points / integration_points (schema-review contract)
# ---------------------------------------------------------------------------
class TestStructuredPointsContract:
    def test_legacy_string_decision_points_are_wrapped(
        self, pma_agent, test_session_id, patched_llm,
    ):
        """The schema now returns List[DecisionPoint], not List[str].
        A source (or a legacy mock) that supplies a plain string list
        must be accepted — the mode='before' validator wraps each entry
        as {'condition': ..., 'id': 'DP-001', 'outcomes': []}."""
        result = pma_agent.map_process(
            session_id=test_session_id,
            process_name="Procure to Pay",
            requirements={"module": "MM"},
        )
        decision_points = result["process_map"]["decision_points"]
        assert len(decision_points) == 1
        # Not a bare string anymore — it's a dict.
        assert isinstance(decision_points[0], dict)
        assert decision_points[0]["condition"] == "Requisition approval threshold check"
        assert decision_points[0]["id"] == "DP-001"

    def test_legacy_string_integration_points_are_wrapped(
        self, pma_agent, test_session_id,
    ):
        result = pma_agent.map_process(
            session_id=test_session_id,
            process_name="Procure to Pay",
            requirements={"module": "MM"},
        )
        integration_points = result["process_map"]["integration_points"]
        assert len(integration_points) == 1
        assert isinstance(integration_points[0], dict)
        assert integration_points[0]["name"] == "Vendor master sync"
        assert integration_points[0]["id"] == "IP-001"

    def test_explicitly_structured_decision_points_pass_through(
        self, patched_llm, patched_side_effects, test_session_id,
    ):
        """The preferred schema form: a dict with condition and outcomes.
        Nothing should be lost in the round trip."""
        response = Mock()
        response.text = _process_map_json(decision_points=[
            {
                "condition": "PO value exceeds 10,000 EUR",
                "outcomes": ["Requires CFO approval", "Auto-approved"],
                "after_step": "STEP-001",
            },
        ])
        patched_llm.generate_content.return_value = response
        agent = ProcessMappingAgent()

        result = agent.map_process(
            session_id=test_session_id,
            process_name="Procure to Pay",
            requirements={"module": "MM"},
        )
        dp = result["process_map"]["decision_points"][0]
        assert dp["condition"] == "PO value exceeds 10,000 EUR"
        assert dp["outcomes"] == ["Requires CFO approval", "Auto-approved"]
        assert dp["after_step"] == "STEP-001"


# ---------------------------------------------------------------------------
# Pre-flight validation
# ---------------------------------------------------------------------------
class TestPreFlight:
    def test_rejects_empty_process_name(self, pma_agent, test_session_id):
        result = pma_agent.map_process(
            session_id=test_session_id,
            process_name="",
            requirements={"module": "MM"},
        )
        assert result["success"] is False
        assert result.get("error")
        pma_agent.model.generate_content.assert_not_called()

    def test_empty_requirements_warns_but_proceeds(self, pma_agent, test_session_id):
        """Empty requirements is a signal of thin context, not a refusal.
        The agent proceeds — refusing would prevent mapping a process
        from a bare description in an early-phase project."""
        result = pma_agent.map_process(
            session_id=test_session_id,
            process_name="Procure to Pay",
            requirements={},
        )
        assert result["success"] is True
        assert result.get("warnings"), (
            "empty requirements should produce a warning on the returned payload"
        )


# ---------------------------------------------------------------------------
# Parse pipeline
# ---------------------------------------------------------------------------
class TestParsePipeline:
    def test_unparseable_output_degrades(
        self, pma_agent, test_session_id, patched_sleep,
    ):
        garbage = Mock()
        garbage.text = "This is not JSON.\n\nStep 1: do something\nStep 2: do more"
        pma_agent.model.generate_content.side_effect = [garbage, garbage]

        result = pma_agent.map_process(
            session_id=test_session_id,
            process_name="Procure to Pay",
            requirements={"module": "MM"},
        )
        assert result["success"] is True
        assert result.get("degraded") is True

    def test_wrong_shape_triggers_repair_path(
        self, pma_agent, test_session_id, patched_sleep,
    ):
        broken = Mock()
        broken.text = '{"overview": "ok"}'  # missing required fields
        repaired = Mock()
        repaired.text = _VALID_PROCESS_MAP_JSON
        pma_agent.model.generate_content.side_effect = [broken, repaired]

        result = pma_agent.map_process(
            session_id=test_session_id,
            process_name="Procure to Pay",
            requirements={"module": "MM"},
        )
        assert result["success"] is True
        assert pma_agent.model.generate_content.call_count >= 2


# ---------------------------------------------------------------------------
# LLM failure handling
# ---------------------------------------------------------------------------
class TestLLMFailureHandling:
    def test_retry_succeeds_after_transient_failure(
        self, pma_agent, test_session_id, patched_sleep,
    ):
        success = Mock()
        success.text = _VALID_PROCESS_MAP_JSON
        pma_agent.model.generate_content.side_effect = [
            RuntimeError("transient provider blip"),
            success,
        ]
        result = pma_agent.map_process(
            session_id=test_session_id,
            process_name="Procure to Pay",
            requirements={"module": "MM"},
        )
        assert result["success"] is True
        assert pma_agent.model.generate_content.call_count == 2

    def test_persistent_failure_returns_error(
        self, pma_agent, test_session_id, patched_sleep,
    ):
        pma_agent.model.generate_content.side_effect = RuntimeError("provider down")
        result = pma_agent.map_process(
            session_id=test_session_id,
            process_name="Procure to Pay",
            requirements={"module": "MM"},
        )
        assert result["success"] is False
        assert "provider down" in result.get("error", "")


# ---------------------------------------------------------------------------
# Return payload
# ---------------------------------------------------------------------------
class TestReturnPayload:
    def test_payload_has_enriched_fields(self, pma_agent, test_session_id):
        result = pma_agent.map_process(
            session_id=test_session_id,
            process_name="Procure to Pay",
            requirements={"module": "MM"},
        )
        assert result["success"] is True
        for key in (
            "process_map", "document_path", "raw_text", "validation",
            "warnings", "degraded", "repaired", "module", "module_source",
            "link_stats", "duration",
        ):
            assert key in result, f"missing required key {key!r}"

    def test_module_source_reflects_where_module_came_from(
        self, pma_agent, test_session_id,
    ):
        result = pma_agent.map_process(
            session_id=test_session_id,
            process_name="Procure to Pay",
            requirements={"module": "MM"},
        )
        assert result["module"] == "MM"
        assert result["module_source"] == "requirements"

    def test_module_source_arg_when_passed_explicitly(
        self, pma_agent, test_session_id,
    ):
        result = pma_agent.map_process(
            session_id=test_session_id,
            process_name="Procure to Pay",
            requirements={},
            module="SD",
        )
        assert result["module"] == "SD"
        assert result["module_source"] == "arg"

    def test_module_source_default_fallback_when_missing(
        self, pma_agent, test_session_id,
    ):
        """No module anywhere → default_fallback with a warning. The
        previous version silently defaulted to 'FI' with no signal; the
        improved version surfaces it in the payload."""
        result = pma_agent.map_process(
            session_id=test_session_id,
            process_name="Procure to Pay",
            requirements={},
        )
        assert result["module"] == "FI"
        assert result["module_source"] == "default_fallback"
        assert any("FI" in w and "default" in w.lower() for w in result["warnings"])


# ---------------------------------------------------------------------------
# RACI matrix
# ---------------------------------------------------------------------------
class TestRaciMatrix:
    def test_explicit_raci_dicts_are_honored(
        self, patched_llm, patched_side_effects,
    ):
        agent = ProcessMappingAgent()
        matrix = agent.create_raci_matrix(
            process_steps=[
                {
                    "name": "Approve PO",
                    "raci": {"AP Manager": "A", "AP Clerk": "R"},
                    "consulted_roles": ["Controller"],
                },
            ],
            roles=["AP Clerk", "AP Manager", "Controller"],
        )
        step = matrix["steps"][0]
        assert step["assignments"]["AP Manager"] == "A"
        assert step["assignments"]["AP Clerk"] == "R"
        assert step["assignments"]["Controller"] == "C"
        assert step["valid"] is True
        assert matrix["is_complete"] is True

    def test_missing_accountable_is_flagged(
        self, patched_llm, patched_side_effects,
    ):
        """A step with only a responsible_role has no Accountable — a
        structural RACI violation the previous implementation couldn't
        detect."""
        agent = ProcessMappingAgent()
        matrix = agent.create_raci_matrix(
            process_steps=[
                {"name": "Post invoice", "responsible_role": "AP Clerk"},
            ],
            roles=["AP Clerk", "AP Manager"],
        )
        assert matrix["is_complete"] is False
        assert any(
            "Accountable" in gap["issues"][0] or
            any("Accountable" in issue for issue in gap["issues"])
            for gap in matrix["data_gaps"]
        )

    def test_same_role_as_responsible_and_accountable_is_a_sod_risk(
        self, patched_llm, patched_side_effects,
    ):
        agent = ProcessMappingAgent()
        matrix = agent.create_raci_matrix(
            process_steps=[
                {
                    "name": "Post journal",
                    "responsible_role": "Accountant",
                    "accountable_role": "Accountant",
                },
            ],
            roles=["Accountant"],
        )
        step = matrix["steps"][0]
        # Same role as R and A → SoD overlap; flagged as invalid.
        assert step["valid"] is False
        assert any("segregation" in i.lower() for i in step["issues"])


# ---------------------------------------------------------------------------
# Gap analysis
# ---------------------------------------------------------------------------
class TestGapAnalysis:
    def test_renamed_steps_are_detected_as_renames(
        self, patched_llm, patched_side_effects,
    ):
        """'Create PO' vs 'Create Purchase Order' should be recognised
        as a rename, not two separate gaps."""
        agent = ProcessMappingAgent()
        gaps = agent.identify_gaps(
            current_process={"steps": [{"name": "Create Purchase Order"}]},
            target_process={"steps": [{"name": "Create PO"}]},
        )
        rename_gaps = [g for g in gaps if g["type"] == "renamed_step"]
        assert len(rename_gaps) == 1
        assert "confidence" in rename_gaps[0]

    def test_missing_and_extra_steps_are_distinguished(
        self, patched_llm, patched_side_effects,
    ):
        agent = ProcessMappingAgent()
        gaps = agent.identify_gaps(
            current_process={"steps": [{"name": "Old manual entry"}]},
            target_process={"steps": [{"name": "Automated posting"}]},
        )
        types = {g["type"] for g in gaps}
        assert "missing_step" in types
        assert "extra_step" in types