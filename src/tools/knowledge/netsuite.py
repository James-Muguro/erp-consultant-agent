"""
NetSuite ERP Knowledge Base.

Provides structured domain knowledge for NetSuite modules, business
processes, integrations, transactions, and implementation practices.
"""

from typing import Any, Dict, List, Optional

from src.tools.knowledge.base import ERPKnowledgeBase


class NetSuiteKnowledgeBase(ERPKnowledgeBase):
    """Knowledge base for NetSuite ERP."""

    ERP_NAME = "NetSuite"
    ERP_KEY = "netsuite"

    def __init__(self):
        super().__init__()

        self.modules = {
            "financial_management": {
                "name": "Financial Management",
                "description": (
                    "Core financial management capabilities covering general "
                    "ledger, accounts payable, accounts receivable, billing, "
                    "cash management, budgeting, and financial reporting."
                ),
                "sub_modules": [
                    "General Ledger",
                    "Accounts Payable",
                    "Accounts Receivable",
                    "Billing",
                    "Cash Management",
                    "Bank Reconciliation",
                    "Fixed Assets",
                    "Revenue Management",
                    "Budgeting",
                    "Financial Reporting",
                    "Multi-Book Accounting",
                    "Period Close Management",
                ],
                "common_transactions": [
                    "Journal Entry",
                    "Vendor Bill",
                    "Vendor Payment",
                    "Customer Invoice",
                    "Customer Payment",
                    "Credit Memo",
                    "Cash Sale",
                    "Deposit",
                    "Bank Reconciliation",
                    "Intercompany Journal Entry",
                ],
                "integration_points": [
                    "Procure-to-Pay",
                    "Order-to-Cash",
                    "Fixed Assets",
                    "Inventory Management",
                    "Revenue Management",
                    "Projects",
                    "Tax",
                    "Banking",
                    "Intercompany",
                ],
                "best_practices": [
                    "Design the chart of accounts around reporting requirements.",
                    "Use subsidiaries and accounting books deliberately in "
                    "multi-entity environments.",
                    "Define accounting periods and period-close controls before "
                    "transaction migration.",
                    "Use approval workflows for material financial transactions.",
                    "Minimize unnecessary customization of standard financial processes.",
                    "Define role permissions around segregation of duties.",
                ],
            },
            "order_management": {
                "name": "Order Management",
                "description": (
                    "Manages the order-to-cash lifecycle from customer orders "
                    "through fulfillment, invoicing, and payment."
                ),
                "sub_modules": [
                    "Sales Orders",
                    "Item Fulfillment",
                    "Invoicing",
                    "Cash Sales",
                    "Customer Payments",
                    "Returns",
                    "Credit Memos",
                    "Advanced Order Management",
                ],
                "common_transactions": [
                    "Estimate",
                    "Sales Order",
                    "Item Fulfillment",
                    "Invoice",
                    "Cash Sale",
                    "Customer Payment",
                    "Return Authorization",
                    "Customer Refund",
                    "Credit Memo",
                ],
                "integration_points": [
                    "Accounts Receivable",
                    "Inventory",
                    "Shipping",
                    "Revenue Management",
                    "CRM",
                    "Payment Processing",
                ],
                "best_practices": [
                    "Define the order-to-cash process before configuring transaction workflows.",
                    "Use consistent approval rules for sales orders and credit limits.",
                    "Define fulfillment rules based on inventory and business requirements.",
                    "Align billing triggers with the contractual revenue process.",
                    "Control customer and item master data centrally.",
                ],
            },
            "procurement": {
                "name": "Procurement",
                "description": (
                    "Supports the procure-to-pay lifecycle from purchasing "
                    "requests through purchase orders, receipts, vendor bills, "
                    "and payments."
                ),
                "sub_modules": [
                    "Purchase Requisitions",
                    "Purchase Orders",
                    "Item Receipts",
                    "Vendor Bills",
                    "Vendor Payments",
                    "Vendor Management",
                    "Procurement Approvals",
                ],
                "common_transactions": [
                    "Purchase Requisition",
                    "Purchase Order",
                    "Item Receipt",
                    "Vendor Bill",
                    "Vendor Credit",
                    "Vendor Payment",
                ],
                "integration_points": [
                    "Accounts Payable",
                    "Inventory",
                    "General Ledger",
                    "Expense Management",
                    "Vendor Management",
                ],
                "best_practices": [
                    "Use approval workflows based on amount, department, and subsidiary.",
                    "Standardize purchasing categories and item classifications.",
                    "Define receiving controls before enabling three-way matching.",
                    "Separate vendor creation from vendor payment authorization.",
                    "Maintain clear approval and audit trails for procurement transactions.",
                ],
            },
            "inventory": {
                "name": "Inventory Management",
                "description": (
                    "Manages inventory items, locations, quantities, costing, "
                    "receipts, fulfillment, transfers, and inventory adjustments."
                ),
                "sub_modules": [
                    "Item Management",
                    "Inventory Locations",
                    "Inventory Transfers",
                    "Inventory Adjustments",
                    "Inventory Costing",
                    "Demand Planning",
                    "Bin Management",
                    "Lot Tracking",
                    "Serial Number Tracking",
                ],
                "common_transactions": [
                    "Item Receipt",
                    "Item Fulfillment",
                    "Inventory Transfer",
                    "Inventory Adjustment",
                    "Inventory Count",
                    "Work Order",
                    "Assembly Build",
                    "Assembly Unbuild",
                ],
                "integration_points": [
                    "Procurement",
                    "Order Management",
                    "Warehouse Management",
                    "Manufacturing",
                    "Cost Accounting",
                    "General Ledger",
                ],
                "best_practices": [
                    "Design item and location structures before transaction migration.",
                    "Define inventory costing requirements before configuration.",
                    "Use appropriate controls for lot and serial-number tracking.",
                    "Separate inventory adjustment access from normal transaction processing.",
                    "Establish inventory reconciliation procedures between operational and financial records.",
                ],
            },
            "crm": {
                "name": "Customer Relationship Management",
                "description": (
                    "Supports customer, prospect, lead, opportunity, activity, "
                    "and sales pipeline management."
                ),
                "sub_modules": [
                    "Leads",
                    "Prospects",
                    "Customers",
                    "Opportunities",
                    "Activities",
                    "Sales Forecasting",
                    "Campaigns",
                    "Customer Support",
                ],
                "common_transactions": [
                    "Lead",
                    "Opportunity",
                    "Estimate",
                    "Sales Order",
                    "Customer Case",
                    "Customer Communication",
                ],
                "integration_points": [
                    "Order Management",
                    "Customer Management",
                    "Marketing",
                    "Support",
                    "Financial Management",
                ],
                "best_practices": [
                    "Define customer lifecycle stages clearly.",
                    "Keep customer master data governed across sales and finance.",
                    "Standardize opportunity stages and required fields.",
                    "Align sales processes with downstream order and billing processes.",
                ],
            },
            "projects": {
                "name": "Project Management",
                "description": (
                    "Supports project planning, resource management, time "
                    "tracking, project costing, billing, and profitability."
                ),
                "sub_modules": [
                    "Project Records",
                    "Project Tasks",
                    "Time Tracking",
                    "Project Expenses",
                    "Project Billing",
                    "Project Costing",
                    "Resource Management",
                ],
                "common_transactions": [
                    "Project",
                    "Project Task",
                    "Time Entry",
                    "Expense Report",
                    "Project Charge",
                    "Project Invoice",
                ],
                "integration_points": [
                    "Financial Management",
                    "Time Management",
                    "Resource Management",
                    "Billing",
                    "Revenue Management",
                ],
                "best_practices": [
                    "Define project structures before loading project data.",
                    "Separate project costing from customer billing requirements.",
                    "Standardize project and task classifications.",
                    "Establish approval controls for time and project expenses.",
                ],
            },
            "manufacturing": {
                "name": "Manufacturing",
                "description": (
                    "Supports manufacturing operations including bills of "
                    "materials, work orders, assemblies, production planning, "
                    "and manufacturing costing."
                ),
                "sub_modules": [
                    "Bills of Materials",
                    "Work Orders",
                    "Assemblies",
                    "Manufacturing Routing",
                    "Production Planning",
                    "Manufacturing Costing",
                ],
                "common_transactions": [
                    "Work Order",
                    "Work Order Completion",
                    "Work Order Close",
                    "Assembly Build",
                    "Assembly Unbuild",
                    "Inventory Adjustment",
                ],
                "integration_points": [
                    "Inventory",
                    "Procurement",
                    "Order Management",
                    "Financial Management",
                    "Demand Planning",
                ],
                "best_practices": [
                    "Validate bills of materials before production transactions begin.",
                    "Define work-center and routing structures around actual production processes.",
                    "Align manufacturing costing with financial reporting requirements.",
                    "Test inventory and accounting impacts together.",
                ],
            },
            "fixed_assets": {
                "name": "Fixed Assets Management",
                "description": (
                    "Manages asset acquisition, capitalization, depreciation, "
                    "transfers, disposal, and asset reporting."
                ),
                "sub_modules": [
                    "Asset Records",
                    "Asset Acquisition",
                    "Asset Capitalization",
                    "Depreciation",
                    "Asset Transfer",
                    "Asset Disposal",
                ],
                "common_transactions": [
                    "Asset Acquisition",
                    "Asset Capitalization",
                    "Asset Depreciation",
                    "Asset Transfer",
                    "Asset Disposal",
                ],
                "integration_points": [
                    "Accounts Payable",
                    "General Ledger",
                    "Procurement",
                    "Financial Reporting",
                ],
                "best_practices": [
                    "Define asset classes and depreciation rules before migration.",
                    "Reconcile the fixed asset register with the general ledger.",
                    "Control asset disposal and transfer permissions.",
                    "Document capitalization rules for each asset category.",
                ],
            },
            "revenue_management": {
                "name": "Revenue Management",
                "description": (
                    "Supports revenue recognition and revenue allocation for "
                    "contracts and transactions subject to revenue recognition requirements."
                ),
                "sub_modules": [
                    "Revenue Arrangements",
                    "Revenue Elements",
                    "Revenue Recognition",
                    "Fair Value Allocation",
                    "Revenue Forecasting",
                ],
                "common_transactions": [
                    "Revenue Arrangement",
                    "Revenue Element",
                    "Revenue Recognition Journal",
                    "Revenue Reclassification",
                ],
                "integration_points": [
                    "Order Management",
                    "Billing",
                    "General Ledger",
                    "Projects",
                    "Subscription Management",
                ],
                "best_practices": [
                    "Document revenue recognition requirements before configuration.",
                    "Map source transactions to revenue arrangements explicitly.",
                    "Test allocation and recognition scenarios across contract variations.",
                    "Reconcile recognized revenue to billing and general ledger balances.",
                ],
            },
            "analytics_reporting": {
                "name": "Analytics and Reporting",
                "description": (
                    "Provides saved searches, reports, dashboards, KPIs, "
                    "analytics, and SuiteAnalytics capabilities for operational "
                    "and financial reporting."
                ),
                "sub_modules": [
                    "Saved Searches",
                    "Reports",
                    "Dashboards",
                    "KPIs",
                    "SuiteAnalytics",
                    "Workbook",
                ],
                "common_transactions": [
                    "Saved Search",
                    "Report",
                    "Dashboard",
                    "KPI",
                    "Analytics Workbook",
                ],
                "integration_points": [
                    "All functional modules",
                    "General Ledger",
                    "Data Warehouse",
                    "External BI Platforms",
                ],
                "best_practices": [
                    "Define reporting requirements before creating custom searches.",
                    "Use standardized reporting dimensions across subsidiaries and departments.",
                    "Control access to financial and operational reporting.",
                    "Avoid duplicating standard reports without a clear business requirement.",
                ],
            },
        }

        self.business_processes = {
            "order_to_cash": {
                "name": "Order-to-Cash",
                "description": (
                    "End-to-end process from customer opportunity or order "
                    "through fulfillment, billing, receivables, and payment."
                ),
                "steps": [
                    "Customer or prospect management",
                    "Estimate or sales order",
                    "Order approval",
                    "Inventory allocation",
                    "Item fulfillment",
                    "Customer invoicing",
                    "Accounts receivable",
                    "Customer payment",
                    "Cash application and reconciliation",
                ],
                "modules": [
                    "CRM",
                    "Order Management",
                    "Inventory",
                    "Accounts Receivable",
                    "General Ledger",
                ],
            },
            "procure_to_pay": {
                "name": "Procure-to-Pay",
                "description": (
                    "End-to-end procurement process from purchasing request "
                    "through receipt, vendor billing, and payment."
                ),
                "steps": [
                    "Purchase requisition",
                    "Purchase order",
                    "Purchase approval",
                    "Goods or service receipt",
                    "Vendor bill",
                    "Three-way matching where applicable",
                    "Vendor payment",
                    "Bank reconciliation",
                ],
                "modules": [
                    "Procurement",
                    "Inventory",
                    "Accounts Payable",
                    "Cash Management",
                    "General Ledger",
                ],
            },
            "record_to_report": {
                "name": "Record-to-Report",
                "description": (
                    "Financial process covering transaction recording, "
                    "reconciliation, period close, consolidation, and reporting."
                ),
                "steps": [
                    "Transaction processing",
                    "Subledger reconciliation",
                    "Journal processing",
                    "Account reconciliation",
                    "Period close",
                    "Intercompany reconciliation",
                    "Consolidation",
                    "Financial reporting",
                ],
                "modules": [
                    "Financial Management",
                    "Intercompany",
                    "Multi-Book Accounting",
                    "Financial Reporting",
                ],
            },
        }

        self.integrations = {
            "suite_script": {
                "name": "SuiteScript",
                "description": (
                    "NetSuite's JavaScript-based platform for extending "
                    "business logic, workflows, records, and integrations."
                ),
                "use_cases": [
                    "Custom business logic",
                    "Record automation",
                    "Validation",
                    "Scheduled processing",
                    "User events",
                    "Custom REST services",
                ],
            },
            "suite_talk": {
                "name": "SuiteTalk",
                "description": (
                    "NetSuite integration framework supporting web-service "
                    "and REST-based integration patterns."
                ),
                "use_cases": [
                    "External system integration",
                    "Record synchronization",
                    "Data extraction",
                    "Transaction creation",
                    "Master data synchronization",
                ],
            },
            "csv_import": {
                "name": "CSV Import",
                "description": (
                    "Bulk data import mechanism for loading supported records "
                    "into NetSuite."
                ),
                "use_cases": [
                    "Initial data migration",
                    "Master data loads",
                    "Transaction imports",
                    "Bulk updates",
                ],
            },
        }

        self.testing_strategies = {
            "unit_testing": {
                "description": "Testing individual custom scripts, workflows, and configuration components.",
                "focus": "Custom logic, validations, scripts, workflows",
                "coverage": "Critical customizations and business rules",
            },
            "integration_testing": {
                "description": "Testing data and process flow between NetSuite and connected systems.",
                "focus": "APIs, integrations, synchronization, error handling",
                "coverage": "All critical external interfaces",
            },
            "end_to_end_testing": {
                "description": "Testing complete business processes across multiple NetSuite modules.",
                "focus": "Order-to-cash, procure-to-pay, record-to-report",
                "coverage": "Critical cross-functional processes",
            },
            "uat_testing": {
                "description": "Business-user validation of configured processes against agreed requirements.",
                "focus": "Business scenarios, reports, roles, usability",
                "coverage": "Approved business processes and acceptance criteria",
            },
            "regression_testing": {
                "description": "Verifying existing functionality after configuration or customization changes.",
                "focus": "Existing business processes and integrations",
                "coverage": "Critical processes affected by changes",
            },
        }

    def get_module_info(
        self,
        module_code: str,
    ) -> Optional[Dict[str, Any]]:
        """Return information about a NetSuite module."""

        key = module_code.lower().strip()

        aliases = {
            "fi": "financial_management",
            "finance": "financial_management",
            "financials": "financial_management",
            "financial management": "financial_management",
            "financial": "financial_management",
            "ar": "financial_management",
            "ap": "financial_management",
            "procurement": "procurement",
            "p2p": "procurement",
            "order management": "order_management",
            "o2c": "order_management",
            "inventory management": "inventory",
            "inventory": "inventory",
            "crm": "crm",
            "projects": "projects",
            "project management": "projects",
            "manufacturing": "manufacturing",
            "fixed assets": "fixed_assets",
            "assets": "fixed_assets",
            "revenue": "revenue_management",
            "revenue management": "revenue_management",
            "analytics": "analytics_reporting",
            "reporting": "analytics_reporting",
        }

        key = aliases.get(key, key)

        module = self.modules.get(key)

        if not module:
            return None

        return {
            "erp": self.ERP_NAME,
            "module_code": key,
            **module,
        }

    def get_transactions_by_module(
        self,
        module_code: str,
    ) -> List[str]:
        """Return common transactions for a NetSuite module."""

        module = self.get_module_info(module_code)

        if not module:
            return []

        return module.get("common_transactions", [])

    def get_best_practices(
        self,
        module_code: str,
    ) -> List[str]:
        """Return implementation best practices for a module."""

        module = self.get_module_info(module_code)

        if not module:
            return []

        return module.get("best_practices", [])

    def get_integration_points(
        self,
        module_code: str,
    ) -> List[str]:
        """Return standard integration points for a module."""

        module = self.get_module_info(module_code)

        if not module:
            return []

        return module.get("integration_points", [])

    def get_process_flow(
        self,
        process_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Return a standard NetSuite business process."""

        key = process_name.lower().strip()

        aliases = {
            "o2c": "order_to_cash",
            "order to cash": "order_to_cash",
            "p2p": "procure_to_pay",
            "procure to pay": "procure_to_pay",
            "r2r": "record_to_report",
            "record to report": "record_to_report",
        }

        key = aliases.get(key, key)

        process = self.business_processes.get(key)

        if not process:
            return None

        return {
            "erp": self.ERP_NAME,
            "process_code": key,
            **process,
        }

    def search_knowledge(
        self,
        query: str,
    ) -> List[Dict[str, Any]]:
        """Search NetSuite-specific knowledge."""

        results = []
        query_lower = query.lower().strip()

        if not query_lower:
            return results

        for code, module in self.modules.items():
            searchable = " ".join(
                [
                    module["name"],
                    module["description"],
                    " ".join(module.get("sub_modules", [])),
                    " ".join(module.get("common_transactions", [])),
                ]
            ).lower()

            if query_lower in searchable:
                results.append(
                    {
                        "type": "module",
                        "erp": self.ERP_NAME,
                        "code": code,
                        "name": module["name"],
                        "description": module["description"],
                    }
                )

        for code, process in self.business_processes.items():
            searchable = " ".join(
                [
                    process["name"],
                    process["description"],
                    " ".join(process.get("steps", [])),
                ]
            ).lower()

            if query_lower in searchable:
                results.append(
                    {
                        "type": "process",
                        "erp": self.ERP_NAME,
                        "code": code,
                        "name": process["name"],
                        "description": process["description"],
                    }
                )

        for code, integration in self.integrations.items():
            searchable = " ".join(
                [
                    integration["name"],
                    integration["description"],
                    " ".join(integration.get("use_cases", [])),
                ]
            ).lower()

            if query_lower in searchable:
                results.append(
                    {
                        "type": "integration",
                        "erp": self.ERP_NAME,
                        "code": code,
                        "name": integration["name"],
                        "description": integration["description"],
                    }
                )

        return results


NETSUITE = NetSuiteKnowledgeBase()