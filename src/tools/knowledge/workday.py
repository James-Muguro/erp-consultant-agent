"""
Workday ERP Knowledge Base

Domain knowledge for Workday, covering Human Capital Management,
Financial Management, business processes, integrations, reporting,
and implementation best practices.

Workday-specific design context
-------------------------------
Three properties of Workday materially change how an implementation
should be designed, and the best-practice guidance below reflects them:

  * SaaS-only. There is no on-premise option. This removes the
    "customize the platform" escape hatch that SAP/Oracle/D365
    deployments rely on, and makes the choice between configuration,
    calculated fields, and Extend/Studio the entire customization
    surface.

  * Mandatory bi-annual releases. Workday ships R1 (spring) and R2
    (autumn) and every tenant must adopt them. Regression testing is a
    recurring commitment, not a one-time activity. Designs that assume
    stability between releases do not survive contact with the
    release calendar.

  * Tenant topology. Workday environments include Implementation,
    Sandbox, Sandbox Preview (which receives the next release ahead of
    Production), and Production. Planning for the Sandbox Preview
    cycle is standard practice for every customer.

Payroll localization
--------------------
Workday Payroll (in-house) is available in a subset of countries —
currently the US, UK, Canada, and France. In every other country, the
standard pattern is Workday HCM with an integration to a third-party
payroll provider. The payroll module entry below notes this; a
multi-country design that assumes Workday Payroll globally is
misunderstanding the product.

Access path
-----------
The canonical read path is the shared erp_kb facade:
    from src.tools import erp_kb
    erp_kb.get_module_info("HCM", "Workday")

The module-level helper functions below are legacy accessors kept for
direct callers. They return a different shape than the KB's own
_module_to_dict and use tokenized-but-local search. New code should
use the KB.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import ERPModule


WORKDAY: Dict[str, Any] = {
    "name": "Workday",
    "vendor": "Workday",
    "category": "ERP",
    "aliases": [
        # Vendor / brand
        "Workday",
        "Workday Cloud",
        # Product-suite names users type
        "Workday HCM",
        "Workday Human Capital Management",
        "Workday Financials",
        "Workday Financial Management",
        "Workday Payroll",
        "Workday Adaptive Planning",
        "Workday Planning",
        "Workday Prism Analytics",
        "Workday Prism",
        "Workday Extend",
        "Workday Strategic Sourcing",
        "Workday Student",
        "Workday Peakon",
        "Peakon",
        # Occasionally users type the acquired brand
        "Adaptive Insights",
        "Adaptive",
    ],
    "description": (
        "Cloud enterprise platform focused on human capital management, "
        "financial management, workforce operations, planning, analytics, "
        "and reporting. SaaS-only with mandatory bi-annual releases "
        "(R1, R2)."
    ),
    "modules": {
        "hcm": ERPModule(
            name="Human Capital Management (HCM)",
            description=(
                "Manages worker information, organizational structures, staffing, "
                "compensation, benefits, talent, and core HR processes. Workday's "
                "HCM suite is the historical core of the platform; most "
                "implementations start here before extending into Financials."
            ),
            sub_modules=[
                "Core HCM",
                "Organization Management",
                "Staffing",
                "Compensation",
                "Benefits",
                "Talent Management",
                "Recruiting",
                "Learning",
                "Absence Management",
                "Time Tracking",
                "Skills Cloud",
                "Journeys",
                "Succession Planning",
            ],
            common_transactions=[
                "Hire Worker",
                "Change Job",
                "Change Organization",
                "Transfer Worker",
                "Terminate Worker",
                "Compensation Change",
                "Request Leave",
                "Enter Time",
                "Create Job Requisition",
                "Complete Performance Review",
                "Assign Learning",
                "Maintain Worker Record",
            ],
            integration_points=[
                "Payroll",
                "Financial Management",
                "Time Tracking",
                "Benefits (Providers)",
                "Recruiting",
                "Learning",
                "Identity Management",
                "External HR systems",
                "Prism Analytics",
            ],
            best_practices=[
                "Establish clear ownership of worker and organizational master "
                "data; Workday's supervisory organizations are structural — "
                "restructuring after transactions accumulate is disruptive.",
                "Design supervisory and organizational structures before "
                "configuring business processes; the process framework reads "
                "the org structure directly.",
                "Use effective-dated changes for worker and organization records; "
                "Workday's effective-dating model is what makes historical "
                "reporting work, and bypassing it loses history.",
                "Prefer calculated fields over custom reports for derived values; "
                "calculated fields are the primary extension mechanism and are "
                "upgrade-safe.",
                "Review every custom field and business process against the "
                "current release notes before R1/R2; unused configuration "
                "is technical debt that accumulates over releases.",
                "Apply role-based security according to job responsibilities; "
                "Workday's domain security policies are granular and over-"
                "granting is the most common SoD finding.",
            ],
        ),
        "financial_management": ERPModule(
            name="Financial Management",
            description=(
                "Supports accounting, general ledger, accounts payable, accounts "
                "receivable, cash management, assets, revenue, expenses, and "
                "financial reporting. Delivered on the same SaaS platform as HCM."
            ),
            sub_modules=[
                "General Ledger",
                "Accounts Payable",
                "Accounts Receivable",
                "Cash Management",
                "Customer Accounts",
                "Supplier Accounts",
                "Fixed Assets",
                "Revenue Management",
                "Expenses",
                "Accounting Center",
                "Financial Accounting",
                "Banking and Settlement",
            ],
            common_transactions=[
                "Create Accounting Journal",
                "Post Supplier Invoice",
                "Post Customer Invoice",
                "Record Customer Receipt",
                "Process Supplier Payment",
                "Submit Expense Report",
                "Bank Reconciliation",
                "Add Asset",
                "Run Depreciation",
                "Close Accounting Period",
                "Run Financial Reports",
            ],
            integration_points=[
                "Procurement",
                "Expenses",
                "HCM",
                "Payroll",
                "Projects",
                "Revenue Management",
                "Banking",
                "External financial systems",
                "Adaptive Planning",
                "Prism Analytics",
            ],
            best_practices=[
                "Design the accounting structure around reporting and operational "
                "requirements; Workday's accounting worktags (cost center, "
                "program, project, region, etc.) are structural — retrofitting "
                "them after transactions post is a re-implementation.",
                "Define business process approvals before transaction "
                "configuration; the approval structure drives the underlying "
                "workflow design, not the other way around.",
                "Use accounting dimensions (worktags) consistently across the "
                "organization; ungoverned worktag usage produces reports that "
                "don't reconcile.",
                "Configure the close calendar and period controls early; "
                "Workday's period-close process has dependencies across "
                "modules that surface later.",
                "Confirm in-house Payroll availability before committing to "
                "Workday Payroll for any country — see the payroll module "
                "for the current country coverage.",
            ],
        ),
        "procurement": ERPModule(
            name="Procurement",
            description=(
                "Supports requisitioning, purchasing, receiving, invoicing, "
                "and procure-to-pay processes. Separate from Strategic "
                "Sourcing, which handles RFPs and contract negotiation."
            ),
            sub_modules=[
                "Requisitions",
                "Purchase Orders",
                "Supplier Management",
                "Supplier Accounts",
                "Receiving",
                "Supplier Invoicing",
                "Procure-to-Pay",
                "Purchase Order Approvals",
            ],
            common_transactions=[
                "Create Requisition",
                "Approve Requisition",
                "Create Purchase Order",
                "Approve Purchase Order",
                "Receive Goods",
                "Receive Services",
                "Register Supplier Invoice",
                "Match Invoice to Receipt",
                "Approve Invoice",
                "Process Supplier Payment",
            ],
            integration_points=[
                "Accounts Payable",
                "General Ledger",
                "Inventory",
                "Supplier Accounts",
                "Expenses",
                "Projects",
                "Strategic Sourcing",
                "Prism Analytics",
            ],
            best_practices=[
                "Define procurement approval thresholds against the accounting "
                "structure; Workday's approval routing reads worktags, so the "
                "approval design and the accounting design are linked.",
                "Maintain supplier master-data governance; Workday's shared "
                "supplier record between procurement and finance means an "
                "ungoverned master is a cross-module problem.",
                "Use three-way matching where appropriate; Workday's matching "
                "reads the receipt-to-invoice link, so consistent receiving "
                "is a prerequisite, not an option.",
                "Separate requisition, approval, receiving, and payment "
                "responsibilities; the domain security model supports this "
                "cleanly but doesn't enforce it by default.",
                "Monitor invoice exceptions rather than bypassing matching "
                "controls; exception queues in Workday are the intended "
                "handling path.",
            ],
        ),
        "payroll": ERPModule(
            name="Payroll",
            description=(
                "Supports payroll processing, worker compensation, deductions, "
                "tax-related processing, and payroll accounting. IMPORTANT: "
                "Workday Payroll (in-house) is available in a subset of "
                "countries — currently the US, UK, Canada, and France. In "
                "every other country, the standard pattern is Workday HCM "
                "with an integration to a third-party payroll provider "
                "(CloudPay, ADP, local providers)."
            ),
            sub_modules=[
                "Payroll Processing",
                "Payroll Inputs",
                "Payroll Calculations",
                "Deductions",
                "Tax Processing",
                "Payroll Accounting",
                "Payroll Costing",
                "Third-Party Payroll Integration",
            ],
            common_transactions=[
                "Enter Payroll Input",
                "Calculate Payroll",
                "Correct Payroll",
                "Approve Payroll",
                "Settle Payroll",
                "Post Payroll Accounting",
                "Reconcile Payroll",
            ],
            integration_points=[
                "Core HCM",
                "Compensation",
                "Benefits",
                "Time Tracking",
                "Absence Management",
                "Financial Management",
                "External banking systems",
                "Third-party payroll providers",
            ],
            best_practices=[
                "Confirm in-house payroll availability for every country in "
                "scope before committing to a Workday Payroll design; "
                "multi-country deployments are typically hybrid (in-house "
                "where available, third-party integration elsewhere).",
                "Validate worker, compensation, time, and deduction inputs "
                "before payroll calculation — payroll errors are high-cost "
                "and have a short correction window.",
                "Reconcile payroll results to financial postings and to the "
                "bank file at each cycle.",
                "Maintain strict access controls around payroll information; "
                "Workday's domain security supports fine-grained restriction "
                "and payroll data requires it.",
                "Test payroll changes through controlled parallel or "
                "regression cycles; there is no production-equivalent dry "
                "run for payroll.",
            ],
        ),
        "expenses": ERPModule(
            name="Expenses",
            description=(
                "Manages employee expense reporting, approvals, corporate card "
                "activity, reimbursements, and related accounting."
            ),
            sub_modules=[
                "Expense Reports",
                "Corporate Cards",
                "Expense Approvals",
                "Reimbursements",
                "Expense Accounting",
                "Expense Policies",
            ],
            common_transactions=[
                "Create Expense Report",
                "Submit Expense Report",
                "Approve Expense Report",
                "Record Corporate Card Transaction",
                "Process Reimbursement",
                "Post Expense Accounting",
            ],
            integration_points=[
                "Financial Management",
                "Accounts Payable",
                "HCM",
                "Corporate Card Providers",
                "Projects",
            ],
            best_practices=[
                "Define expense policies before configuring validation rules; "
                "the policy drives the workflow design, not the other way "
                "around.",
                "Automate approval routing based on organizational "
                "responsibility; Workday's business process framework "
                "supports this natively when the org structure is clean.",
                "Reconcile corporate card transactions regularly; unmatched "
                "corporate card activity is the highest-frequency expense "
                "exception.",
                "Separate expense approval from reimbursement processing; "
                "these are different control points and Workday's security "
                "model supports separating them.",
                "Monitor policy exceptions and recurring violations; Workday "
                "reports policy violations at approval time, and reviewing "
                "them is the mechanism that keeps the policy meaningful.",
            ],
        ),
        "projects": ERPModule(
            name="Project Management",
            description=(
                "Supports project planning, project costing, billing, revenue, "
                "resources, and project financial management. Common in "
                "professional services, higher education, and capital projects."
            ),
            sub_modules=[
                "Project Planning",
                "Project Costing",
                "Project Billing",
                "Project Revenue",
                "Project Resources",
                "Project Accounting",
                "Project Contracts",
            ],
            common_transactions=[
                "Create Project",
                "Create Project Task",
                "Enter Project Time",
                "Enter Project Cost",
                "Approve Project Time",
                "Generate Project Invoice",
                "Recognize Project Revenue",
                "Close Project",
            ],
            integration_points=[
                "Financial Management",
                "HCM",
                "Time Tracking",
                "Procurement",
                "Expenses",
                "Customer Accounts",
                "Adaptive Planning",
            ],
            best_practices=[
                "Define project structures before recording project activity; "
                "Workday's project hierarchy is structural, not configuration.",
                "Align project dimensions (worktags) with financial reporting "
                "requirements; the worktag structure is what makes project "
                "profitability reporting work.",
                "Establish billing and revenue rules early; Workday's revenue "
                "arrangements read the billing structure, so retrofitting is "
                "expensive.",
                "Reconcile project costs and billing to the general ledger as "
                "part of the close cycle.",
                "Confirm the Project Billing scope (T&M, fixed fee, milestone) "
                "against the standard Workday capability before committing — "
                "some combinations need configuration beyond the defaults.",
            ],
        ),
        "planning": ERPModule(
            name="Workday Adaptive Planning",
            description=(
                "Supports financial planning, budgeting, forecasting, workforce "
                "planning, scenario analysis, and management reporting. "
                "Delivered as a distinct product (originally Adaptive Insights) "
                "with its own tenant and often its own integration boundary "
                "from the core Workday tenant."
            ),
            sub_modules=[
                "Financial Planning",
                "Budgeting",
                "Forecasting",
                "Workforce Planning",
                "Scenario Planning",
                "Management Reporting",
                "Strategic Planning",
                "Operational Planning",
            ],
            common_transactions=[
                "Create Budget",
                "Submit Budget",
                "Approve Budget",
                "Update Forecast",
                "Create Planning Scenario",
                "Load Actuals",
                "Publish Management Report",
            ],
            integration_points=[
                "Financial Management",
                "HCM",
                "Payroll",
                "External ERP Systems",
                "Data Warehouses",
                "Prism Analytics",
            ],
            best_practices=[
                "Confirm the integration approach between Adaptive Planning "
                "and Workday core early — they are separate tenants and the "
                "data flow is a design decision, not an afterthought.",
                "Define planning dimensions (accounts, levels, versions) "
                "consistently with the financial structures in Workday core; "
                "divergence produces reconciliation issues at every forecast "
                "cycle.",
                "Separate approved budgets from working forecasts; the "
                "version structure in Adaptive supports this cleanly but "
                "needs deliberate design.",
                "Automate source-data loads where possible; manual loads are "
                "the most common source of forecast-versus-actual variance "
                "that isn't a real variance.",
                "Control scenario versions and ownership; ungoverned scenarios "
                "multiply and become indistinguishable within a few cycles.",
            ],
        ),
        # ------------------------------------------------------------------
        # Strategic Sourcing (separate from Procurement)
        # ------------------------------------------------------------------
        "strategic_sourcing": ERPModule(
            name="Strategic Sourcing",
            description=(
                "Manages supplier sourcing events: RFPs, RFQs, competitive "
                "bids, contract negotiation, and supplier award decisions. "
                "Distinct from Procurement (which handles requisitions and "
                "purchase orders) — Strategic Sourcing is the upstream "
                "negotiation application."
            ),
            sub_modules=[
                "Sourcing Events",
                "RFx Management",
                "Supplier Bid Responses",
                "Bid Evaluation",
                "Supplier Award",
                "Contract Negotiation",
                "Supplier Scorecards",
            ],
            common_transactions=[
                "Create Sourcing Event",
                "Publish Sourcing Event",
                "Receive Supplier Bid",
                "Evaluate Bids",
                "Award Sourcing Event",
                "Create Contract",
            ],
            integration_points=[
                "Procurement",
                "Supplier Accounts",
                "Financial Management",
                "Contract Management",
            ],
            best_practices=[
                "Define the sourcing event types the business will use "
                "(RFP, RFQ, reverse auction) before configuring events; the "
                "event type drives the supplier response structure.",
                "Align supplier records between Strategic Sourcing and "
                "Procurement — the same supplier appears in both and the "
                "records must be reconciled.",
                "Define bid evaluation criteria and weights explicitly; "
                "Workday's evaluation framework reads the criteria at "
                "event creation, not at evaluation time.",
            ],
        ),
        # ------------------------------------------------------------------
        # Prism Analytics
        # ------------------------------------------------------------------
        "prism_analytics": ERPModule(
            name="Prism Analytics",
            description=(
                "Workday's internal data platform for combining Workday data "
                "with external data sources into governed datasets, and "
                "publishing them back into Workday for reporting and "
                "analysis."
            ),
            sub_modules=[
                "Data Catalog",
                "Datasets",
                "Data Sources (External)",
                "Data Pipelines",
                "Security and Governance",
                "Published Reports",
            ],
            common_transactions=[
                "Create Dataset",
                "Load Data",
                "Define Data Change Task",
                "Publish Dataset",
                "Create Prism Report",
            ],
            integration_points=[
                "HCM",
                "Financial Management",
                "Payroll",
                "External Data Sources",
                "Data Warehouses",
                "BI Platforms",
            ],
            best_practices=[
                "Define the source-of-truth boundary for every dataset; "
                "Prism is often used to blend Workday and non-Workday data, "
                "and unclear ownership produces stale or contradictory "
                "reports.",
                "Govern dataset access consistent with the sensitivity of "
                "the underlying data; Prism datasets inherit security from "
                "their sources only when the security model is configured.",
                "Confirm the deployment's license coverage for Prism before "
                "designing against it — it is not always included.",
            ],
        ),
        # ------------------------------------------------------------------
        # Extend (low-code extension platform)
        # ------------------------------------------------------------------
        "extend": ERPModule(
            name="Workday Extend",
            description=(
                "Workday's low-code extension platform for building custom "
                "applications that integrate with Workday data and business "
                "processes. Deployed as apps within the tenant, using "
                "Workday's supported extension framework rather than custom "
                "code."
            ),
            sub_modules=[
                "Custom Apps",
                "App Builder",
                "Orchestrations",
                "Model Components",
                "Presentation Components",
                "Custom Business Objects",
            ],
            common_transactions=[
                "Create App",
                "Add Page",
                "Add Orchestration",
                "Define Custom Object",
                "Deploy App",
                "Manage App Versions",
            ],
            integration_points=[
                "HCM",
                "Financial Management",
                "Prism Analytics",
                "External APIs",
            ],
            best_practices=[
                "Prefer Extend over Workday Studio or custom integrations "
                "where the requirement fits the low-code model — Extend "
                "apps are upgrade-safe and Studio integrations are not.",
                "Confirm the deployment's Extend license before designing "
                "against it; it is a distinct SKU from core Workday.",
                "Design for the release cadence — Extend apps are tested "
                "during the Sandbox Preview window and must pass regression "
                "each R1/R2.",
            ],
        ),
    },
    "concepts": {
        "business_process_framework": {
            "description": (
                "Workday uses configurable business processes to define how "
                "transactions move through initiation, validation, approval, "
                "and completion. The framework is the primary configuration "
                "surface for how work flows through the system."
            ),
            "best_practices": [
                "Map business processes before configuring approval steps.",
                "Keep approval rules aligned with organizational responsibility.",
                "Avoid unnecessary approval layers; each one adds latency and "
                "a place for the process to stall.",
                "Document exception paths alongside the normal workflow.",
                "Review business process changes against the release notes "
                "each R1/R2 — the framework evolves."
            ],
        },
        "security": {
            "description": (
                "Workday uses role-based security and domain security policies "
                "to determine what users and integrations are allowed to "
                "access. Domains are granular and security is configured at "
                "the domain level."
            ),
            "best_practices": [
                "Apply least-privilege access; Workday's domain model makes "
                "fine-grained restriction possible and the default is not "
                "conservative.",
                "Separate administrative and transactional responsibilities "
                "in role design.",
                "Review security changes through controlled governance — "
                "security configuration is often the source of audit findings.",
                "Test security using representative user roles, not "
                "administrator accounts.",
            ],
        },
        "organizations": {
            "description": (
                "Workday uses organizational structures such as supervisory "
                "organizations, companies, cost centers, and other "
                "organizational dimensions. These are structural: they drive "
                "approval routing, reporting, and process behavior."
            ),
            "best_practices": [
                "Design organizational structures before configuring "
                "dependent processes — the org structure is read by many "
                "other parts of the system.",
                "Define ownership for organizational master data.",
                "Use consistent naming and hierarchy conventions.",
                "Validate organizational changes against reporting "
                "requirements before committing.",
            ],
        },
        "integrations": {
            "description": (
                "Workday integrates with external systems through several "
                "mechanisms: Workday Studio (custom integrations), EIB "
                "(Enterprise Interface Builder for file-based loads), Core "
                "Connectors (packaged integrations for common use cases like "
                "payroll and benefits), Workday Web Services (SOAP/REST APIs), "
                "and RAAS (Reports as a Service, for exposing Workday "
                "reports as data sources)."
            ),
            "best_practices": [
                "Choose the simplest supported mechanism that fits the "
                "requirement — EIB or Core Connector before Studio, Studio "
                "before custom code.",
                "Document system ownership and integration direction.",
                "Define source-of-truth rules for shared data.",
                "Design integration error handling before deployment.",
                "Monitor scheduled and event-driven integrations; silent "
                "failures are the highest-cost integration problem.",
                "Protect credentials and sensitive worker information.",
            ],
        },
        "release_cadence": {
            "description": (
                "Workday ships two major releases per year — R1 (spring) "
                "and R2 (autumn) — and every tenant must adopt them. "
                "Sandbox Preview receives the next release ahead of "
                "Production, giving customers a test window before the "
                "release lands in production."
            ),
            "best_practices": [
                "Plan regression testing around the R1 and R2 calendar; "
                "testing is a recurring commitment, not a one-time activity.",
                "Use the Sandbox Preview window to test customizations, "
                "integrations, and business processes against the next "
                "release before it reaches Production.",
                "Review release notes for every impacted module before each "
                "release; Workday publishes them in advance and skipping "
                "them is the most common cause of post-release surprises.",
                "Prefer upgrade-safe extension mechanisms (calculated "
                "fields, Extend, packaged integrations) over custom code "
                "that must be re-validated each release.",
            ],
        },
    },
    "processes": {
        "hire_to_retire": [
            "Create job requisition",
            "Recruit candidate",
            "Hire worker",
            "Maintain worker record",
            "Manage compensation and benefits",
            "Track time and absence",
            "Process payroll",
            "Terminate worker",
        ],
        "procure_to_pay": [
            "Create requisition",
            "Approve requisition",
            "Create purchase order",
            "Approve purchase order",
            "Receive goods or services",
            "Process supplier invoice",
            "Match invoice",
            "Pay supplier",
        ],
        "record_to_report": [
            "Record operational transactions",
            "Process accounting",
            "Post journals",
            "Reconcile accounts",
            "Close accounting period",
            "Generate financial reports",
        ],
        "expense_to_reimbursement": [
            "Employee incurs expense",
            "Create expense report",
            "Submit expense report",
            "Manager or designated approver reviews",
            "Expense is validated",
            "Accounting is generated",
            "Employee is reimbursed",
        ],
        "plan_to_perform": [
            "Create planning assumptions",
            "Build budget",
            "Approve budget",
            "Collect actual results",
            "Update forecast",
            "Run scenario analysis",
            "Review performance",
        ],
        "source_to_contract": [
            "Identify sourcing need",
            "Create sourcing event",
            "Publish to suppliers",
            "Receive supplier bids",
            "Evaluate bids",
            "Award event",
            "Negotiate contract",
            "Publish contract",
        ],
    },
    "testing_strategies": {
        "unit_testing": {
            "description": "Validate individual configurations, rules, reports, and integration components.",
            "focus": "Business process rules, calculated fields, security, reports, and individual transactions.",
        },
        "integration_testing": {
            "description": "Validate data and process flow between Workday and external systems.",
            "focus": "APIs, integrations, payroll, banking, identity systems, and downstream financial systems.",
        },
        "uat_testing": {
            "description": "Validate business processes using representative real-world scenarios.",
            "focus": "Worker lifecycle, finance, procurement, payroll, reporting, approvals, and exceptions.",
        },
        "regression_testing": {
            "description": (
                "Confirm existing business processes remain functional after "
                "configuration or release changes. Workday's mandatory "
                "bi-annual releases (R1, R2) make regression testing a "
                "recurring requirement rather than a one-time activity."
            ),
            "focus": "Critical business processes, integrations, reports, and security roles.",
        },
        "security_testing": {
            "description": "Validate access against defined roles and organizational responsibilities.",
            "focus": "Domain access, role assignments, segregation of duties, and sensitive data visibility.",
        },
        "performance_testing": {
            "description": "Validate system and integration behavior under expected operational volumes.",
            "focus": "High-volume integrations, reporting, payroll processing, and scheduled workloads.",
        },
        "release_regression_testing": {
            "description": (
                "Testing against the next release in Sandbox Preview before "
                "it reaches Production. Workday-specific: every customer "
                "must run this twice a year."
            ),
            "focus": "Customizations, integrations, business process changes, reports, and Extend apps.",
        },
    },
}


# ---------------------------------------------------------------------------
# Legacy helper accessors
# ---------------------------------------------------------------------------
# The canonical read path is src.tools.erp_kb. These functions exist so
# any external consumer that imported them directly continues to work.
# They normalize module codes, return copies, and use tokenized search,
# but callers should prefer the KB path.

def _normalize_module_code_for_lookup(module_code: str) -> str:
    """Canonicalize a module code: lowercase, spaces and dashes to
    underscores. Matches what the KB's own normalizer produces, so a
    caller passing 'Human Capital Management', 'human-capital-management',
    or 'HCM' gets the same result through either path."""
    if not module_code:
        return ""
    return (
        str(module_code).strip().lower()
        .replace(" ", "_").replace("-", "_")
    )


def get_module_info(module_code: str) -> Optional[Dict[str, Any]]:
    """Legacy accessor: return information about a Workday module by
    code or display name. Prefer erp_kb.get_module_info(...)."""
    module = WORKDAY["modules"].get(_normalize_module_code_for_lookup(module_code))
    if not module:
        return None
    return {
        "name": module.name,
        "description": module.description,
        "sub_modules": list(module.sub_modules),
        "common_transactions": list(module.common_transactions),
        "integration_points": list(module.integration_points),
        "best_practices": list(module.best_practices),
    }


def get_transactions_by_module(module_code: str) -> List[str]:
    """Legacy accessor: return common transactions for a Workday module.
    Prefer erp_kb.get_transactions_by_module(...)."""
    module = WORKDAY["modules"].get(_normalize_module_code_for_lookup(module_code))
    return list(module.common_transactions) if module else []


def get_best_practices(module_code: str) -> List[str]:
    """Legacy accessor: return best practices for a Workday module.
    Prefer erp_kb.get_best_practices(...)."""
    module = WORKDAY["modules"].get(_normalize_module_code_for_lookup(module_code))
    return list(module.best_practices) if module else []


def get_integration_points(module_code: str) -> List[str]:
    """Legacy accessor: return integration points for a Workday module.
    Prefer erp_kb.get_integration_points(...)."""
    module = WORKDAY["modules"].get(_normalize_module_code_for_lookup(module_code))
    return list(module.integration_points) if module else []


def get_concept(concept_name: str) -> Optional[Dict[str, Any]]:
    """Legacy accessor: return a Workday concept block by name (e.g.
    'business_process_framework', 'release_cadence'). New helper — the
    original file had no accessor for the `concepts` block."""
    if not concept_name:
        return None
    key = str(concept_name).strip().lower().replace(" ", "_").replace("-", "_")
    concept = WORKDAY["concepts"].get(key)
    if not concept:
        return None
    return {**concept}


def get_process_flow(process_name: str) -> Optional[List[str]]:
    """Legacy accessor: return a standard Workday business process flow
    by name (e.g. 'hire_to_retire', 'Hire to Retire', 'hire-to-retire')."""
    if not process_name:
        return None
    key = (
        str(process_name).strip().lower()
        .replace("-", "_").replace(" ", "_")
    )
    flow = WORKDAY["processes"].get(key)
    return list(flow) if flow else None


def search_knowledge(query: str) -> List[Dict[str, Any]]:
    """Legacy accessor: search Workday-specific knowledge.

    Tokenized search across module fields, concepts, and process
    definitions — a value matches if it contains ANY token from the
    query, and results are ordered by number of tokens matched. Prefer
    erp_kb.search_knowledge(...), which additionally searches the ERP's
    metadata block."""
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

    for code, module in WORKDAY["modules"].items():
        score = (
            _score(code) + _score(module.name) + _score(module.description)
            + _score_any(module.sub_modules)
            + _score_any(module.common_transactions)
            + _score_any(module.integration_points)
            + _score_any(module.best_practices)
        )
        if score > 0:
            scored.append((score, {
                "type": "module",
                "erp": "Workday",
                "code": code,
                "name": module.name,
                "description": module.description,
            }))

    for concept_name, concept in WORKDAY["concepts"].items():
        score = (
            _score(concept_name)
            + _score(concept.get("description", ""))
            + _score_any(concept.get("best_practices"))
        )
        if score > 0:
            scored.append((score, {
                "type": "concept",
                "erp": "Workday",
                "name": concept_name,
                "description": concept.get("description", ""),
            }))

    for process_name, steps in WORKDAY["processes"].items():
        score = _score(process_name) + _score_any(steps)
        if score > 0:
            scored.append((score, {
                "type": "process",
                "erp": "Workday",
                "name": process_name,
                "steps": steps,
            }))

    scored.sort(key=lambda pair: -pair[0])
    return [entry for _, entry in scored]