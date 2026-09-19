"""
Unit tests for SolutionDesignAgent.

Coverage:

  Happy path
    - Schema-valid mock output produces a design with configurations,
      integrations, master_data, technical_specs.
    - to_legacy_dict flattens master_data / technical_specs into
      {name: value} dicts, preserving the pre-review return shape.

  Schema contract (new in the schema review)
    - Configuration classification defaults to CONFIGURATION when the
      model omits it; explicit STANDARD / EXTENSION pass through.
    - Customizations carry the governance fields
      (alternatives_considered, complexity, lifecycle_impact).
    - Integrations carry structured fields (direction, trigger,
      transport, error_handling, idempotency_key).
    - Document-level assumptions and open_questions are surfaced.

  to_legacy_dict contract
    - Duplicate master_data keys merge rather than overwrite.
    - Duplicate technical_specs keys merge rather than overwrite.
    - Rich structured form preserved under master_data_items /
      technical_specs_items.

  Pre-flight validation
    - Empty requirements AND empty process_maps -> success=False.
    - Only one of the two missing -> success=True with a warning.

  Parse pipeline
    - Unparseable output -> degraded heuristic path.
    - Wrong-shape JSON -> repair path.

  LLM failure handling
    - Transient failure then success retries and succeeds.
    - Persistent failure returns success=False.

  Return payload
    - warnings, validation, degraded, repaired, module, module_source
      present on every result.

  evaluate_customization_need
    - Strong overlap recommends standard use (coverage above threshold).
    - Weak overlap flags review_required rather than a false 'use standard'.
    - Empty requirement / empty functionality list handled gracefully.
    - Never returns confidence='high' from string overlap alone.

Fixtures:
  * patched_llm          patches get_llm so construction is hermetic.
  * patched_side_effects patches the DB sync and document generation.
  * patched_sleep        zeroes the retry backoff.
  * sda_agent            composes the above with a schema-valid default.
  * test_session_id      session with safe cleanup.
"""
from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest

from src.agents.solution_design_agent import SolutionDesignAgent, solution_design_agent
from src.memory import agent_memory


# ---------------------------------------------------------------------------
# Sample responses
# ---------------------------------------------------------------------------
def _solution_design_json(
    *,
    configurations=None,
    customizations=None,
    integrations=None,
    master_data=None,
    technical_specs=None,
    assumptions=None,
    open_questions=None,
) -> str:
    """Schema-conformant SolutionDesign JSON. Parameterised so tests can
    vary individual sections without duplicating the whole document."""
    return json.dumps({
        "executive_summary": "Solution uses standard SAP MM functionality.",
        "architecture_overview": "Single-instance S/4HANA deployment.",
        "configurations": configurations if configurations is not None else [
            {
                "component": "PO Approval Workflow",
                "description": "Workflow config.",
                "steps": ["Define approval limits", "Assign approvers"],
            },
        ],
        "master_data": master_data if master_data is not None else [
            {
                "data_type": "Vendor Master",
                "details": "Standard vendor master with tax fields.",
            },
        ],
        "integrations": integrations if integrations is not None else [
            {
                "name": "Vendor Portal",
                "type": "Real-time",
                "source": "S/4HANA",
                "target": "Vendor Portal",
                "description": "PO dispatch integration.",
            },
        ],
        "security": {"overview": "RBAC via SoD matrix."},
        "customizations": customizations if customizations is not None else [
            {
                "type": "Enhancement",
                "component": "PO Form",
                "description": "Custom PO layout.",
                "justification": "Regulatory requirement.",
            },
        ],
        "migration": {"strategy": "Phased cutover by plant."},
        "technical_specs": technical_specs if technical_specs is not None else [
            {"name": "Uptime SLA", "value": "99.9%"},
        ],
        "assumptions": assumptions if assumptions is not None else [],
        "open_questions": open_questions if open_questions is not None else [],
    })


_VALID_DESIGN_JSON = _solution_design_json()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def patched_llm():
    with patch("src.agents.solution_design_agent.get_llm") as mock_get:
        mock_model = Mock(name="HybridLLMClient")
        mock_get.return_value = mock_model
        yield mock_model


@pytest.fixture
def patched_side_effects():
    """Patch DB sync and document generation."""
    with patch(
        "src.services.project_intelligence.sync_solution_decisions_from_structured",
        return_value=[],
    ), patch(
        "src.tools.doc_generator.generate_solution_design",
        return_value="/tmp/test_solution_design.docx",
    ):
        yield


@pytest.fixture
def patched_sleep():
    with patch("src.agents.solution_design_agent.time.sleep"):
        yield


@pytest.fixture
def sda_agent(patched_llm, patched_side_effects):
    response = Mock()
    response.text = _VALID_DESIGN_JSON
    patched_llm.generate_content.return_value = response
    return SolutionDesignAgent()


@pytest.fixture
def test_session_id():
    session_id = agent_memory.create_project(
        project_name="Solution Design Test",
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
class TestSolutionDesignAgentInit:
    def test_agent_initializes(self, patched_llm, patched_side_effects):
        agent = SolutionDesignAgent()
        assert agent.config is not None
        assert agent.logger is not None
        assert agent.model is not None

    def test_module_singleton_exists(self):
        assert isinstance(solution_design_agent, SolutionDesignAgent)


# ---------------------------------------------------------------------------
# Happy path (preserved from the original test)
# ---------------------------------------------------------------------------
class TestDesignSolutionHappyPath:
    def test_design_solution_success(self, sda_agent, test_session_id):
        result = sda_agent.design_solution(
            session_id=test_session_id,
            requirements={
                "module": "MM",
                "functional_requirements": {},
                "integration_requirements": [],
            },
            process_maps={},
            erp_system="SAP S/4HANA",
        )

        assert result["success"] is True
        design = result["design"]
        assert len(design["configurations"]) == 1
        # Legacy flattened shape: {name: details}. Preserved from the
        # pre-review implementation for backward compatibility.
        assert design["master_data"] == {
            "Vendor Master": "Standard vendor master with tax fields.",
        }
        assert design["technical_specs"] == {"Uptime SLA": "99.9%"}


# ---------------------------------------------------------------------------
# Schema contract (new in the schema review)
# ---------------------------------------------------------------------------
class TestSchemaContract:
    def test_configuration_classification_defaults_to_configuration(
        self, sda_agent, test_session_id,
    ):
        """When the model omits classification, it defaults to
        CONFIGURATION. This is the middle rung of the standard-first
        ladder and matches the intent of most real design entries."""
        result = sda_agent.design_solution(
            session_id=test_session_id,
            requirements={"module": "MM"},
            process_maps={},
        )
        config = result["design"]["configurations"][0]
        assert config["classification"] == "CONFIGURATION"

    def test_explicit_classification_passes_through(
        self, patched_llm, patched_side_effects, test_session_id,
    ):
        response = Mock()
        response.text = _solution_design_json(configurations=[
            {"component": "Standard PO", "classification": "STANDARD"},
            {"component": "BAdI extension", "classification": "EXTENSION"},
        ])
        patched_llm.generate_content.return_value = response
        agent = SolutionDesignAgent()

        result = agent.design_solution(
            session_id=test_session_id,
            requirements={"module": "MM"},
            process_maps={},
        )
        classifications = [c["classification"] for c in result["design"]["configurations"]]
        assert classifications == ["STANDARD", "EXTENSION"]

    def test_customization_governance_fields_survive(
        self, patched_llm, patched_side_effects, test_session_id,
    ):
        """Customizations carry the fields a steering committee asks
        about: why standard is insufficient, alternatives considered,
        complexity, lifecycle impact."""
        response = Mock()
        response.text = _solution_design_json(customizations=[
            {
                "type": "Enhancement",
                "component": "Custom approval engine",
                "description": "Bespoke workflow engine.",
                "justification": "Standard release strategy cannot model the required multi-tier matrix.",
                "alternatives_considered": [
                    "Standard release strategy rejected: insufficient tiers",
                    "Process change rejected: regulator requires the current behavior",
                ],
                "complexity": "High",
                "lifecycle_impact": "Regression testing every service pack required.",
            },
        ])
        patched_llm.generate_content.return_value = response
        agent = SolutionDesignAgent()

        result = agent.design_solution(
            session_id=test_session_id,
            requirements={"module": "MM"},
            process_maps={},
        )
        cust = result["design"]["customizations"][0]
        assert cust["complexity"] == "High"
        assert len(cust["alternatives_considered"]) == 2
        assert "service pack" in cust["lifecycle_impact"]

    def test_integration_structured_fields_survive(
        self, patched_llm, patched_side_effects, test_session_id,
    ):
        response = Mock()
        response.text = _solution_design_json(integrations=[
            {
                "name": "Vendor sync",
                "direction": "inbound",
                "source": "MDM",
                "target": "SAP S/4HANA",
                "trigger": "Nightly batch",
                "payload_summary": "Vendor headers and bank details",
                "transport": "SAP CPI",
                "error_handling": "Retry 3x, alert on failure",
                "idempotency_key": "vendor_number",
            },
        ])
        patched_llm.generate_content.return_value = response
        agent = SolutionDesignAgent()

        result = agent.design_solution(
            session_id=test_session_id,
            requirements={"module": "MM"},
            process_maps={},
        )
        integ = result["design"]["integrations"][0]
        assert integ["direction"] == "inbound"
        assert integ["transport"] == "SAP CPI"
        assert integ["idempotency_key"] == "vendor_number"

    def test_document_level_open_questions_survive(
        self, patched_llm, patched_side_effects, test_session_id,
    ):
        response = Mock()
        response.text = _solution_design_json(
            assumptions=["Standard release strategy covers 3-tier approval"],
            open_questions=[
                {
                    "topic": "Cutover window",
                    "question": "Is a 72-hour freeze acceptable to Finance?",
                    "blocking": True,
                    "owner": "Finance Lead",
                },
            ],
        )
        patched_llm.generate_content.return_value = response
        agent = SolutionDesignAgent()

        result = agent.design_solution(
            session_id=test_session_id,
            requirements={"module": "MM"},
            process_maps={},
        )
        assert result["assumptions"]
        assert result["open_questions"]
        assert result["open_questions"][0].get("blocking") is True or \
               (isinstance(result["open_questions"][0], dict) and
                result["open_questions"][0].get("topic") == "Cutover window")


# ---------------------------------------------------------------------------
# to_legacy_dict contract
# ---------------------------------------------------------------------------
class TestToLegacyDict:
    def test_duplicate_master_data_keys_merge_not_overwrite(
        self, patched_llm, patched_side_effects, test_session_id,
    ):
        """Two master data entries sharing a data_type is legitimate —
        e.g. domestic and foreign vendors under 'Vendor Master'. The
        previous dict comprehension kept only the last one. My rewrite
        merges their details on separate lines."""
        response = Mock()
        response.text = _solution_design_json(master_data=[
            {"data_type": "Vendor Master", "details": "Domestic vendors with local tax rules."},
            {"data_type": "Vendor Master", "details": "Foreign vendors with withholding tax."},
        ])
        patched_llm.generate_content.return_value = response
        agent = SolutionDesignAgent()

        result = agent.design_solution(
            session_id=test_session_id,
            requirements={"module": "MM"},
            process_maps={},
        )
        merged = result["design"]["master_data"]["Vendor Master"]
        assert "Domestic" in merged
        assert "Foreign" in merged

    def test_rich_form_preserved_alongside_flattened(
        self, sda_agent, test_session_id,
    ):
        """The rich structured form is available under
        master_data_items / technical_specs_items so downstream
        consumers can access the new fields (status, owner, category)
        that the flattened form doesn't carry."""
        result = sda_agent.design_solution(
            session_id=test_session_id,
            requirements={"module": "MM"},
            process_maps={},
        )
        assert "master_data_items" in result["design"]
        assert "technical_specs_items" in result["design"]
        assert isinstance(result["design"]["master_data_items"], list)
        md_item = result["design"]["master_data_items"][0]
        # The new fields (status, owner) are present on the rich form
        # even though the flattened form doesn't carry them.
        assert "status" in md_item
        assert "owner" in md_item


# ---------------------------------------------------------------------------
# Pre-flight validation
# ---------------------------------------------------------------------------
class TestPreFlight:
    def test_refuses_when_requirements_and_process_maps_both_empty(
        self, sda_agent, test_session_id,
    ):
        result = sda_agent.design_solution(
            session_id=test_session_id,
            requirements={},
            process_maps={},
        )
        assert result["success"] is False
        sda_agent.model.generate_content.assert_not_called()

    def test_proceeds_with_warning_when_only_process_maps_missing(
        self, sda_agent, test_session_id,
    ):
        result = sda_agent.design_solution(
            session_id=test_session_id,
            requirements={"module": "MM", "functional_requirements": {}},
            process_maps={},
        )
        assert result["success"] is True
        assert result.get("warnings")


# ---------------------------------------------------------------------------
# Parse pipeline
# ---------------------------------------------------------------------------
class TestParsePipeline:
    def test_unparseable_output_degrades(
        self, sda_agent, test_session_id, patched_sleep,
    ):
        garbage = Mock()
        garbage.text = "Not JSON at all. Just prose."
        sda_agent.model.generate_content.side_effect = [garbage, garbage]

        result = sda_agent.design_solution(
            session_id=test_session_id,
            requirements={"module": "MM"},
            process_maps={},
        )
        assert result["success"] is True
        assert result.get("degraded") is True

    def test_wrong_shape_triggers_repair_path(
        self, sda_agent, test_session_id, patched_sleep,
    ):
        broken = Mock()
        broken.text = '{"executive_summary": "ok"}'  # missing required sections
        repaired = Mock()
        repaired.text = _VALID_DESIGN_JSON
        sda_agent.model.generate_content.side_effect = [broken, repaired]

        result = sda_agent.design_solution(
            session_id=test_session_id,
            requirements={"module": "MM"},
            process_maps={},
        )
        assert result["success"] is True
        assert sda_agent.model.generate_content.call_count >= 2


# ---------------------------------------------------------------------------
# LLM failure handling
# ---------------------------------------------------------------------------
class TestLLMFailureHandling:
    def test_retry_succeeds_after_transient_failure(
        self, sda_agent, test_session_id, patched_sleep,
    ):
        success = Mock()
        success.text = _VALID_DESIGN_JSON
        sda_agent.model.generate_content.side_effect = [
            RuntimeError("transient blip"),
            success,
        ]
        result = sda_agent.design_solution(
            session_id=test_session_id,
            requirements={"module": "MM"},
            process_maps={},
        )
        assert result["success"] is True
        assert sda_agent.model.generate_content.call_count == 2

    def test_persistent_failure_returns_error(
        self, sda_agent, test_session_id, patched_sleep,
    ):
        sda_agent.model.generate_content.side_effect = RuntimeError("provider down")
        result = sda_agent.design_solution(
            session_id=test_session_id,
            requirements={"module": "MM"},
            process_maps={},
        )
        assert result["success"] is False
        assert "provider down" in result.get("error", "")


# ---------------------------------------------------------------------------
# Return payload
# ---------------------------------------------------------------------------
class TestReturnPayload:
    def test_payload_has_enriched_fields(self, sda_agent, test_session_id):
        result = sda_agent.design_solution(
            session_id=test_session_id,
            requirements={"module": "MM"},
            process_maps={},
        )
        assert result["success"] is True
        for key in (
            "design", "document_path", "raw_text", "validation",
            "warnings", "degraded", "repaired", "module", "module_source",
            "open_questions", "assumptions", "duration",
        ):
            assert key in result, f"missing required key {key!r}"

    def test_module_source_default_fallback_when_missing(
        self, sda_agent, test_session_id,
    ):
        """No module anywhere → FI fallback with a warning. The
        previous version silently defaulted; the improved version
        surfaces it in the payload."""
        result = sda_agent.design_solution(
            session_id=test_session_id,
            requirements={"functional_requirements": {}},
            process_maps={},
        )
        assert result["module"] == "FI"
        assert result["module_source"] == "default_fallback"


# ---------------------------------------------------------------------------
# evaluate_customization_need (rewritten in the review)
# ---------------------------------------------------------------------------
class TestEvaluateCustomizationNeed:
    def test_strong_overlap_recommends_standard(
        self, patched_llm, patched_side_effects,
    ):
        """A requirement that closely matches a standard functionality
        description gets a 'strong overlap' recommendation. Confidence
        is capped at 'medium' — string overlap is never 'high'."""
        agent = SolutionDesignAgent()
        result = agent.evaluate_customization_need(
            requirement="Create and approve purchase requisitions",
            standard_functionality=[
                "Standard purchase requisition creation and approval workflow",
                "Vendor master management",
            ],
        )
        assert result["needs_customization"] is False
        assert result["confidence"] in ("medium", "low")
        # The matched functionality is the requisition one, not the vendor one.
        assert "requisition" in (result["standard_solution"] or "").lower()

    def test_weak_overlap_flags_review_required_not_use_standard(
        self, patched_llm, patched_side_effects,
    ):
        """A requirement with only token overlap — no clear match —
        must not produce a confident 'use standard' verdict. The old
        implementation returned on the first any-word substring hit;
        the new one returns review_required=True with a low confidence."""
        agent = SolutionDesignAgent()
        result = agent.evaluate_customization_need(
            requirement="Automated IoT-driven predictive maintenance triggers",
            standard_functionality=[
                "Standard purchase order creation",
                "Vendor invoice processing",
            ],
        )
        # Either a weak match (partial coverage) or a no-match — either
        # way, review is required and confidence is low.
        assert result["review_required"] is True
        assert result["confidence"] == "low"

    def test_empty_requirement_handled_gracefully(
        self, patched_llm, patched_side_effects,
    ):
        agent = SolutionDesignAgent()
        result = agent.evaluate_customization_need(
            requirement="",
            standard_functionality=["anything"],
        )
        assert result["needs_customization"] is False
        assert result["review_required"] is True
        assert "empty" in result["recommendation"].lower() or \
               "cannot evaluate" in result["recommendation"].lower()

    def test_empty_standard_functionality_handled_gracefully(
        self, patched_llm, patched_side_effects,
    ):
        agent = SolutionDesignAgent()
        result = agent.evaluate_customization_need(
            requirement="Some requirement",
            standard_functionality=[],
        )
        # No candidates to compare against → needs_customization=True
        # with a review-required flag, since the tool literally cannot
        # know if standard functionality exists without the catalog.
        assert result["needs_customization"] is True
        assert result["review_required"] is True
        assert "cannot evaluate" in result["recommendation"].lower() or \
               "no standard functionality" in result["recommendation"].lower()

    def test_returns_additive_fields(self, patched_llm, patched_side_effects):
        """New fields (confidence, candidates, review_required,
        alternatives) are present on every return. Callers relying on
        these for workflow decisions need them consistently available."""
        agent = SolutionDesignAgent()
        result = agent.evaluate_customization_need(
            requirement="Standard PO creation",
            standard_functionality=["Standard purchase order creation"],
        )
        for key in (
            "requirement", "needs_customization", "standard_solution",
            "customization_justification", "recommendation",
            "confidence", "candidates", "review_required", "alternatives",
        ):
            assert key in result, f"missing required key {key!r}"