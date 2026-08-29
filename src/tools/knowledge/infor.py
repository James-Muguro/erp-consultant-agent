"""
Infor ERP Knowledge Base

Domain knowledge for Infor ERP platforms, modules, business processes,
integrations, transactions, and implementation best practices.
"""

from typing import Dict, List, Optional, Any

from .base import ERPModule


INFOR = {
    "name": "Infor",
    "vendor": "Infor",
    "description": (
        "Infor enterprise resource planning platforms supporting finance, "
        "supply chain, manufacturing, distribution, workforce, and industry-specific operations."
    ),
    "modules": {
        "finance": ERPModule(
            name="Financial Management",
            description=(
                "Supports general ledger, accounts payable, accounts receivable, "
                "cash management, fixed assets, budgeting, and financial reporting."
            ),
            sub_modules=[
                "General Ledger",
                "Accounts Payable",
                "Accounts Receivable",
                "Cash Management",
                "Fixed Assets",
                "Budgeting",
                "Financial Reporting",
            ],
            common_transactions=[
                "General ledger journal entry",
                "Supplier invoice",
                "Customer invoice",
                "Customer receipt",
                "Supplier payment",
                "Bank reconciliation",
                "Fixed asset acquisition",
                "Fixed asset depreciation",
                "Period close",
            ],
            integration_points=[
                "Procurement",
                "Accounts Payable",
                "Order Management",
                "Accounts Receivable",
                "Inventory",
                "Manufacturing",
                "Projects",
                "Banking",
            ],
            best_practices=[
                "Define a consistent chart of accounts and financial dimensions.",
                "Establish clear approval controls for journals and payments.",
                "Separate operational and financial responsibilities through role design.",
                "Standardize period-close procedures across entities.",
                "Use automated reconciliations where transaction volumes justify them.",
            ],
        ),
        "supply_chain": ERPModule(
            name="Supply Chain Management",
            description=(
                "Manages procurement, purchasing, inventory, warehouse operations, "
                "order fulfillment, and supply chain planning."
            ),
            sub_modules=[
                "Procurement",
                "Purchasing",
                "Inventory Management",
                "Warehouse Management",
                "Order Management",
                "Supply Planning",
                "Supplier Management",
            ],
            common_transactions=[
                "Purchase requisition",
                "Purchase order",
                "Goods receipt",
                "Supplier return",
                "Inventory transfer",
                "Inventory adjustment",
                "Sales order",
                "Shipment",
                "Customer return",
            ],
            integration_points=[
                "Financial Management",
                "Accounts Payable",
                "Accounts Receivable",
                "Manufacturing",
                "Demand Planning",
                "Warehouse Management",
                "Supplier Management",
            ],
            best_practices=[
                "Define item, supplier, and location master-data ownership.",
                "Use approval workflows appropriate to purchasing thresholds.",
                "Maintain accurate inventory units of measure and locations.",
                "Define receiving and three-way matching controls.",
                "Monitor inventory exceptions and fulfillment failures.",
            ],
        ),
        "manufacturing": ERPModule(
            name="Manufacturing",
            description=(
                "Supports production planning, bills of material, routings, "
                "work orders, scheduling, costing, and shop-floor operations."
            ),
            sub_modules=[
                "Production Planning",
                "Bill of Materials",
                "Routings",
                "Work Orders",
                "Material Requirements Planning",
                "Production Scheduling",
                "Manufacturing Costing",
            ],
            common_transactions=[
                "Create production order",
                "Release production order",
                "Material issue",
                "Production completion",
                "Production receipt",
                "Work order closure",
                "Material requirements planning run",
            ],
            integration_points=[
                "Inventory",
                "Procurement",
                "Warehouse Management",
                "Financial Management",
                "Quality Management",
                "Order Management",
            ],
            best_practices=[
                "Keep bills of material and routings governed by effective dates.",
                "Align production master data with inventory and costing structures.",
                "Validate material availability before releasing production.",
                "Track production variances and investigate recurring exceptions.",
                "Separate engineering changes from uncontrolled master-data edits.",
            ],
        ),
        "distribution": ERPModule(
            name="Distribution",
            description=(
                "Supports distribution operations including sales orders, purchasing, "
                "inventory, pricing, fulfillment, and customer service."
            ),
            sub_modules=[
                "Sales Order Management",
                "Purchasing",
                "Inventory",
                "Pricing",
                "Warehouse Operations",
                "Shipping",
                "Customer Service",
            ],
            common_transactions=[
                "Sales order entry",
                "Sales order allocation",
                "Pick release",
                "Shipment confirmation",
                "Customer invoice",
                "Purchase order",
                "Receipt",
                "Customer return",
            ],
            integration_points=[
                "Accounts Receivable",
                "Accounts Payable",
                "Inventory",
                "Warehouse Management",
                "Procurement",
                "Financial Management",
            ],
            best_practices=[
                "Define order-to-cash ownership across sales, warehouse, and finance.",
                "Standardize pricing and discount rules.",
                "Validate inventory availability before promising delivery.",
                "Automate invoice creation from confirmed fulfillment events.",
                "Monitor order exceptions from entry through shipment.",
            ],
        ),
        "projects": ERPModule(
            name="Project Management",
            description=(
                "Supports project planning, costing, billing, resource tracking, "
                "and project financial control."
            ),
            sub_modules=[
                "Project Planning",
                "Project Costing",
                "Project Billing",
                "Resource Management",
                "Project Accounting",
            ],
            common_transactions=[
                "Create project",
                "Project budget entry",
                "Project cost entry",
                "Time entry",
                "Project billing",
                "Project revenue recognition",
                "Project close",
            ],
            integration_points=[
                "Financial Management",
                "Procurement",
                "Accounts Payable",
                "Accounts Receivable",
                "Human Resources",
            ],
            best_practices=[
                "Define project structures before transactional activity begins.",
                "Separate project costs by meaningful cost categories.",
                "Establish clear billing and revenue-recognition rules.",
                "Reconcile project subledgers with the general ledger.",
                "Close completed projects promptly.",
            ],
        ),
        "human_resources": ERPModule(
            name="Human Capital Management",
            description=(
                "Supports workforce administration, employee data, payroll-related "
                "processes, talent, workforce management, and HR operations."
            ),
            sub_modules=[
                "Employee Administration",
                "Payroll",
                "Talent Management",
                "Workforce Management",
                "Benefits",
                "Recruitment",
            ],
            common_transactions=[
                "Employee creation",
                "Employee transfer",
                "Time entry",
                "Leave request",
                "Payroll processing",
                "Payroll adjustment",
                "Employee termination",
            ],
            integration_points=[
                "Financial Management",
                "Payroll",
                "Time Management",
                "Workforce Management",
                "Identity Management",
            ],
            best_practices=[
                "Apply strict access controls to employee information.",
                "Define authoritative sources for employee master data.",
                "Separate HR administration from payroll approval responsibilities.",
                "Reconcile payroll postings to the general ledger.",
                "Maintain effective-dated organizational structures.",
            ],
        ),
    },
    "concepts": {
        "multi_entity": {
            "description": (
                "Infor environments often support organizations operating across "
                "multiple legal entities, locations, currencies, and operating units."
            ),
            "best_practices": [
                "Define legal-entity ownership clearly.",
                "Standardize financial dimensions across entities where appropriate.",
                "Document intercompany transaction rules.",
                "Define currency and consolidation requirements early.",
            ],
        },
        "industry_specific_erp": {
            "description": (
                "Infor provides ERP platforms and capabilities tailored to industries "
                "such as manufacturing, distribution, healthcare, hospitality, and public sector."
            ),
            "best_practices": [
                "Separate industry-specific requirements from generic ERP requirements.",
                "Prefer standard industry functionality before introducing customization.",
                "Document regulatory and operational requirements explicitly.",
                "Validate industry workflows with business process owners.",
            ],
        },
        "cloud_erp": {
            "description": (
                "Infor CloudSuite provides cloud-based ERP capabilities with "
                "industry-oriented applications and integrations."
            ),
            "best_practices": [
                "Document integration dependencies before implementation.",
                "Keep extensions isolated from core application behavior.",
                "Define release and regression-testing procedures.",
                "Monitor integrations and scheduled processes after deployment.",
            ],
        },
    },
    "processes": {
        "procure_to_pay": [
            "Purchase requisition",
            "Purchase order",
            "Receipt",
            "Supplier invoice",
            "Invoice matching",
            "Payment",
            "General ledger posting",
        ],
        "order_to_cash": [
            "Customer order",
            "Order validation",
            "Allocation",
            "Picking",
            "Shipment",
            "Customer invoicing",
            "Receipt",
            "Accounts receivable reconciliation",
        ],
        "record_to_report": [
            "Operational transaction posting",
            "Subledger processing",
            "Journal processing",
            "Account reconciliation",
            "Period close",
            "Financial reporting",
        ],
        "plan_to_produce": [
            "Demand planning",
            "Material requirements planning",
            "Production planning",
            "Material allocation",
            "Production execution",
            "Production completion",
            "Costing and variance analysis",
        ],
    },
    "testing_strategies": {
        "unit_testing": {
            "description": "Validate individual configurations, rules, integrations, and custom components.",
            "focus": "Configuration logic, master data, calculations, and individual transactions.",
        },
        "integration_testing": {
            "description": "Validate data and process flow across Infor modules and external systems.",
            "focus": "End-to-end processes, interfaces, APIs, and financial postings.",
        },
        "uat_testing": {
            "description": "Validate business processes against real operational requirements.",
            "focus": "Business scenarios, controls, reports, exceptions, and usability.",
        },
        "regression_testing": {
            "description": "Confirm existing processes continue to work after configuration or release changes.",
            "focus": "Critical business processes and integrations.",
        },
        "performance_testing": {
            "description": "Validate system behavior under expected transaction volumes and concurrent usage.",
            "focus": "High-volume transactions, integrations, reporting, and batch processing.",
        },
    },
}


def get_module_info(module_code: str) -> Optional[Dict[str, Any]]:
    """Return information about an Infor module."""
    module = INFOR["modules"].get(module_code.lower())

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
    """Return common transactions for an Infor module."""
    module = INFOR["modules"].get(module_code.lower())
    return module.common_transactions if module else []


def get_best_practices(module_code: str) -> List[str]:
    """Return best practices for an Infor module."""
    module = INFOR["modules"].get(module_code.lower())
    return module.best_practices if module else []


def get_integration_points(module_code: str) -> List[str]:
    """Return standard integration points for an Infor module."""
    module = INFOR["modules"].get(module_code.lower())
    return module.integration_points if module else []


def get_process_flow(process_name: str) -> Optional[List[str]]:
    """Return a standard Infor business process flow."""
    process_key = process_name.lower().replace("-", "_").replace(" ", "_")
    return INFOR["processes"].get(process_key)


def search_knowledge(query: str) -> List[Dict[str, Any]]:
    """Search Infor-specific knowledge."""
    query_lower = query.lower()
    results = []

    for code, module in INFOR["modules"].items():
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
                    "erp": "Infor",
                    "code": code,
                    "name": module.name,
                    "description": module.description,
                }
            )

    for process_name, steps in INFOR["processes"].items():
        searchable = " ".join([process_name, *steps]).lower()

        if query_lower in searchable:
            results.append(
                {
                    "type": "process",
                    "erp": "Infor",
                    "name": process_name,
                    "steps": steps,
                }
            )

    return results