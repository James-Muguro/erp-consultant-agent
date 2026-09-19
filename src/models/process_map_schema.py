"""
Pydantic schema for structured process map output.

Used to constrain and validate LLM JSON responses for the Process Mapping
Agent. The schema is passed to the Gemini and OpenAI structured-output
APIs as JSON Schema and used for validation on all fallback tiers, so:

  * Fields use only JSON-Schema constructs that Gemini's structured-output
    dialect supports: primitives, enums (Literal), optional fields, nested
    objects, arrays. No `pattern=` regexes, no numeric range constraints,
    no arbitrary unions.
  * Every field has a `Field(description=...)`. Those descriptions flow
    into the JSON Schema the model receives — they are field-level
    instructions and measurably improve content quality without touching
    the prompt.
  * Empty-string defaults on string fields and empty-list defaults on
    lists mean the model can omit a field it can't fill, rather than
    inventing a plausible-sounding value to satisfy a required field.
  * `open_questions` is a first-class output field. Gaps and ambiguities
    belong in the document, not in the agent's head — the process mapping
    guardrails instruct the model to mark unknowns rather than invent
    specifics, and this is where those unknowns are recorded.
"""
from __future__ import annotations

import re
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------
_STEP_ID_PATTERN = re.compile(r"^STEP-\d{3,}$")
_DECISION_ID_PATTERN = re.compile(r"^DP-\d{3,}$")
_INTEGRATION_ID_PATTERN = re.compile(r"^IP-\d{3,}$")
_REQ_ID_PATTERN = re.compile(r"^REQ-\d{3,}$")


def _canonical_id(value: Any, prefix: str, pattern: re.Pattern) -> str:
    """Map a model-supplied identifier onto its canonical `PREFIX-NNN` form.

    Falls back to an empty string on failure rather than raising, because
    a single odd identifier should not fail the whole document. The list-
    level validators in ProcessMap auto-assign missing IDs, so an empty
    return is always recoverable.
    """
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
    """Normalize a requirement ID to canonical `REQ-NNN` form so that
    links to the requirements phase match by a stable key, regardless of
    how the model spelled it in this particular output."""
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


# ---------------------------------------------------------------------------
# Process step
# ---------------------------------------------------------------------------
class ProcessStep(BaseModel):
    """A single step in a business process flow.

    The fields below represent the minimum a reviewer, tester, or trainer
    needs to act on the step. Fields the model cannot fill from the input
    default to empty and should be flagged in `open_questions` rather than
    invented.
    """
    model_config = ConfigDict(extra="ignore")

    id: str = Field(
        default="",
        description="Unique step identifier, canonical form STEP-001. "
                    "Auto-assigned if omitted.",
    )
    number: int = Field(
        default=0,
        description="Display order. 1-based sequential.",
    )
    name: str = Field(
        default="",
        description="Short imperative name for the step, e.g. 'Create purchase "
                    "requisition'. Used as the primary label everywhere.",
    )
    description: str = Field(
        default="",
        description="What happens at this step, in one or two sentences. "
                    "Focus on the business outcome, not screen clicks.",
    )
    responsible_role: str = Field(
        default="",
        description="The single role that owns this step. Use 'TBD' rather "
                    "than guessing if the input doesn't specify.",
    )
    trigger: str = Field(
        default="",
        description="What causes the step to start: an upstream event, a "
                    "document reaching a state, a scheduled date, or a manual "
                    "action by the responsible role.",
    )
    inputs: List[str] = Field(
        default_factory=list,
        description="Data or documents the step consumes, in business terms "
                    "(e.g. 'Approved purchase requisition').",
    )
    outputs: List[str] = Field(
        default_factory=list,
        description="Data or documents the step produces.",
    )
    transaction: str = Field(
        default="",
        description="System transaction, app ID, or function used to execute "
                    "the step. Leave empty and note in open_questions if "
                    "unknown — do not invent T-codes, Fiori app IDs, or "
                    "Oracle form names.",
    )
    exception_paths: List[str] = Field(
        default_factory=list,
        description="What can go wrong at this step and what happens then "
                    "(approval rejection, data error, timeout). Feeds UAT "
                    "error-handling scenarios.",
    )
    related_requirement_ids: List[str] = Field(
        default_factory=list,
        description="Requirement ID codes (canonical form 'REQ-001') from "
                    "the provided requirement list that this step implements. "
                    "Leave empty if none clearly apply — never guess.",
    )

    @field_validator("id", mode="before")
    @classmethod
    def _norm_id(cls, v: Any) -> str:
        return _canonical_id(v, "STEP", _STEP_ID_PATTERN)

    @field_validator("related_requirement_ids", mode="before")
    @classmethod
    def _norm_req_ids(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            return [_normalize_requirement_id(v)]
        return [_normalize_requirement_id(x) for x in v]


# ---------------------------------------------------------------------------
# Decision and integration points — structured rather than free strings
# ---------------------------------------------------------------------------
# The process mapping guardrails require decision points to name a branch
# condition and its outcomes, and integration points to name direction,
# trigger, payload, and error handling. Representing those as structured
# objects gives the model field-level slots to fill (rather than forcing
# it to cram everything into one string) and gives downstream tooling
# (UAT scenario generation, gap analysis) well-typed data to iterate.
#
# Backward compatibility: both models accept a plain string via a
# mode="before" validator, wrapping it as `condition`/`name` with empty
# extras. This keeps older outputs and any heuristic-parser output valid
# without a schema change on the caller side.
class DecisionPoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(
        default="",
        description="Unique identifier, canonical form DP-001. Auto-assigned "
                    "if omitted.",
    )
    after_step: Optional[str] = Field(
        default=None,
        description="Step ID (STEP-XXX) that this decision follows. Null if "
                    "the decision isn't tied to a specific step.",
    )
    condition: str = Field(
        default="",
        description="The branch condition stated positively, e.g. 'Purchase "
                    "order value exceeds 10,000 EUR'.",
    )
    outcomes: List[str] = Field(
        default_factory=list,
        description="Possible outcomes of the decision. Minimum two: the "
                    "yes-branch and the no-branch. Use concrete outcomes "
                    "('Requires CFO approval'), not 'handled differently'.",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Any constraint on the decision: authorization required, "
                    "SLA, regulatory context. Leave null if none.",
    )

    @field_validator("id", mode="before")
    @classmethod
    def _norm_id(cls, v: Any) -> str:
        return _canonical_id(v, "DP", _DECISION_ID_PATTERN)

    @field_validator("after_step", mode="before")
    @classmethod
    def _norm_step_ref(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return _canonical_id(s, "STEP", _STEP_ID_PATTERN) or None

    @field_validator("condition", "outcomes", mode="before")
    @classmethod
    def _accept_string_for_condition(cls, v: Any) -> Any:
        # Legacy or heuristic-parser form: a bare string where a
        # structured field is expected. Wrapped by the parent list
        # validator below; here we just pass through.
        return v


class IntegrationPoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(
        default="",
        description="Unique identifier, canonical form IP-001. Auto-assigned "
                    "if omitted.",
    )
    name: str = Field(
        default="",
        description="Human-readable name for the interface, e.g. 'Requisition "
                    "sync to Ariba'.",
    )
    direction: Literal["inbound", "outbound", "bidirectional", "internal"] = Field(
        default="inbound",
        description="Data flow direction relative to this process. 'internal' "
                    "for flows between steps of the same process.",
    )
    source: str = Field(
        default="",
        description="Originating system, module, or external party.",
    )
    target: str = Field(
        default="",
        description="Receiving system, module, or external party.",
    )
    trigger: str = Field(
        default="",
        description="What causes the interface to fire: event, schedule, or "
                    "manual push.",
    )
    payload_summary: str = Field(
        default="",
        description="What data moves across the interface, in business terms "
                    "(e.g. 'Requisition header and lines with cost center').",
    )
    error_handling: str = Field(
        default="",
        description="How the interface behaves on failure — retry, queue, "
                    "manual intervention, alert. Leave empty if unknown.",
    )
    related_step_ids: List[str] = Field(
        default_factory=list,
        description="Step IDs (STEP-XXX) that this interface touches.",
    )

    @field_validator("id", mode="before")
    @classmethod
    def _norm_id(cls, v: Any) -> str:
        return _canonical_id(v, "IP", _INTEGRATION_ID_PATTERN)

    @field_validator("related_step_ids", mode="before")
    @classmethod
    def _norm_step_ids(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            v = [v]
        return [_canonical_id(x, "STEP", _STEP_ID_PATTERN) for x in v if x]


# ---------------------------------------------------------------------------
# Open questions (same pattern as the requirements schema)
# ---------------------------------------------------------------------------
class OpenQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    topic: str = Field(
        default="",
        description="Short label, e.g. 'Approval thresholds', 'Interface "
                    "ownership'.",
    )
    question: str = Field(
        default="",
        description="The question, phrased so a business stakeholder can "
                    "answer it directly.",
    )
    blocking: bool = Field(
        default=False,
        description="True only if the process map cannot be finalized until "
                    "this is answered. Use sparingly.",
    )
    owner: Optional[str] = Field(
        default=None,
        description="Role expected to resolve this. Null if unknown.",
    )
    related_step_ids: List[str] = Field(
        default_factory=list,
        description="Step IDs this question affects, if any.",
    )

    @field_validator("related_step_ids", mode="before")
    @classmethod
    def _norm_step_ids(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            v = [v]
        return [_canonical_id(x, "STEP", _STEP_ID_PATTERN) for x in v if x]


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------
class ProcessMap(BaseModel):
    model_config = ConfigDict(extra="ignore")

    as_is_or_to_be: Literal["AS-IS", "TO-BE", "Both", "Unspecified"] = Field(
        default="Unspecified",
        description="Whether this map describes the current process (AS-IS), "
                    "the target process (TO-BE), both, or is unspecified. "
                    "Gap analysis between AS-IS and TO-BE depends on this "
                    "being set correctly.",
    )
    overview: str = Field(
        default="",
        description="One-paragraph summary: what the process achieves, who "
                    "it serves, and where it starts and ends.",
    )
    scope: str = Field(
        default="",
        description="What is inside the process boundary and what is out of "
                    "scope. Explicit exclusions are as valuable as inclusions.",
    )
    roles: List[str] = Field(
        default_factory=list,
        description="Roles that participate in the process. Use plain role "
                    "names ('AP Clerk'), not job codes or system user IDs.",
    )
    steps: List[ProcessStep] = Field(default_factory=list)
    decision_points: List[DecisionPoint] = Field(
        default_factory=list,
        description="Branch points in the flow. Each must name its condition "
                    "and at least two outcomes.",
    )
    integration_points: List[IntegrationPoint] = Field(
        default_factory=list,
        description="Interfaces to other systems, modules, or processes. "
                    "Each must name direction, trigger, and payload.",
    )
    exceptions: List[str] = Field(
        default_factory=list,
        description="Process-level exception handling that doesn't belong to "
                    "a single step (e.g. 'Requisitions rejected twice are "
                    "escalated to the category manager').",
    )
    improvements: List[str] = Field(
        default_factory=list,
        description="Identified opportunities for improvement relative to "
                    "the current state. These are candidates, not commitments.",
    )
    open_questions: List[OpenQuestion] = Field(
        default_factory=list,
        description="Gaps and ambiguities requiring stakeholder confirmation. "
                    "Populate this rather than inventing specifics for unknowns.",
    )

    # ------------------------------------------------------------------ #
    # ID assignment
    # ------------------------------------------------------------------ #
    @field_validator("steps")
    @classmethod
    def _ensure_step_ids(cls, v: List[ProcessStep]) -> List[ProcessStep]:
        """Fill in missing step IDs and normalize step.number so downstream
        linking (project_intelligence.sync_process_steps_from_structured)
        can key on a stable identifier even when the model omits IDs."""
        for i, step in enumerate(v, start=1):
            if not step.id:
                step.id = f"STEP-{i:03d}"
            if not step.number:
                step.number = i
        return v

    @field_validator("decision_points")
    @classmethod
    def _ensure_decision_ids(cls, v: List[DecisionPoint]) -> List[DecisionPoint]:
        for i, dp in enumerate(v, start=1):
            if not dp.id:
                dp.id = f"DP-{i:03d}"
        return v

    @field_validator("integration_points", mode="before")
    @classmethod
    def _accept_string_integration_points(cls, v: Any) -> Any:
        """Accept legacy list-of-strings form and wrap each string as a
        minimal IntegrationPoint. Keeps older outputs and any heuristic
        parser output valid."""
        if not isinstance(v, list):
            return v
        wrapped: List[Any] = []
        for item in v:
            if isinstance(item, str):
                wrapped.append({"name": item})
            else:
                wrapped.append(item)
        return wrapped

    @field_validator("integration_points")
    @classmethod
    def _ensure_integration_ids(cls, v: List[IntegrationPoint]) -> List[IntegrationPoint]:
        for i, ip in enumerate(v, start=1):
            if not ip.id:
                ip.id = f"IP-{i:03d}"
        return v

    @field_validator("decision_points", mode="before")
    @classmethod
    def _accept_string_decision_points(cls, v: Any) -> Any:
        if not isinstance(v, list):
            return v
        wrapped: List[Any] = []
        for item in v:
            if isinstance(item, str):
                wrapped.append({"condition": item})
            else:
                wrapped.append(item)
        return wrapped