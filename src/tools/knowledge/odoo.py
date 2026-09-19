"""
Odoo ERP Knowledge Base.

Provides structured domain knowledge for Odoo modules, business
processes, integrations, transactions, and implementation practices.

Shape note
----------
This file uses the class-based shape (subclassing ERPKnowledgeBase and
declaring knowledge as instance attributes). The loader reads it through
the third branch of _convert_to_erp_system, which extracts:

    ERP_NAME     -> ERPSystem.name
    self.modules -> ERPSystem.modules
    ALIASES      -> ERPSystem.aliases   (new in this revision)
    VENDOR       -> ERPSystem.vendor    (new in this revision)
    METADATA     -> ERPSystem.metadata  (new in this revision)

Everything not in self.modules must live under METADATA to reach the KB.
The class's own method overrides are kept for backward compatibility
with any direct caller, but they are NOT reached through the loader path.

Edition awareness
-----------------
Odoo ships in two editions that materially change what's possible:

  Community (free, open source) - core transactional modules. No Studio,
  no Advanced Accounting (bank sync, automated valuation, full financial
  reports), no Subscriptions, no Quality, no Maintenance, no Field
  Service, no Helpdesk, no Marketing Automation, no Approvals.

  Enterprise (per-user paid) - the full suite plus Studio, mobile apps,
  and full accounting/reporting capabilities.

No guidance in this file is edition-neutral by accident. Where a
capability is Enterprise-only, the module description notes it.
Consultants working in Community should verify each recommended feature
against Community's module list before assuming it's available.

Hosting model
-------------
The hosting choice constrains the customization surface:
  - Odoo Online (SaaS): Studio-only customization; no custom code modules.
  - Odoo.sh (PaaS, Odoo-run): full code modules; git-based deployment.
  - On-premise: everything, including OCA (community) modules and custom
    infrastructure, at the cost of running it yourself.

This matters for design decisions (a design that assumes Studio cannot
be built if you need a complex extension; a design that assumes a custom
module requires Odoo.sh or on-premise).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.tools.knowledge.base import ERPKnowledgeBase


class OdooKnowledgeBase(ERPKnowledgeBase):
    """Knowledge base for Odoo ERP."""

    ERP_NAME = "Odoo"
    ERP_KEY = "odoo"
    VENDOR = "Odoo S.A."

    ALIASES: List[str] = [
        "Odoo",
        "Odoo ERP",
        "Odoo Community",
        "Odoo Community Edition",
        "Odoo Enterprise",
        "Odoo Enterprise Edition",
        "Odoo.sh",
        "Odoo Online",
    ]

    def __init__(self):
        super().__init__()

        self.modules: Dict[str, Dict[str, Any]] = {
            "accounting": {
                "name": "Accounting",
                "description": (
                    "Financial management covering general ledger, accounts "
                    "payable, accounts receivable, payments, bank reconciliation, "
                    "tax, budgeting, and financial reporting. Full financial "
                    "reporting, bank synchronization, and automated inventory "
                    "valuation are Enterprise-only capabilities; Community "
                    "provides core transaction recording."
                ),
                "sub_modules": [
                    "General Ledger",
                    "Accounts Payable",
                    "Accounts Receivable",
                    "Customer Invoicing",
                    "Vendor Bills",
                    "Payments",
                    "Bank Reconciliation",
                    "Bank Synchronization (Enterprise)",
                    "Taxes",
                    "Budgets (Enterprise)",
                    "Analytic Accounting",
                    "Fixed Assets",
                    "Financial Reporting",
                    "Multi-Currency",
                    "Multi-Company Consolidation (Enterprise)",
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
                    "Reconciliation",
                    "Period Close",
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
                    "Confirm the edition early — full financial reporting, bank "
                    "synchronization, and automated inventory valuation are "
                    "Enterprise-only; a Community design has to work around "
                    "their absence.",
                    "Design the chart of accounts around statutory and management "
                    "reporting requirements; Odoo's chart-of-accounts templates "
                    "are country-specific and the choice is structural.",
                    "Configure fiscal positions and tax rules before transaction "
                    "migration — retroactive tax-rule changes are disruptive.",
                    "Install and verify the country localization pack before "
                    "configuration; Odoo's localization coverage varies by "
                    "country and some require community modules for completeness.",
                    "Use analytic accounts (Odoo's cost-center equivalent) "
                    "consistently; retrofitting analytic dimensions after "
                    "transactions are posted loses history.",
                    "Configure multi-company early if it's in scope — enabling "
                    "it later affects every existing record's visibility rules.",
                    "Establish period-lock and journal-approval controls before "
                    "production use; Odoo's defaults are permissive.",
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
                    "Subscription Sales (Enterprise)",
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
                    "Define quotation and sales order approval rules; Odoo's "
                    "approval feature is Enterprise-only — Community deployments "
                    "need custom rules or role-based limits.",
                    "Standardize products, pricing, taxes, and units of measure; "
                    "the sales/purchase/inventory shared product model makes "
                    "uncontrolled product data a cross-module problem.",
                    "Use pricelists for pricing logic rather than creating many "
                    "product variants — variants multiply inventory and accounting "
                    "complexity.",
                    "Test the complete sales-to-cash flow with accounting entries, "
                    "not just the operational flow.",
                ],
            },
            "purchase": {
                "name": "Purchase",
                "description": (
                    "Supports procurement from requests and purchase orders "
                    "through receipts, vendor bills, and supplier payments. "
                    "Odoo's purchase approval feature is Enterprise-only; "
                    "Community deployments need role-based controls."
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
                    "Approvals (Enterprise)",
                ],
                "best_practices": [
                    "Define procurement approval thresholds; use Odoo's "
                    "Approvals module (Enterprise) or role-based permissions "
                    "(Community) — mixed approaches create inconsistency.",
                    "Maintain consistent supplier and product master data; the "
                    "shared vendor record between purchase and accounting means "
                    "an ungoverned master is a two-module problem.",
                    "Configure receipt and billing controls before go-live; "
                    "Odoo's three-way match depends on the receipt-to-bill "
                    "link being populated consistently.",
                    "Separate supplier creation from payment authorization; "
                    "Odoo's permission model supports this but doesn't enforce "
                    "it by default.",
                ],
            },
            "inventory": {
                "name": "Inventory",
                "description": (
                    "Manages products, warehouses, stock movements, replenishment, "
                    "inventory valuation, transfers, and traceability. Automated "
                    "inventory valuation (FIFO/AVCO with real-time accounting "
                    "postings) is Enterprise-only; Community uses manual/periodic "
                    "valuation."
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
                    "Storage Categories (Enterprise)",
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
                    "Design warehouse and location structures around physical "
                    "operations — Odoo's location model supports multi-step "
                    "receipt and delivery, which is powerful but easy to "
                    "misconfigure.",
                    "Define routes and replenishment rules before activating "
                    "automation; the automation runs silently once enabled.",
                    "Configure inventory valuation according to financial "
                    "requirements; in Community the choices are more limited "
                    "than in Enterprise.",
                    "Use lot and serial tracking where traceability requires it; "
                    "enabling tracking changes how existing products must be "
                    "received and delivered.",
                    "Reconcile inventory quantities and valuation with accounting "
                    "records as part of the close cycle.",
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
                    "Forecasting (Enterprise)",
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
                    "Define pipeline stages around measurable sales activities; "
                    "Odoo's forecasting depends on stage discipline.",
                    "Standardize lead qualification rules; the sales team's "
                    "inconsistent qualification is the most common CRM data-"
                    "quality problem.",
                    "Align CRM stages with quotation and sales processes; Odoo's "
                    "tight CRM-to-Sales integration makes alignment cheap when "
                    "done early.",
                ],
            },
            "manufacturing": {
                "name": "Manufacturing",
                "description": (
                    "Supports production planning and execution through bills "
                    "of materials, manufacturing orders, work centers, and "
                    "production tracking. Odoo MRP (including work centers, "
                    "routings, and quality integration) is Enterprise-only; "
                    "Community provides a simpler manufacturing model."
                ),
                "sub_modules": [
                    "Bills of Materials",
                    "Manufacturing Orders",
                    "Work Orders (Enterprise)",
                    "Work Centers (Enterprise)",
                    "Work Center Operations (Enterprise)",
                    "Production Planning",
                    "Quality (Enterprise)",
                    "Maintenance (Enterprise)",
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
                    "Confirm the manufacturing model (MRP vs. simple assembly) "
                    "matches the deployment's capabilities — the simpler "
                    "Community model lacks the work-center and routing depth "
                    "of MRP.",
                    "Validate bills of materials before production transactions "
                    "begin; BOM errors surface as costing variance that's harder "
                    "to trace than to prevent.",
                    "Test component consumption and finished-goods movements "
                    "together; they post to different accounts and the "
                    "reconciliation is the check.",
                    "Establish controls for changes to bills of materials and "
                    "routings — engineering change discipline keeps the master "
                    "clean.",
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
                    "Planning (Enterprise)",
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
                    "Define project and task structures before migration; "
                    "restructuring mid-project loses history.",
                    "Separate internal project costing from customer billing "
                    "requirements; they use different dimensions and conflating "
                    "them creates reporting compromises.",
                    "Establish approval rules for timesheets and expenses — "
                    "Odoo's approvals are Enterprise-only.",
                    "Use consistent project analytic dimensions; the analytics "
                    "module reads these directly for profitability reporting.",
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
                    "Define expense categories and accounting mappings; the "
                    "mapping is what determines the GL account each expense "
                    "posts to.",
                    "Set approval rules according to organizational structure; "
                    "Odoo's default is single-level — multi-level requires "
                    "configuration.",
                    "Reconcile employee reimbursements with accounting records; "
                    "the accrual and payment should always match.",
                ],
            },
            "human_resources": {
                "name": "Human Resources",
                "description": (
                    "Provides employee administration, recruitment, time off, "
                    "attendances, appraisals, and related HR processes. "
                    "Payroll is country-localized and provided via a "
                    "country-specific Odoo payroll module."
                ),
                "sub_modules": [
                    "Employees",
                    "Recruitment",
                    "Time Off",
                    "Attendances",
                    "Appraisals (Enterprise)",
                    "Payroll (localized)",
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
                    "Restrict employee data access based on HR responsibilities; "
                    "Odoo's record rules support this but don't enforce it by "
                    "default.",
                    "Confirm the payroll localization for every country in scope "
                    "before committing — Odoo's payroll coverage is via "
                    "community modules in many countries.",
                    "Keep employee master data consistent across HR applications; "
                    "the shared employee record between HR, expenses, and "
                    "timesheets is one record.",
                ],
            },
            # ------------------------------------------------------------------
            # Point of Sale
            # ------------------------------------------------------------------
            "point_of_sale": {
                "name": "Point of Sale",
                "description": (
                    "Manages physical and mobile point-of-sale operations: "
                    "retail transactions, cash management, and integration "
                    "with inventory and accounting."
                ),
                "sub_modules": [
                    "Point of Sale Sessions",
                    "Point of Sale Orders",
                    "Payment Methods",
                    "Cash Registers",
                    "Restaurant Mode",
                    "Self-Service",
                ],
                "common_transactions": [
                    "Point of Sale Order",
                    "Point of Sale Session Open",
                    "Point of Sale Session Close",
                    "Cash Payment",
                    "Card Payment",
                    "Refund",
                ],
                "integration_points": [
                    "Inventory",
                    "Accounting",
                    "Sales",
                    "Loyalty",
                ],
                "best_practices": [
                    "Define the POS session close and cash-count procedure "
                    "before go-live; discrepancies at close are almost always "
                    "process, not system.",
                    "Reconcile POS payments with accounting and bank deposits "
                    "on a defined cadence.",
                    "Test offline behavior where the POS operates intermittently "
                    "connected.",
                ],
            },
            # ------------------------------------------------------------------
            # Subscriptions
            # ------------------------------------------------------------------
            "subscriptions": {
                "name": "Subscriptions",
                "description": (
                    "Manages recurring revenue: subscription products, recurring "
                    "invoicing, renewals, upsells, and revenue forecasting. "
                    "Enterprise-only."
                ),
                "sub_modules": [
                    "Subscription Products",
                    "Recurring Invoices",
                    "Subscription Plans",
                    "Renewals",
                    "Upsells and Cross-sells",
                    "Recurring Revenue Reporting",
                ],
                "common_transactions": [
                    "Subscription",
                    "Recurring Invoice",
                    "Subscription Renewal",
                    "Subscription Change",
                    "Subscription Close",
                ],
                "integration_points": [
                    "Sales",
                    "Accounting",
                    "CRM",
                    "Website",
                ],
                "best_practices": [
                    "Define the billing period and proration rules before "
                    "configuring subscription products; retroactive changes "
                    "affect every existing subscription.",
                    "Test mid-term changes (upgrades, downgrades, cancellations) "
                    "against revenue treatment — this is where misconfiguration "
                    "surfaces.",
                    "Reconcile recurring revenue to the deferred-revenue balance "
                    "at close.",
                ],
            },
            # ------------------------------------------------------------------
            # Helpdesk
            # ------------------------------------------------------------------
            "helpdesk": {
                "name": "Helpdesk",
                "description": (
                    "Manages customer support: tickets, SLAs, customer portal, "
                    "and knowledge base. Enterprise-only."
                ),
                "sub_modules": [
                    "Tickets",
                    "Service-Level Agreements",
                    "Customer Portal",
                    "Knowledge Base",
                    "Teams",
                    "SLA Policies",
                ],
                "common_transactions": [
                    "Ticket",
                    "Ticket Assignment",
                    "Ticket Escalation",
                    "Ticket Resolution",
                    "Knowledge Article",
                ],
                "integration_points": [
                    "CRM",
                    "Sales",
                    "Accounting",
                    "Website",
                    "Email",
                ],
                "best_practices": [
                    "Design the ticket-to-resolution flow before configuring "
                    "SLAs — SLAs depend on the process, not the other way around.",
                    "Define queue/team ownership clearly; unassigned tickets are "
                    "the most common source of SLA breaches.",
                    "Govern the knowledge base with ownership and review; "
                    "unmaintained articles are worse than none.",
                ],
            },
            # ------------------------------------------------------------------
            # Approvals
            # ------------------------------------------------------------------
            "approvals": {
                "name": "Approvals",
                "description": (
                    "Configurable approval workflows for documents and "
                    "transactions across modules. Enterprise-only. Community "
                    "deployments rely on per-module or role-based controls "
                    "instead."
                ),
                "sub_modules": [
                    "Approval Categories",
                    "Approval Requests",
                    "Multi-Level Approval",
                    "Approval Delegation",
                ],
                "common_transactions": [
                    "Approval Request",
                    "Approval Decision",
                    "Approval Delegation",
                ],
                "integration_points": [
                    "Purchase",
                    "Sales",
                    "Expenses",
                    "Human Resources",
                ],
                "best_practices": [
                    "Use the Approvals module for cross-module workflows; "
                    "per-module approval logic is limited and easier to "
                    "misconfigure.",
                    "Define approval hierarchies to match the org chart and "
                    "document the delegation rules.",
                ],
            },
            "website_ecommerce": {
                "name": "Website and eCommerce",
                "description": (
                    "Provides website, online storefront, product catalog, "
                    "shopping cart, online payments, and customer ordering "
                    "capabilities."
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
                    "Keep website product data aligned with the product master; "
                    "e-commerce's need for rich content often tempts a parallel "
                    "product catalog, which drifts.",
                    "Define payment and fulfillment flows before launch; the "
                    "sequence from order to delivery involves more configuration "
                    "than it appears.",
                    "Test tax, pricing, stock, and accounting behavior for online "
                    "orders — the e-commerce pricing context differs from the "
                    "back-office one.",
                ],
            },
        }

        # ------------------------------------------------------------------
        # METADATA — read by the loader via getattr(obj, "METADATA").
        # On a loader that predates ALIASES/METADATA/VENDOR support, this
        # content is silently dropped.
        # ------------------------------------------------------------------
        self.METADATA: Dict[str, Any] = {
            "category": "ERP",
            "description": (
                "Odoo is an open-source ERP suite delivered in two editions "
                "(Community, free, and Enterprise, per-user paid) and three "
                "hosting models (Odoo Online SaaS, Odoo.sh PaaS, on-premise). "
                "The edition and hosting choices materially constrain which "
                "modules and customization patterns are available; a design "
                "that doesn't account for them will not be buildable."
            ),
            "business_processes": {
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
                    "modules": ["CRM", "Sales", "Inventory", "Accounting"],
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
                    "modules": ["Purchase", "Inventory", "Accounting"],
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
                        "material availability, manufacturing, and inventory "
                        "updates."
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
                "hire_to_retire": {
                    "name": "Hire-to-Retire",
                    "description": (
                        "HR process from recruitment through onboarding, "
                        "employee administration, and offboarding."
                    ),
                    "steps": [
                        "Recruitment",
                        "Job application",
                        "Interview and selection",
                        "Offer",
                        "Onboarding",
                        "Employee administration",
                        "Time and attendance",
                        "Appraisal",
                        "Offboarding",
                    ],
                    "modules": ["Human Resources", "Payroll", "Expenses"],
                },
            },
            "integrations": {
                "json_rpc": {
                    "name": "JSON-RPC API",
                    "description": (
                        "Odoo's primary external integration interface. "
                        "Authenticated via API keys (Odoo 14+) or user "
                        "credentials. Used by most integrations and by the "
                        "Odoo mobile apps."
                    ),
                    "use_cases": [
                        "External application integration",
                        "Master data synchronization",
                        "Transaction synchronization",
                        "Data extraction",
                        "Automation",
                    ],
                },
                "xml_rpc": {
                    "name": "XML-RPC API",
                    "description": (
                        "Odoo's original external integration protocol. "
                        "Still supported and used by many third-party "
                        "integrations and OCA libraries; JSON-RPC is "
                        "preferred for new work."
                    ),
                    "use_cases": [
                        "Legacy integration support",
                        "Libraries that predate JSON-RPC",
                    ],
                },
                "odoo_modules": {
                    "name": "Odoo Module Integration",
                    "description": (
                        "Native integration between Odoo applications through "
                        "shared business models and workflows. The shared "
                        "product / partner / account model is what makes "
                        "cross-module flows work without explicit interfaces."
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
                        "migration, bulk updates, and operational data "
                        "exchange. XLSX and CSV are both supported."
                    ),
                    "use_cases": [
                        "Initial data migration",
                        "Master data loads",
                        "Bulk updates",
                        "Data extraction",
                        "System transition",
                    ],
                },
                "oca_modules": {
                    "name": "OCA (Odoo Community Association) Modules",
                    "description": (
                        "Community-maintained modules that extend Odoo beyond "
                        "the standard apps. Quality varies; some are used "
                        "extensively by the community. Not usable on Odoo "
                        "Online (SaaS) hosting."
                    ),
                    "use_cases": [
                        "Localization supplements",
                        "Vertical-specific functionality",
                        "Filling gaps in Community edition",
                        "Extending standard modules",
                    ],
                },
            },
            "testing_strategies": {
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
                        "Testing data and process flows between Odoo "
                        "applications and external systems."
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
                        "Business-user validation of configured processes "
                        "against approved requirements."
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
                "upgrade_testing": {
                    "description": (
                        "Verifying behavior after an Odoo major-version "
                        "upgrade. Odoo upgrades between major releases are "
                        "non-trivial; regression coverage of critical "
                        "processes is essential."
                    ),
                    "focus": "Custom modules, third-party apps, cross-module flows",
                    "coverage": "Full regression on critical business processes",
                },
            },
            "editions": {
                "community": {
                    "description": "Free, open-source Odoo with core transactional modules.",
                    "notable_limitations": [
                        "No Studio (visual customization tool)",
                        "No Advanced Accounting features (bank sync, automated valuation, full reports)",
                        "No Subscriptions, Quality, Maintenance, Field Service, Helpdesk, Marketing Automation, or Approvals",
                        "No mobile apps for some workflows",
                    ],
                },
                "enterprise": {
                    "description": "Paid per-user Odoo with the full module suite.",
                    "notable_additions": [
                        "Studio for low-code customization",
                        "Advanced Accounting and full financial reporting",
                        "Subscriptions, Quality, Maintenance, Field Service, Helpdesk",
                        "Marketing Automation and Approvals",
                        "Mobile apps",
                    ],
                },
            },
            "hosting_models": {
                "odoo_online": {
                    "description": "Odoo's SaaS offering.",
                    "customization_surface": "Studio only; no custom code modules, no shell access.",
                    "best_for": "Standard implementations with minimal customization.",
                },
                "odoo_sh": {
                    "description": "Odoo's PaaS offering, git-based deployment.",
                    "customization_surface": "Full custom code modules; staging, CI, and OCA modules supported.",
                    "best_for": "Implementations with custom modules or complex integrations.",
                },
                "on_premise": {
                    "description": "Self-hosted Odoo.",
                    "customization_surface": "Everything, including custom infrastructure and any OCA module.",
                    "best_for": "Organizations with on-premise requirements or full control needs.",
                },
            },
        }

    # ------------------------------------------------------------------
    # Legacy accessors (kept for direct callers)
    # ------------------------------------------------------------------
    # See module docstring — the canonical read path is the shared
    # erp_kb facade. These methods exist so direct callers continue to
    # work.

    _MODULE_ALIASES: Dict[str, str] = {
        "accounting": "accounting",
        "finance": "accounting",
        "financials": "accounting",
        "financial management": "accounting",
        "ar": "accounting",
        "ap": "accounting",
        "gl": "accounting",
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
        "pos": "point_of_sale",
        "point of sale": "point_of_sale",
        "point_of_sale": "point_of_sale",
        "subscriptions": "subscriptions",
        "recurring": "subscriptions",
        "helpdesk": "helpdesk",
        "support": "helpdesk",
        "approvals": "approvals",
        "approval": "approvals",
    }

    def get_module_info(
        self,
        module_code: str,
        erp_name: Optional[str] = None,  # accepted for signature compat
    ) -> Optional[Dict[str, Any]]:
        """Legacy accessor. Prefer erp_kb.get_module_info(...).

        Signature matches the parent so a caller following the parent's
        contract doesn't hit a TypeError. `erp_name` is accepted but
        ignored — this instance only knows about Odoo."""
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
        key = str(process_name).strip().lower().replace(" ", "_").replace("-", "_")
        aliases = {
            "o2c": "order_to_cash",
            "p2p": "procure_to_pay",
            "r2r": "record_to_report",
        }
        key = aliases.get(key, key)
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
        (business_processes, integrations). Ordered by number of tokens
        matched, descending."""
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


ODOO = OdooKnowledgeBase()