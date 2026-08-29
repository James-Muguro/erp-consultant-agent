"""
Odoo ERP Knowledge Base.

Provides structured domain knowledge for Odoo modules, business
processes, integrations, transactions, and implementation practices.
"""

from typing import Any, Dict, List, Optional

from src.tools.knowledge.base import ERPKnowledgeBase


class OdooKnowledgeBase(ERPKnowledgeBase):
    """Knowledge base for Odoo ERP."""

    ERP_NAME = "Odoo"
    ERP_KEY = "odoo"

    def __init__(self):
        super().__init__()

        self.modules = {
            "accounting": {
                "name": "Accounting",
                "description": (
                    "Financial management covering general ledger, accounts "
                    "payable, accounts receivable, payments, bank reconciliation, "
                    "tax, budgeting, and financial reporting."
                ),
                "sub_modules": [
                    "General Ledger",
                    "Accounts Payable",
                    "Accounts Receivable",
                    "Customer Invoicing",
                    "Vendor Bills",
                    "Payments",
                    "Bank Reconciliation",
                    "Taxes",
                    "Budgets",
                    "Analytic Accounting",
                    "Fixed Assets",
                    "Financial Reporting",
                    "Multi-Currency",
                ],
                "common_transactions": [
                    "Customer Invoice",
                    "Vendor Bill",
                    "Credit Note",
                    "Customer Payment",
                    "Vendor Payment",
                    "Journal Entry",
                    "Bank Transaction",
                    "Asset",
                ],
                "integration_points": [
                    "Sales",
                    "Purchase",
                    "Inventory",
                    "Expenses",
                    "Point of Sale",
                    "Manufacturing",
                    "Projects",
                    "Subscriptions",
                ],
                "best_practices": [
                    "Design the chart of accounts around statutory and management reporting requirements.",
                    "Configure fiscal positions and tax rules before transaction migration.",
                    "Define payment terms and reconciliation rules early.",
                    "Use analytic accounts and analytic dimensions consistently.",
                    "Restrict accounting access according to segregation-of-duties requirements.",
                    "Establish period closing and journal controls before production use.",
                ],
            },
            "sales": {
                "name": "Sales",
                "description": (
                    "Manages the sales lifecycle from quotations and sales "
                    "orders through delivery, invoicing, and customer payment."
                ),
                "sub_modules": [
                    "Quotations",
                    "Sales Orders",
                    "Pricelists",
                    "Products",
                    "Customer Management",
                    "Invoicing",
                    "Sales Teams",
                    "Sales Analysis",
                ],
                "common_transactions": [
                    "Quotation",
                    "Sales Order",
                    "Delivery Order",
                    "Customer Invoice",
                    "Credit Note",
                    "Customer Payment",
                ],
                "integration_points": [
                    "CRM",
                    "Inventory",
                    "Accounting",
                    "Purchase",
                    "Subscriptions",
                    "Project",
                ],
                "best_practices": [
                    "Define quotation and sales order approval rules.",
                    "Standardize products, pricing, taxes, and units of measure.",
                    "Align delivery and invoicing policies with the commercial process.",
                    "Control discounts and pricing overrides through roles and approval rules.",
                    "Test the complete sales-to-cash flow with accounting entries.",
                ],
            },
            "purchase": {
                "name": "Purchase",
                "description": (
                    "Supports procurement from requests and purchase orders "
                    "through receipts, vendor bills, and supplier payments."
                ),
                "sub_modules": [
                    "Purchase Requests",
                    "Requests for Quotation",
                    "Purchase Orders",
                    "Vendor Management",
                    "Receipts",
                    "Vendor Bills",
                    "Purchase Agreements",
                ],
                "common_transactions": [
                    "Request for Quotation",
                    "Purchase Order",
                    "Receipt",
                    "Vendor Bill",
                    "Vendor Credit",
                    "Vendor Payment",
                ],
                "integration_points": [
                    "Accounting",
                    "Inventory",
                    "Expenses",
                    "Manufacturing",
                    "Approvals",
                ],
                "best_practices": [
                    "Define procurement approval thresholds.",
                    "Maintain consistent supplier and product master data.",
                    "Configure receipt and billing controls before go-live.",
                    "Use three-way matching where required by the business process.",
                    "Separate supplier creation from payment authorization.",
                ],
            },
            "inventory": {
                "name": "Inventory",
                "description": (
                    "Manages products, warehouses, stock movements, replenishment, "
                    "inventory valuation, transfers, and traceability."
                ),
                "sub_modules": [
                    "Warehouses",
                    "Locations",
                    "Stock Moves",
                    "Inventory Adjustments",
                    "Reordering Rules",
                    "Routes",
                    "Lots and Serial Numbers",
                    "Inventory Valuation",
                    "Barcode",
                ],
                "common_transactions": [
                    "Receipt",
                    "Delivery Order",
                    "Internal Transfer",
                    "Inventory Adjustment",
                    "Scrap",
                    "Return",
                    "Inventory Count",
                ],
                "integration_points": [
                    "Sales",
                    "Purchase",
                    "Manufacturing",
                    "Accounting",
                    "Point of Sale",
                ],
                "best_practices": [
                    "Design warehouse and location structures around physical operations.",
                    "Define routes and replenishment rules before activating automation.",
                    "Configure inventory valuation according to financial requirements.",
                    "Use lot and serial tracking where traceability requires it.",
                    "Reconcile inventory quantities and valuation with accounting records.",
                ],
            },
            "crm": {
                "name": "CRM",
                "description": (
                    "Manages leads, opportunities, sales pipelines, customer "
                    "activities, forecasting, and commercial follow-up."
                ),
                "sub_modules": [
                    "Leads",
                    "Opportunities",
                    "Pipeline",
                    "Activities",
                    "Sales Teams",
                    "Forecasting",
                    "Lead Generation",
                ],
                "common_transactions": [
                    "Lead",
                    "Opportunity",
                    "Activity",
                    "Quotation",
                    "Customer",
                ],
                "integration_points": [
                    "Sales",
                    "Marketing",
                    "Contacts",
                    "Subscriptions",
                    "Accounting",
                ],
                "best_practices": [
                    "Define pipeline stages around measurable sales activities.",
                    "Standardize lead qualification rules.",
                    "Use activities and scheduled follow-ups consistently.",
                    "Keep customer and contact information governed across applications.",
                    "Align CRM stages with quotation and sales processes.",
                ],
            },
            "manufacturing": {
                "name": "Manufacturing",
                "description": (
                    "Supports production planning and execution through bills "
                    "of materials, manufacturing orders, work centers, and production tracking."
                ),
                "sub_modules": [
                    "Bills of Materials",
                    "Manufacturing Orders",
                    "Work Orders",
                    "Work Centers",
                    "Work Center Operations",
                    "Production Planning",
                    "Quality",
                    "Maintenance",
                ],
                "common_transactions": [
                    "Manufacturing Order",
                    "Work Order",
                    "Production",
                    "Component Consumption",
                    "Scrap",
                    "Finished Product Receipt",
                ],
                "integration_points": [
                    "Inventory",
                    "Purchase",
                    "Sales",
                    "Quality",
                    "Maintenance",
                    "Accounting",
                ],
                "best_practices": [
                    "Validate bills of materials before production transactions begin.",
                    "Define work centers and operations around actual production processes.",
                    "Test component consumption and finished-goods movements together.",
                    "Align manufacturing costing with accounting requirements.",
                    "Establish controls for changes to bills of materials and routings.",
                ],
            },
            "project": {
                "name": "Project",
                "description": (
                    "Manages projects, tasks, planning, timesheets, project "
                    "costs, customer billing, and project profitability."
                ),
                "sub_modules": [
                    "Projects",
                    "Tasks",
                    "Timesheets",
                    "Planning",
                    "Project Milestones",
                    "Project Profitability",
                    "Customer Billing",
                ],
                "common_transactions": [
                    "Project",
                    "Task",
                    "Timesheet",
                    "Project Expense",
                    "Project Invoice",
                ],
                "integration_points": [
                    "Sales",
                    "Accounting",
                    "Timesheets",
                    "Planning",
                    "Expenses",
                ],
                "best_practices": [
                    "Define project and task structures before migration.",
                    "Separate internal project costing from customer billing requirements.",
                    "Establish approval rules for timesheets and expenses.",
                    "Use consistent project analytic dimensions for profitability reporting.",
                ],
            },
            "expenses": {
                "name": "Expenses",
                "description": (
                    "Manages employee expenses, expense reports, approvals, "
                    "reimbursements, and accounting integration."
                ),
                "sub_modules": [
                    "Expense Reports",
                    "Expense Categories",
                    "Approvals",
                    "Reimbursements",
                    "Corporate Cards",
                ],
                "common_transactions": [
                    "Expense",
                    "Expense Report",
                    "Expense Approval",
                    "Employee Reimbursement",
                ],
                "integration_points": [
                    "Accounting",
                    "Employees",
                    "Projects",
                    "Analytic Accounting",
                ],
                "best_practices": [
                    "Define expense categories and accounting mappings.",
                    "Set approval rules according to organizational structure.",
                    "Require appropriate supporting documentation.",
                    "Reconcile employee reimbursements with accounting records.",
                ],
            },
            "human_resources": {
                "name": "Human Resources",
                "description": (
                    "Provides employee administration, recruitment, time off, "
                    "attendance, appraisals, and related HR processes."
                ),
                "sub_modules": [
                    "Employees",
                    "Recruitment",
                    "Time Off",
                    "Attendances",
                    "Appraisals",
                    "Payroll",
                    "Expenses",
                ],
                "common_transactions": [
                    "Employee Record",
                    "Job Application",
                    "Time Off Request",
                    "Attendance",
                    "Appraisal",
                    "Expense Report",
                ],
                "integration_points": [
                    "Payroll",
                    "Expenses",
                    "Projects",
                    "Timesheets",
                    "Accounting",
                ],
                "best_practices": [
                    "Restrict employee data access based on HR responsibilities.",
                    "Define approval hierarchies for leave and employee processes.",
                    "Keep employee master data consistent across HR applications.",
                    "Separate HR administration from payroll and financial access where appropriate.",
                ],
            },
            "website_ecommerce": {
                "name": "Website and eCommerce",
                "description": (
                    "Provides website, online storefront, product catalog, "
                    "shopping cart, online payments, and customer ordering capabilities."
                ),
                "sub_modules": [
                    "Website",
                    "eCommerce",
                    "Product Catalog",
                    "Online Payments",
                    "Shopping Cart",
                    "Online Customer Portal",
                ],
                "common_transactions": [
                    "Online Quotation",
                    "eCommerce Order",
                    "Online Payment",
                    "Delivery Order",
                    "Customer Invoice",
                ],
                "integration_points": [
                    "Sales",
                    "Inventory",
                    "Accounting",
                    "CRM",
                    "Marketing",
                ],
                "best_practices": [
                    "Keep website product data aligned with the product master.",
                    "Define payment and fulfillment flows before launch.",
                    "Test tax, pricing, stock, and accounting behavior for online orders.",
                    "Control customer portal access carefully.",
                ],
            },
        }

        self.business_processes = {
            "order_to_cash": {
                "name": "Order-to-Cash",
                "description": (
                    "End-to-end process from lead or quotation through sales, "
                    "delivery, invoicing, receivables, and payment."
                ),
                "steps": [
                    "Lead or customer creation",
                    "Quotation",
                    "Sales order",
                    "Order confirmation",
                    "Inventory reservation",
                    "Delivery",
                    "Customer invoice",
                    "Customer payment",
                    "Bank reconciliation",
                ],
                "modules": [
                    "CRM",
                    "Sales",
                    "Inventory",
                    "Accounting",
                ],
            },
            "procure_to_pay": {
                "name": "Procure-to-Pay",
                "description": (
                    "End-to-end procurement process from supplier selection "
                    "through purchase, receipt, vendor billing, and payment."
                ),
                "steps": [
                    "Supplier selection",
                    "Request for quotation",
                    "Purchase order",
                    "Purchase approval",
                    "Receipt",
                    "Vendor bill",
                    "Bill validation",
                    "Vendor payment",
                    "Bank reconciliation",
                ],
                "modules": [
                    "Purchase",
                    "Inventory",
                    "Accounting",
                ],
            },
            "record_to_report": {
                "name": "Record-to-Report",
                "description": (
                    "Financial process covering transaction recording, "
                    "reconciliation, period close, and financial reporting."
                ),
                "steps": [
                    "Transaction processing",
                    "Subledger reconciliation",
                    "Journal processing",
                    "Account reconciliation",
                    "Period close",
                    "Tax reporting",
                    "Financial reporting",
                ],
                "modules": [
                    "Accounting",
                    "Analytic Accounting",
                    "Financial Reporting",
                ],
            },
            "plan_to_produce": {
                "name": "Plan-to-Produce",
                "description": (
                    "Manufacturing process covering production planning, "
                    "material availability, manufacturing, and inventory updates."
                ),
                "steps": [
                    "Demand identification",
                    "Production planning",
                    "Material availability check",
                    "Manufacturing order",
                    "Component consumption",
                    "Production",
                    "Quality checks",
                    "Finished goods receipt",
                    "Inventory valuation",
                ],
                "modules": [
                    "Manufacturing",
                    "Inventory",
                    "Purchase",
                    "Quality",
                    "Accounting",
                ],
            },
        }

        self.integrations = {
            "odoo_api": {
                "name": "Odoo API",
                "description": (
                    "Programmatic integration mechanisms for interacting "
                    "with Odoo records and business processes."
                ),
                "use_cases": [
                    "External application integration",
                    "Master data synchronization",
                    "Transaction synchronization",
                    "Data extraction",
                    "Automation",
                ],
            },
            "odoo_modules": {
                "name": "Odoo Module Integration",
                "description": (
                    "Native integration between Odoo applications through "
                    "shared business models and workflows."
                ),
                "use_cases": [
                    "Cross-module transaction flow",
                    "Shared master data",
                    "Accounting automation",
                    "Inventory synchronization",
                    "Sales and purchase integration",
                ],
            },
            "import_export": {
                "name": "Import and Export",
                "description": (
                    "Structured data import and export facilities used for "
                    "migration, bulk updates, and operational data exchange."
                ),
                "use_cases": [
                    "Initial data migration",
                    "Master data loads",
                    "Bulk updates",
                    "Data extraction",
                    "System transition",
                ],
            },
        }

        self.testing_strategies = {
            "unit_testing": {
                "description": (
                    "Testing individual custom modules, business logic, "
                    "automations, and configuration components."
                ),
                "focus": "Custom logic, validations, workflows, access rules",
                "coverage": "Critical customizations and business rules",
            },
            "integration_testing": {
                "description": (
                    "Testing data and process flows between Odoo applications "
                    "and external systems."
                ),
                "focus": "APIs, synchronization, integrations, error handling",
                "coverage": "All critical interfaces",
            },
            "end_to_end_testing": {
                "description": (
                    "Testing complete business processes across multiple "
                    "Odoo applications."
                ),
                "focus": "Order-to-cash, procure-to-pay, record-to-report",
                "coverage": "Critical cross-functional processes",
            },
            "uat_testing": {
                "description": (
                    "Business-user validation of configured processes against "
                    "approved requirements."
                ),
                "focus": "Business scenarios, reports, roles, usability",
                "coverage": "Approved business processes and acceptance criteria",
            },
            "regression_testing": {
                "description": (
                    "Verifying existing functionality after configuration, "
                    "module, or customization changes."
                ),
                "focus": "Existing business processes and integrations",
                "coverage": "Critical processes affected by changes",
            },
        }

    def get_module_info(
        self,
        module_code: str,
    ) -> Optional[Dict[str, Any]]:
        """Return information about an Odoo module."""

        key = module_code.lower().strip()

        aliases = {
            "accounting": "accounting",
            "finance": "accounting",
            "financials": "accounting",
            "financial management": "accounting",
            "ar": "accounting",
            "ap": "accounting",
            "sales": "sales",
            "order management": "sales",
            "o2c": "sales",
            "purchase": "purchase",
            "procurement": "purchase",
            "p2p": "purchase",
            "inventory": "inventory",
            "warehouse": "inventory",
            "crm": "crm",
            "manufacturing": "manufacturing",
            "mfg": "manufacturing",
            "project": "project",
            "projects": "project",
            "expenses": "expenses",
            "hr": "human_resources",
            "human resources": "human_resources",
            "ecommerce": "website_ecommerce",
            "e-commerce": "website_ecommerce",
            "website": "website_ecommerce",
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
        """Return common transactions for an Odoo module."""

        module = self.get_module_info(module_code)

        if not module:
            return []

        return module.get("common_transactions", [])

    def get_best_practices(
        self,
        module_code: str,
    ) -> List[str]:
        """Return implementation best practices for an Odoo module."""

        module = self.get_module_info(module_code)

        if not module:
            return []

        return module.get("best_practices", [])

    def get_integration_points(
        self,
        module_code: str,
    ) -> List[str]:
        """Return standard integration points for an Odoo module."""

        module = self.get_module_info(module_code)

        if not module:
            return []

        return module.get("integration_points", [])

    def get_process_flow(
        self,
        process_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Return a standard Odoo business process."""

        key = process_name.lower().strip()

        aliases = {
            "o2c": "order_to_cash",
            "order to cash": "order_to_cash",
            "p2p": "procure_to_pay",
            "procure to pay": "procure_to_pay",
            "r2r": "record_to_report",
            "record to report": "record_to_report",
            "p2p production": "plan_to_produce",
            "plan to produce": "plan_to_produce",
            "manufacturing": "plan_to_produce",
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
        """Search Odoo-specific knowledge."""

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


ODOO = OdooKnowledgeBase()