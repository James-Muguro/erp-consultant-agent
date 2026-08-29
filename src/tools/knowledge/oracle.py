"""
Oracle ERP Knowledge Base

Domain knowledge for Oracle Fusion Cloud Applications.
Focuses on functional consulting, business processes,
integrations, testing, implementation, and common terminology.
"""

from typing import Any, Dict, List


ORACLE: Dict[str, Any] = {
    "name": "Oracle Fusion Cloud Applications",
    "vendor": "Oracle",
    "category": "ERP",
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
    },

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
    """Oracle Fusion Cloud ERP knowledge interface."""

    name = ORACLE["name"]
    vendor = ORACLE["vendor"]

    def get_module_info(self, module: str) -> Dict[str, Any]:
        """Return information about an Oracle module."""
        key = module.lower().replace(" ", "_")

        return ORACLE["modules"].get(key, {})

    def get_modules(self) -> List[str]:
        """Return available Oracle modules."""
        return list(ORACLE["modules"].keys())

    def get_processes(self, module: str) -> List[str]:
        """Return common business processes for a module."""
        info = self.get_module_info(module)
        return info.get("common_processes", [])

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
        """Search Oracle knowledge by module, process, or concept."""
        query_lower = query.lower()
        results: List[Dict[str, Any]] = []

        for module_code, module in ORACLE["modules"].items():
            searchable = " ".join(
                [
                    module["name"],
                    module["description"],
                    *module["sub_modules"],
                    *module["common_processes"],
                    *module["integration_points"],
                    *module["best_practices"],
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