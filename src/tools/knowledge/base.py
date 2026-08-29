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
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ERPModule:
    """Represents an ERP module and its supporting knowledge."""

    name: str
    description: str
    sub_modules: List[str] = field(default_factory=list)
    common_transactions: List[str] = field(default_factory=list)
    integration_points: List[str] = field(default_factory=list)
    best_practices: List[str] = field(default_factory=list)


@dataclass
class ERPSystem:
    """Represents one ERP platform and its module catalogue."""

    name: str
    vendor: str
    aliases: List[str] = field(default_factory=list)
    modules: Dict[str, ERPModule] = field(default_factory=dict)


class ERPKnowledgeBase:
    """
    Central ERP knowledge base.

    ERP-specific knowledge is registered through register_erp().
    Consumers query this class instead of importing individual ERP
    knowledge modules directly.
    """

    def __init__(self):
        self._erps: Dict[str, ERPSystem] = {}
        self._aliases: Dict[str, str] = {}

        self.erp_concepts = self._initialize_general_concepts()
        self.testing_strategies = self._initialize_testing_strategies()

    # ------------------------------------------------------------------
    # ERP registration
    # ------------------------------------------------------------------

    def register_erp(self, erp: ERPSystem) -> None:
        """Register an ERP platform with the central knowledge base."""

        key = self._normalize(erp.name)

        self._erps[key] = erp

        aliases = set(erp.aliases)
        aliases.add(erp.name)

        for alias in aliases:
            self._aliases[self._normalize(alias)] = key

    def get_erp(self, erp_name: str) -> Optional[ERPSystem]:
        """Return an ERP system by name or alias."""

        key = self._aliases.get(self._normalize(erp_name))

        if not key:
            return None

        return self._erps.get(key)

    def list_erps(self) -> List[str]:
        """Return registered ERP platform names."""

        return [erp.name for erp in self._erps.values()]

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

        If erp_name is provided, lookup occurs only within that ERP.

        If erp_name is omitted, the module is searched across all
        registered ERP systems. If multiple ERPs contain the same
        module code, the result includes the ERP context.
        """

        module_code = module_code.upper().strip()

        if erp_name:
            erp = self.get_erp(erp_name)

            if not erp:
                return None

            module = erp.modules.get(module_code)

            if not module:
                return None

            return self._module_to_dict(
                erp=erp,
                module_code=module_code,
                module=module,
            )

        matches = []

        for erp in self._erps.values():
            module = erp.modules.get(module_code)

            if module:
                matches.append(
                    self._module_to_dict(
                        erp=erp,
                        module_code=module_code,
                        module=module,
                    )
                )

        if len(matches) == 1:
            return matches[0]

        if matches:
            return {
                "type": "multiple_matches",
                "module_code": module_code,
                "matches": matches,
            }

        return None

    def _module_to_dict(
        self,
        erp: ERPSystem,
        module_code: str,
        module: ERPModule,
    ) -> Dict[str, Any]:
        """Convert an ERPModule into the existing tool response shape."""

        return {
            "erp": erp.name,
            "vendor": erp.vendor,
            "code": module_code,
            "name": module.name,
            "description": module.description,
            "sub_modules": module.sub_modules,
            "common_transactions": module.common_transactions,
            "integration_points": module.integration_points,
            "best_practices": module.best_practices,
        }

    # ------------------------------------------------------------------
    # Module-related helpers
    # ------------------------------------------------------------------

    def get_transactions_by_module(
        self,
        module_code: str,
        erp_name: Optional[str] = None,
    ) -> List[str]:
        """Get common transactions for an ERP module."""

        info = self.get_module_info(module_code, erp_name)

        if not info:
            return []

        if info.get("type") == "multiple_matches":
            return []

        return info.get("common_transactions", [])

    def get_best_practices(
        self,
        module_code: str,
        erp_name: Optional[str] = None,
    ) -> List[str]:
        """Get best practices for an ERP module."""

        info = self.get_module_info(module_code, erp_name)

        if not info:
            return []

        if info.get("type") == "multiple_matches":
            return []

        return info.get("best_practices", [])

    def get_integration_points(
        self,
        module_code: str,
        erp_name: Optional[str] = None,
    ) -> List[str]:
        """Get standard integration points for an ERP module."""

        info = self.get_module_info(module_code, erp_name)

        if not info:
            return []

        if info.get("type") == "multiple_matches":
            return []

        return info.get("integration_points", [])

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
        behaviour expected by calling agents.
        """

        return None

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_knowledge(self, query: str) -> List[Dict[str, Any]]:
        """
        Search registered ERP knowledge.

        Search covers:
        - ERP names
        - aliases
        - module codes
        - module names
        - module descriptions
        - sub-modules
        - transactions
        - integration points
        - best practices
        - general ERP concepts
        """

        query_lower = query.lower().strip()

        if not query_lower:
            return []

        results: List[Dict[str, Any]] = []

        for erp in self._erps.values():
            erp_match = (
                query_lower in erp.name.lower()
                or query_lower in erp.vendor.lower()
                or any(query_lower in alias.lower() for alias in erp.aliases)
            )

            if erp_match:
                results.append(
                    {
                        "type": "erp",
                        "name": erp.name,
                        "vendor": erp.vendor,
                        "aliases": erp.aliases,
                    }
                )

            for code, module in erp.modules.items():
                searchable_values = [
                    code,
                    module.name,
                    module.description,
                    *module.sub_modules,
                    *module.common_transactions,
                    *module.integration_points,
                    *module.best_practices,
                ]

                if any(query_lower in value.lower() for value in searchable_values):
                    results.append(
                        {
                            "type": "module",
                            "erp": erp.name,
                            "vendor": erp.vendor,
                            "code": code,
                            "name": module.name,
                            "description": module.description,
                        }
                    )

        for concept_name, concept in self.erp_concepts.items():
            searchable_values = [
                concept_name,
                concept.get("description", ""),
                *concept.get("examples", []),
                *concept.get("types", []),
                *concept.get("best_practices", []),
            ]

            if any(query_lower in value.lower() for value in searchable_values):
                results.append(
                    {
                        "type": "concept",
                        "name": concept_name,
                        "description": concept.get("description"),
                    }
                )

        return results

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(value: str) -> str:
        """Normalize names used for ERP registry lookup."""

        return " ".join(value.lower().strip().split())


class ERPKnowledgeBaseTool:
    """
    Tool wrapper exposed to agents.

    The wrapper keeps the agent-facing API simple while the underlying
    knowledge base grows to support multiple ERP platforms.
    """

    def __init__(self, kb: ERPKnowledgeBase):
        self.kb = kb

    def query_module(
        self,
        module_code: str,
        erp_name: Optional[str] = None,
    ):
        return self.kb.get_module_info(module_code, erp_name)

    def query_transactions(
        self,
        module_code: str,
        erp_name: Optional[str] = None,
    ):
        return self.kb.get_transactions_by_module(module_code, erp_name)

    def query_best_practices(
        self,
        module_code: str,
        erp_name: Optional[str] = None,
    ):
        return self.kb.get_best_practices(module_code, erp_name)

    def query_integrations(
        self,
        module_code: str,
        erp_name: Optional[str] = None,
    ):
        return self.kb.get_integration_points(module_code, erp_name)

    def search(self, query: str):
        return self.kb.search_knowledge(query)

    def list_erps(self):
        return self.kb.list_erps()


# Global knowledge base instance.
erp_kb = ERPKnowledgeBase()

# Agent-facing tool instance.
erp_kb_tool = ERPKnowledgeBaseTool(erp_kb)