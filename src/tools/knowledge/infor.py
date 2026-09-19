"""
Infor ERP Knowledge Base

Domain knowledge for Infor ERP platforms, modules, business processes,
integrations, transactions, and implementation best practices.

Content notes
-------------
Infor's product landscape is unusually fragmented compared to SAP or
Oracle: separate platforms exist for the same functional area
(LN for manufacturing, M3 for distribution, CloudSuite variants by
industry, EAM for asset management, SunSystems for financials in some
segments). This file models Infor at the *functional* level (finance,
supply chain, manufacturing) rather than at the product level, because
that is what a consultant asks about first — "what does Infor do for
manufacturing" precedes "which Infor product handles it". The
`aliases` list carries the product-line names so `get_erp("Infor LN")`
and `get_erp("Infor CloudSuite Industrial")` resolve to this same
knowledge base.

Field-semantics note on `common_transactions`:
  Infor, like Oracle and D365, has no SAP-style T-code convention. The
  entries in `common_transactions` are user-facing tasks ("General
  ledger journal entry", "Purchase requisition"), not program
  identifiers. A future schema extension adding `common_tasks` to
  ERPModule would let this content move to a semantically correct
  field; until then it stays under the inherited name, which the
  loader reads unchanged.

Access path
-----------
The canonical way to read this knowledge is through the shared
ERPKnowledgeBase:
    from src.tools import erp_kb
    erp_kb.get_module_info("FINANCE", "Infor")

The module-level helper functions below (`get_module_info`,
`get_process_flow`, etc.) are legacy accessors kept for backward
compatibility. They return a different shape than the KB's own
`_module_to_dict`, and their search uses literal substring matching
rather than the KB's tokenized search. New code should use the KB.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import ERPModule


INFOR: Dict[str, Any] = {
    "name": "Infor",
    "vendor": "Infor",
    "category": "ERP",
    "aliases": [
        # Vendor / brand
        "Infor",
        "Infor ERP",
        # Cloud product line
        "Infor CloudSuite",
        "CloudSuite",
        "Infor Cloud",
        "Infor Cloud ERP",
        "CloudSuite ERP",
        # Product-specific (older on-prem products still widely deployed)
        "Infor LN",
        "Infor M3",
        "Infor SyteLine",
        "Infor XA",
        "Infor CloudSuite Industrial",
        "Infor CloudSuite Financials",
        "Infor CloudSuite Distribution",
        "Infor CloudSuite Business",
        "Infor CloudSuite Automotive",
        "Infor CloudSuite Food & Beverage",
        "Infor CloudSuite Healthcare",
        # Adjacent products users may ask about under the same umbrella
        "Infor EAM",
        "Infor WMS",
        "Infor SunSystems",
        "Infor CRM",
        "Infor HCM",
        # Legacy / acquired brands
        "Lawson",
        "Lawson S3",
    ],
    "description": (
        "Infor enterprise resource planning platforms supporting finance, "
        "supply chain, manufacturing, distribution, workforce, and "
        "industry-specific operations. Deployed on-premise (LN, M3, "
        "SyteLine, XA) or in the cloud (Infor CloudSuite)."
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
                "Intercompany Accounting",
                "Multi-Currency",
            ],
            common_transactions=[
                "General ledger journal entry",
                "Journal approval",
                "Supplier invoice",
                "Customer invoice",
                "Customer receipt",
                "Supplier payment",
                "Bank reconciliation",
                "Fixed asset acquisition",
                "Fixed asset depreciation",
                "Intercompany transaction",
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
                "Tax",
            ],
            best_practices=[
                "Define a consistent chart of accounts and financial dimensions "
                "across legal entities before transactional configuration.",
                "Establish clear approval controls for journals and payments; use "
                "Infor's standard approval workflow rather than custom code where "
                "possible.",
                "Separate operational and financial responsibilities through role "
                "design; validate segregation-of-duties at role level.",
                "Standardize period-close procedures across entities; use a shared "
                "close calendar if Infor's close-management capability is enabled.",
                "Use automated reconciliations where transaction volumes justify "
                "them; bank reconciliation in particular benefits from automation "
                "at scale.",
                "Align the financial calendar and fiscal periods with the group "
                "reporting calendar before data migration.",
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
                "Demand Planning",
                "Supplier Management",
            ],
            common_transactions=[
                "Purchase requisition",
                "Purchase requisition approval",
                "Purchase order",
                "Goods receipt",
                "Supplier return",
                "Inventory transfer",
                "Inventory adjustment",
                "Inventory count",
                "Sales order",
                "Sales order allocation",
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
                "Define item, supplier, and location master-data ownership; "
                "uncontrolled master data is the leading cause of downstream "
                "supply-chain reporting problems.",
                "Use approval workflows appropriate to purchasing thresholds; "
                "document thresholds and escalation paths explicitly.",
                "Maintain accurate inventory units of measure and locations; "
                "UoM conversion errors produce persistent valuation discrepancies.",
                "Define receiving and three-way matching controls; document "
                "tolerance levels for quantity and price variance.",
                "Monitor inventory exceptions and fulfillment failures via "
                "standard reports before building custom ones.",
                "Align planning parameters (lead times, safety stock, lot sizing) "
                "with actual supply constraints rather than with historical defaults.",
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
                "Shop Floor Control",
            ],
            common_transactions=[
                "Create production order",
                "Release production order",
                "Material issue",
                "Production completion",
                "Production receipt",
                "Work order closure",
                "Material requirements planning run",
                "Production variance report",
            ],
            integration_points=[
                "Inventory",
                "Procurement",
                "Warehouse Management",
                "Financial Management",
                "Quality Management",
                "Order Management",
                "Engineering Change Management",
            ],
            best_practices=[
                "Keep bills of material and routings governed by effective dates; "
                "retroactive changes invalidate historical costing.",
                "Align production master data with inventory and costing structures; "
                "a mismatch here produces persistent variance surprises.",
                "Validate material availability before releasing production; use "
                "Infor's planning tools rather than manual short-supply checks.",
                "Track production variances and investigate recurring exceptions "
                "before month-end close rather than after.",
                "Separate engineering changes from uncontrolled master-data edits; "
                "ECM discipline is what keeps BOMs and routings clean.",
                "Confirm the deployment's manufacturing model (discrete, process, "
                "repetitive, mixed-mode) matches the business's actual production "
                "pattern before committing to a design.",
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
                "Returns Management",
            ],
            common_transactions=[
                "Sales order entry",
                "Sales order allocation",
                "Pick release",
                "Pick confirmation",
                "Shipment confirmation",
                "Customer invoice",
                "Purchase order",
                "Receipt",
                "Customer return",
                "Credit memo",
            ],
            integration_points=[
                "Accounts Receivable",
                "Accounts Payable",
                "Inventory",
                "Warehouse Management",
                "Procurement",
                "Financial Management",
                "Transportation Management",
            ],
            best_practices=[
                "Define order-to-cash ownership across sales, warehouse, and "
                "finance; unclear ownership is where most fulfillment exceptions "
                "originate.",
                "Standardize pricing and discount rules; document exception "
                "approval paths for pricing overrides.",
                "Validate inventory availability before promising delivery; use "
                "available-to-promise (ATP) if the business needs it.",
                "Automate invoice creation from confirmed fulfillment events; "
                "manual invoicing introduces revenue-recognition timing risk.",
                "Monitor order exceptions from entry through shipment; standard "
                "monitors beat custom reports.",
                "Reconcile returned goods against credit memos and physical "
                "receipt; unreconciled returns are a common audit finding.",
            ],
        ),
        "projects": ERPModule(
            name="Project Management",
            description=(
                "Supports project planning, costing, billing, resource tracking, "
                "and project financial control. Commonly used in professional-"
                "services, construction, and capital-intensive industries."
            ),
            sub_modules=[
                "Project Planning",
                "Project Costing",
                "Project Billing",
                "Resource Management",
                "Project Accounting",
                "Project Contracts",
            ],
            common_transactions=[
                "Create project",
                "Project budget entry",
                "Project cost entry",
                "Time entry",
                "Expense entry",
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
                "Time and Attendance",
            ],
            best_practices=[
                "Define project structures before transactional activity begins; "
                "restructuring after transactions are posted is disruptive.",
                "Separate project costs by meaningful cost categories; the "
                "category structure drives downstream reporting.",
                "Establish clear billing and revenue-recognition rules; align "
                "with the finance team's revenue policy from the start.",
                "Reconcile project subledgers with the general ledger as part of "
                "the close cycle, not as a periodic cleanup.",
                "Close completed projects promptly; unreconciled WIP accumulates "
                "on the balance sheet otherwise.",
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
                "Time and Attendance",
            ],
            common_transactions=[
                "Employee creation",
                "Employee transfer",
                "Employee termination",
                "Time entry",
                "Time approval",
                "Leave request",
                "Leave approval",
                "Payroll processing",
                "Payroll adjustment",
            ],
            integration_points=[
                "Financial Management",
                "Payroll",
                "Time Management",
                "Workforce Management",
                "Identity Management",
                "Talent Management",
            ],
            best_practices=[
                "Apply strict access controls to employee information; HR data "
                "is among the most sensitive in the system.",
                "Define authoritative sources for employee master data; when "
                "identity management and HR systems disagree, document which wins.",
                "Separate HR administration from payroll approval responsibilities; "
                "this is a standard audit control.",
                "Reconcile payroll postings to the general ledger every cycle; "
                "payroll is a high-frequency source of reconciliation findings.",
                "Maintain effective-dated organizational structures so historical "
                "reporting reflects the org as it was.",
                "Confirm payroll localization coverage for every country in scope "
                "before committing to an in-house payroll approach.",
            ],
        ),
        # ------------------------------------------------------------------
        # Enterprise Asset Management (EAM)
        # ------------------------------------------------------------------
        "eam": ERPModule(
            name="Enterprise Asset Management (EAM)",
            description=(
                "Manages the full lifecycle of physical assets: maintenance, "
                "work orders, preventive maintenance, inspections, and asset "
                "hierarchy. Deployed standalone or alongside finance and supply "
                "chain modules."
            ),
            sub_modules=[
                "Asset Registry",
                "Work Orders",
                "Preventive Maintenance",
                "Corrective Maintenance",
                "Inspections",
                "Asset Hierarchy",
                "Meter Readings",
                "Maintenance Planning",
            ],
            common_transactions=[
                "Create asset",
                "Create work order",
                "Issue work order",
                "Complete work order",
                "Record meter reading",
                "Create preventive maintenance schedule",
                "Record inspection result",
                "Asset transfer",
                "Asset disposal",
            ],
            integration_points=[
                "Financial Management",
                "Procurement",
                "Inventory",
                "Human Resources",
                "Production",
                "IoT / Condition Monitoring",
            ],
            best_practices=[
                "Model the asset hierarchy deliberately before go-live; "
                "restructuring after maintenance history accumulates is "
                "disruptive and loses continuity.",
                "Link maintenance-relevant assets to financial asset records "
                "so capital and maintenance costs reconcile.",
                "Use maintenance strategies (time, meter, condition) with "
                "scheduled plans rather than manual work-order creation for "
                "recurring work.",
                "Define the maintenance cost roll-up (asset vs. cost center) "
                "consistent with the controlling design.",
                "Confirm the deployment model (EAM as part of ERP vs. EAM "
                "standalone with integration) before starting configuration.",
            ],
        ),
        # ------------------------------------------------------------------
        # Analytics (Birst / Infor Analytics)
        # ------------------------------------------------------------------
        "analytics": ERPModule(
            name="Analytics and Reporting",
            description=(
                "Provides operational, financial, and management reporting. "
                "Includes Infor Birst, Infor Analytics, and embedded reporting "
                "within CloudSuite applications."
            ),
            sub_modules=[
                "Embedded Reports",
                "Birst / Infor Analytics",
                "Financial Reporting",
                "Operational Dashboards",
                "Data Warehouse",
                "Ad-hoc Analysis",
            ],
            common_transactions=[
                "Run standard report",
                "Create dashboard",
                "Schedule report",
                "Export data",
                "Define measure",
            ],
            integration_points=[
                "Financial Management",
                "Supply Chain",
                "Manufacturing",
                "Human Resources",
                "External BI Tools",
                "Data Lake / Warehouse",
            ],
            best_practices=[
                "Define authoritative sources for each key metric; a metric "
                "computed two ways produces two different answers on the same "
                "day.",
                "Prefer standard embedded reports before building custom ones; "
                "they're maintained across product releases.",
                "Reconcile financial reports to the general ledger, and "
                "operational reports to their source transactions.",
                "Govern report access consistent with the underlying data's "
                "sensitivity.",
                "Confirm the reporting architecture (embedded vs. Birst vs. "
                "external BI) matches the business's analytical maturity.",
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
        "infor_os_and_integration": {
            "description": (
                "Infor OS provides the shared services layer for Infor "
                "applications: ION (integration), Ming.le (collaboration), "
                "Coleman (AI), and shared data services. Most multi-product "
                "Infor deployments rely on Infor OS for cross-application "
                "integration and identity."
            ),
            "best_practices": [
                "Confirm early whether Infor OS is in scope — it materially "
                "changes how integrations between Infor products are built.",
                "Prefer ION-based integration over point-to-point interfaces "
                "for Infor-to-Infor flows; it's the supported pattern.",
                "Define identity and single sign-on strategy before user "
                "provisioning begins.",
                "Plan Coleman (AI) adoption separately from core ERP scope — "
                "it's additive capability, not a prerequisite.",
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
        "maintain_to_retire": [
            "Asset registration",
            "Preventive maintenance scheduling",
            "Work order execution",
            "Inspection and compliance",
            "Corrective maintenance",
            "Asset transfer",
            "Asset disposal",
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


# ---------------------------------------------------------------------------
# Legacy helper accessors
# ---------------------------------------------------------------------------
# The canonical read path is src.tools.erp_kb. These functions exist so
# any external consumer that imported them directly continues to work.
# They return a different shape than ERPKnowledgeBase._module_to_dict —
# a caller using both would see slightly different keys, which is one of
# the reasons to prefer the KB path.
#
# Module lookup normalization below accepts case-insensitive names with
# spaces or dashes converted to underscores, matching what the KB's own
# _normalize_module_code does (uppercase + underscores). That way a
# caller who has been passing "Supply Chain" gets the same result as
# through the KB.


def _normalize_module_code_for_lookup(module_code: str) -> str:
    """Canonicalize a module code the same way the shared KB does:
    lowercase, spaces and dashes to underscores. Local to this file
    because the legacy accessors predate the KB-level normalizer."""
    if not module_code:
        return ""
    return str(module_code).strip().lower().replace(" ", "_").replace("-", "_")


def get_module_info(module_code: str) -> Optional[Dict[str, Any]]:
    """Legacy accessor: return information about an Infor module by
    code or display name. Prefer erp_kb.get_module_info(...)."""
    module = INFOR["modules"].get(_normalize_module_code_for_lookup(module_code))
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
    """Legacy accessor: return common transactions for an Infor module.
    Prefer erp_kb.get_transactions_by_module(...)."""
    module = INFOR["modules"].get(_normalize_module_code_for_lookup(module_code))
    return list(module.common_transactions) if module else []


def get_best_practices(module_code: str) -> List[str]:
    """Legacy accessor: return best practices for an Infor module.
    Prefer erp_kb.get_best_practices(...)."""
    module = INFOR["modules"].get(_normalize_module_code_for_lookup(module_code))
    return list(module.best_practices) if module else []


def get_integration_points(module_code: str) -> List[str]:
    """Legacy accessor: return integration points for an Infor module.
    Prefer erp_kb.get_integration_points(...)."""
    module = INFOR["modules"].get(_normalize_module_code_for_lookup(module_code))
    return list(module.integration_points) if module else []


def get_process_flow(process_name: str) -> Optional[List[str]]:
    """Legacy accessor: return a standard Infor business process flow by
    name (e.g. 'procure_to_pay', 'Procure to Pay', 'procure-to-pay')."""
    if not process_name:
        return None
    key = (
        str(process_name).strip().lower()
        .replace("-", "_").replace(" ", "_")
    )
    flow = INFOR["processes"].get(key)
    return list(flow) if flow else None


def search_knowledge(query: str) -> List[Dict[str, Any]]:
    """Legacy accessor: search Infor-specific knowledge.

    Tokenized search across module fields and process definitions — a
    value matches if it contains ANY token from the query, and results
    are ordered by number of tokens matched. Prefer
    erp_kb.search_knowledge(...) which additionally searches the ERP's
    metadata block.
    """
    tokens = [t for t in (query or "").lower().split() if t]
    if not tokens:
        return []

    def _score(value: Any) -> int:
        if not isinstance(value, str):
            return 0
        low = value.lower()
        return sum(1 for t in tokens if t in low)

    scored: List[tuple] = []

    for code, module in INFOR["modules"].items():
        score = (
            _score(code) + _score(module.name) + _score(module.description)
            + sum(_score(v) for v in (module.sub_modules or []))
            + sum(_score(v) for v in (module.common_transactions or []))
            + sum(_score(v) for v in (module.integration_points or []))
            + sum(_score(v) for v in (module.best_practices or []))
        )
        if score > 0:
            scored.append((score, {
                "type": "module",
                "erp": "Infor",
                "code": code,
                "name": module.name,
                "description": module.description,
            }))

    for process_name, steps in INFOR["processes"].items():
        score = _score(process_name) + sum(_score(s) for s in (steps or []))
        if score > 0:
            scored.append((score, {
                "type": "process",
                "erp": "Infor",
                "name": process_name,
                "steps": steps,
            }))

    scored.sort(key=lambda pair: -pair[0])
    return [entry for _, entry in scored]