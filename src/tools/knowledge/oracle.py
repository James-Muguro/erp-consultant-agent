"""
Oracle ERP Knowledge Base

Domain knowledge for Oracle Fusion Cloud Applications.
Focuses on functional consulting, business processes, integrations,
testing, implementation, and common terminology.

Content policy
--------------
  * The `aliases` list is the set of strings get_erp() will resolve to
    this ERP. Adding Oracle legacy names (EBS, R12, JD Edwards) would be
    misleading - the content here is Fusion Cloud only, and a caller
    passing "EBS" would get Fusion material with no signal that the
    legacy product differs.

  * `common_processes` are Oracle's business process families
    (Record to Report, Procure to Pay). They are semantically distinct
    from transaction codes in the SAP sense and are held in this field
    deliberately rather than under `common_transactions`. When the base
    ERPModule schema gains a field for processes (or a
    Dict[str, Any] metadata extension), this file already conforms.
    Until then, the loader's fallback maps them into
    `common_transactions` - acceptable as a stopgap but worth knowing.

  * `common_transactions` (new in this revision) carries the Oracle
    "task" / "page" identifiers that a business user actually runs -
    things like "Create Invoice", "Submit Payment Process Request".
    These are the closest Oracle equivalent to SAP T-codes.

  * Top-level keys other than name/vendor/aliases/modules
    (core_concepts, common_integrations, implementation_lifecycle,
    testing, consulting_focus) are retained in this file so a future
    schema extension can capture them. The current loader's
    _convert_dict_source only reads the four fields above; the
    remaining content is not lost from the source file, but it is not
    currently reachable through erp_kb.
"""

from typing import Any, Dict, List


ORACLE: Dict[str, Any] = {
    "name": "Oracle Fusion Cloud Applications",
    "vendor": "Oracle",
    "category": "ERP",
    "aliases": [
        # Vendor / brand
        "Oracle",
        "Oracle ERP",
        "Oracle Cloud",
        "Oracle Cloud ERP",
        "Oracle ERP Cloud",
        # Product family
        "Oracle Fusion",
        "Oracle Fusion Cloud",
        "Oracle Fusion Cloud ERP",
        "Fusion Cloud",
        "Fusion Cloud ERP",
        "Fusion",
        "Oracle Fusion Applications",
        # Module-suite shorthand users often type
        "Oracle Financials",
        "Oracle Financials Cloud",
        "Oracle SCM",
        "Oracle Supply Chain",
        "Oracle HCM",
        "Oracle HCM Cloud",
    ],
    "description": (
        "Oracle Fusion Cloud Applications is a cloud ERP and business "
        "applications suite covering financials, procurement, project "
        "management, supply chain, manufacturing, and related business "
        "processes."
    ),

    "modules": {
        "financials": {
            "name": "Oracle Financials",
            "description": (
                "Core financial management capabilities covering general "
                "ledger, payables, receivables, assets, cash management, "
                "tax, and financial reporting."
            ),
            "sub_modules": [
                "General Ledger",
                "Accounts Payable",
                "Accounts Receivable",
                "Fixed Assets",
                "Cash Management",
                "Tax",
                "Expenses",
                "Intercompany",
                "Financial Reporting",
            ],
            "common_processes": [
                "Record to Report",
                "Accounts Payable",
                "Accounts Receivable",
                "Cash Management",
                "Asset Lifecycle",
                "Intercompany Accounting",
                "Period Close",
                "Financial Reporting",
            ],
            "common_transactions": [
                "Create Journal Entry",
                "Post Journal Entry",
                "Manage Journals",
                "Create Invoice (Payables)",
                "Create Credit Memo",
                "Submit Payment Process Request",
                "Manage Payment Process Requests",
                "Create Receipt (Receivables)",
                "Apply Receipt to Invoice",
                "Run Depreciation (Fixed Assets)",
                "Add Asset",
                "Transfer Asset",
                "Reconcile Bank Statement",
                "Close Accounting Period",
                "Run Financial Statement Reports",
            ],
            "integration_points": [
                "Procurement",
                "Order Management",
                "Inventory",
                "Projects",
                "Supply Chain",
                "Human Capital Management",
                "External Banking",
                "Tax Systems",
            ],
            "best_practices": [
                "Design the chart of accounts around reporting and statutory requirements.",
                "Define accounting calendars and ledgers before transactional configuration.",
                "Establish clear approval and segregation-of-duties controls.",
                "Use standardized supplier and customer master-data governance.",
                "Define intercompany balancing rules before cross-entity transactions begin.",
                "Validate period-close dependencies across integrated modules.",
                "Use role-based access aligned with business responsibilities.",
                "Use Subledger Accounting (SLA) for accounting rules rather than "
                "customizing individual subledgers - SLA is Oracle's supported extension point.",
                "Leverage the Accounting Hub for external-source accounting rather than "
                "duplicating entries via custom interfaces.",
            ],
        },

        "procurement": {
            "name": "Oracle Procurement",
            "description": (
                "Procurement capabilities covering sourcing, purchasing, "
                "supplier management, requisitions, purchase orders, and "
                "procure-to-pay processes."
            ),
            "sub_modules": [
                "Self Service Procurement",
                "Purchasing",
                "Sourcing",
                "Supplier Qualification",
                "Supplier Portal",
                "Procurement Contracts",
            ],
            "common_processes": [
                "Requisition to Purchase Order",
                "Procure to Pay",
                "Supplier Onboarding",
                "Supplier Qualification",
                "Sourcing Events",
                "Purchase Order Approval",
                "Receipt and Invoice Matching",
            ],
            "common_transactions": [
                "Create Requisition",
                "Manage Requisitions",
                "Create Purchase Order",
                "Manage Purchase Orders",
                "Approve Purchase Order",
                "Create Receipt",
                "Receive Goods",
                "Match Invoice to Purchase Order",
                "Register Supplier",
                "Manage Supplier Qualifications",
                "Create Sourcing Negotiation",
            ],
            "integration_points": [
                "Accounts Payable",
                "General Ledger",
                "Inventory",
                "Projects",
                "Order Management",
                "Supplier Portal",
            ],
            "best_practices": [
                "Define procurement approval rules based on organizational authority.",
                "Standardize supplier onboarding and qualification requirements.",
                "Use catalogs and negotiated agreements where appropriate.",
                "Define receiving and invoice-matching policies before configuration.",
                "Control supplier master data centrally.",
                "Align purchasing categories with reporting requirements.",
                "Use Oracle Sourcing for competitive events where the business "
                "procures commodities or services with multiple qualified suppliers.",
            ],
        },

        "order_management": {
            "name": "Oracle Order Management",
            "description": (
                "Manages order capture, orchestration, fulfillment, and "
                "order lifecycle processes."
            ),
            "sub_modules": [
                "Order Management",
                "Order Promising",
                "Order Orchestration",
                "Pricing",
                "Fulfillment",
            ],
            "common_processes": [
                "Order to Cash",
                "Sales Order Entry",
                "Order Scheduling",
                "Order Fulfillment",
                "Shipment",
                "Customer Invoicing",
                "Order Returns",
            ],
            "common_transactions": [
                "Create Order",
                "Manage Orders",
                "Submit Order",
                "Cancel Order",
                "Return Order",
                "Create Shipment",
                "Confirm Shipment",
                "Create Invoice from Order",
                "Apply Price List",
                "Run Order Orchestration",
            ],
            "integration_points": [
                "Accounts Receivable",
                "Inventory",
                "Shipping",
                "Procurement",
                "Manufacturing",
                "Product Information Management",
            ],
            "best_practices": [
                "Define order orchestration rules around fulfillment requirements.",
                "Separate order capture from fulfillment logic where appropriate.",
                "Validate pricing and customer-account dependencies early.",
                "Test partial fulfillment and backorder scenarios.",
                "Include returns and cancellations in end-to-end testing.",
            ],
        },

        "supply_chain": {
            "name": "Oracle Supply Chain Management",
            "description": (
                "Supply chain capabilities covering inventory, planning, "
                "manufacturing, maintenance, logistics, and product information."
            ),
            "sub_modules": [
                "Inventory Management",
                "Supply Planning",
                "Demand Management",
                "Manufacturing",
                "Maintenance",
                "Product Information Management",
                "Shipping",
                "Cost Management",
            ],
            "common_processes": [
                "Plan to Produce",
                "Inventory Management",
                "Demand to Supply",
                "Manufacturing",
                "Warehouse Operations",
                "Shipment",
                "Product Lifecycle Management",
            ],
            "common_transactions": [
                "Create Item",
                "Manage Items",
                "Create Subinventory Transfer",
                "Miscellaneous Transaction",
                "Create Work Order",
                "Release Work Order",
                "Complete Work Order",
                "Run Plan (Supply Planning)",
                "Create Shipping Document",
                "Manage Cost Adjustments",
            ],
            "integration_points": [
                "Procurement",
                "Order Management",
                "Financials",
                "Projects",
                "Product Lifecycle Management",
            ],
            "best_practices": [
                "Establish item and product master governance early.",
                "Define inventory organizations and locations around operational requirements.",
                "Validate supply and demand planning assumptions.",
                "Test inventory transactions across financial and operational flows.",
                "Align costing configuration with financial reporting requirements.",
            ],
        },

        "project_management": {
            "name": "Oracle Project Management",
            "description": (
                "Manages project planning, costing, billing, revenue, "
                "contracts, and project financial performance."
            ),
            "sub_modules": [
                "Project Control",
                "Project Costing",
                "Project Billing",
                "Project Contracts",
                "Project Performance Reporting",
            ],
            "common_processes": [
                "Project Creation",
                "Project Cost Capture",
                "Project Billing",
                "Project Revenue Recognition",
                "Project Budgeting",
                "Project Close",
            ],
            "common_transactions": [
                "Create Project",
                "Manage Project",
                "Create Project Budget",
                "Enter Project Expenditure",
                "Generate Project Invoice",
                "Run Project Costing",
                "Run Project Revenue Recognition",
                "Close Project",
            ],
            "integration_points": [
                "General Ledger",
                "Accounts Payable",
                "Accounts Receivable",
                "Procurement",
                "Human Capital Management",
            ],
            "best_practices": [
                "Define project structures before transactional configuration.",
                "Establish project costing rules early.",
                "Align project classifications with reporting requirements.",
                "Test project billing and revenue flows with Finance.",
                "Define project close procedures and ownership.",
            ],
        },

        # ------------------------------------------------------------------
        # Human Capital Management
        # ------------------------------------------------------------------
        "hcm": {
            "name": "Oracle Human Capital Management (HCM) Cloud",
            "description": (
                "Cloud HCM covering core HR, payroll, time and labor, "
                "benefits, talent management, recruiting, and workforce "
                "analytics. Common in implementations that run Financials "
                "and Payroll in the same Oracle Cloud tenant, or alongside "
                "existing HR systems in a hybrid landscape."
            ),
            "sub_modules": [
                "Core HR",
                "Payroll",
                "Time and Labor",
                "Absence Management",
                "Benefits",
                "Compensation",
                "Recruiting",
                "Talent Management",
                "Workforce Analytics",
            ],
            "common_processes": [
                "Hire to Retire",
                "Payroll to Payment",
                "Time to Payroll",
                "Absence to Return",
                "Recruit to Hire",
                "Performance to Reward",
            ],
            "common_transactions": [
                "Hire an Employee",
                "Manage Employee",
                "Terminate Employee",
                "Transfer Employee",
                "Calculate Payroll",
                "Run Payroll Process",
                "Approve Timecard",
                "Submit Absence Request",
                "Enroll in Benefits",
            ],
            "integration_points": [
                "Financials (payroll journals)",
                "Projects (labor cost allocation)",
                "Procurement (contractor spend)",
                "Third-party Payroll Providers",
                "Benefits Providers",
                "Time Clocks and Time-Capture Systems",
            ],
            "best_practices": [
                "Align the HCM organizational structure with the Financials "
                "business-unit and cost-center design before configuration.",
                "Decide early whether payroll runs in Oracle Cloud Payroll or "
                "a localized third-party provider - payroll localization "
                "coverage varies significantly by country.",
                "Treat employee master data as sensitive; apply role-based "
                "access and log privileged actions.",
                "Confirm cloud data-retention and localization constraints "
                "(GDPR and country-specific employment law) before loading "
                "historical employee data.",
            ],
        },

        # ------------------------------------------------------------------
        # Enterprise Performance Management
        # ------------------------------------------------------------------
        "epm": {
            "name": "Oracle Enterprise Performance Management (EPM) Cloud",
            "description": (
                "Cloud EPM covering planning, budgeting, forecasting, "
                "financial consolidation and close, account reconciliation, "
                "profitability and cost management, and narrative reporting. "
                "Often implemented alongside Fusion Cloud Financials as the "
                "management-reporting and consolidation layer."
            ),
            "sub_modules": [
                "Planning (EPBCS)",
                "Financial Consolidation and Close (FCCS)",
                "Account Reconciliation (ARCS)",
                "Profitability and Cost Management (PCMCS)",
                "Enterprise Data Management (EDMCS)",
                "Narrative Reporting",
                "Tax Reporting",
            ],
            "common_processes": [
                "Plan to Perform",
                "Forecast to Plan",
                "Consolidate to Report",
                "Reconcile to Close",
                "Profitability Analysis",
            ],
            "common_transactions": [
                "Create Plan",
                "Submit Plan Data",
                "Run Consolidation",
                "Match Reconciliations",
                "Run Allocation",
                "Publish Management Report",
            ],
            "integration_points": [
                "Financials (data integration)",
                "EPM Automate (CLI)",
                "Data Management",
                "Oracle Integration Cloud",
                "Third-party BI Tools",
            ],
            "best_practices": [
                "Decide early whether EPM is in scope - it is often "
                "underestimated in effort compared with Financials.",
                "Align the EPM chart of accounts / dimensions with the "
                "Financials chart of accounts to avoid reconciliation drift.",
                "Use EPM Automate for scheduled data loads; do not rely on "
                "manual uploads.",
                "Define consolidation and close procedures with the Finance "
                "team before configuring FCCS.",
            ],
        },
    },

    # ------------------------------------------------------------------
    # Additional knowledge - retained for future schema extensions
    # ------------------------------------------------------------------
    # Note: the loader's _convert_dict_source currently reads only the
    # top-level name/vendor/aliases/modules fields. The blocks below are
    # not lost from this source file, but they are not currently reachable
    # through erp_kb. When the ERPModule/ERPSystem schema is extended to
    # carry arbitrary metadata, these become available with no changes
    # here.
    "core_concepts": {
        "enterprise_structure": [
            "Enterprise",
            "Legal Entity",
            "Business Unit",
            "Ledger",
            "Primary Ledger",
            "Secondary Ledger",
            "Chart of Accounts",
            "Accounting Calendar",
            "Currency",
        ],
        "master_data": [
            "Customer",
            "Supplier",
            "Item",
            "Employee",
            "Bank Account",
            "Chart of Accounts",
            "Locations",
            "Business Units",
        ],
        "financial_controls": [
            "Approval Rules",
            "Segregation of Duties",
            "Accounting Rules",
            "Period Close",
            "Intercompany Balancing",
            "Tax Configuration",
            "Role-Based Access",
        ],
    },

    "common_integrations": [
        "REST APIs",
        "SOAP Web Services",
        "Oracle Integration Cloud",
        "File-Based Data Import",
        "Business Events",
        "External Banking Interfaces",
        "Third-Party Tax Systems",
        "External Reporting Platforms",
    ],

    "implementation_lifecycle": [
        "Discovery",
        "Requirements Gathering",
        "Fit-Gap Analysis",
        "Solution Design",
        "Configuration",
        "Integration Development",
        "Data Migration",
        "System Integration Testing",
        "User Acceptance Testing",
        "Training",
        "Cutover",
        "Go-Live",
        "Hypercare",
    ],

    "testing": {
        "unit_testing": [
            "Configuration validation",
            "Individual transaction testing",
            "Master-data validation",
            "Approval-rule testing",
        ],
        "integration_testing": [
            "Procure to Pay",
            "Order to Cash",
            "Record to Report",
            "Project to Cash",
            "Inventory to Financials",
            "Cross-module integrations",
        ],
        "uat": [
            "Business process scenarios",
            "Role-based workflows",
            "Exception handling",
            "Financial reporting",
            "Month-end and year-end processes",
        ],
        "negative_testing": [
            "Invalid master data",
            "Unauthorized transactions",
            "Missing required fields",
            "Approval rejection",
            "Period restrictions",
            "Invalid accounting combinations",
        ],
    },

    "consulting_focus": [
        "Requirements gathering",
        "Business process mapping",
        "Fit-gap analysis",
        "Solution design",
        "Configuration documentation",
        "Integration requirements",
        "Data migration planning",
        "Test case design",
        "UAT preparation",
        "User training",
        "Cutover planning",
        "Post-go-live support",
    ],
}


class Oracle:
    """Oracle Fusion Cloud ERP knowledge interface.

    NOTE: this class is not currently consumed by the knowledge-base
    loader (src/tools/knowledge/__init__.py imports `ORACLE`, the dict,
    and not this class). Its helpers exist for direct callers that want
    to browse Oracle knowledge without going through the ERP-agnostic
    facade. If you want the class to be reachable from `erp_kb`, the
    loader needs to know about it - it does not discover helper classes
    automatically.
    """

    name = ORACLE["name"]
    vendor = ORACLE["vendor"]

    def get_module_info(self, module: str) -> Dict[str, Any]:
        """Return information about an Oracle module.

        Accepts either the canonical module key ("financials",
        "order_management") or the display name ("Oracle Financials",
        "Oracle Order Management"). The lookups are tried in that order.
        """
        if not module:
            return {}
        key = module.lower().replace(" ", "_")
        info = ORACLE["modules"].get(key)
        if info:
            return info
        # Fallback: match by display name.
        module_lower = module.lower()
        for mod in ORACLE["modules"].values():
            if mod.get("name", "").lower() == module_lower:
                return mod
        return {}

    def get_modules(self) -> List[str]:
        """Return available Oracle modules (canonical keys)."""
        return list(ORACLE["modules"].keys())

    def get_processes(self, module: str) -> List[str]:
        """Return common business processes for a module."""
        info = self.get_module_info(module)
        return info.get("common_processes", [])

    def get_transactions(self, module: str) -> List[str]:
        """Return common functional identifiers (tasks/pages) for a
        module."""
        info = self.get_module_info(module)
        return info.get("common_transactions", [])

    def get_integration_points(self, module: str) -> List[str]:
        """Return integration points for a module."""
        info = self.get_module_info(module)
        return info.get("integration_points", [])

    def get_best_practices(self, module: str) -> List[str]:
        """Return module-specific best practices."""
        info = self.get_module_info(module)
        return info.get("best_practices", [])

    def get_core_concepts(self) -> Dict[str, List[str]]:
        """Return Oracle ERP core concepts."""
        return ORACLE["core_concepts"]

    def get_common_integrations(self) -> List[str]:
        """Return common Oracle integration mechanisms."""
        return ORACLE["common_integrations"]

    def get_implementation_lifecycle(self) -> List[str]:
        """Return the standard ERP implementation lifecycle."""
        return ORACLE["implementation_lifecycle"]

    def get_testing_strategies(self) -> Dict[str, List[str]]:
        """Return Oracle testing strategies."""
        return ORACLE["testing"]

    def search(self, query: str) -> List[Dict[str, Any]]:
        """Search Oracle knowledge by module, process, or concept.

        Substring matching on the combined text of each module's fields.
        Multi-word queries match as a literal substring (matching the
        base knowledge base's historical behaviour); for tokenized
        search, use erp_kb.search_knowledge instead.
        """
        query_lower = (query or "").lower().strip()
        if not query_lower:
            return []
        results: List[Dict[str, Any]] = []

        for module_code, module in ORACLE["modules"].items():
            searchable = " ".join(
                [
                    module["name"],
                    module["description"],
                    *module.get("sub_modules", []),
                    *module.get("common_processes", []),
                    *module.get("common_transactions", []),
                    *module.get("integration_points", []),
                    *module.get("best_practices", []),
                ]
            ).lower()

            if query_lower in searchable:
                results.append(
                    {
                        "erp": self.name,
                        "type": "module",
                        "module": module_code,
                        "name": module["name"],
                        "description": module["description"],
                    }
                )

        return results


oracle = Oracle()