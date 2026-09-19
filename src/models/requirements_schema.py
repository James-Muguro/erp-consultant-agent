"""
Pydantic schema for structured requirements output.

Used to constrain and validate LLM JSON responses for the Requirements
Gathering Agent. The schema is passed directly to the Gemini and OpenAI
structured-output APIs (as JSON Schema) and used for validation on all
fallback tiers, so:

  * Fields must be simple enough for provider structured-output support.
    That means: no regex `pattern=` on Field(), no numeric `ge=`/`le=`
    constraints on non-integers, no arbitrary unions. Validation that
    providers don't understand is implemented as `@field_validator`s,
    which do NOT appear in the generated JSON Schema and run only after
    the model returns.
  * Defaults are chosen so the schema is usable when the model omits a
    field the guardrails requested but couldn't produce. Every field
    except the two required narrative sections has a default.
  * `Field(description=...)` strings flow into the JSON Schema that
    providers see, so they act as field-level instructions to the model.
  * `to_legacy_dict()` produces the flat dict shape that document
    generators and downstream consumers already expect; new fields are
    additive to that shape and do not change existing keys.
"""
from __future__ import annotations

import re
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------
# Field-level constraints like Literal[...] don't tolerate near-misses: a
# model that returns "P1" or "high " will fail validation, then fall into
# the JSON-repair pass, then maybe still fail. These normalizers accept
# the common variants and map them onto the canonical set, so we get
# well-typed data without pushing every run into the repair path.

_PRIORITY_CANONICAL = ("Critical", "High", "Medium", "Low")
_PRIORITY_ALIASES = {
    "p1": "Critical", "urgent": "Critical", "blocker": "Critical",
    "must have": "Critical", "must-have": "Critical",
    "p2": "High", "important": "High", "should have": "High",
    "p3": "Medium", "normal": "Medium", "standard": "Medium",
    "p4": "Low", "nice to have": "Low", "nice-to-have": "Low", "optional": "Low",
}

_STATUS_CANONICAL = ("Draft", "Confirmed", "Assumed", "TBD")
_STATUS_ALIASES = {
    "draft": "Draft", "proposed": "Draft", "new": "Draft",
    "confirmed": "Confirmed", "approved": "Confirmed", "signed off": "Confirmed",
    "assumed": "Assumed", "inferred": "Assumed",
    "tbd": "TBD", "unknown": "TBD", "open": "TBD", "pending": "TBD",
}

_REQUIREMENT_ID_PATTERN = re.compile(r"^REQ-\d{3,}$")


def _normalize_priority(value: Any) -> str:
    """Map a model-supplied priority onto the canonical set.

    Falls back to 'Medium' rather than raising on unrecognized values,
    because a single odd priority string should not fail the entire
    document. The model's intent is preserved where it matches a known
    form; unmatched values default to the safest middle ground.
    """
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
    for canonical in _PRIORITY_CANONICAL:
        if s.lower() == canonical.lower():
            return canonical
    return "Medium"


def _normalize_status(value: Any) -> str:
    if value is None:
        return "Draft"
    s = str(value).strip()
    if not s:
        return "Draft"
    if s in _STATUS_CANONICAL:
        return s
    alias = _STATUS_ALIASES.get(s.lower())
    if alias:
        return alias
    for canonical in _STATUS_CANONICAL:
        if s.lower() == canonical.lower():
            return canonical
    return "Draft"


def _normalize_requirement_id(value: Any) -> str:
    """Ensure requirement IDs match the canonical `REQ-NNN` form so
    downstream linking (project_intelligence.link_requirements) has a
    stable key to match on. The model sometimes emits REQ1, REQ_001,
    req-001, or free-form text; we normalize rather than reject, because
    a single odd id shouldn't invalidate the entire document.

    Note: this can in principle produce duplicate IDs (e.g. REQ1 and
    REQ-001 both normalize to REQ-001). The requirements agent's
    validate_requirements() checks for duplicates and raises a warning,
    so collisions surface for review rather than silently propagating.
    """
    if value is None:
        return "REQ-000"
    s = str(value).strip()
    if not s:
        return "REQ-000"
    if _REQUIREMENT_ID_PATTERN.match(s):
        return s
    m = re.match(r"^[A-Za-z_\-]*?(\d+)$", s)
    if m:
        return f"REQ-{int(m.group(1)):03d}"
    # Last resort: keep whatever the model produced so we don't lose the
    # link between id and content. Validation will flag unusual formats.
    return s


# ---------------------------------------------------------------------------
# Requirement items
# ---------------------------------------------------------------------------
class BaseRequirementItem(BaseModel):
    """Fields common to every requirement, regardless of section.

    The rule of thumb for what belongs here: if a reviewer auditing a
    requirements document would need this field to evaluate *any* kind
    of requirement, it lives on the base. Section-specific extras live
    on the subclasses.
    """
    model_config = ConfigDict(extra="ignore")

    id: str = Field(
        description="Unique identifier, canonical form REQ-001. "
                    "Normalization is applied if the model emits another format.",
    )
    description: str = Field(
        description="What the system must do, stated as a single testable "
                    "requirement. Avoid compound 'and/or' statements.",
    )
    priority: Literal["Critical", "High", "Medium", "Low"] = Field(
        default="Medium",
        description="Business criticality: Critical = go-live blocker or "
                    "regulatory; High = core process; Medium = standard; "
                    "Low = nice-to-have.",
    )
    acceptance_criteria: Optional[str] = Field(
        default=None,
        description="How a reviewer confirms the requirement is satisfied. "
                    "Observable and specific; 'works correctly' is not acceptable.",
    )
    rationale: Optional[str] = Field(
        default=None,
        description="Business reason the requirement exists. Required for "
                    "change control when scope is renegotiated.",
    )
    source: Optional[str] = Field(
        default=None,
        description="Origin: named stakeholder, workshop, regulation, or document. "
                    "Leave null and add to open_questions if unknown.",
    )
    status: Literal["Draft", "Confirmed", "Assumed", "TBD"] = Field(
        default="Draft",
        description="Draft while open, Confirmed after stakeholder sign-off, "
                    "Assumed when inferred by the agent, TBD when unresolved.",
    )

    @field_validator("id", mode="before")
    @classmethod
    def _norm_id(cls, v: Any) -> str:
        return _normalize_requirement_id(v)

    @field_validator("priority", mode="before")
    @classmethod
    def _norm_priority(cls, v: Any) -> str:
        return _normalize_priority(v)

    @field_validator("status", mode="before")
    @classmethod
    def _norm_status(cls, v: Any) -> str:
        return _normalize_status(v)


class RequirementItem(BaseRequirementItem):
    """A functional requirement — one that specifies business behavior."""
    type: Literal[
        "Functional",
        "Business Rule",
        "Data",
        "Security",
        "Compliance",
        "Localization",
    ] = Field(
        default="Functional",
        description="Sub-classification useful for coverage analysis. "
                    "'Functional' is the common case.",
    )
    related_process_ids: List[str] = Field(
        default_factory=list,
        description="IDs of process steps this requirement affects, if known. "
                    "Leave empty and note in open_questions if traceability "
                    "cannot be established yet.",
    )


class GeneralRequirementItem(BaseRequirementItem):
    """Used for technical / integration / reporting / non-functional
    sections where the category hierarchy of functional requirements
    isn't needed and the extra `type`/`related_process_ids` fields would
    be noise. Kept as a distinct class so section semantics are visible
    in the schema and in downstream type checks."""
    pass


class FunctionalRequirementCategory(BaseModel):
    model_config = ConfigDict(extra="ignore")

    category: str = Field(
        description="Business area, e.g. 'Procure to Pay', 'Order to Cash', "
                    "'Record to Report'. Use consistent names across categories.",
    )
    requirements: List[RequirementItem] = Field(default_factory=list)


class OpenQuestion(BaseModel):
    """A gap, ambiguity, or unresolved decision surfaced by the requirements
    phase. The agent's guardrails require these to be captured rather than
    papered over with invented specifics; previously the schema had no
    place to record them, so they were silently dropped.

    Open questions are first-class output, not footnotes: unresolved
    blocking questions are a signal that the requirements phase isn't
    complete, and reviewers should be able to see them at a glance.
    """
    model_config = ConfigDict(extra="ignore")

    topic: str = Field(
        description="Short label for what the question is about, e.g. "
                    "'Approval thresholds', 'Multi-currency requirements'.",
    )
    question: str = Field(
        description="The question as the stakeholder should see it. Concrete "
                    "and answerable, not 'clarify requirements'.",
    )
    blocking: bool = Field(
        default=False,
        description="True if the document cannot be finalized until answered. "
                    "Use sparingly — blocking questions should be genuinely "
                    "unresolvable from available input.",
    )
    owner: Optional[str] = Field(
        default=None,
        description="Role or person expected to resolve this. Leave null if unknown.",
    )
    related_requirement_ids: List[str] = Field(
        default_factory=list,
        description="IDs of requirements this question affects, if any.",
    )

    @field_validator("related_requirement_ids", mode="before")
    @classmethod
    def _norm_related_ids(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            return [str(v)]
        return [_normalize_requirement_id(x) for x in v]


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------
class RequirementsDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")

    executive_summary: str = Field(
        description="Two-paragraph summary for project sponsors: what is being "
                    "built, why, and what the main open risks are.",
    )
    business_context: str = Field(
        description="Business situation driving the requirements, including "
                    "current pain points and strategic drivers.",
    )
    objectives: List[str] = Field(
        default_factory=list,
        description="Specific, measurable business objectives the project must achieve.",
    )
    functional_requirements: List[FunctionalRequirementCategory] = Field(
        default_factory=list,
        description="Requirements grouped by business area.",
    )
    non_functional_requirements: List[GeneralRequirementItem] = Field(
        default_factory=list,
        description="Performance, availability, scalability, usability, "
                    "accessibility, localization. These constrain how the "
                    "system performs, not what it does.",
    )
    technical_requirements: List[GeneralRequirementItem] = Field(default_factory=list)
    integration_requirements: List[GeneralRequirementItem] = Field(default_factory=list)
    reporting_requirements: List[GeneralRequirementItem] = Field(default_factory=list)
    dependencies: List[str] = Field(
        default_factory=list,
        description="External or internal dependencies the project relies on: "
                    "master data readiness, upstream integrations, sign-off owners.",
    )
    constraints: List[str] = Field(
        default_factory=list,
        description="Known limitations: budget, timeline, regulatory, technical.",
    )
    assumptions: List[str] = Field(
        default_factory=list,
        description="Statements taken as true without confirmation. These must "
                    "be validated — if any is wrong, the requirements may change.",
    )
    open_questions: List[OpenQuestion] = Field(
        default_factory=list,
        description="Gaps and ambiguities requiring stakeholder confirmation "
                    "before the requirements can be considered complete. "
                    "Populate this rather than inventing specifics for unknowns.",
    )

    # ------------------------------------------------------------------ #
    # Legacy conversion
    # ------------------------------------------------------------------ #
    def to_legacy_dict(self) -> dict:
        """Convert to the dict shape downstream consumers expect:
        functional_requirements is a dict keyed by category name (not a
        list of {category, requirements} objects). All other fields pass
        through as-is; new fields (non_functional_requirements,
        open_questions, and the traceability fields on requirement items)
        are additive and do not change existing keys.

        Note: the previous implementation used a dict comprehension that
        silently dropped requirements when two categories shared a name.
        The model does emit duplicate categories occasionally — e.g. two
        'Procure to Pay' sections split by sub-process — so this merges
        rather than overwrites to avoid losing requirements.
        """
        data = self.model_dump()
        cats = data.pop("functional_requirements", []) or []

        merged: dict[str, list] = {}
        for cat in cats:
            if not isinstance(cat, dict):
                continue
            name = cat.get("category") or "general"
            reqs = cat.get("requirements") or []
            if not isinstance(reqs, list):
                continue
            merged.setdefault(name, []).extend(reqs)

        data["functional_requirements"] = merged
        return data