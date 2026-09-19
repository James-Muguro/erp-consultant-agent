"""
Pydantic schema for structured test case output.

Shared by the QA Testing Agent and UAT Testing Agent, since both feed the
same document_generator.generate_test_case_document().

Design notes:

  * This is intentionally one schema serving two agents. QA and UAT
    scenarios share a common shape (setup, steps, expected result,
    traceability) and diverge in emphasis. The divergence is carried by
    fields that are meaningful to one and left empty by the other:
      - QA usually populates `related_requirement_ids`,
        `related_process_step_ids`, `related_design_component`, and
        `execution_status`.
      - UAT usually populates `user_role`, `business_process`, and
        `acceptance_criteria` — the business sign-off criteria, distinct
        from the immediate expected result.
    The schema accommodates both without a discriminator field, so a
    downstream consumer can read either output with the same code.

  * Every traceability field exists because something downstream depends
    on it. Removing any of them silently breaks a coverage metric or a
    link into project_intelligence.

  * Field constraints use only JSON-Schema constructs supported by
    Gemini and OpenAI structured-output APIs. Richer validation lives in
    @field_validators, which do not appear in the generated schema.
"""
from __future__ import annotations

import re
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------
_TEST_ID_PATTERN = re.compile(r"^TC-[A-Fa-f0-9]{4,}$|^TC-\d{3,}$")
_REQ_ID_PATTERN = re.compile(r"^REQ-\d{3,}$")
_STEP_ID_PATTERN = re.compile(r"^STEP-\d{3,}$")

_PRIORITY_CANONICAL = ("Critical", "High", "Medium", "Low")
_PRIORITY_ALIASES = {
    "p1": "Critical", "urgent": "Critical", "blocker": "Critical",
    "p2": "High", "important": "High",
    "p3": "Medium", "normal": "Medium",
    "p4": "Low", "optional": "Low",
}

# Canonical case types. The set is deliberately exhaustive over what the
# QA guardrails and validators actually check for. Adding a category here
# is a schema change; using `Other` is the escape hatch.
_CASE_TYPES = (
    "Functional",
    "Negative",
    "Boundary",
    "Integration",
    "Security",
    "Data",
    "Regression",
    "Performance",
    "Usability",
    "Other",
)
_CASE_TYPE_ALIASES = {
    "positive": "Functional", "happy path": "Functional", "happy-path": "Functional",
    "negative": "Negative", "error": "Negative", "exception": "Negative",
    "boundary": "Boundary", "edge": "Boundary", "edge case": "Boundary",
    "integration": "Integration", "interface": "Integration", "api": "Integration",
    "security": "Security", "authorization": "Security", "auth": "Security",
    "permission": "Security", "sod": "Security",
    "data": "Data", "master data": "Data",
    "regression": "Regression",
    "performance": "Performance", "load": "Performance",
    "usability": "Usability", "ux": "Usability",
}


def _normalize_priority(value: Any) -> str:
    if value is None:
        return "Medium"
    s = str(value).strip()
    if not s:
        return "Medium"
    if s in _PRIORITY_CANONICAL:
        return s
    alias = _PRIORITY_ALIASES.get(s.lower())
    if alias:
        return alias
    for c in _PRIORITY_CANONICAL:
        if s.lower() == c.lower():
            return c
    return "Medium"


def _normalize_case_type(value: Any) -> str:
    if value is None:
        return "Functional"
    s = str(value).strip()
    if not s:
        return "Functional"
    if s in _CASE_TYPES:
        return s
    alias = _CASE_TYPE_ALIASES.get(s.lower())
    if alias:
        return alias
    for c in _CASE_TYPES:
        if s.lower() == c.lower():
            return c
    # Last resort: the model may have written something like
    # "Functional (positive)" — try a substring match on the canonical set.
    low = s.lower()
    for c in _CASE_TYPES:
        if c.lower() in low:
            return c
    return "Other"


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


def _normalize_step_id(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    if _STEP_ID_PATTERN.match(s):
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
    return [_normalize_step_id(x) for x in v if x is not None and str(x).strip()]


# ---------------------------------------------------------------------------
# Test data item
# ---------------------------------------------------------------------------
class TestDataItem(BaseModel):
    """A single named test data input. Kept as a list rather than a dict
    so duplicates don't silently collapse during model output, and so
    ordering is preserved. Flattened to a dict in to_legacy_dict() for
    backward compatibility with the document generator."""
    model_config = ConfigDict(extra="ignore")

    key: str = Field(
        default="",
        description="Name of the data input, e.g. 'Vendor number', "
                    "'PO value', 'Approver role'.",
    )
    value: str = Field(
        default="",
        description="The value to use, or 'TBD — confirm with business' if "
                    "the exact value must be supplied by the client. Do NOT "
                    "invent realistic-looking customer numbers, amounts, or "
                    "dates — use a placeholder instead.",
    )


# ---------------------------------------------------------------------------
# Test case
# ---------------------------------------------------------------------------
class TestCase(BaseModel):
    """One test case or one UAT scenario. Fields that are section-specific
    (see module docstring) default to empty when not applicable."""
    model_config = ConfigDict(extra="ignore")

    # ---- identity ------------------------------------------------------ #
    id: str = Field(
        default="",
        description="Unique identifier. QA uses content-addressed IDs of the "
                    "form TC-<hex>; other tools may use TC-NNN. Auto-assigned "
                    "by the calling agent if omitted.",
    )
    scenario: str = Field(
        default="",
        description="Short, specific title. 'Create PO over approval "
                    "threshold' is good; 'Test procurement' is not.",
    )
    objective: str = Field(
        default="",
        description="What this test proves. One sentence. Distinct from the "
                    "scenario title — states the business or technical "
                    "verification goal.",
    )

    # ---- classification ------------------------------------------------ #
    type: Literal[
        "Functional",
        "Negative",
        "Boundary",
        "Integration",
        "Security",
        "Data",
        "Regression",
        "Performance",
        "Usability",
        "Other",
    ] = Field(
        default="Functional",
        description="Category of test. Covered by the QA guardrails: a suite "
                    "with only Functional cases is incomplete and should be "
                    "flagged for review.",
    )
    priority: Literal["Critical", "High", "Medium", "Low"] = Field(
        default="Medium",
        description="Critical for regulatory, financial close, or go-live "
                    "blockers; High for core process; Medium/Low for edge cases.",
    )

    # ---- setup and execution ------------------------------------------- #
    preconditions: List[str] = Field(
        default_factory=list,
        description="Setup required before the test can run: master data, "
                    "prior document state, user role, active configuration.",
    )
    steps: List[str] = Field(
        default_factory=list,
        description="Discrete, executable actions. One action per step. A "
                    "step with an observable outcome; 'process the document' "
                    "is not acceptable.",
    )
    test_data: List[TestDataItem] = Field(
        default_factory=list,
        description="Named test data inputs. Use placeholders marked TBD for "
                    "values that must be supplied by the client.",
    )
    expected_result: str = Field(
        default="",
        description="Observable, specific outcome. 'System works correctly' "
                    "is not acceptable. State the exact UI state, message, "
                    "record status, or document number format a tester sees.",
    )

    # ---- UAT-specific -------------------------------------------------- #
    user_role: str = Field(
        default="",
        description="Primary business role that executes this scenario. "
                    "Populated for UAT; leave empty for QA cases that are "
                    "role-agnostic.",
    )
    business_process: str = Field(
        default="",
        description="Name of the business process this scenario validates. "
                    "Populated for UAT; drives process coverage reporting.",
    )
    acceptance_criteria: str = Field(
        default="",
        description="The criteria the business will use to sign this scenario "
                    "off. Distinct from expected_result: expected_result is "
                    "what the tester observes at the end; acceptance_criteria "
                    "is the business statement of 'this is acceptable'. "
                    "Populated for UAT; leave empty for QA.",
    )

    # ---- traceability -------------------------------------------------- #
    # All four traceability fields are populated only where genuinely
    # applicable — never guessed. An empty list is a valid, honest state
    # and is preferred over fabricated links.
    related_requirement_ids: List[str] = Field(
        default_factory=list,
        description="Requirement ID codes (canonical form 'REQ-001') this "
                    "test validates. Leave empty if none clearly apply — "
                    "never guess.",
    )
    related_process_step_ids: List[str] = Field(
        default_factory=list,
        description="Process step IDs (canonical form 'STEP-001') this test "
                    "exercises. Leave empty if none clearly apply.",
    )
    related_design_component: str = Field(
        default="",
        description="The design component (configuration, integration, or "
                    "customization) this test verifies. Free-form short label "
                    "matching the design document. Leave empty if none clearly "
                    "applies.",
    )

    # ---- execution results (optional; populated only when known) ------- #
    # These fields describe the *outcome* of a test, if it has been
    # executed. When the requirements/context does not describe an outcome,
    # they must remain at defaults — a fabricated 'passed' result is worse
    # than an honest 'not_run' because it misrepresents system readiness.
    execution_status: Literal["not_run", "passed", "failed", "blocked"] = Field(
        default="not_run",
        description="Only set to passed/failed/blocked if the input explicitly "
                    "describes a test outcome. Otherwise leave as not_run; "
                    "never guess a result.",
    )
    failure_classification: Optional[Literal[
        "defect",
        "unclear_requirement",
        "changed_requirement",
        "data_issue",
        "integration_issue",
        "environment_issue",
        "other",
    ]] = Field(
        default=None,
        description="Only set when execution_status is 'failed'. Classifies "
                    "the cause so trend analysis can drive the right fix.",
    )
    failure_description: Optional[str] = Field(
        default=None,
        description="Only set when execution_status is 'failed'. Concrete "
                    "description of what went wrong, grounded in the given "
                    "context — never fabricated.",
    )

    # ---- cross-field validators ---------------------------------------- #
    @field_validator("id", mode="before")
    @classmethod
    def _norm_id(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v).strip()

    @field_validator("priority", mode="before")
    @classmethod
    def _norm_priority(cls, v: Any) -> str:
        return _normalize_priority(v)

    @field_validator("type", mode="before")
    @classmethod
    def _norm_type(cls, v: Any) -> str:
        return _normalize_case_type(v)

    @field_validator("related_requirement_ids", mode="before")
    @classmethod
    def _norm_req_ids(cls, v: Any) -> List[str]:
        return _norm_req_id_list(v)

    @field_validator("related_process_step_ids", mode="before")
    @classmethod
    def _norm_step_ids(cls, v: Any) -> List[str]:
        return _norm_step_id_list(v)

    @model_validator(mode="after")
    def _failure_fields_consistent(self) -> "TestCase":
        """failure_classification and failure_description are only meaningful
        on a failed test. Rather than raise (which would push the run into
        the repair path over a data-quality nuisance), clear them when the
        status is not 'failed'. This enforces the invariant without being
        brittle to model over-eagerness.
        """
        if self.execution_status != "failed":
            if self.failure_classification is not None:
                self.failure_classification = None
            if self.failure_description is not None:
                self.failure_description = None
        return self

    # ---- legacy conversion --------------------------------------------- #
    def to_legacy_dict(self) -> dict:
        """Flatten test_data to a dict for the document generator.

        Fixes a silent data-loss bug: the previous implementation used a
        dict comprehension that kept only the last entry whenever two test
        data items shared a key. This version merges same-key entries by
        joining their values, and skips entries with an empty key (which
        the model occasionally emits) rather than collapsing them into an
        empty-string bucket.

        Preserves the rich list form under `test_data_items` so downstream
        consumers that want the structured data can reach it. All other
        keys are unchanged for backward compatibility.
        """
        data = self.model_dump()
        items = data.pop("test_data", []) or []
        data["test_data_items"] = items

        flat: dict[str, str] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            key = (item.get("key") or "").strip()
            if not key:
                continue
            val = (item.get("value") or "").strip()
            if key in flat and val:
                flat[key] = f"{flat[key]}; {val}"
            else:
                flat.setdefault(key, val)
        data["test_data"] = flat
        return data


# ---------------------------------------------------------------------------
# Open questions (same pattern as the other schemas)
# ---------------------------------------------------------------------------
class OpenQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    topic: str = Field(default="", description="Short label for the question.")
    question: str = Field(
        default="",
        description="The question, phrased so a stakeholder can answer it "
                    "directly.",
    )
    blocking: bool = Field(
        default=False,
        description="True only if test execution cannot be finalized without "
                    "an answer. Use sparingly.",
    )
    owner: Optional[str] = Field(
        default=None,
        description="Role expected to resolve this. Null if unknown.",
    )
    related_requirement_ids: List[str] = Field(
        default_factory=list,
        description="Requirement IDs affected by this question, if any.",
    )

    @field_validator("related_requirement_ids", mode="before")
    @classmethod
    def _norm_req_ids(cls, v: Any) -> List[str]:
        return _norm_req_id_list(v)


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------
class TestCasesDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")

    test_cases: List[TestCase] = Field(default_factory=list)
    assumptions: List[str] = Field(
        default_factory=list,
        description="Statements taken as true without confirmation, e.g. "
                    "'Approval workflow is configured per the design'. These "
                    "must be validated before execution.",
    )
    open_questions: List[OpenQuestion] = Field(
        default_factory=list,
        description="Gaps and ambiguities requiring resolution. Populate "
                    "this rather than inventing test details for unknowns.",
    )