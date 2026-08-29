"""
Workday ERP Knowledge Base

Domain knowledge for Workday, covering Human Capital Management,
Financial Management, business processes, integrations, reporting,
and implementation best practices.
"""

from typing import Dict, List, Optional, Any

from .base import ERPModule


WORKDAY = {
    "name": "Workday",
    "vendor": "Workday",
    "description": (
        "Cloud enterprise platform focused on human capital management, "
        "financial management, workforce operations, planning, analytics, and reporting."
    ),
    "modules": {
        "hcm": ERPModule(
            name="Human Capital Management (HCM)",
            description=(
                "Manages worker information, organizational structures, staffing, "
                "compensation, benefits, talent, and core HR processes."
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
            ],
            common_transactions=[
                "Hire worker",
                "Change job",
                "Change organization",
                "Transfer worker",
                "Terminate worker",
                "Compensation change",
                "Leave request",
                "Time entry",
                "Job requisition",
                "Performance review",
            ],
            integration_points=[
                "Payroll",
                "Financial Management",
                "Time Tracking",
                "Benefits",
                "Recruiting",
                "Learning",
                "Identity Management",
                "External HR systems",
            ],
            best_practices=[
                "Establish clear ownership of worker and organizational master data.",
                "Design supervisory and organizational structures before configuring business processes.",
                "Use effective-dated changes for worker and organization records.",
                "Apply role-based security according to job responsibilities.",
                "Standardize business processes across organizations where requirements permit.",
            ],
        ),
        "financial_management": ERPModule(
            name="Financial Management",
            description=(
                "Supports accounting, general ledger, accounts payable, accounts receivable, "
                "cash management, assets, revenue, expenses, and financial reporting."
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
            ],
            common_transactions=[
                "Create accounting journal",
                "Supplier invoice",
                "Customer invoice",
                "Customer receipt",
                "Supplier payment",
                "Expense report",
                "Bank reconciliation",
                "Asset acquisition",
                "Asset depreciation",
                "Accounting period close",
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
            ],
            best_practices=[
                "Design the accounting structure around reporting and operational requirements.",
                "Define business process approvals before transaction configuration.",
                "Use accounting dimensions consistently across the organization.",
                "Reconcile subledger activity to the general ledger regularly.",
                "Standardize period-close activities and ownership.",
            ],
        ),
        "procurement": ERPModule(
            name="Procurement",
            description=(
                "Supports requisitioning, sourcing, purchasing, supplier management, "
                "receiving, invoicing, and procure-to-pay processes."
            ),
            sub_modules=[
                "Requisitions",
                "Purchase Orders",
                "Supplier Management",
                "Sourcing",
                "Receiving",
                "Supplier Invoicing",
                "Procure-to-Pay",
            ],
            common_transactions=[
                "Create requisition",
                "Approve requisition",
                "Create purchase order",
                "Approve purchase order",
                "Receive goods",
                "Receive services",
                "Supplier invoice",
                "Invoice matching",
                "Supplier payment",
            ],
            integration_points=[
                "Accounts Payable",
                "General Ledger",
                "Inventory",
                "Supplier Management",
                "Expenses",
                "Projects",
            ],
            best_practices=[
                "Define procurement approval thresholds clearly.",
                "Maintain supplier master-data governance.",
                "Use three-way matching where appropriate.",
                "Separate requisition, approval, receiving, and payment responsibilities.",
                "Monitor invoice exceptions rather than bypassing matching controls.",
            ],
        ),
        "payroll": ERPModule(
            name="Payroll",
            description=(
                "Supports payroll processing, worker compensation, deductions, "
                "tax-related processing, and payroll accounting."
            ),
            sub_modules=[
                "Payroll Processing",
                "Payroll Inputs",
                "Compensation",
                "Deductions",
                "Tax Processing",
                "Payroll Accounting",
            ],
            common_transactions=[
                "Payroll input",
                "Payroll calculation",
                "Payroll correction",
                "Payroll approval",
                "Payroll settlement",
                "Payroll accounting",
                "Payroll reconciliation",
            ],
            integration_points=[
                "Core HCM",
                "Compensation",
                "Benefits",
                "Time Tracking",
                "Absence Management",
                "Financial Management",
                "External banking systems",
            ],
            best_practices=[
                "Define payroll ownership and approval responsibilities.",
                "Validate worker, compensation, time, and deduction inputs before payroll calculation.",
                "Reconcile payroll results to financial postings.",
                "Maintain strict access controls around payroll information.",
                "Test payroll changes through controlled parallel or regression cycles.",
            ],
        ),
        "expenses": ERPModule(
            name="Expenses",
            description=(
                "Manages employee expense reporting, approvals, corporate card activity, "
                "reimbursements, and related accounting."
            ),
            sub_modules=[
                "Expense Reports",
                "Corporate Cards",
                "Expense Approvals",
                "Reimbursements",
                "Expense Accounting",
            ],
            common_transactions=[
                "Create expense report",
                "Submit expense report",
                "Approve expense report",
                "Corporate card transaction",
                "Expense reimbursement",
                "Expense accounting",
            ],
            integration_points=[
                "Financial Management",
                "Accounts Payable",
                "HCM",
                "Corporate Card Providers",
                "Projects",
            ],
            best_practices=[
                "Define expense policies before configuring validation rules.",
                "Automate approval routing based on organizational responsibility.",
                "Reconcile corporate card transactions regularly.",
                "Separate expense approval from reimbursement processing.",
                "Monitor policy exceptions and recurring violations.",
            ],
        ),
        "projects": ERPModule(
            name="Project Management",
            description=(
                "Supports project planning, project costing, billing, revenue, "
                "resources, and project financial management."
            ),
            sub_modules=[
                "Project Planning",
                "Project Costing",
                "Project Billing",
                "Project Revenue",
                "Project Resources",
                "Project Accounting",
            ],
            common_transactions=[
                "Create project",
                "Create project task",
                "Enter project time",
                "Enter project cost",
                "Approve project time",
                "Generate project invoice",
                "Recognize project revenue",
                "Close project",
            ],
            integration_points=[
                "Financial Management",
                "HCM",
                "Time Tracking",
                "Procurement",
                "Expenses",
                "Customer Accounts",
            ],
            best_practices=[
                "Define project structures before recording project activity.",
                "Align project dimensions with financial reporting requirements.",
                "Establish billing and revenue rules early.",
                "Reconcile project costs and billing to the general ledger.",
                "Define clear project closure criteria.",
            ],
        ),
        "planning": ERPModule(
            name="Workday Adaptive Planning",
            description=(
                "Supports financial planning, budgeting, forecasting, workforce planning, "
                "scenario analysis, and management reporting."
            ),
            sub_modules=[
                "Financial Planning",
                "Budgeting",
                "Forecasting",
                "Workforce Planning",
                "Scenario Planning",
                "Management Reporting",
            ],
            common_transactions=[
                "Create budget",
                "Submit budget",
                "Approve budget",
                "Update forecast",
                "Create planning scenario",
                "Workforce plan",
                "Management reporting",
            ],
            integration_points=[
                "Financial Management",
                "HCM",
                "Payroll",
                "External ERP Systems",
                "Data Warehouses",
            ],
            best_practices=[
                "Define planning dimensions consistently with financial structures.",
                "Separate approved budgets from working forecasts.",
                "Automate source-data loads where possible.",
                "Control scenario versions and ownership.",
                "Reconcile planning data with actual financial results.",
            ],
        ),
    },
    "concepts": {
        "business_process_framework": {
            "description": (
                "Workday uses configurable business processes to define how transactions "
                "move through initiation, validation, approval, and completion."
            ),
            "best_practices": [
                "Map business processes before configuring approval steps.",
                "Keep approval rules aligned with organizational responsibility.",
                "Avoid unnecessary approval layers.",
                "Document exception paths alongside the normal workflow.",
            ],
        },
        "security": {
            "description": (
                "Workday uses role-based security and domain-based access controls "
                "to determine what users and integrations are allowed to access."
            ),
            "best_practices": [
                "Apply least-privilege access.",
                "Separate administrative and transactional responsibilities.",
                "Review security changes through controlled governance.",
                "Test security using representative user roles.",
            ],
        },
        "organizations": {
            "description": (
                "Workday uses organizational structures such as supervisory organizations, "
                "companies, cost centers, and other organizational dimensions."
            ),
            "best_practices": [
                "Design organizational structures before configuring dependent processes.",
                "Define ownership for organizational master data.",
                "Use consistent naming and hierarchy conventions.",
                "Validate organizational changes against reporting requirements.",
            ],
        },
        "integrations": {
            "description": (
                "Workday integrates with external systems through supported integration "
                "frameworks, APIs, reports, and file-based interfaces."
            ),
            "best_practices": [
                "Document system ownership and integration direction.",
                "Define source-of-truth rules for shared data.",
                "Design integration error handling before deployment.",
                "Monitor scheduled and event-driven integrations.",
                "Protect credentials and sensitive employee information.",
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
            "description": "Confirm existing business processes remain functional after configuration or release changes.",
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
    },
}


def get_module_info(module_code: str) -> Optional[Dict[str, Any]]:
    """Return information about a Workday module."""
    module = WORKDAY["modules"].get(module_code.lower())

    if not module:
        return None

    return {
        "name": module.name,
        "description": module.description,
        "sub_modules": module.sub_modules,
        "common_transactions": module.common_transactions,
        "integration_points": module.integration_points,
        "best_practices": module.best_practices,
    }


def get_transactions_by_module(module_code: str) -> List[str]:
    """Return common transactions for a Workday module."""
    module = WORKDAY["modules"].get(module_code.lower())
    return module.common_transactions if module else []


def get_best_practices(module_code: str) -> List[str]:
    """Return best practices for a Workday module."""
    module = WORKDAY["modules"].get(module_code.lower())
    return module.best_practices if module else []


def get_integration_points(module_code: str) -> List[str]:
    """Return standard integration points for a Workday module."""
    module = WORKDAY["modules"].get(module_code.lower())
    return module.integration_points if module else []


def get_process_flow(process_name: str) -> Optional[List[str]]:
    """Return a standard Workday business process flow."""
    process_key = process_name.lower().replace("-", "_").replace(" ", "_")
    return WORKDAY["processes"].get(process_key)


def search_knowledge(query: str) -> List[Dict[str, Any]]:
    """Search Workday-specific knowledge."""
    query_lower = query.lower()
    results = []

    for code, module in WORKDAY["modules"].items():
        searchable = " ".join(
            [
                module.name,
                module.description,
                *module.sub_modules,
                *module.common_transactions,
                *module.integration_points,
                *module.best_practices,
            ]
        ).lower()

        if query_lower in searchable:
            results.append(
                {
                    "type": "module",
                    "erp": "Workday",
                    "code": code,
                    "name": module.name,
                    "description": module.description,
                }
            )

    for concept_name, concept in WORKDAY["concepts"].items():
        searchable = " ".join(
            [
                concept_name,
                concept["description"],
                *concept.get("best_practices", []),
            ]
        ).lower()

        if query_lower in searchable:
            results.append(
                {
                    "type": "concept",
                    "erp": "Workday",
                    "name": concept_name,
                    "description": concept["description"],
                }
            )

    for process_name, steps in WORKDAY["processes"].items():
        searchable = " ".join([process_name, *steps]).lower()

        if query_lower in searchable:
            results.append(
                {
                    "type": "process",
                    "erp": "Workday",
                    "name": process_name,
                    "steps": steps,
                }
            )

    return results