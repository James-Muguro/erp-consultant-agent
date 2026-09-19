"""
Pydantic schema for structured training materials output.

Used to constrain and validate LLM JSON responses for the Training Agent.

Design priorities:
  * Procedures must be actionable. Every `UserManualStep` carries the
    fields an end user needs to execute the step: prerequisites,
    instructions, verification (how they know it worked), and known
    errors with resolutions. Training content that only has "instructions"
    leaves users stuck the first time something doesn't go as expected.
  * Role-specific content is a first-class concept. Steps can name the
    role that performs them, and the manual can declare which roles it
    covers, so a role-specific manual can be extracted by filtering.
  * Traceability to requirements AND process steps. Training usually
    follows the process map more closely than the requirements list, so
    both link types are supported and neither is guessed.
  * No invented specifics. Field descriptions enforce the "TBD — confirm
    with the implementation team" rule for menu paths, T-codes, and field
    names the model is not certain of.
  * Unresolved unknowns surface in `open_questions` and `assumptions`
    rather than being papered over.

Field constraints use only JSON-Schema constructs supported by Gemini and
OpenAI structured-output APIs. Richer validation lives in
`@field_validator`s, which do not appear in the generated JSON Schema.
"""
from __future__ import annotations

import re
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------
_STEP_ID_PATTERN = re.compile(r"^TSTEP-\d{3,}$")
_REQ_ID_PATTERN = re.compile(r"^REQ-\d{3,}$")
_PROC_STEP_ID_PATTERN = re.compile(r"^STEP-\d{3,}$")

_REQUIRED_CANONICAL = ("Yes", "No", "Conditional")
_REQUIRED_ALIASES = {
    "yes": "Yes", "y": "Yes", "true": "Yes", "required": "Yes",
    "mandatory": "Yes", "must": "Yes",
    "no": "No", "n": "No", "false": "No", "not required": "No",
    "optional": "No",
    "conditional": "Conditional", "depending": "Conditional",
    "sometimes": "Conditional", "if applicable": "Conditional",
}

_STEP_TYPE_CANONICAL = (
    "Procedure", "Decision", "Check", "Warning", "Information", "Other"
)
_STEP_TYPE_ALIASES = {
    "procedure": "Procedure", "step": "Procedure", "action": "Procedure",
    "decision": "Decision", "branch": "Decision", "conditional": "Decision",
    "check": "Check", "verify": "Check", "validation": "Check",
    "warning": "Warning", "caution": "Warning", "note": "Warning",
    "information": "Information", "info": "Information", "background": "Information",
}


def _canonical_id(value: Any, prefix: str, pattern: re.Pattern) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    if pattern.match(s):
        return s
    m = re.match(r"^[A-Za-z_\-]*?(\d+)$", s)
    if m:
        return f"{prefix}-{int(m.group(1)):03d}"
    return s


def _normalize_requirement_id(value: Any) -> str:
    if value is None:
        return "REQ-000"
    s = str(value).strip()
    if not s:
        return "REQ-000"
    if _REQ_ID_PATTERN.match(s):
        return s
    m = re.match(r"^[A-Za-z_\-]*?(\d+)$", s)
    if m:
        return f"REQ-{int(m.group(1)):03d}"
    return s


def _normalize_process_step_id(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    if _PROC_STEP_ID_PATTERN.match(s):
        return s
    m = re.match(r"^[A-Za-z_\-]*?(\d+)$", s)
    if m:
        return f"STEP-{int(m.group(1)):03d}"
    return s


def _norm_req_id_list(v: Any) -> List[str]:
    if v is None:
        return []
    if not isinstance(v, list):
        v = [v]
    return [_normalize_requirement_id(x) for x in v if x is not None and str(x).strip()]


def _norm_step_id_list(v: Any) -> List[str]:
    if v is None:
        return []
    if not isinstance(v, list):
        v = [v]
    return [_normalize_process_step_id(x) for x in v if x is not None and str(x).strip()]


def _normalize_required(value: Any) -> str:
    if value is None:
        return "No"
    s = str(value).strip().lower()
    if not s:
        return "No"
    if s in _REQUIRED_ALIASES:
        return _REQUIRED_ALIASES[s]
    for canonical in _REQUIRED_CANONICAL:
        if s == canonical.lower():
            return canonical
    # Bool-like values that arrived as their str() form.
    if s in ("1", "yes", "y", "true", "t"):
        return "Yes"
    if s in ("0", "no", "n", "false", "f"):
        return "No"
    return "No"


def _normalize_step_type(value: Any) -> str:
    if value is None:
        return "Procedure"
    s = str(value).strip()
    if not s:
        return "Procedure"
    if s in _STEP_TYPE_CANONICAL:
        return s
    alias = _STEP_TYPE_ALIASES.get(s.lower())
    if alias:
        return alias
    for c in _STEP_TYPE_CANONICAL:
        if s.lower() == c.lower():
            return c
    low = s.lower()
    for c in _STEP_TYPE_CANONICAL:
        if c.lower() in low:
            return c
    return "Other"


# ---------------------------------------------------------------------------
# Field-level structures
# ---------------------------------------------------------------------------
class UserManualField(BaseModel):
    """A data field the user interacts with during a step. Explaining fields
    separately from prose instructions makes the manual scannable and lets
    reviewers check that no required field was missed."""
    model_config = ConfigDict(extra="ignore")

    name: str = Field(
        default="",
        description="Field label as the user sees it in the system. If you "
                    "are not certain of the exact label, write the business "
                    "name and mark it TBD — do not invent a system label.",
    )
    description: str = Field(
        default="",
        description="What the field means and how the user should fill it.",
    )
    required: Literal["Yes", "No", "Conditional"] = Field(
        default="No",
        description="Yes if the field must be filled to proceed, No if it "
                    "can be left blank, Conditional if it depends on the "
                    "scenario. If unsure, leave as No and add a note to "
                    "open_questions rather than guessing.",
    )
    example: str = Field(
        default="",
        description="A representative value. Do NOT use real customer names, "
                    "vendor numbers, employee IDs, or account numbers — use "
                    "a placeholder like '<vendor number>' and mark it "
                    "'TBD — training example'.",
    )

    @field_validator("required", mode="before")
    @classmethod
    def _norm_required(cls, v: Any) -> str:
        return _normalize_required(v)


class KnownError(BaseModel):
    """A common error a user may hit at a step, with its cause and remedy.
    Structured so it can be rendered as a troubleshooting table and so it
    can be filtered by severity or by symptom."""
    model_config = ConfigDict(extra="ignore")

    symptom: str = Field(
        default="",
        description="What the user sees (message text, blocked action, "
                    "unexpected result).",
    )
    likely_cause: str = Field(
        default="",
        description="The most likely reason. If you don't know, leave empty "
                    "and note the step in open_questions — do not invent a "
                    "plausible-sounding cause.",
    )
    resolution: str = Field(
        default="",
        description="What the user should do. If resolution requires IT or "
                    "support, say so explicitly.",
    )
    severity: Literal["Blocking", "Warning", "Cosmetic"] = Field(
        default="Warning",
        description="Blocking: the user cannot proceed. Warning: they can "
                    "proceed but the outcome may be wrong. Cosmetic: display "
                    "or formatting only.",
    )


class TrainingExercise(BaseModel):
    """A practice activity for the training guide. Structured so the
    facilitator and the trainee both know what to do and what success
    looks like."""
    model_config = ConfigDict(extra="ignore")

    title: str = Field(
        default="",
        description="Short name for the exercise, e.g. 'Create a purchase "
                    "order above the approval threshold'.",
    )
    scenario: str = Field(
        default="",
        description="The situation the trainee is placed in.",
    )
    role: str = Field(
        default="",
        description="The role the trainee plays in this exercise. Should "
                    "match a role from the training guide's audience.",
    )
    expected_outcome: str = Field(
        default="",
        description="What a correctly completed exercise looks like. "
                    "Observable and specific.",
    )
    duration_minutes: Optional[int] = Field(
        default=None,
        description="Estimated time to complete, if known. Drives agenda "
                    "planning.",
    )


# ---------------------------------------------------------------------------
# User manual
# ---------------------------------------------------------------------------
class UserManualStep(BaseModel):
    """One procedure step in the user manual. The step is the unit of
    instruction — it should be executable on its own given its
    preconditions, and verifiable via its verification field."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(
        default="",
        description="Unique identifier, canonical form TSTEP-001. "
                    "Auto-assigned if omitted.",
    )
    title: str = Field(
        default="",
        description="Short imperative title for the step, e.g. 'Enter the "
                    "vendor number and press Enter'.",
    )
    type: Literal[
        "Procedure", "Decision", "Check", "Warning", "Information", "Other"
    ] = Field(
        default="Procedure",
        description="Procedure for a normal action step; Decision when the "
                    "user must branch; Check when they verify something; "
                    "Warning for cautions; Information for background.",
    )
    role: str = Field(
        default="",
        description="The single role that performs this step. Leave empty "
                    "only if the step is genuinely role-agnostic.",
    )
    preconditions: List[str] = Field(
        default_factory=list,
        description="What must be in place before the step can be executed: "
                    "master data, prior step completed, authorization, "
                    "configuration. State in business terms.",
    )
    instructions: str = Field(
        default="",
        description="Step-by-step what the user does. One action per sentence. "
                    "Reference the exact screen/field/app if you are certain "
                    "of it; otherwise mark the missing detail as TBD rather "
                    "than inventing a path, T-code, or field label.",
    )
    fields: List[UserManualField] = Field(
        default_factory=list,
        description="Data fields the user interacts with at this step.",
    )
    transaction: str = Field(
        default="",
        description="Transaction code, app ID, or function name for this "
                    "step. Leave empty and note in open_questions if unknown "
                    "— never invent T-codes, Fiori app IDs, or Oracle form "
                    "names.",
    )
    verification: str = Field(
        default="",
        description="How the user knows the step succeeded: an observable "
                    "outcome (message text, record status, downstream "
                    "document created). Distinct from instructions — this "
                    "is the check the user performs after acting.",
    )
    common_errors: List[KnownError] = Field(
        default_factory=list,
        description="Known errors at this step with cause and resolution. "
                    "Include only errors you are confident occur — a "
                    "speculative troubleshooting list is worse than none.",
    )
    tips: List[str] = Field(
        default_factory=list,
        description="Practical shortcuts, keyboard hints, or best practices "
                    "specific to this step.",
    )
    duration_estimate: str = Field(
        default="",
        description="Approximate time to execute, e.g. '2 minutes'. Useful "
                    "for training time budgeting. Leave empty if unknown.",
    )
    related_requirement_ids: List[str] = Field(
        default_factory=list,
        description="Requirement ID codes (canonical form 'REQ-001') that "
                    "this step covers. Leave empty if none clearly apply — "
                    "never guess.",
    )
    related_process_step_ids: List[str] = Field(
        default_factory=list,
        description="Process step IDs (canonical form 'STEP-001') from the "
                    "process map that this training step corresponds to. "
                    "Preferred over requirements linking for training "
                    "content — leave empty if none clearly apply.",
    )

    @field_validator("id", mode="before")
    @classmethod
    def _norm_id(cls, v: Any) -> str:
        return _canonical_id(v, "TSTEP", _STEP_ID_PATTERN)

    @field_validator("type", mode="before")
    @classmethod
    def _norm_type(cls, v: Any) -> str:
        return _normalize_step_type(v)

    @field_validator("related_requirement_ids", mode="before")
    @classmethod
    def _norm_req_ids(cls, v: Any) -> List[str]:
        return _norm_req_id_list(v)

    @field_validator("related_process_step_ids", mode="before")
    @classmethod
    def _norm_process_step_ids(cls, v: Any) -> List[str]:
        return _norm_step_id_list(v)


class UserManual(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(
        default="",
        description="Human-readable title for the manual, e.g. 'Procure to "
                    "Pay — Buyer User Manual'.",
    )
    role_scope: List[str] = Field(
        default_factory=list,
        description="Roles this manual is written for. Empty means the "
                    "manual covers all roles in the process.",
    )
    steps: List[UserManualStep] = Field(
        default_factory=list,
        description="Ordered steps of the procedure. Order matters — this "
                    "is the sequence a user follows.",
    )
    tips: List[str] = Field(
        default_factory=list,
        description="Document-wide tips not tied to a specific step.",
    )
    faqs: List[str] = Field(
        default_factory=list,
        description="Document-wide FAQs. Each entry should be a "
                    "question-and-answer pair, phrased as the user would "
                    "ask it.",
    )


# ---------------------------------------------------------------------------
# Training guide
# ---------------------------------------------------------------------------
class TrainingGuide(BaseModel):
    model_config = ConfigDict(extra="ignore")

    objectives: List[str] = Field(
        default_factory=list,
        description="What learners should be able to do by the end. "
                    "Specific and testable, not 'understand the system'.",
    )
    agenda: List[str] = Field(
        default_factory=list,
        description="Session agenda entries. Include duration where relevant "
                    "(e.g. 'Welcome and objectives — 15 min').",
    )
    exercises: List[TrainingExercise] = Field(
        default_factory=list,
        description="Practice activities. Structured so each has a "
                    "scenario, a role, and an expected outcome.",
    )

    @field_validator("exercises", mode="before")
    @classmethod
    def _accept_string_exercises(cls, v: Any) -> Any:
        """Accept legacy list-of-strings form (also produced by the
        heuristic parser) and wrap each string as a minimal exercise, so
        older outputs remain valid without a schema change at the caller."""
        if not isinstance(v, list):
            return v
        wrapped: List[Any] = []
        for item in v:
            if isinstance(item, str):
                wrapped.append({"title": item})
            else:
                wrapped.append(item)
        return wrapped


# ---------------------------------------------------------------------------
# Open questions (same pattern as the other schemas)
# ---------------------------------------------------------------------------
class OpenQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    topic: str = Field(default="", description="Short label for the question.")
    question: str = Field(
        default="",
        description="The question, phrased so the implementation team can "
                    "answer it directly.",
    )
    blocking: bool = Field(
        default=False,
        description="True only if the training material cannot be finalized "
                    "without an answer. Use sparingly.",
    )
    owner: Optional[str] = Field(
        default=None,
        description="Role expected to resolve this. Null if unknown.",
    )
    related_step_ids: List[str] = Field(
        default_factory=list,
        description="UserManualStep IDs affected by this question, if any.",
    )

    @field_validator("related_step_ids", mode="before")
    @classmethod
    def _norm_step_ids(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            v = [v]
        return [_canonical_id(x, "TSTEP", _STEP_ID_PATTERN) for x in v if x]


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------
class TrainingMaterials(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # ---- document metadata -------------------------------------------- #
    process_name: str = Field(
        default="",
        description="Business process this material teaches. Should match "
                    "the process name used in the process map.",
    )
    module: str = Field(
        default="",
        description="ERP module code (e.g. 'MM', 'FI'). Leave empty if the "
                    "content spans multiple modules.",
    )
    audience: List[str] = Field(
        default_factory=list,
        description="Roles this material is written for. Redundant with "
                    "user_manual.role_scope by design — kept at document "
                    "level so quick_reference and sop can share the scope "
                    "without duplicating the field inside each artifact.",
    )

    # ---- artifacts ----------------------------------------------------- #
    user_manual: UserManual = Field(default_factory=UserManual)
    training_guide: TrainingGuide = Field(default_factory=TrainingGuide)
    quick_reference: str = Field(
        default="",
        description="Short one-to-two-page markdown summary for quick "
                    "lookup. Plain markdown — no code blocks or HTML. Where "
                    "a transaction code or menu path is unknown, mark it "
                    "TBD rather than inventing one.",
    )
    sop: str = Field(
        default="",
        description="Standard operating procedure as markdown. Should read "
                    "as a formal process document: purpose, scope, roles, "
                    "procedure steps, controls, references. Where a specific "
                    "artifact is unknown, mark it TBD.",
    )

    # ---- unresolved items --------------------------------------------- #
    assumptions: List[str] = Field(
        default_factory=list,
        description="Statements taken as true without confirmation. If any "
                    "is wrong, the training material may need to change. "
                    "These must be listed so the implementation team can "
                    "validate them before the material is used.",
    )
    open_questions: List[OpenQuestion] = Field(
        default_factory=list,
        description="Gaps and ambiguities requiring resolution. Populate "
                    "this rather than inventing system details for unknowns.",
    )

    # ---- ID assignment ------------------------------------------------- #
    @field_validator("user_manual")
    @classmethod
    def _ensure_step_ids(cls, v: UserManual) -> UserManual:
        """Fill in missing step IDs so downstream linking (project_intelligence
        sync, cross-references in the SOP, exercise references) has a stable
        identifier even when the model omits one."""
        if v is None:
            return v
        for i, step in enumerate(v.steps, start=1):
            if not step.id:
                step.id = f"TSTEP-{i:03d}"
        return v