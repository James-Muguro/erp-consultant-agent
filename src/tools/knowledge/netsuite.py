"""
NetSuite ERP Knowledge Base.

Provides structured domain knowledge for NetSuite modules, business
processes, integrations, transactions, and implementation practices.

Shape note
----------
This file uses the class-based shape (subclassing ERPKnowledgeBase and
declaring knowledge as instance attributes) rather than the
ERPSystem-instance or dict shapes used by the other ERP files. The
loader reads it through the third branch of _convert_to_erp_system,
which extracts:

    ERP_NAME    -> ERPSystem.name
    self.modules -> ERPSystem.modules (dict of module dicts)
    ALIASES     -> ERPSystem.aliases       (new in this revision)
    METADATA    -> ERPSystem.metadata      (new in this revision)
    VENDOR      -> ERPSystem.vendor        (new in this revision)

Everything not in self.modules must live under METADATA to reach the
KB. The class's own method overrides (get_module_info, get_process_flow,
etc.) are kept for backward compatibility with any direct caller, but
they are NOT reached through the loader path — the loader builds a fresh
ERPSystem from the class's attributes. New code should use the shared
erp_kb facade:

    from src.tools import erp_kb
    erp_kb.get_module_info("FINANCIAL_MANAGEMENT", "NetSuite")

Loader dependency
-----------------
ALIASES, METADATA, and VENDOR are read by
src/tools/knowledge/__init__.py::_convert_class_source. If your copy of
that file predates this revision, only ERP_NAME and self.modules are
honoured — everything else is silently dropped. Verify before relying
on the alias list or on the metadata blocks being present.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.tools.knowledge.base import ERPKnowledgeBase


class NetSuiteKnowledgeBase(ERPKnowledgeBase):
    """Knowledge base for NetSuite ERP.

    Instantiated as a module-level singleton (`NETSUITE`) and read by the
    loader as data. The inherited ERPKnowledgeBase methods exist on the
    instance because the class subclasses it, but they are not used by
    the loader and no code in the reviewed codebase calls them."""

    ERP_NAME = "NetSuite"
    ERP_KEY = "netsuite"
    VENDOR = "Oracle"

    # Aliases the loader registers alongside ERP_NAME so get_erp(...)
    # resolves the product names users actually type. "Oracle NetSuite"
    # is the current corporate name; "OneWorld" is the multi-subsidiary
    # variant; "NS" is internal shorthand.
    ALIASES: List[str] = [
        "NetSuite",
        "Oracle NetSuite",
        "NetSuite ERP",
        "NetSuite OneWorld",
        "Oracle NetSuite ERP",
        "NS",
    ]

    def __init__(self):
        super().__init__()

        self.modules: Dict[str, Dict[str, Any]] = {
            "financial_management": {
                "name": "Financial Management",
                "description": (
                    "Core financial management capabilities covering general "
                    "ledger, accounts payable, accounts receivable, billing, "
                    "cash management, budgeting, and financial reporting. "
                    "Supports multi-subsidiary and multi-book accounting."
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
                    "Advanced Intercompany",
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
                    "Period Close",
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
                    "Design the chart of accounts around reporting requirements, and "
                    "define the role of subsidiaries before migration — subsidiaries "
                    "are structural, not cosmetic, in NetSuite.",
                    "Use OneWorld's multi-subsidiary features deliberately; the "
                    "same accounting decision has different implications on single-"
                    "subsidiary and multi-subsidiary deployments.",
                    "Define Multi-Book Accounting requirements early — enabling it "
                    "after go-live affects existing transaction history.",
                    "Configure accounting periods and period-close controls, and use "
                    "the Period Close Checklist as the canonical close workflow.",
                    "Set up intercompany preferences and intercompany accounts before "
                    "any cross-subsidiary transaction occurs; retrofitting is "
                    "high-risk.",
                    "Prefer standard approval workflows over SuiteScript approval "
                    "logic where the standard workflow supports the requirement — "
                    "SuiteScript-based approvals are upgrade-sensitive.",
                    "Validate segregation of duties at the role level; NetSuite's "
                    "permission model is granular and per-role over-grants are the "
                    "most common SoD finding.",
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
                    "Define the order-to-cash process before configuring transaction "
                    "workflows; order workflows are the highest-churn area of the "
                    "system.",
                    "Use consistent approval rules for sales orders and credit "
                    "limits — mismatched thresholds between the two produce "
                    "inconsistent behavior on high-value orders.",
                    "Define fulfillment rules based on inventory and business "
                    "requirements; the standard Item Fulfillment record supports "
                    "partial and back-order scenarios without customization.",
                    "Align billing triggers with the contractual revenue process; "
                    "NetSuite's Revenue Management reads the billing arrangement, "
                    "not the sales order.",
                    "Control customer and item master data centrally; NetSuite's "
                    "shared master across CRM and finance makes an ungoverned "
                    "master a cross-functional problem.",
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
                    "Use approval workflows based on amount, department, and "
                    "subsidiary — NetSuite's approval routing supports all three, "
                    "but the combination needs explicit design.",
                    "Standardize purchasing categories and item classifications; "
                    "uncontrolled item categories are the leading cause of "
                    "unreliable procurement reporting.",
                    "Define receiving controls before enabling three-way matching; "
                    "NetSuite's matching behavior depends on the receipt-to-bill "
                    "link being consistently populated.",
                    "Separate vendor creation from vendor payment authorization; "
                    "this is the standard audit control and is easy to under-specify "
                    "in NetSuite's role-based permission model.",
                    "Maintain clear approval and audit trails for procurement "
                    "transactions; enable the system notes and use custom fields "
                    "sparingly to preserve upgrade compatibility.",
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
                    "Advanced Inventory Management",
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
                    "Design item and location structures before transaction migration; "
                    "restructuring items after transactions are posted affects "
                    "historical costing.",
                    "Define inventory costing requirements (FIFO, LIFO, Average, "
                    "Standard) before configuration — the choice affects every "
                    "subsequent inventory valuation.",
                    "Use lot and serial-number tracking only where the business "
                    "genuinely requires it; the extra control surface has a "
                    "performance and support cost.",
                    "Separate inventory adjustment access from normal transaction "
                    "processing; inventory adjustments are the classic shrinkage "
                    "vector.",
                    "Establish inventory reconciliation procedures between operational "
                    "and financial records; use the standard Inventory Valuation "
                    "report as the reconciliation anchor.",
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
                    "Define customer lifecycle stages clearly; NetSuite's shared "
                    "customer record between CRM and finance means stage discipline "
                    "matters for both sales and accounting.",
                    "Keep customer master data governed across sales and finance; "
                    "there is one customer record, not two.",
                    "Standardize opportunity stages and required fields; the "
                    "forecasting accuracy depends on the sales team actually "
                    "advancing stages.",
                    "Align sales processes with downstream order and billing "
                    "processes; NetSuite's tight CRM-to-order integration makes "
                    "the alignment low-cost when done early and expensive later.",
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
                    "Project Budgeting",
                ],
                "common_transactions": [
                    "Project",
                    "Project Task",
                    "Time Entry",
                    "Expense Report",
                    "Project Charge",
                    "Project Invoice",
                    "Project Budget Revision",
                ],
                "integration_points": [
                    "Financial Management",
                    "Time Management",
                    "Resource Management",
                    "Billing",
                    "Revenue Management",
                ],
                "best_practices": [
                    "Define project structures before loading project data; project "
                    "hierarchies are structural in NetSuite, not configuration, and "
                    "restructuring mid-project is disruptive.",
                    "Separate project costing from customer billing requirements — "
                    "they use different dimensions and conflating them creates "
                    "reporting compromises.",
                    "Standardize project and task classifications; the classification "
                    "drives the reporting hierarchy.",
                    "Establish approval controls for time and project expenses; the "
                    "standard approval workflow supports both with the same "
                    "configuration surface.",
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
                    "Advanced Manufacturing",
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
                    "Validate bills of materials before production transactions "
                    "begin; BOM errors surface as costing variance that's harder "
                    "to trace back than to prevent.",
                    "Define work-center and routing structures around actual "
                    "production processes; align with the business's real production "
                    "model (discrete vs. assembly) before committing.",
                    "Align manufacturing costing with financial reporting "
                    "requirements — NetSuite uses standard cost with variance, and "
                    "the variance account structure needs deliberate design.",
                    "Test inventory and accounting impacts together; a manufacturing "
                    "issue in NetSuite typically affects both.",
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
                    "Define asset classes and depreciation rules before migration; "
                    "the depreciation method affects every historical period.",
                    "Reconcile the fixed asset register with the general ledger; "
                    "unreconciled fixed asset subledgers are a common audit finding.",
                    "Control asset disposal and transfer permissions — these are "
                    "high-risk transactions from a controls perspective.",
                    "Document capitalization rules for each asset category; the "
                    "threshold and category conventions matter more than the "
                    "specific system configuration.",
                ],
            },
            "revenue_management": {
                "name": "Revenue Management",
                "description": (
                    "Supports revenue recognition and revenue allocation for "
                    "contracts and transactions subject to revenue recognition "
                    "requirements (ASC 606 / IFRS 15)."
                ),
                "sub_modules": [
                    "Revenue Arrangements",
                    "Revenue Elements",
                    "Revenue Recognition",
                    "Fair Value Allocation",
                    "Revenue Forecasting",
                    "Advanced Revenue Management (ARM)",
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
                    "Document revenue recognition requirements before configuration; "
                    "the accounting policy precedes the system design here, not "
                    "the other way around.",
                    "Map source transactions to revenue arrangements explicitly; "
                    "the mapping is the primary configuration surface and needs "
                    "to be reviewed with finance, not just with IT.",
                    "Test allocation and recognition scenarios across contract "
                    "variations; ASC 606 / IFRS 15 edge cases are where the "
                    "implementation most often surprises the business.",
                    "Reconcile recognized revenue to billing and general ledger "
                    "balances; the ARM subledger and the GL should always agree.",
                ],
            },
            # ------------------------------------------------------------------
            # SuiteBilling (Subscription / Recurring Revenue)
            # ------------------------------------------------------------------
            "suite_billing": {
                "name": "SuiteBilling (Subscription Management)",
                "description": (
                    "Manages subscription and recurring revenue: subscription "
                    "plans, billing schedules, usage-based billing, and "
                    "revenue integration. Frequently in scope for SaaS and "
                    "subscription businesses running on NetSuite."
                ),
                "sub_modules": [
                    "Subscription Plans",
                    "Billing Schedules",
                    "Usage-Based Billing",
                    "Rate Cards",
                    "Renewal Management",
                    "Revenue Integration",
                ],
                "common_transactions": [
                    "Subscription",
                    "Subscription Plan",
                    "Billing Schedule",
                    "Usage Record",
                    "Renewal",
                    "Subscription Change Order",
                ],
                "integration_points": [
                    "Order Management",
                    "Revenue Management",
                    "Financial Management",
                    "CRM",
                ],
                "best_practices": [
                    "Define the billing schedule model before configuring "
                    "subscription plans; the schedule is what determines revenue "
                    "timing.",
                    "Align SuiteBilling with ARM (Advanced Revenue Management); "
                    "the two must be configured together, not sequentially.",
                    "Test mid-term changes (upgrades, downgrades, cancellations) "
                    "against revenue treatment; these scenarios are where "
                    "misconfiguration most often surfaces.",
                    "Validate usage-based rating against a real usage history "
                    "before go-live — synthetic samples miss edge cases.",
                ],
            },
            # ------------------------------------------------------------------
            # Warehouse Management
            # ------------------------------------------------------------------
            "warehouse_management": {
                "name": "Warehouse Management (NetSuite WMS)",
                "description": (
                    "Manages warehouse operations at the bin level: putaway, "
                    "picking, packing, and inventory counts. Distinct from the "
                    "core Inventory Management module."
                ),
                "sub_modules": [
                    "Bin Management",
                    "Putaway",
                    "Wave Picking",
                    "Cartonization",
                    "Barcode Scanning",
                    "Cycle Counting",
                ],
                "common_transactions": [
                    "Putaway",
                    "Wave",
                    "Pick Task",
                    "Pack Task",
                    "Cycle Count",
                    "Bin Transfer",
                ],
                "integration_points": [
                    "Inventory",
                    "Order Management",
                    "Procurement",
                    "Manufacturing",
                ],
                "best_practices": [
                    "Design bin and zone structure before enabling WMS; bin "
                    "restructuring after operations begin is disruptive.",
                    "Define putaway and picking strategies explicitly — NetSuite's "
                    "defaults rarely match the operation.",
                    "Integrate WMS scanning with receiving and shipping workflows; "
                    "the value of WMS is realized at the scan points.",
                    "Reconcile WMS cycle counts with core inventory on a defined "
                    "cadence; discrepancies are almost always configuration, "
                    "not data entry.",
                ],
            },
            # ------------------------------------------------------------------
            # Expense Reporting
            # ------------------------------------------------------------------
            "expense_reporting": {
                "name": "Expense Reporting",
                "description": (
                    "Manages employee expense entry, approval, and reimbursement, "
                    "with policy enforcement and accounting integration."
                ),
                "sub_modules": [
                    "Expense Reports",
                    "Expense Categories",
                    "Expense Policies",
                    "Approval Workflows",
                    "Corporate Card Integration",
                    "Reimbursement Processing",
                ],
                "common_transactions": [
                    "Expense Report",
                    "Expense Report Approval",
                    "Expense Reimbursement",
                    "Corporate Card Charge",
                    "Expense Adjustment",
                ],
                "integration_points": [
                    "Accounts Payable",
                    "General Ledger",
                    "Human Resources",
                    "Payroll",
                    "Corporate Card Providers",
                ],
                "best_practices": [
                    "Define expense policy rules before enabling enforcement; the "
                    "policy drives the workflow design, not the other way around.",
                    "Use corporate card integration where the business has card "
                    "spend — the automated matching reduces the highest-frequency "
                    "manual touchpoint.",
                    "Separate expense approval from reimbursement processing; these "
                    "are different control points.",
                    "Reconcile expense reimbursements to the general ledger; the "
                    "expense accrual and payment should always match.",
                ],
            },
            # ------------------------------------------------------------------
            # SuitePeople (HR)
            # ------------------------------------------------------------------
            "suite_people": {
                "name": "SuitePeople (Human Capital Management)",
                "description": (
                    "NetSuite's HR module: employee records, organizational "
                    "structure, payroll (in supported countries), and workforce "
                    "management. Frequently deployed alongside Financials in "
                    "single-vendor deployments."
                ),
                "sub_modules": [
                    "Employee Records",
                    "Organizational Structure",
                    "Payroll (supported countries)",
                    "Time Tracking",
                    "Workforce Analytics",
                    "Employee Self-Service",
                ],
                "common_transactions": [
                    "Employee Record",
                    "Employee Change",
                    "Payroll Run",
                    "Time Entry",
                    "Time Approval",
                ],
                "integration_points": [
                    "Financial Management",
                    "Payroll",
                    "Projects",
                    "Time Management",
                ],
                "best_practices": [
                    "Confirm payroll localization coverage before committing to "
                    "SuitePeople payroll; NetSuite's payroll covers a subset of "
                    "countries.",
                    "Apply strict access controls to employee information; HR "
                    "data is among the most sensitive in the system.",
                    "Align the HR organizational structure with the financial "
                    "dimensions used for reporting; they should not diverge.",
                    "Define effective-dated organizational changes so historical "
                    "reporting reflects the org as it was at the time.",
                ],
            },
            "analytics_reporting": {
                "name": "Analytics and Reporting",
                "description": (
                    "Provides saved searches, reports, dashboards, KPIs, "
                    "SuiteAnalytics, and SuiteAnalytics Workbook capabilities "
                    "for operational and financial reporting."
                ),
                "sub_modules": [
                    "Saved Searches",
                    "Reports",
                    "Dashboards",
                    "KPIs",
                    "SuiteAnalytics Connect",
                    "SuiteAnalytics Workbook",
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
                    "Define reporting requirements before creating custom searches; "
                    "NetSuite's saved search library grows rapidly and unmanaged "
                    "growth is a maintenance burden.",
                    "Use standardized reporting dimensions across subsidiaries "
                    "and departments; NetSuite's flexibility here is a feature "
                    "only when governed.",
                    "Control access to financial and operational reporting; report "
                    "access in NetSuite is permission-driven and easy to over-grant.",
                    "Prefer SuiteAnalytics Workbook over custom SuiteScript "
                    "dashboards — Workbook is the supported and upgrade-safe path.",
                    "Reconcile operational reports to their source transactions "
                    "and financial reports to the general ledger.",
                ],
            },
        }

        # ------------------------------------------------------------------
        # METADATA — everything below this line reaches the KB only if the
        # loader's _convert_class_source reads a METADATA attribute. It
        # does, as of the loader revision that introduced ALIASES/VENDOR
        # support. On an older loader, this content is silently dropped.
        # ------------------------------------------------------------------
        self.METADATA: Dict[str, Any] = {
            "category": "ERP",
            "description": (
                "NetSuite is a cloud ERP platform delivered as a single, "
                "multi-tenant application covering financials, order "
                "management, procurement, inventory, CRM, projects, "
                "manufacturing, and HR. OneWorld is the multi-subsidiary "
                "version. SuiteCloud is the extension platform."
            ),
            "business_processes": {
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
            },
            "integrations": {
                "suite_script": {
                    "name": "SuiteScript",
                    "description": (
                        "NetSuite's JavaScript-based platform for extending "
                        "business logic, workflows, records, and integrations. "
                        "SuiteScript 2.x is the current version; 1.x is "
                        "deprecated."
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
                        "NetSuite integration framework supporting SOAP and "
                        "REST-based web services. REST is the strategic path; "
                        "SOAP remains supported."
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
                        "Bulk data import mechanism for loading supported "
                        "records into NetSuite."
                    ),
                    "use_cases": [
                        "Initial data migration",
                        "Master data loads",
                        "Transaction imports",
                        "Bulk updates",
                    ],
                },
                "rest_web_services": {
                    "name": "REST Web Services",
                    "description": (
                        "NetSuite's REST API for record CRUD, queries (SuiteQL "
                        "and REST Query), and integrations. Preferred for new "
                        "integrations over SOAP where the target endpoints exist."
                    ),
                    "use_cases": [
                        "Record CRUD",
                        "SuiteQL queries",
                        "OAuth 2.0 authenticated integration",
                        "Real-time sync",
                    ],
                },
            },
            "testing_strategies": {
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
            },
        }

    # ------------------------------------------------------------------
    # Legacy accessors (kept for direct callers)
    # ------------------------------------------------------------------
    # The canonical read path is the shared erp_kb facade. These methods
    # exist so any external consumer that imported NETSUITE directly and
    # called e.g. NETSUITE.get_module_info("FI") continues to work.
    #
    # NOTE: they are NOT called through the loader path — the loader
    # reads ERP_NAME, self.modules, ALIASES, METADATA, and VENDOR as
    # data, and constructs a fresh ERPSystem. See the module docstring.

    _MODULE_ALIASES: Dict[str, str] = {
        "fi": "financial_management",
        "finance": "financial_management",
        "financials": "financial_management",
        "financial management": "financial_management",
        "financial": "financial_management",
        "ar": "financial_management",
        "ap": "financial_management",
        "gl": "financial_management",
        "procurement": "procurement",
        "p2p": "procurement",
        "purchasing": "procurement",
        "order management": "order_management",
        "o2c": "order_management",
        "sales order": "order_management",
        "inventory management": "inventory",
        "inventory": "inventory",
        "wms": "warehouse_management",
        "warehouse": "warehouse_management",
        "warehouse management": "warehouse_management",
        "crm": "crm",
        "projects": "projects",
        "project management": "projects",
        "manufacturing": "manufacturing",
        "fixed assets": "fixed_assets",
        "assets": "fixed_assets",
        "revenue": "revenue_management",
        "revenue management": "revenue_management",
        "arm": "revenue_management",
        "billing": "suite_billing",
        "subscription": "suite_billing",
        "suitebilling": "suite_billing",
        "expense": "expense_reporting",
        "expenses": "expense_reporting",
        "hr": "suite_people",
        "people": "suite_people",
        "suitepeople": "suite_people",
        "analytics": "analytics_reporting",
        "reporting": "analytics_reporting",
    }

    def get_module_info(
        self,
        module_code: str,
        erp_name: Optional[str] = None,  # accepted for signature compat; unused
    ) -> Optional[Dict[str, Any]]:
        """Legacy accessor. Prefer erp_kb.get_module_info(...).

        Signature matches the parent so a caller following the parent's
        contract doesn't hit a TypeError. `erp_name` is accepted but
        ignored — this instance only knows about NetSuite."""
        if not module_code:
            return None
        key = str(module_code).strip().lower()
        key = self._MODULE_ALIASES.get(key, key)
        module = self.modules.get(key)
        if not module:
            return None
        return {
            "erp": self.ERP_NAME,
            "module_code": key,
            **module,
        }

    def get_transactions_by_module(
        self, module_code: str, erp_name: Optional[str] = None,
    ) -> List[str]:
        """Legacy accessor. Prefer erp_kb.get_transactions_by_module(...)."""
        module = self.get_module_info(module_code)
        return list(module.get("common_transactions", [])) if module else []

    def get_best_practices(
        self, module_code: str, erp_name: Optional[str] = None,
    ) -> List[str]:
        """Legacy accessor. Prefer erp_kb.get_best_practices(...)."""
        module = self.get_module_info(module_code)
        return list(module.get("best_practices", [])) if module else []

    def get_integration_points(
        self, module_code: str, erp_name: Optional[str] = None,
    ) -> List[str]:
        """Legacy accessor. Prefer erp_kb.get_integration_points(...)."""
        module = self.get_module_info(module_code)
        return list(module.get("integration_points", [])) if module else []

    def get_process_flow(
        self, process_name: str, erp_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Legacy accessor. Prefer erp_kb's metadata lookup for
        business_processes under this ERP."""
        if not process_name:
            return None
        key = str(process_name).strip().lower()
        aliases = {
            "o2c": "order_to_cash",
            "order to cash": "order_to_cash",
            "p2p": "procure_to_pay",
            "procure to pay": "procure_to_pay",
            "r2r": "record_to_report",
            "record to report": "record_to_report",
        }
        key = aliases.get(key, key.replace(" ", "_"))
        process = (self.METADATA.get("business_processes") or {}).get(key)
        if not process:
            return None
        return {
            "erp": self.ERP_NAME,
            "process_code": key,
            **process,
        }

    def search_knowledge(
        self, query: str, limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Legacy accessor. Prefer erp_kb.search_knowledge(...).

        Tokenized search across module fields plus the metadata blocks
        (business_processes, integrations). Results ordered by number of
        matched tokens, descending."""
        tokens = [t for t in (query or "").lower().split() if t]
        if not tokens:
            return []

        def _score(value: Any) -> int:
            if not isinstance(value, str):
                return 0
            low = value.lower()
            return sum(1 for t in tokens if t in low)

        def _score_any(values) -> int:
            return sum(_score(v) for v in (values or []))

        scored: List[tuple] = []

        for code, module in self.modules.items():
            score = (
                _score(code) + _score(module.get("name", ""))
                + _score(module.get("description", ""))
                + _score_any(module.get("sub_modules"))
                + _score_any(module.get("common_transactions"))
                + _score_any(module.get("integration_points"))
                + _score_any(module.get("best_practices"))
            )
            if score > 0:
                scored.append((score, {
                    "type": "module", "erp": self.ERP_NAME,
                    "code": code, "name": module.get("name", ""),
                    "description": module.get("description", ""),
                }))

        for code, process in (self.METADATA.get("business_processes") or {}).items():
            score = (
                _score(process.get("name", ""))
                + _score(process.get("description", ""))
                + _score_any(process.get("steps"))
                + _score_any(process.get("modules"))
            )
            if score > 0:
                scored.append((score, {
                    "type": "process", "erp": self.ERP_NAME,
                    "code": code, "name": process.get("name", ""),
                    "description": process.get("description", ""),
                }))

        for code, integration in (self.METADATA.get("integrations") or {}).items():
            score = (
                _score(integration.get("name", ""))
                + _score(integration.get("description", ""))
                + _score_any(integration.get("use_cases"))
            )
            if score > 0:
                scored.append((score, {
                    "type": "integration", "erp": self.ERP_NAME,
                    "code": code, "name": integration.get("name", ""),
                    "description": integration.get("description", ""),
                }))

        scored.sort(key=lambda pair: -pair[0])
        results = [entry for _, entry in scored]
        if limit is not None and limit > 0:
            results = results[:limit]
        return results


NETSUITE = NetSuiteKnowledgeBase()