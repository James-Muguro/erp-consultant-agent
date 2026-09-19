"""
Pydantic schema for structured solution design output.

Used to constrain and validate LLM JSON responses for the Solution Design
Agent. Design decisions are the highest-risk content in an ERP project
because they commit cost, complexity, and upgrade exposure. The schema is
shaped to make three things explicit rather than implicit:

  * Classification: every configuration entry declares whether it is
    STANDARD, CONFIGURATION, or EXTENSION — the first three rungs of the
    standard-first ladder the agent's guardrails enforce. Customizations
    live in their own list and carry mandatory justification.
  * Traceability: every design decision can link back to requirement IDs
    so the design can be defended against the requirements baseline.
  * Unresolved unknowns: `open_questions` and `assumptions` are first-
    class fields, so gaps surface in the document rather than being
    silently papered over.

Field constraints use only JSON-Schema constructs supported by Gemini and
OpenAI structured-output APIs (primitives, enums, optional, arrays, nested
objects). Validation logic that providers don't understand lives in
`@field_validator`s, which do NOT appear in the generated JSON Schema.
"""
from __future__ import annotations

import re
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------
_CONFIG_ID_PATTERN = re.compile(r"^CFG-\d{3,}$")
_INTEGRATION_ID_PATTERN = re.compile(r"^INT-\d{3,}$")
_CUSTOM_ID_PATTERN = re.compile(r"^CUST-\d{3,}$")
_MD_ID_PATTERN = re.compile(r"^MD-\d{3,}$")
_REQ_ID_PATTERN = re.compile(r"^REQ-\d{3,}$")


def _canonical_id(value: Any, prefix: str, pattern: re.Pattern) -> str:
    """Normalize a model-supplied identifier to canonical `PREFIX-NNN` form.
    Permissive: returns the input or empty string rather than raising, so a
    single odd identifier can't fail the whole document."""
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
    """Canonicalize a requirement reference to `REQ-NNN` so traceability
    links match the requirements phase regardless of the spelling used here."""
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


def _norm_req_id_list(v: Any) -> List[str]:
    if v is None:
        return []
    if not isinstance(v, list):
        v = [v]
    return [_normalize_requirement_id(x) for x in v if x is not None and str(x).strip()]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
class ConfigurationItem(BaseModel):
    """A standard ERP feature that is enabled or parameterized.

    `classification` distinguishes the three rungs of the standard-first
    ladder. Customizations are deliberately NOT a classification here —
    they live in the separate `customizations` list on SolutionDesign,
    where the mandatory justification, alternatives, and complexity
    fields apply. This keeps the two concepts from overlapping.
    """
    model_config = ConfigDict(extra="ignore")

    id: str = Field(
        default="",
        description="Unique identifier, canonical form CFG-001. Auto-assigned "
                    "if omitted.",
    )
    component: str = Field(
        default="",
        description="Name of the configuration area or object, e.g. "
                    "'Approval workflow', 'Tax determination', 'Number ranges'.",
    )
    classification: Literal["STANDARD", "CONFIGURATION", "EXTENSION"] = Field(
        default="CONFIGURATION",
        description="STANDARD: out-of-the-box functionality used as delivered. "
                    "CONFIGURATION: standard functionality enabled or "
                    "parameterized (no code change). EXTENSION: standard "
                    "extension point (enhancement framework, plug-in, custom "
                    "object in an extension layer) — still upgrade-safe. "
                    "Do not use for bespoke builds; those belong in customizations.",
    )
    description: str = Field(
        default="",
        description="What the configuration achieves, in business terms.",
    )
    steps: List[str] = Field(
        default_factory=list,
        description="Configuration steps or settings, described generically "
                    "(e.g. 'Enable two-step approval above threshold'). "
                    "Do NOT invent SPRO paths, transaction codes, Fiori app "
                    "IDs, or form names you are not certain of.",
    )
    module: str = Field(
        default="",
        description="ERP module the configuration lives in, e.g. 'MM', 'FI'. "
                    "Leave empty if the configuration spans modules.",
    )
    related_requirement_ids: List[str] = Field(
        default_factory=list,
        description="Requirement ID codes (canonical form 'REQ-001') this "
                    "configuration addresses. Leave empty if none clearly "
                    "apply — never guess.",
    )

    @field_validator("id", mode="before")
    @classmethod
    def _norm_id(cls, v: Any) -> str:
        return _canonical_id(v, "CFG", _CONFIG_ID_PATTERN)

    @field_validator("related_requirement_ids", mode="before")
    @classmethod
    def _norm_req_ids(cls, v: Any) -> List[str]:
        return _norm_req_id_list(v)


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------
class IntegrationItem(BaseModel):
    """An interface between this solution and another system, module, or
    external party.

    The fields mirror the integration design checklist used on real ERP
    projects: direction, trigger, payload, transport, error handling, and
    idempotency keying. That last one is frequently forgotten in early
    design and then discovered during testing when duplicate records appear.
    """
    model_config = ConfigDict(extra="ignore")

    id: str = Field(
        default="",
        description="Unique identifier, canonical form INT-001. Auto-assigned "
                    "if omitted.",
    )
    name: str = Field(
        default="",
        description="Human-readable name, e.g. 'Vendor sync from MDM'.",
    )
    type: str = Field(
        default="Real-time",
        description="Interface category, e.g. Real-time / Batch / File-based "
                    "/ Event-driven / EDI. Use the terminology the target ERP "
                    "system actually uses.",
    )
    direction: Literal["inbound", "outbound", "bidirectional", "internal"] = Field(
        default="inbound",
        description="Direction of data flow relative to this solution. "
                    "'internal' for flows between modules of the same system.",
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
        description="What causes the interface to fire: business event, "
                    "schedule, or manual push.",
    )
    payload_summary: str = Field(
        default="",
        description="What data moves across the interface, in business terms.",
    )
    transport: str = Field(
        default="",
        description="How the data physically moves: API, file share, message "
                    "queue, middleware product, database link. Leave empty if "
                    "the transport is not yet decided.",
    )
    error_handling: str = Field(
        default="",
        description="How the interface behaves on failure — retry, dead-letter "
                    "queue, alert, manual intervention. Leave empty if unknown.",
    )
    idempotency_key: str = Field(
        default="",
        description="The field or combination of fields that uniquely "
                    "identifies a record so reprocessing doesn't create "
                    "duplicates. Frequently forgotten; mark TBD if unknown.",
    )
    description: str = Field(
        default="",
        description="Any additional context not covered by the structured fields.",
    )
    related_requirement_ids: List[str] = Field(
        default_factory=list,
        description="Requirement ID codes (canonical form 'REQ-001') this "
                    "integration addresses. Leave empty if none clearly apply.",
    )

    @field_validator("id", mode="before")
    @classmethod
    def _norm_id(cls, v: Any) -> str:
        return _canonical_id(v, "INT", _INTEGRATION_ID_PATTERN)

    @field_validator("related_requirement_ids", mode="before")
    @classmethod
    def _norm_req_ids(cls, v: Any) -> List[str]:
        return _norm_req_id_list(v)


# ---------------------------------------------------------------------------
# Customization
# ---------------------------------------------------------------------------
class CustomizationItem(BaseModel):
    """A bespoke build. Every field here exists because a real ERP steering
    committee will ask the questions these fields answer before approving a
    customization: Why can't standard do this? What else was considered?
    How complex is it? What does it cost us on every future upgrade?"""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(
        default="",
        description="Unique identifier, canonical form CUST-001. Auto-assigned "
                    "if omitted.",
    )
    type: str = Field(
        default="",
        description="Kind of customization in the target ERP's terminology, "
                    "e.g. 'Enhancement', 'User Exit', 'BAdI', 'Custom Report', "
                    "'Custom Form', 'Custom Workflow', 'Custom Object'.",
    )
    component: str = Field(
        default="",
        description="Name of the object or area being customized.",
    )
    description: str = Field(
        default="",
        description="What the customization does, in business terms.",
    )
    justification: str = Field(
        default="",
        description="Why standard functionality and configuration are "
                    "insufficient. Required for approval — a customization "
                    "without justification will not be approved.",
    )
    alternatives_considered: List[str] = Field(
        default_factory=list,
        description="Non-customization options that were evaluated and "
                    "rejected, with the reason (e.g. 'Process change rejected "
                    "because customer contract requires current behavior'). "
                    "Required for steering committee review.",
    )
    complexity: Literal["Low", "Medium", "High"] = Field(
        default="Medium",
        description="Rough implementation complexity and risk. High "
                    "complexity customizations warrant a technical spike "
                    "before commitment.",
    )
    lifecycle_impact: str = Field(
        default="",
        description="Effect on future upgrades, patches, and support — e.g. "
                    "'Requires regression testing every service pack'. Leave "
                    "empty only if genuinely not assessable yet.",
    )
    related_requirement_ids: List[str] = Field(
        default_factory=list,
        description="Requirement ID codes (canonical form 'REQ-001') this "
                    "customization addresses. Leave empty if none clearly apply.",
    )

    @field_validator("id", mode="before")
    @classmethod
    def _norm_id(cls, v: Any) -> str:
        return _canonical_id(v, "CUST", _CUSTOM_ID_PATTERN)

    @field_validator("related_requirement_ids", mode="before")
    @classmethod
    def _norm_req_ids(cls, v: Any) -> List[str]:
        return _norm_req_id_list(v)


# ---------------------------------------------------------------------------
# Master data
# ---------------------------------------------------------------------------
class MasterDataItem(BaseModel):
    """A master data object required by the solution. Status is critical:
    'Existing' data is a scope clarification, 'To-be-created' is a workstream
    with an owner and a cutover dependency. Conflating the two is a common
    source of missed go-live tasks."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(
        default="",
        description="Unique identifier, canonical form MD-001. Auto-assigned "
                    "if omitted.",
    )
    data_type: str = Field(
        default="",
        description="Master data object name, e.g. 'Vendor master', "
                    "'Material master', 'Chart of accounts'.",
    )
    details: str = Field(
        default="",
        description="What is required: fields, validation rules, sourcing, "
                    "and any known quality issues in the existing data.",
    )
    status: Literal[
        "Existing", "To-be-created", "To-be-migrated", "To-be-cleaned", "TBD"
    ] = Field(
        default="TBD",
        description="Whether the data exists today, must be created, must be "
                    "migrated from a legacy system, or must be cleaned before "
                    "use. 'TBD' is legitimate and should be resolved by the "
                    "business owner.",
    )
    owner: str = Field(
        default="",
        description="Role or team accountable for readiness. Leave empty if "
                    "not yet assigned.",
    )
    volume_estimate: str = Field(
        default="",
        description="Approximate record count or data volume, when known. "
                    "Affects migration effort and testing scope.",
    )
    related_requirement_ids: List[str] = Field(
        default_factory=list,
        description="Requirement ID codes (canonical form 'REQ-001') that "
                    "depend on this master data being ready.",
    )

    @field_validator("id", mode="before")
    @classmethod
    def _norm_id(cls, v: Any) -> str:
        return _canonical_id(v, "MD", _MD_ID_PATTERN)

    @field_validator("related_requirement_ids", mode="before")
    @classmethod
    def _norm_req_ids(cls, v: Any) -> List[str]:
        return _norm_req_id_list(v)


# ---------------------------------------------------------------------------
# Technical specs
# ---------------------------------------------------------------------------
class TechnicalSpecItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    category: str = Field(
        default="",
        description="Grouping, e.g. 'Environment', 'Performance', 'Availability', "
                    "'Compliance'. Helps when the list grows large.",
    )
    name: str = Field(
        default="",
        description="Short name for the spec, e.g. 'Peak concurrent users'.",
    )
    value: str = Field(
        default="",
        description="The specification value, target, or statement.",
    )


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
class SecurityDesign(BaseModel):
    """Authorization model, role matrix, and segregation-of-duties approach.

    Kept as a structured object rather than a single string because
    security review is a distinct workstream on real projects, and
    SoD findings frequently block go-live. A free-text field hides that.
    """
    model_config = ConfigDict(extra="ignore")

    overview: str = Field(
        default="",
        description="High-level statement of the security approach.",
    )
    authorization_model: str = Field(
        default="",
        description="How access is granted: role-based, attribute-based, "
                    "position-based, or a combination. Name the mechanism the "
                    "target ERP actually provides.",
    )
    roles: List[str] = Field(
        default_factory=list,
        description="Business roles the solution will define, with their "
                    "scope. Not the same as the roles list on a process map — "
                    "these are security roles.",
    )
    sod_controls: List[str] = Field(
        default_factory=list,
        description="Segregation-of-duties controls required by the business "
                    "or by regulation. These are compliance-critical and "
                    "should be validated with audit before go-live.",
    )
    sensitive_access: List[str] = Field(
        default_factory=list,
        description="Specific sensitive transactions, data, or functions that "
                    "require additional controls (approval, logging, review).",
    )
    related_requirement_ids: List[str] = Field(
        default_factory=list,
        description="Requirement ID codes (canonical form 'REQ-001') this "
                    "security design addresses.",
    )

    @field_validator("related_requirement_ids", mode="before")
    @classmethod
    def _norm_req_ids(cls, v: Any) -> List[str]:
        return _norm_req_id_list(v)


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------
class MigrationStrategy(BaseModel):
    model_config = ConfigDict(extra="ignore")

    strategy: str = Field(
        default="",
        description="Summary of the migration approach, e.g. 'Phased cutover "
                    "by module over three waves'.",
    )
    approach: Literal[
        "Big-bang", "Phased", "Parallel run", "Pilot", "Hybrid", "TBD"
    ] = Field(
        default="TBD",
        description="Cutover pattern. 'TBD' is common at design time and "
                    "should be resolved before detailed planning.",
    )
    cutover_window: str = Field(
        default="",
        description="Expected cutover duration and constraints, e.g. "
                    "'72-hour weekend window during month-end close freeze'.",
    )
    data_scope: List[str] = Field(
        default_factory=list,
        description="Data objects in scope for migration, with source system "
                    "and target object.",
    )
    reconciliation_approach: str = Field(
        default="",
        description="How migrated data will be verified against the source "
                    "(record counts, value totals, sampling, sign-off).",
    )
    rollback_approach: str = Field(
        default="",
        description="How the project recovers if cutover fails, and the "
                    "decision point for triggering rollback.",
    )


# ---------------------------------------------------------------------------
# Open questions and assumptions
# ---------------------------------------------------------------------------
class OpenQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    topic: str = Field(default="", description="Short label for the question.")
    question: str = Field(
        default="",
        description="The question, phrased so a stakeholder can answer it.",
    )
    blocking: bool = Field(
        default=False,
        description="True only if design cannot be finalized without an "
                    "answer. Use sparingly.",
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
class SolutionDesign(BaseModel):
    model_config = ConfigDict(extra="ignore")

    executive_summary: str = Field(
        default="",
        description="Two-paragraph summary for sponsors: what is being built, "
                    "how the design achieves the objectives, and what the "
                    "principal risks and open decisions are.",
    )
    architecture_overview: str = Field(
        default="",
        description="System landscape, key components, and how data flows "
                    "between them. Plain language unless the audience is "
                    "technical.",
    )
    configurations: List[ConfigurationItem] = Field(
        default_factory=list,
        description="Standard functionality enabled or parameterized. Every "
                    "entry declares STANDARD / CONFIGURATION / EXTENSION.",
    )
    master_data: List[MasterDataItem] = Field(
        default_factory=list,
        description="Master data objects the solution depends on, with "
                    "readiness status and owner.",
    )
    integrations: List[IntegrationItem] = Field(
        default_factory=list,
        description="Interfaces to other systems or modules.",
    )
    security: SecurityDesign = Field(default_factory=SecurityDesign)
    customizations: List[CustomizationItem] = Field(
        default_factory=list,
        description="Bespoke builds. Every entry requires a justification and "
                    "the alternatives that were considered first.",
    )
    migration: MigrationStrategy = Field(default_factory=MigrationStrategy)
    technical_specs: List[TechnicalSpecItem] = Field(
        default_factory=list,
        description="Non-functional specifications that constrain the design "
                    "(performance, availability, compliance, localization).",
    )
    assumptions: List[str] = Field(
        default_factory=list,
        description="Statements taken as true without confirmation. These "
                    "must be validated — if any is wrong, the design may "
                    "change.",
    )
    open_questions: List[OpenQuestion] = Field(
        default_factory=list,
        description="Gaps and ambiguities requiring resolution. Populate this "
                    "rather than inventing design specifics for unknowns.",
    )

    # ------------------------------------------------------------------ #
    # ID assignment
    # ------------------------------------------------------------------ #
    @field_validator("configurations")
    @classmethod
    def _ensure_config_ids(cls, v: List[ConfigurationItem]) -> List[ConfigurationItem]:
        for i, c in enumerate(v, start=1):
            if not c.id:
                c.id = f"CFG-{i:03d}"
        return v

    @field_validator("integrations")
    @classmethod
    def _ensure_integration_ids(cls, v: List[IntegrationItem]) -> List[IntegrationItem]:
        for i, c in enumerate(v, start=1):
            if not c.id:
                c.id = f"INT-{i:03d}"
        return v

    @field_validator("customizations")
    @classmethod
    def _ensure_custom_ids(cls, v: List[CustomizationItem]) -> List[CustomizationItem]:
        for i, c in enumerate(v, start=1):
            if not c.id:
                c.id = f"CUST-{i:03d}"
        return v

    @field_validator("master_data")
    @classmethod
    def _ensure_md_ids(cls, v: List[MasterDataItem]) -> List[MasterDataItem]:
        for i, c in enumerate(v, start=1):
            if not c.id:
                c.id = f"MD-{i:03d}"
        return v

    # ------------------------------------------------------------------ #
    # Legacy conversion
    # ------------------------------------------------------------------ #
    def to_legacy_dict(self) -> dict:
        """Convert to the dict shape document_generator.py expects:
        master_data keyed by data_type, technical_specs keyed by name.

        Fixes a silent data-loss bug in the previous implementation: when
        two items shared a key (e.g. two master data entries for the same
        data type covering different sub-scopes), the dict comprehension
        kept only the last one. This version merges same-key entries by
        joining their detail values rather than dropping them, and
        preserves the full structured items alongside the flattened form
        so downstream consumers that want the richer data can still reach it.
        """
        data = self.model_dump()
        md_items = data.pop("master_data", []) or []
        ts_items = data.pop("technical_specs", []) or []

        # Preserve rich form (does not break existing consumers, who read
        # the flattened keys below).
        data["master_data_items"] = md_items
        data["technical_specs_items"] = ts_items

        # Flattened form for backward compatibility, with duplicate-key
        # merging so nothing is silently lost.
        md_flat: dict[str, str] = {}
        for item in md_items:
            if not isinstance(item, dict):
                continue
            key = (item.get("data_type") or "").strip() or "Unnamed master data"
            val = (item.get("details") or "").strip()
            if key in md_flat and val:
                md_flat[key] = f"{md_flat[key]}\n{val}".strip()
            else:
                md_flat.setdefault(key, val)
        data["master_data"] = md_flat

        ts_flat: dict[str, str] = {}
        for item in ts_items:
            if not isinstance(item, dict):
                continue
            key = (item.get("name") or "").strip() or "Unnamed spec"
            val = (item.get("value") or "").strip()
            if key in ts_flat and val:
                ts_flat[key] = f"{ts_flat[key]}\n{val}".strip()
            else:
                ts_flat.setdefault(key, val)
        data["technical_specs"] = ts_flat

        return data