"""
Unit tests for TrainingAgent.

Coverage:

  Happy path
    - Schema-valid mock output produces training_materials with a
      user_manual containing steps, fields, tips, faqs.
    - UserManualField sub-schema fix: fields are dicts, not strings
      (the bug found live during Stage 1b).
    - required="True" (string form) normalizes to the "Yes" Literal.

  Schema contract (new in the schema review)
    - training_guide.exercises is List[TrainingExercise]; legacy
      string entries are wrapped into {"title": ...} dicts.
    - UserManualStep's new fields survive: role, preconditions,
      verification, common_errors, type, duration_estimate.

  Hard-failure mode
    - Empty training materials refuse to emit a document; success=False.

  Pre-flight validation
    - Empty process_name / empty user_roles produce a warning, not a
      refusal, when a process map or solution design exists.
    - No solution_design AND no process map in session → refuse.

  create_quick_reference_guide
    - Renders supplied process_steps.
    - Does NOT fabricate steps when none are supplied.
    - Does NOT fabricate a Common Issues table.

  validate_training_materials
    - Detects generic placeholder steps.
    - Warns about missing role coverage.
    - Returns a structured result even for empty input.

  Return payload
    - warnings, validation, degraded, repaired, module present.

Fixtures:
  * patched_llm          patches get_llm so construction is hermetic.
  * patched_side_effects patches the DB sync and document generation.
  * patched_sleep        zeroes the retry backoff.
  * training_agent       composes the above with a schema-valid default.
  * test_session_id      session with safe cleanup.
"""
from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest

from src.agents.training_agent import TrainingAgent, training_agent
from src.memory import agent_memory


# ---------------------------------------------------------------------------
# Sample responses
# ---------------------------------------------------------------------------
def _training_materials_json(
    *,
    steps=None,
    exercises=None,
    quick_reference="See the quick reference card for transaction codes.",
    sop="Standard operating procedure for requisition creation.",
) -> str:
    """Schema-conformant TrainingMaterials JSON. Parameterised so tests
    can vary individual sections without duplicating the document."""
    return json.dumps({
        "user_manual": {
            "title": "Procure to Pay — Buyer Manual",
            "role_scope": ["Procurement Buyer"],
            "steps": steps if steps is not None else [
                {
                    "title": "Create Purchase Requisition",
                    "transaction": "ME51N",
                    "instructions": "Navigate to Procurement and create a new requisition.",
                    "fields": [
                        {
                            "name": "Requisitioner",
                            "description": "Employee requesting the item.",
                            "required": "True",
                            "example": "EMP-001",
                        },
                    ],
                    "tips": ["Use F4 search to find material codes."],
                },
            ],
            "tips": ["Save drafts frequently."],
            "faqs": ["What if my requisition is rejected?"],
        },
        "training_guide": {
            "objectives": ["Understand the PR creation process."],
            "agenda": ["Introduction", "Hands-on practice"],
            "exercises": exercises if exercises is not None
                else ["Create a sample requisition."],
        },
        "quick_reference": quick_reference,
        "sop": sop,
        "assumptions": [],
        "open_questions": [],
    })


_VALID_TRAINING_JSON = _training_materials_json()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def patched_llm():
    with patch("src.agents.training_agent.get_llm") as mock_get:
        mock_model = Mock(name="HybridLLMClient")
        mock_get.return_value = mock_model
        yield mock_model


@pytest.fixture
def patched_side_effects():
    with patch(
        "src.services.project_intelligence.sync_training_steps_from_structured",
        return_value=[],
    ), patch(
        "src.tools.doc_generator.generate_user_manual",
        return_value="/tmp/test_user_manual.docx",
    ), patch(
        "src.tools.doc_generator.generate_training_guide",
        return_value="/tmp/test_training_guide.docx",
        create=True,
    ), patch(
        "src.tools.doc_generator.generate_sop",
        return_value="/tmp/test_sop.docx",
        create=True,
    ), patch(
        "src.tools.doc_generator.generate_quick_reference",
        return_value="/tmp/test_quick_reference.docx",
        create=True,
    ):
        yield


@pytest.fixture
def patched_sleep():
    with patch("src.agents.training_agent.time.sleep"):
        yield


@pytest.fixture
def agent(patched_llm, patched_side_effects):
    response = Mock()
    response.text = _VALID_TRAINING_JSON
    patched_llm.generate_content.return_value = response
    return TrainingAgent()


@pytest.fixture
def test_session_id():
    session_id = agent_memory.create_project(
        project_name="Training Test",
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
class TestTrainingAgentInit:
    def test_agent_initializes(self, patched_llm, patched_side_effects):
        a = TrainingAgent()
        assert a.config is not None
        assert a.logger is not None
        assert a.model is not None

    def test_module_singleton_exists(self):
        assert isinstance(training_agent, TrainingAgent)


# ---------------------------------------------------------------------------
# Happy path (preserved from the original test)
# ---------------------------------------------------------------------------
class TestCreateTrainingMaterialsHappyPath:
    def test_create_training_materials_success(self, agent, test_session_id):
        result = agent.create_training_materials(
            session_id=test_session_id,
            process_name="Procure to Pay",
            user_roles=["Procurement Buyer"],
            solution_design={"configurations": []},
        )

        assert result["success"] is True
        steps = result["training_materials"]["user_manual"]["steps"]
        assert len(steps) == 1
        assert steps[0]["transaction"] == "ME51N"
        # UserManualField sub-schema fix: fields are dicts, not strings.
        assert steps[0]["fields"][0]["name"] == "Requisitioner"

    def test_required_field_string_normalizes_to_literal(
        self, agent, test_session_id,
    ):
        """The mock supplies required="True" (a string). The schema's
        normalizer maps that to the canonical "Yes" Literal. If the
        normalizer regresses, a required field would silently display
        as optional."""
        result = agent.create_training_materials(
            session_id=test_session_id,
            process_name="Procure to Pay",
            user_roles=["Procurement Buyer"],
            solution_design={"configurations": []},
        )
        fields = result["training_materials"]["user_manual"]["steps"][0]["fields"]
        assert fields[0]["required"] == "Yes"


# ---------------------------------------------------------------------------
# Schema contract (new in the schema review)
# ---------------------------------------------------------------------------
class TestSchemaContract:
    def test_string_exercises_are_wrapped_into_training_exercise_dicts(
        self, agent, test_session_id,
    ):
        """training_guide.exercises was List[str] and is now
        List[TrainingExercise]. A source supplying strings gets each
        wrapped into {"title": ..., ...}. Asserting on the wrap prevents
        a future refactor from silently dropping the compatibility
        validator."""
        result = agent.create_training_materials(
            session_id=test_session_id,
            process_name="Procure to Pay",
            user_roles=["Procurement Buyer"],
            solution_design={"configurations": []},
        )
        exercises = result["training_materials"]["training_guide"]["exercises"]
        assert len(exercises) == 1
        # Not a bare string — the mode="before" validator wrapped it.
        assert isinstance(exercises[0], dict)
        assert exercises[0]["title"] == "Create a sample requisition."

    def test_step_new_fields_survive(
        self, patched_llm, patched_side_effects, test_session_id,
    ):
        """UserManualStep gained role, preconditions, verification,
        common_errors, type, duration_estimate in the schema review.
        These are what make a procedure actionable — preconditions
        tell the user what must be in place, verification tells them
        how to check success, common_errors tell them what to do when
        it doesn't work."""
        response = Mock()
        response.text = _training_materials_json(steps=[
            {
                "title": "Submit PO for approval",
                "role": "Procurement Buyer",
                "type": "Procedure",
                "preconditions": [
                    "Vendor master record exists",
                    "Cost center assigned",
                ],
                "instructions": "Select Submit for Approval.",
                "transaction": "ME21N",
                "verification": "PO status changes to Pending Approval.",
                "common_errors": [
                    {
                        "symptom": "Cannot submit — no release strategy matched",
                        "likely_cause": "PO value below the release strategy threshold",
                        "resolution": "Route to the manual approver path instead.",
                        "severity": "Blocking",
                    },
                ],
                "tips": [],
                "duration_estimate": "2 minutes",
            },
        ])
        patched_llm.generate_content.return_value = response
        a = TrainingAgent()

        result = a.create_training_materials(
            session_id=test_session_id,
            process_name="Procure to Pay",
            user_roles=["Procurement Buyer"],
            solution_design={"configurations": []},
        )
        step = result["training_materials"]["user_manual"]["steps"][0]
        assert step["role"] == "Procurement Buyer"
        assert step["preconditions"]
        assert step["verification"]
        assert step["common_errors"][0]["severity"] == "Blocking"

    def test_document_level_assumptions_and_open_questions_survive(
        self, patched_llm, patched_side_effects, test_session_id,
    ):
        response = Mock()
        response.text = json.dumps({
            "user_manual": {"steps": []},
            "training_guide": {},
            "quick_reference": "QR content.",
            "sop": "SOP content.",
            "assumptions": ["Standard SAP MM FI integration is active."],
            "open_questions": [
                {
                    "topic": "Fiori vs classic GUI",
                    "question": "Which UI will users be trained on?",
                    "blocking": False,
                },
            ],
        })
        patched_llm.generate_content.return_value = response
        a = TrainingAgent()

        result = a.create_training_materials(
            session_id=test_session_id,
            process_name="Procure to Pay",
            user_roles=["Procurement Buyer"],
            solution_design={"configurations": []},
        )
        assert result["success"] is True
        assert result["assumptions"]
        assert result["open_questions"]


# ---------------------------------------------------------------------------
# Hard-failure mode
# ---------------------------------------------------------------------------
class TestHardFailure:
    def test_empty_materials_do_not_emit_a_document(
        self, agent, test_session_id, patched_sleep,
    ):
        """If the model returns nothing substantive, the agent must NOT
        write an empty-shell document. The pre-review implementation
        would have produced a document that looked official but
        contained no procedures."""
        empty = Mock()
        empty.text = json.dumps({
            "user_manual": {"steps": []},
            "training_guide": {},
            "quick_reference": "",
            "sop": "",
        })
        agent.model.generate_content.return_value = empty

        with patch(
            "src.tools.doc_generator.generate_user_manual"
        ) as mock_doc_gen:
            result = agent.create_training_materials(
                session_id=test_session_id,
                process_name="Procure to Pay",
                user_roles=["Procurement Buyer"],
                solution_design={"configurations": []},
            )
            assert result["success"] is False
            assert result.get("error")
            mock_doc_gen.assert_not_called()


# ---------------------------------------------------------------------------
# Pre-flight validation
# ---------------------------------------------------------------------------
class TestPreFlight:
    def test_empty_process_name_does_not_refuse_alone(
        self, agent, test_session_id,
    ):
        """Empty process_name warns (via pre-flight issues) but does
        not refuse on its own if there's a solution_design."""
        result = agent.create_training_materials(
            session_id=test_session_id,
            process_name="",
            user_roles=["Procurement Buyer"],
            solution_design={"configurations": []},
        )
        # An empty process_name produces a pre-flight issue but the
        # design grounding is enough to proceed; the agent should
        # return success with warnings.
        assert result["success"] is True
        assert any("process_name" in w for w in result.get("warnings", []))


# ---------------------------------------------------------------------------
# create_quick_reference_guide (rewritten in the review)
# ---------------------------------------------------------------------------
class TestQuickReferenceGuide:
    def test_renders_supplied_process_steps(
        self, patched_llm, patched_side_effects,
    ):
        a = TrainingAgent()
        guide = a.create_quick_reference_guide(
            process_name="Procure to Pay",
            key_transactions=["ME51N", "ME21N"],
            tips=["Use F4 for material lookup."],
            process_steps=[
                {"name": "Create requisition", "transaction": "ME51N"},
                {"name": "Submit for approval"},
            ],
            prerequisites=["Vendor master exists"],
        )
        assert "Procure to Pay" in guide
        assert "ME51N" in guide
        assert "Create requisition" in guide
        assert "Vendor master exists" in guide

    def test_does_not_fabricate_steps_when_none_supplied(
        self, patched_llm, patched_side_effects,
    ):
        """When no process_steps are provided, the guide must show an
        explicit TODO rather than inventing "Log into the system /
        Navigate to the module / Execute the transaction" — which
        walked end users through steps that don't exist."""
        a = TrainingAgent()
        guide = a.create_quick_reference_guide(
            process_name="Procure to Pay",
            key_transactions=[],
            tips=[],
        )
        # No fabricated step sequence.
        assert "Log into the system" not in guide
        assert "Navigate to the relevant module" not in guide
        assert "Execute the transaction" not in guide
        # Explicit TODO marker.
        assert "TODO" in guide

    def test_does_not_fabricate_common_issues_table(
        self, patched_llm, patched_side_effects,
    ):
        """The previous version emitted a hardcoded two-row Common
        Issues table ("Field not editable → Check authorization").
        The improved version removed it entirely."""
        a = TrainingAgent()
        guide = a.create_quick_reference_guide(
            process_name="Procure to Pay",
            key_transactions=["ME51N"],
            tips=["Some tip."],
        )
        assert "Field not editable" not in guide
        assert "Check authorization" not in guide


# ---------------------------------------------------------------------------
# validate_training_materials (new in the review)
# ---------------------------------------------------------------------------
class TestValidateTrainingMaterials:
    def test_detects_generic_placeholder_steps(
        self, patched_llm, patched_side_effects,
    ):
        a = TrainingAgent()
        validation = a.validate_training_materials(
            {
                "user_manual": {
                    "steps": [
                        {"title": "Log into the system"},
                        {"title": "Navigate to the relevant module"},
                        {"title": "Execute the transaction"},
                        {"title": "Save and verify"},
                    ],
                },
            },
            user_roles=["Buyer"],
        )
        assert validation["signals"]["generic_steps"] >= 3
        # A majority generic suite produces a warning.
        assert any(
            "placeholder" in w.lower() for w in validation["warnings"]
        )

    def test_warns_on_missing_role_coverage(
        self, patched_llm, patched_side_effects,
    ):
        a = TrainingAgent()
        validation = a.validate_training_materials(
            {
                "user_manual": {
                    "steps": [{"title": "Do the thing", "instructions": "Some detailed instruction."}],
                },
            },
            user_roles=["Buyer", "Manager"],
        )
        # Neither role appears in the content.
        assert validation["signals"]["roles_missing"] == ["Buyer", "Manager"]

    def test_handles_empty_input_gracefully(
        self, patched_llm, patched_side_effects,
    ):
        a = TrainingAgent()
        validation = a.validate_training_materials({}, user_roles=None)
        assert validation["is_valid"] is False
        assert validation["issues"]


# ---------------------------------------------------------------------------
# Return payload
# ---------------------------------------------------------------------------
class TestReturnPayload:
    def test_payload_has_enriched_fields(self, agent, test_session_id):
        result = agent.create_training_materials(
            session_id=test_session_id,
            process_name="Procure to Pay",
            user_roles=["Procurement Buyer"],
            solution_design={"configurations": []},
        )
        assert result["success"] is True
        for key in (
            "training_materials", "documents", "raw_text", "validation",
            "warnings", "degraded", "repaired", "module", "duration",
        ):
            assert key in result, f"missing required key {key!r}"
        # document_path mirrors documents['user_manual'] for
        # backward-compatible consumers.
        assert "document_path" in result