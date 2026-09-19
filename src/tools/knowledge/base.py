"""
Shared ERP Knowledge Base foundation.

This module provides the common data structures, registry, lookup,
and search behaviour used by all ERP-specific knowledge bases.

ERP-specific knowledge belongs in separate modules such as:
    sap.py
    microsoft_dynamics.py
    oracle.py
    salesforce.py

The application interacts with one ERPKnowledgeBase instance regardless
of how many ERP knowledge sources are registered.

Notes on this revision:

  * Schema extension: ERPModule gained `common_tasks` and ERPSystem
    gained `metadata`. Both are additive with defaults, so existing ERP
    data files that don't declare them continue to work without
    modification. Together they close a real content-loss gap that
    surfaced across the Oracle and D365 module files:

      - `common_tasks` distinguishes user-facing tasks / menu items
        ("Create Purchase Order", "Submit timesheet") from transaction
        codes in the SAP sense ("ME21N"). Sources that use the
        task-style vocabulary (D365, Oracle Fusion) can now declare
        them honestly rather than having them mapped into
        `common_transactions` by the loader's fallback.

      - `metadata` is a free-form dict for ERP-level knowledge that
        isn't a module: core concepts, common integration mechanisms,
        implementation lifecycle notes, testing strategy hints. Oracle
        and D365 both have this content in their source files already;
        the loader can now capture it instead of dropping it.

  * Module code normalization: get_module_info and register_erp now
    both translate spaces and dashes to underscores before comparison.
    Previously a caller passing "Customer Service" (uppercased to
    "CUSTOMER SERVICE") missed the D365 module registered as
    "CUSTOMER_SERVICE" - a silent None with no signal. The same
    normalization applies to hyphenated and single-word codes, so
    "Order-to-Cash" and "Order to Cash" both resolve to
    "ORDER_TO_CASH" if such a module is registered.

  * Logger switched from stdlib `logging` to structlog `get_logger`.
    Every other module in the application uses the shared structlog
    logger so that lines carry the same context (request_id, user_id,
    session_id) and render in the same format. This module was an
    outlier; the switch is a one-line change at the import and no
    call-site changes.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class ERPModule:
    """Represents an ERP module and its supporting knowledge.

    Field semantics for the two "action" lists:

      common_transactions: ERP-native transaction codes / identifiers
        - SAP T-codes ("FB50", "ME21N"), Oracle forms identifiers if the
          deployment uses them, or equivalent short codes. This is the
          field for anything a technical user would type into a
          transaction launcher.

      common_tasks: User-facing tasks, menu items, or application page
        names - "Create Purchase Order", "Submit timesheet", "Manage
        Orders". Populated by sources whose ERP has no T-code convention
        (D365, Oracle Fusion). Downstream consumers should prefer
        `common_tasks` when displaying guidance to business users, and
        `common_transactions` when the audience is technical.

    Both lists may be populated; they are not mutually exclusive. A
    single ERP could theoretically expose both if a deployment uses
    T-codes for power users and page names for business users.
    """

    name: str
    description: str
    sub_modules: List[str] = field(default_factory=list)
    common_transactions: List[str] = field(default_factory=list)
    common_tasks: List[str] = field(default_factory=list)
    integration_points: List[str] = field(default_factory=list)
    best_practices: List[str] = field(default_factory=list)


@dataclass
class ERPSystem:
    """Represents one ERP platform and its module catalogue.

    `metadata` is a free-form dict for ERP-level knowledge that isn't
    tied to any specific module. Typical contents (all optional):
        core_concepts: Dict[str, List[str]]   - enterprise structure,
                                                 master data categories,
                                                 financial controls, ...
        common_integrations: List[str]        - integration mechanisms
                                                 (REST, SOAP, OIC, FBDI, ...)
        implementation_lifecycle: List[str]   - ERP-specific lifecycle
                                                 phase naming, if it differs
                                                 from the generic one
        testing: Dict[str, List[str]]         - ERP-specific test
                                                 categories and scope hints
        consulting_focus: List[str]           - consulting workstreams
        category: str                         - "ERP" | "CRM" | "HCM" | ...
        description: str                      - long-form description
    Consumers should treat any missing key as "not provided" rather than
    an error, and should not assume any particular schema within the
    dict - the shape is source-specific by design.
    """

    name: str
    vendor: str
    aliases: List[str] = field(default_factory=list)
    modules: Dict[str, ERPModule] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------
# Module codes appear in three forms across sources:
#   - Single-word uppercase: "FI", "MM", "SD"        (SAP)
#   - Underscored uppercase: "CUSTOMER_SERVICE"      (D365)
#   - Lowercase with spaces: "order management"      (Oracle loader input)
# All three must resolve to the same canonical key: underscored uppercase.
#
# This function is the single source of truth for that mapping. Both
# register_erp and get_module_info call it, so they cannot drift.
def _normalize_module_code(code: Any) -> str:
    """Canonicalize a module code: uppercase, no leading/trailing
    whitespace, spaces and dashes replaced with underscores. Returns
    "" for None or an all-whitespace input."""
    if code is None:
        return ""
    s = str(code).strip().upper()
    if not s:
        return ""
    return s.replace(" ", "_").replace("-", "_")


def _normalize_name(value: Optional[str]) -> str:
    """Normalize ERP names and aliases for registry lookup. Lowercase,
    collapsed whitespace. Distinct from module-code normalization: ERP
    names contain spaces naturally ("Microsoft Dynamics 365"), module
    codes do not."""
    if not value:
        return ""
    return " ".join(value.lower().strip().split())


class ERPKnowledgeBase:
    """
    Central ERP knowledge base.

    ERP-specific knowledge is registered through register_erp().
    Consumers query this class instead of importing individual ERP
    knowledge modules directly.

    Thread safety: register_erp is guarded by a lock, so registration
    may happen lazily or from a background initializer. Read methods
    (get_module_info, search_knowledge, etc.) are not locked; they rely
    on the invariant that registration is complete before the first
    read. In the current application, all registration happens at
    import time, which satisfies that invariant. If you ever add
    runtime registration (e.g. hot-loading a new ERP system), reads
    become racy and would need an immutable-snapshot approach.
    """

    def __init__(self):
        self._erps: Dict[str, ERPSystem] = {}
        self._aliases: Dict[str, str] = {}
        self._register_lock = threading.Lock()
        self._process_flow_warned = False

        self.erp_concepts = self._initialize_general_concepts()
        self.testing_strategies = self._initialize_testing_strategies()

    # ------------------------------------------------------------------
    # ERP registration
    # ------------------------------------------------------------------

    def register_erp(self, erp: ERPSystem) -> None:
        """Register an ERP platform with the central knowledge base.

        Module codes are normalized on registration to canonical form
        (uppercased; spaces and dashes converted to underscores), so
        lookup doesn't need to scan for the right spelling. Without
        this, a module registered as "Customer Service" was invisible
        to a lookup for "CUSTOMER_SERVICE" and vice versa.

        Mutates the passed-in ERPSystem in place, replacing its modules
        dict with the normalized-keys version. Callers that pass a
        fresh ERPSystem (the normal pattern) are unaffected; callers
        that hold a reference for later inspection see the normalized
        form.
        """
        key = _normalize_name(erp.name)

        # Normalize module codes once, at registration. Duplicate codes
        # after normalization are a source-data bug and are logged.
        normalized_modules: Dict[str, ERPModule] = {}
        for code, module in erp.modules.items():
            norm_code = _normalize_module_code(code)
            if not norm_code:
                logger.warning(
                    "register_erp: skipping module with empty code on ERP %r",
                    erp.name,
                )
                continue
            if norm_code in normalized_modules:
                logger.warning(
                    "register_erp: duplicate module code %r (after normalization) "
                    "on ERP %r; keeping the first registration",
                    norm_code, erp.name,
                )
                continue
            normalized_modules[norm_code] = module
        erp.modules = normalized_modules

        # Ensure metadata is a dict (defensive against a source that
        # passed None or a non-dict).
        if not isinstance(erp.metadata, dict):
            logger.warning(
                "register_erp: ERP %r has non-dict metadata of type %s; "
                "resetting to empty dict",
                erp.name, type(erp.metadata).__name__,
            )
            erp.metadata = {}

        with self._register_lock:
            self._erps[key] = erp

            aliases = set(erp.aliases or [])
            aliases.add(erp.name)

            for alias in aliases:
                if not alias:
                    continue
                self._aliases[_normalize_name(alias)] = key

        logger.info(
            "Registered ERP: %s (%d module(s), %d alias(es), metadata keys=%s)",
            erp.name, len(erp.modules), len(aliases),
            sorted(erp.metadata.keys()) if erp.metadata else [],
        )

    def get_erp(self, erp_name: str) -> Optional[ERPSystem]:
        """Return an ERP system by name or alias.

        Returns None when the name is not recognized. A WARNING is logged
        - a caller passing a name that doesn't match a registered alias
        (e.g. 'SAP S/4HANA' when registration used 'SAP S4HANA') is
        almost always a bug, and previously it produced an empty context
        with no signal at all."""
        if not erp_name:
            return None
        key = self._aliases.get(_normalize_name(erp_name))
        if not key:
            logger.warning(
                "get_erp: no ERP registered under name or alias %r. "
                "Registered ERPs: %s",
                erp_name, self.list_erps(),
            )
            return None
        return self._erps.get(key)

    def list_erps(self) -> List[str]:
        """Return registered ERP platform names."""
        return [erp.name for erp in self._erps.values()]

    def list_aliases(self) -> Dict[str, str]:
        """Return the normalized-alias -> ERP-canonical-name mapping.

        Diagnostic helper - useful when a caller can't figure out why
        get_erp isn't finding a name it expects to be registered."""
        return {
            alias: self._erps[key].name
            for alias, key in self._aliases.items()
            if key in self._erps
        }

    def list_module_codes(self, erp_name: Optional[str] = None) -> List[str]:
        """Return module codes known to the KB, optionally scoped to one
        ERP. Diagnostic helper for the same reason as list_aliases."""
        if erp_name:
            erp = self.get_erp(erp_name)
            if not erp:
                return []
            return sorted(erp.modules.keys())
        codes: set = set()
        for erp in self._erps.values():
            codes.update(erp.modules.keys())
        return sorted(codes)

    # ------------------------------------------------------------------
    # Module lookup
    # ------------------------------------------------------------------

    def get_module_info(
        self,
        module_code: str,
        erp_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get information about an ERP module.

        The module code is canonicalized (uppercased; spaces and dashes
        to underscores) before lookup, so "Customer Service",
        "customer_service", "CUSTOMER_SERVICE", and "Customer-Service"
        all resolve to the same module.

        If erp_name is provided, lookup occurs only within that ERP.

        If erp_name is omitted, the module is searched across all
        registered ERP systems. When multiple ERPs contain the same
        module code, the return value carries an 'ambiguous' flag, an
        empty set of the standard fields, and a 'matches' list.

        Return contract (stable across all branches):
          None                          module or ERP not found
          {'erp': ..., 'name': ..., ...}                 single match
          {'ambiguous': True,
           'name': None, 'description': None, ...,
           'matches': [<module dict>, ...]}              multiple matches

        Every non-None return includes the same keys (erp, vendor, code,
        name, description, sub_modules, common_transactions,
        common_tasks, integration_points, best_practices) plus
        'ambiguous'. Callers can safely do .get('name') without a
        KeyError on any branch.
        """
        if not module_code:
            return None
        module_code = _normalize_module_code(module_code)
        if not module_code:
            return None

        if erp_name:
            erp = self.get_erp(erp_name)
            if not erp:
                # get_erp already logged; return None so the caller's
                # standard "no context" path runs.
                return None

            module = erp.modules.get(module_code)
            if not module:
                logger.info(
                    "get_module_info: module code %r not found under ERP %r. "
                    "Known codes for this ERP: %s",
                    module_code, erp.name, sorted(erp.modules.keys()),
                )
                return None

            return self._module_to_dict(erp=erp, module_code=module_code, module=module)

        # Cross-ERP lookup (no erp_name provided).
        matches = []
        for erp in self._erps.values():
            module = erp.modules.get(module_code)
            if module:
                matches.append(
                    self._module_to_dict(
                        erp=erp, module_code=module_code, module=module,
                    )
                )

        if len(matches) == 1:
            return matches[0]

        if matches:
            logger.info(
                "get_module_info: module code %r is ambiguous across ERPs "
                "(%d matches); callers should pass erp_name to disambiguate.",
                module_code, len(matches),
            )
            # Stable shape: same keys as a single match, but with the
            # primary fields set to None and 'ambiguous: True' + 'matches'.
            return {
                "ambiguous": True,
                "erp": None,
                "vendor": None,
                "code": module_code,
                "name": None,
                "description": None,
                "sub_modules": [],
                "common_transactions": [],
                "common_tasks": [],
                "integration_points": [],
                "best_practices": [],
                "matches": matches,
            }

        logger.info(
            "get_module_info: module code %r not found in any registered ERP. "
            "Known codes across all ERPs: %s",
            module_code, self.list_module_codes(),
        )
        return None

    def _module_to_dict(
        self,
        erp: ERPSystem,
        module_code: str,
        module: ERPModule,
    ) -> Dict[str, Any]:
        """Convert an ERPModule into the tool response shape. 'ambiguous'
        is always present for shape stability across the two non-None
        return branches."""
        return {
            "ambiguous": False,
            "erp": erp.name,
            "vendor": erp.vendor,
            "code": module_code,
            "name": module.name,
            "description": module.description,
            "sub_modules": list(module.sub_modules or []),
            "common_transactions": list(module.common_transactions or []),
            "common_tasks": list(module.common_tasks or []),
            "integration_points": list(module.integration_points or []),
            "best_practices": list(module.best_practices or []),
        }

    # ------------------------------------------------------------------
    # Module-related helpers
    # ------------------------------------------------------------------

    def get_transactions_by_module(
        self,
        module_code: str,
        erp_name: Optional[str] = None,
    ) -> List[str]:
        """Get the module's native transaction codes (SAP T-codes, etc.).

        Does NOT fall back to common_tasks - callers who want a unified
        action list regardless of source should use
        get_actions_by_module."""
        info = self.get_module_info(module_code, erp_name)
        if not info or info.get("ambiguous"):
            return []
        return info.get("common_transactions", []) or []

    def get_tasks_by_module(
        self,
        module_code: str,
        erp_name: Optional[str] = None,
    ) -> List[str]:
        """Get the module's user-facing tasks / menu items / page names.
        Populated for ERPs without a T-code convention (D365, Oracle
        Fusion). Empty for SAP-style sources unless they declare it."""
        info = self.get_module_info(module_code, erp_name)
        if not info or info.get("ambiguous"):
            return []
        return info.get("common_tasks", []) or []

    def get_actions_by_module(
        self,
        module_code: str,
        erp_name: Optional[str] = None,
    ) -> List[str]:
        """Get a unified action list for the module: transaction codes
        first, then tasks. This is the list most agents want when
        generating guidance or test cases - they don't care whether the
        underlying ERP uses T-codes or page names."""
        info = self.get_module_info(module_code, erp_name)
        if not info or info.get("ambiguous"):
            return []
        combined = list(info.get("common_transactions") or [])
        combined.extend(info.get("common_tasks") or [])
        return combined

    def get_best_practices(
        self,
        module_code: str,
        erp_name: Optional[str] = None,
    ) -> List[str]:
        """Get best practices for an ERP module."""
        info = self.get_module_info(module_code, erp_name)
        if not info or info.get("ambiguous"):
            return []
        return info.get("best_practices", []) or []

    def get_integration_points(
        self,
        module_code: str,
        erp_name: Optional[str] = None,
    ) -> List[str]:
        """Get standard integration points for an ERP module."""
        info = self.get_module_info(module_code, erp_name)
        if not info or info.get("ambiguous"):
            return []
        return info.get("integration_points", []) or []

    def get_erp_metadata(
        self,
        erp_name: str,
        key: Optional[str] = None,
    ) -> Any:
        """Return an ERP's metadata dict, or one specific key from it.

        Returns {} when the ERP is unknown or has no metadata. Returns
        None when a specific key was requested and isn't present, so
        callers can distinguish "the ERP has no metadata" (empty dict)
        from "this particular key isn't set" (None)."""
        erp = self.get_erp(erp_name)
        if not erp:
            return {} if key is None else None
        md = erp.metadata if isinstance(erp.metadata, dict) else {}
        if key is None:
            return dict(md)
        return md.get(key)

    # ------------------------------------------------------------------
    # General ERP concepts
    # ------------------------------------------------------------------

    def _initialize_general_concepts(self) -> Dict[str, Dict[str, Any]]:
        """Initialize ERP concepts shared across platforms."""
        return {
            "master_data": {
                "description": "Core business data that remains consistent across transactions.",
                "examples": [
                    "Customer master",
                    "Vendor or supplier master",
                    "Material or item master",
                    "Chart of accounts",
                    "Cost center",
                    "Employee master",
                ],
                "best_practices": [
                    "Establish clear ownership for master data.",
                    "Use validation rules to prevent invalid records.",
                    "Apply consistent naming and coding standards.",
                    "Control duplicate creation.",
                    "Maintain an auditable change history.",
                ],
            },
            "transactional_data": {
                "description": "Business events recorded as operational or financial transactions.",
                "examples": [
                    "Sales orders",
                    "Purchase orders",
                    "Goods receipts",
                    "Invoices",
                    "Payments",
                    "Journal entries",
                ],
                "best_practices": [
                    "Define document types and numbering rules.",
                    "Apply appropriate approval controls.",
                    "Maintain traceability from source transaction to accounting impact.",
                    "Define retention and archival requirements.",
                ],
            },
            "integration": {
                "description": "Data and process flow between ERP modules and external systems.",
                "types": [
                    "Real-time integration",
                    "Batch integration",
                    "Event-driven integration",
                    "API-based integration",
                    "File-based integration",
                    "Middleware-based integration",
                ],
                "best_practices": [
                    "Define ownership for each integration endpoint.",
                    "Document source-to-target mappings.",
                    "Implement retry and error handling.",
                    "Monitor failures and processing delays.",
                    "Protect credentials and sensitive data.",
                    "Maintain reconciliation between source and target systems.",
                ],
            },
            "security": {
                "description": "Controls governing access to ERP data, processes, and functionality.",
                "best_practices": [
                    "Apply least-privilege access.",
                    "Separate conflicting duties.",
                    "Use role-based access controls.",
                    "Review privileged access regularly.",
                    "Maintain audit logs for sensitive activities.",
                ],
            },
            "reporting": {
                "description": "Operational, management, and financial reporting generated from ERP data.",
                "best_practices": [
                    "Define authoritative sources for key metrics.",
                    "Document report logic and filters.",
                    "Reconcile financial reports to the general ledger where applicable.",
                    "Control report access.",
                    "Avoid duplicating business logic across reports.",
                ],
            },
        }

    # ------------------------------------------------------------------
    # Testing
    # ------------------------------------------------------------------

    def _initialize_testing_strategies(self) -> Dict[str, Dict[str, str]]:
        """Initialize ERP implementation testing strategies."""
        return {
            "unit_testing": {
                "description": "Tests an individual configuration, function, extension, or component.",
                "focus": "Individual components and isolated business rules.",
                "coverage": "Custom code, critical configuration, validation rules.",
            },
            "integration_testing": {
                "description": "Tests data and process flow across ERP modules and connected systems.",
                "focus": "End-to-end process chains and interfaces.",
                "coverage": "Critical integrations and cross-module processes.",
            },
            "system_testing": {
                "description": "Tests the configured ERP solution as an integrated system.",
                "focus": "Complete business processes and system behaviour.",
                "coverage": "End-to-end scenarios across the implementation scope.",
            },
            "uat_testing": {
                "description": "Business users validate that the solution supports agreed requirements.",
                "focus": "Realistic business scenarios and expected outcomes.",
                "coverage": "Critical business processes and user-facing outputs.",
            },
            "performance_testing": {
                "description": "Validates system behaviour under expected and peak workloads.",
                "focus": "Response times, batch processing, concurrency, and throughput.",
                "coverage": "Critical transactions, integrations, reports, and peak workloads.",
            },
            "regression_testing": {
                "description": "Confirms existing functionality remains stable after changes.",
                "focus": "Previously validated critical processes.",
                "coverage": "Processes affected directly or indirectly by changes.",
            },
        }

    def get_testing_strategy(self, strategy_key: str) -> Optional[Dict[str, str]]:
        """Return one testing strategy by key, or None if unknown."""
        return self.testing_strategies.get(strategy_key)

    def get_concept(self, concept_name: str) -> Optional[Dict[str, Any]]:
        """Return one general ERP concept by name, or None if unknown."""
        return self.erp_concepts.get(concept_name)

    # ------------------------------------------------------------------
    # Process flows
    # ------------------------------------------------------------------

    def get_process_flow(
        self,
        process_name: str,
        erp_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Return a standard process flow when one exists.

        Process-flow content will be added as ERP-specific knowledge
        develops. Returning None preserves the existing optional
        behaviour expected by calling agents. Logs a one-shot INFO on
        first call so operators can distinguish "this method is a
        placeholder" from "a configured lookup found no result."

        Process-flow content, when added, belongs in ERPSystem.metadata
        under a `process_flows` key rather than requiring a schema
        change - the metadata dict is designed for exactly this kind
        of extension.
        """
        if not self._process_flow_warned:
            logger.info(
                "get_process_flow: process-flow knowledge is not yet "
                "populated; returning None for process_name=%r. This is a "
                "one-shot notice per process lifetime.",
                process_name,
            )
            self._process_flow_warned = True

        # When process flows are added, they'll live in ERPSystem.metadata
        # keyed as {"process_flows": {name: {...}}}. This method will read
        # from there. For now, always None.
        return None

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_knowledge(
        self,
        query: str,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search registered ERP knowledge.

        Search covers:
        - ERP names
        - aliases
        - ERP metadata (values, recursively)
        - module codes
        - module names
        - module descriptions
        - sub-modules
        - transactions (common_transactions)
        - tasks (common_tasks)
        - integration points
        - best practices
        - general ERP concepts

        Query handling: the query is tokenized on whitespace, and a
        value matches if it contains ANY token (case-insensitive).
        Results are ordered by number of matched tokens, descending.
        """
        tokens = [t for t in (query or "").lower().split() if t]
        if not tokens:
            return []

        results: List[Dict[str, Any]] = []

        def _match_score(value: Any) -> int:
            """Return the number of query tokens present in `value`,
            recursively scanning containers. Returns 0 for values that
            can't be stringified meaningfully."""
            if value is None:
                return 0
            if isinstance(value, str):
                low = value.lower()
                return sum(1 for t in tokens if t in low)
            if isinstance(value, dict):
                return sum(_match_score(k) + _match_score(v) for k, v in value.items())
            if isinstance(value, (list, tuple, set)):
                return sum(_match_score(v) for v in value)
            # Numbers, booleans - stringify and match.
            try:
                return _match_score(str(value))
            except Exception:  # noqa: BLE001
                return 0

        for erp in self._erps.values():
            # ERP-level matches: name, vendor, aliases, and metadata
            # (metadata scanning surfaces hits on core concepts,
            # common_integrations, implementation_lifecycle, etc.).
            erp_score = (
                _match_score(erp.name)
                + _match_score(erp.vendor)
                + _match_score(list(erp.aliases or []))
                + _match_score(erp.metadata)
            )
            if erp_score > 0:
                results.append({
                    "type": "erp",
                    "name": erp.name,
                    "vendor": erp.vendor,
                    "aliases": erp.aliases,
                    "_score": erp_score,
                })

            # Module-level matches.
            for code, module in erp.modules.items():
                score = (
                    _match_score(code)
                    + _match_score(module.name)
                    + _match_score(module.description)
                    + _match_score(module.sub_modules or [])
                    + _match_score(module.common_transactions or [])
                    + _match_score(module.common_tasks or [])
                    + _match_score(module.integration_points or [])
                    + _match_score(module.best_practices or [])
                )
                if score > 0:
                    results.append({
                        "type": "module",
                        "erp": erp.name,
                        "vendor": erp.vendor,
                        "code": code,
                        "name": module.name,
                        "description": module.description,
                        "_score": score,
                    })

        for concept_name, concept in self.erp_concepts.items():
            score = (
                _match_score(concept_name)
                + _match_score(concept.get("description", ""))
                + _match_score(concept.get("examples", []))
                + _match_score(concept.get("types", []))
                + _match_score(concept.get("best_practices", []))
            )
            if score > 0:
                results.append({
                    "type": "concept",
                    "name": concept_name,
                    "description": concept.get("description"),
                    "_score": score,
                })

        # Highest score first. Stable across ties via name.
        results.sort(key=lambda r: (-r["_score"], r.get("name") or r.get("code") or ""))

        # Strip the internal score before returning - it was a ranking
        # artifact, not part of the public shape.
        for r in results:
            r.pop("_score", None)

        if limit is not None and limit > 0:
            results = results[:limit]

        return results


class ERPKnowledgeBaseTool:
    """
    Tool wrapper exposed to agents.

    The wrapper keeps the agent-facing API simple while the underlying
    knowledge base grows to support multiple ERP platforms.
    """

    def __init__(self, kb: ERPKnowledgeBase):
        self.kb = kb

    def query_module(self, module_code: str, erp_name: Optional[str] = None):
        """Return module info for `module_code`, optionally scoped to an
        ERP. See ERPKnowledgeBase.get_module_info for the return contract."""
        return self.kb.get_module_info(module_code, erp_name)

    def query_transactions(self, module_code: str, erp_name: Optional[str] = None):
        """Return the module's native transaction codes, or [] if unknown."""
        return self.kb.get_transactions_by_module(module_code, erp_name)

    def query_tasks(self, module_code: str, erp_name: Optional[str] = None):
        """Return the module's user-facing tasks / menu items, or [] if
        unknown."""
        return self.kb.get_tasks_by_module(module_code, erp_name)

    def query_actions(self, module_code: str, erp_name: Optional[str] = None):
        """Return a unified action list (transactions + tasks), or [] if
        unknown. This is the list to prefer for user-facing guidance and
        test case generation when the caller doesn't care about the
        underlying convention."""
        return self.kb.get_actions_by_module(module_code, erp_name)

    def query_best_practices(self, module_code: str, erp_name: Optional[str] = None):
        """Return the module's best-practice list, or [] if unknown."""
        return self.kb.get_best_practices(module_code, erp_name)

    def query_integrations(self, module_code: str, erp_name: Optional[str] = None):
        """Return the module's standard integration points, or [] if unknown."""
        return self.kb.get_integration_points(module_code, erp_name)

    def query_metadata(self, erp_name: str, key: Optional[str] = None):
        """Return an ERP's metadata dict, or one specific key from it."""
        return self.kb.get_erp_metadata(erp_name, key)

    def search(self, query: str, limit: Optional[int] = None):
        """Tokenized search across all registered knowledge."""
        return self.kb.search_knowledge(query, limit=limit)

    def list_erps(self):
        """Return registered ERP platform names."""
        return self.kb.list_erps()


# Global knowledge base instance.
erp_kb = ERPKnowledgeBase()

# Agent-facing tool instance.
erp_kb_tool = ERPKnowledgeBaseTool(erp_kb)