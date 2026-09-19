"""
SAP ERP knowledge base.

This module contains SAP-specific module knowledge. The central
ERPKnowledgeBase remains ERP-agnostic.

Content policy
--------------
Two considerations shape what's included here:

  * Transaction codes are the ECC-era codes (FB50, ME21N, VA01, ...),
    which remain valid in SAP S/4HANA and are the shared vocabulary
    between consultants, business users, and the platform. S/4HANA's
    Fiori app equivalents exist and would be the right content for
    end-user training material, but ERPModule has no field for them
    yet - see the module docstring on the schema extension note.

  * Best practices are written to be SAP-specific rather than generic
    ERP guidance. A best practice like "align the chart of accounts
    with reporting requirements" applies equally to any ERP; the
    value of a SAP-specific KB is guidance grounded in SAP's actual
    architecture (universal journal, new asset accounting, business
    partner, embedded analytics, BRF+, release strategies, and so on).

Module coverage
---------------
The ten modules below cover the operational and financial core of a
typical SAP implementation: FI, CO, MM, SD, PP, PM, QM, WM/EWM, PS,
HR/HCM, plus BP (Business Partner), which is included because S/4HANA
migrated vendor and customer master data into the Business Partner
model and any real S/4HANA project must address it.

The KB is deliberately not exhaustive - SAP has well over a hundred
modules once industry solutions and cloud add-ons are counted. The
ten here are the ones business users and consultants ask about most
often. Additional modules can be added as data; the loader handles
them without code changes.
"""

from src.tools.knowledge.base import ERPModule, ERPSystem


SAP = ERPSystem(
    name="SAP",
    vendor="SAP",
    aliases=[
        # Vendor / brand
        "SAP",
        "SAP SE",
        "SAP ERP",
        "SAP Business Suite",
        # Modern (S/4HANA) — the primary target for new implementations
        "SAP S/4HANA",
        "S/4HANA",
        "S4HANA",
        "S/4 HANA",
        "S4 HANA",
        "S/4HANA Cloud",
        "SAP S/4HANA Cloud",
        "S/4HANA On-Premise",
        "S/4HANA On Premise",
        "S/4HANA Private Cloud",
        "S/4HANA Public Cloud",
        # Legacy (ECC / R/3) — still widely in production, users ask about them
        "SAP ECC",
        "ECC",
        "SAP ERP Central Component",
        "SAP R/3",
        "R/3",
        "SAP R3",
        "R3",
        # Generic HANA platform
        "SAP HANA",
        "HANA",
    ],
    modules={
        # ------------------------------------------------------------------
        # Financials
        # ------------------------------------------------------------------
        "FI": ERPModule(
            name="Financial Accounting (FI)",
            description=(
                "Manages financial accounting, statutory reporting, and core "
                "financial transactions. In S/4HANA, FI postings land in the "
                "universal journal (table ACDOCA), which unifies FI and CO "
                "into a single source of truth."
            ),
            sub_modules=[
                "General Ledger (FI-GL)",
                "Accounts Payable (FI-AP)",
                "Accounts Receivable (FI-AR)",
                "Asset Accounting (FI-AA)",
                "Bank Accounting (FI-BL)",
                "Travel Management (FI-TV)",
            ],
            common_transactions=[
                "FB50 - G/L Account Posting",
                "FB60 - Vendor Invoice Entry",
                "FB70 - Customer Invoice Entry",
                "F-02 - General Posting",
                "F-28 - Post Incoming Payments",
                "F-53 - Post Outgoing Payments",
                "FS00 - G/L Account Master",
                "FK01 - Vendor Master Creation",
                "FD01 - Customer Master Creation",
            ],
            integration_points=[
                "CO - Controlling",
                "MM - Materials Management",
                "SD - Sales and Distribution",
                "AA - Asset Accounting",
                "FI-BL - Bank Accounting",
            ],
            best_practices=[
                "Use the universal journal (ACDOCA) as the single source of "
                "financial truth - avoid custom FI/CO reconciliation reports.",
                "Configure document splitting for segment or profit-center "
                "reporting if segment reporting is required.",
                "Enable parallel currencies and valuation for IFRS/local GAAP "
                "reporting if the business operates in multiple currencies.",
                "Use new asset accounting (FI-AA new GL) in S/4HANA - the "
                "classic asset accounting is deprecated.",
                "Align the chart of accounts with statutory and management "
                "reporting needs; prefer a country-specific chart with group "
                "chart of accounts consolidation.",
                "Apply role-based authorization and segregation of duties; "
                "validate SoD at role design, not go-live.",
                "Use substitution and validation rules for posting controls "
                "rather than custom ABAP where standard rules suffice.",
            ],
        ),

        "CO": ERPModule(
            name="Controlling (CO)",
            description=(
                "Supports management accounting, cost allocation, internal "
                "reporting, and profitability analysis. In S/4HANA, cost "
                "elements are replaced by G/L accounts (cost element "
                "categories on the GL account master)."
            ),
            sub_modules=[
                "Cost Center Accounting (CO-CCA)",
                "Internal Orders (CO-IO)",
                "Product Costing (CO-PC)",
                "Profitability Analysis (CO-PA)",
                "Profit Center Accounting (CO-PCA)",
                "Cost Element Accounting (CO-OM)",
            ],
            common_transactions=[
                "KS01 - Create Cost Center",
                "KS02 - Change Cost Center",
                "KO01 - Create Internal Order",
                "KB11N - Enter Manual Reposting of Costs",
                "KSH1 - Create Cost Center Group",
                "KSH2 - Change Cost Center Group",
                "KE5Z - Profitability Analysis: Actual Line Items",
                "CK11N - Create Material Cost Estimate",
            ],
            integration_points=[
                "FI - Financial Accounting",
                "PP - Production Planning",
                "SD - Sales and Distribution",
                "MM - Materials Management",
                "PS - Project System",
            ],
            best_practices=[
                "Use margin analysis (account-based CO-PA) in S/4HANA; the "
                "classic costing-based CO-PA is deprecated.",
                "Design cost center structures around management reporting "
                "needs, not around the org chart.",
                "Configure commitment management on cost centers and internal "
                "orders if budget control is required.",
                "Use assessment and distribution cycles for cost allocation; "
                "prefer top-down distribution where allocation rules are "
                "driven by sender-receiver relationships.",
                "Reconcile profitability reporting back to the universal "
                "journal (ACDOCA) to keep CO and FI aligned.",
            ],
        ),

        # ------------------------------------------------------------------
        # Logistics
        # ------------------------------------------------------------------
        "MM": ERPModule(
            name="Materials Management (MM)",
            description=(
                "Manages procurement, inventory management, material master "
                "data, and goods movements. In S/4HANA, vendor master data "
                "moves to the Business Partner (BP) model."
            ),
            sub_modules=[
                "Purchasing (MM-PUR)",
                "Inventory Management (MM-IM)",
                "Material Requirements Planning (MM-MRP)",
                "Logistics Invoice Verification (MM-LIV)",
                "Vendor Master (MM-VM)",
                "Physical Inventory (MM-IM-PI)",
            ],
            common_transactions=[
                "ME21N - Create Purchase Order",
                "ME22N - Change Purchase Order",
                "ME23N - Display Purchase Order",
                "ME51N - Create Purchase Requisition",
                "ME52N - Change Purchase Requisition",
                "MIGO - Goods Movement",
                "MIRO - Enter Incoming Invoice",
                "MR8M - Cancel Invoice Document",
                "MM01 - Create Material Master",
                "MM03 - Display Material Master",
                "MB51 - Material Document List",
                "MB52 - Warehouse Stock by Material",
            ],
            integration_points=[
                "FI - Financial Accounting",
                "CO - Controlling",
                "PP - Production Planning",
                "SD - Sales and Distribution",
                "WM - Warehouse Management",
                "QM - Quality Management",
            ],
            best_practices=[
                "Use Business Partner (BP) for vendor master in S/4HANA - the "
                "classic vendor master (FK01/FK02/FK03) is read-only.",
                "Configure release strategies for purchase order and "
                "purchase requisition approvals; use the release strategy "
                "engine rather than custom workflow where standard suffices.",
                "Enable three-way match (PO, goods receipt, invoice) as the "
                "default control for procurement; document tolerances "
                "explicitly.",
                "Separate procurement responsibilities - requisitioner, "
                "approver, goods receiver, invoice processor - to satisfy "
                "segregation-of-duties requirements.",
                "Maintain controlled material master data with a clear "
                "governance process; uncontrolled master data is a leading "
                "cause of downstream reporting problems.",
                "Monitor inventory movements and valuation via standard "
                "reports (MB51, MB5B, MB52) rather than custom extracts.",
            ],
        ),

        "SD": ERPModule(
            name="Sales and Distribution (SD)",
            description=(
                "Manages customer-facing sales processes from quotation "
                "through delivery, billing, and financial posting. In "
                "S/4HANA, customer master data moves to the Business "
                "Partner (BP) model."
            ),
            sub_modules=[
                "Sales (SD-SLS)",
                "Shipping (SD-SHP)",
                "Billing (SD-BIL)",
                "Pricing (SD-BF-PR)",
                "Customer Master (SD-BF-CM)",
                "Credit Management (SD-BF-CM)",
                "Foreign Trade (SD-FT)",
            ],
            common_transactions=[
                "VA01 - Create Sales Order",
                "VA02 - Change Sales Order",
                "VA03 - Display Sales Order",
                "VL01N - Create Outbound Delivery",
                "VL02N - Change Outbound Delivery",
                "VL06O - Outbound Delivery Monitor",
                "VF01 - Create Billing Document",
                "VF02 - Change Billing Document",
                "VF03 - Display Billing Document",
                "VKM1 - Blocked SD Documents",
            ],
            integration_points=[
                "FI - Financial Accounting",
                "MM - Materials Management",
                "CO - Controlling",
                "PP - Production Planning",
                "WM - Warehouse Management",
                "Credit Management (FSCM)",
            ],
            best_practices=[
                "Use Business Partner (BP) for customer master in S/4HANA.",
                "Use BRF+ for output determination (order confirmations, "
                "delivery notes, invoices) - the classic output determination "
                "is being phased out.",
                "Configure credit management in FSCM (Financial Supply Chain "
                "Management) for real-time credit checks and automated "
                "credit-block handling.",
                "Design pricing procedures with clear condition types and "
                "access sequences; review pricing reports regularly to catch "
                "unintended discount stacking.",
                "Reconcile delivery, billing, and accounting stages via "
                "standard reports; blocked billing and blocked deliveries "
                "should have defined resolution ownership.",
                "Use advanced ATP (aATP) if scheduling and product "
                "availability are business-critical.",
            ],
        ),

        "PP": ERPModule(
            name="Production Planning (PP)",
            description=(
                "Supports production planning, material requirements, "
                "manufacturing execution, and production costing."
            ),
            sub_modules=[
                "Demand Management (PP-MP-DEM)",
                "Material Requirements Planning (PP-MRP)",
                "Production Orders (PP-SFC)",
                "Capacity Planning (PP-CRP)",
                "Shop Floor Control (PP-SFC)",
                "Repetitive Manufacturing (PP-REM)",
                "Bills of Material (PP-BD-BOM)",
                "Routings (PP-BD-RTG)",
            ],
            common_transactions=[
                "MD01 - MRP Run (Total Planning)",
                "MD02 - MRP Single Item Planning",
                "MD04 - Stock/Requirements List",
                "MD07 - Collective Stock/Requirements List",
                "CO01 - Create Production Order",
                "CO02 - Change Production Order",
                "CO03 - Display Production Order",
                "MB31 - Goods Receipt for Production Order",
                "MIGO - Goods Movement (consumption / receipt)",
                "COOIS - Production Order Information System",
            ],
            integration_points=[
                "MM - Materials Management",
                "CO - Controlling",
                "FI - Financial Accounting",
                "SD - Sales and Distribution",
                "QM - Quality Management",
                "WM - Warehouse Management",
            ],
            best_practices=[
                "Govern bills of material and routings as master data with "
                "clear ownership and change control.",
                "Align planning parameters (lot size, safety stock, lead "
                "time) with actual supply constraints, not with historical "
                "defaults.",
                "Reconcile material consumption against production output "
                "regularly; unreconciled variances indicate master data or "
                "backflush configuration issues.",
                "Monitor production variances via COOIS and cost analysis; "
                "investigate large variances before month-end close.",
                "Use embedded analytics or Fiori apps for production "
                "monitoring where available; classic COOIS remains valid but "
                "is being supplemented.",
            ],
        ),

        # ------------------------------------------------------------------
        # Plant Maintenance
        # ------------------------------------------------------------------
        "PM": ERPModule(
            name="Plant Maintenance (PM)",
            description=(
                "Manages maintenance activities for technical assets - "
                "equipment, functional locations, preventive maintenance, and "
                "work orders. Used in manufacturing, utilities, facilities, "
                "and asset-intensive industries."
            ),
            sub_modules=[
                "Preventive Maintenance (PM-PRM)",
                "Maintenance Processing (PM-WOC)",
                "Maintenance Notifications (PM-WOC-MN)",
                "Equipment and Technical Objects (PM-EQM)",
                "Functional Locations (PM-EQM-FL)",
                "Maintenance Task Lists (PM-PRM-TL)",
            ],
            common_transactions=[
                "IE01 - Create Equipment",
                "IL01 - Create Functional Location",
                "IW31 - Create Maintenance Order",
                "IW32 - Change Maintenance Order",
                "IW33 - Display Maintenance Order",
                "IW21 - Create Maintenance Notification",
                "IW41 - Enter Maintenance Order Confirmation",
                "IP10 - Schedule Maintenance Plan",
                "IP30 - Deadline Monitoring",
            ],
            integration_points=[
                "MM - Materials Management",
                "CO - Controlling",
                "FI - Financial Accounting",
                "AA - Asset Accounting",
                "PP - Production Planning",
            ],
            best_practices=[
                "Model the technical asset hierarchy (functional locations "
                "and equipment) before loading maintenance plans - a poor "
                "hierarchy is expensive to restructure later.",
                "Link maintenance-relevant equipment to asset accounting "
                "(FI-AA) so capex and maintenance history reconcile.",
                "Use maintenance strategies (time-based, performance-based, "
                "condition-based) with scheduled plans rather than manual "
                "order creation for recurring work.",
                "Configure work order settlement to cost centers or assets "
                "consistent with the controlling design.",
            ],
        ),

        # ------------------------------------------------------------------
        # Quality Management
        # ------------------------------------------------------------------
        "QM": ERPModule(
            name="Quality Management (QM)",
            description=(
                "Supports quality planning, inspection, and control across "
                "procurement, production, and delivery. Common in regulated "
                "industries (pharma, food, automotive)."
            ),
            sub_modules=[
                "Quality Planning (QM-PT)",
                "Quality Inspection (QM-IM)",
                "Quality Notifications (QM-QN)",
                "Test Equipment Management (QM-IM-TE)",
                "Quality Control (QM-QC)",
                "Audit Management (QM-AU)",
            ],
            common_transactions=[
                "QM01 - Create Quality Info Record",
                "QP01 - Create Inspection Plan",
                "QA01 - Create Inspection Lot",
                "QA32 - Change Inspection Lot",
                "QA11 - Record Usage Decision",
                "QE01 - Record Results for Inspection",
                "QM11 - Create Quality Notification",
                "QS21 - Create Master Inspection Characteristic",
            ],
            integration_points=[
                "MM - Materials Management",
                "PP - Production Planning",
                "SD - Sales and Distribution",
                "PM - Plant Maintenance",
            ],
            best_practices=[
                "Define inspection plans and characteristics before go-live "
                "for all regulated materials - retrofitting is disruptive.",
                "Use dynamic modification rules to adjust inspection scope "
                "based on vendor or process quality history.",
                "Integrate quality notifications with corrective action "
                "workflows and track closure.",
                "Align QM inspection results with batch management and "
                "traceability requirements if the business requires it.",
            ],
        ),

        # ------------------------------------------------------------------
        # Warehouse Management
        # ------------------------------------------------------------------
        "WM": ERPModule(
            name="Warehouse Management (WM / EWM)",
            description=(
                "Manages warehouse operations at the bin level. Classic WM "
                "is available in ECC and via compatibility in S/4HANA; "
                "Extended Warehouse Management (EWM) is the strategic "
                "S/4HANA warehouse solution and can be embedded or "
                "decentralized."
            ),
            sub_modules=[
                "Warehouse Structure (WM-MD)",
                "Transfer Orders (WM-TO)",
                "Inventory Management (WM-IM)",
                "Storage Unit Management (WM-SU)",
                "Extended Warehouse Management (EWM)",
                "Yard Management (EWM-YM)",
                "Labor Management (EWM-LM)",
            ],
            common_transactions=[
                "LX01 - Create Warehouse",
                "LS01N - Create Storage Bin",
                "LT01 - Create Transfer Order",
                "LT03 - Create Transfer Order from Delivery",
                "LT0G - Return Transfer Order",
                "LX02 - Warehouse Stock",
                "LI01N - Create Physical Inventory Document",
                "LI11N - Enter Physical Inventory Count",
            ],
            integration_points=[
                "MM - Materials Management",
                "SD - Sales and Distribution",
                "PP - Production Planning",
                "QM - Quality Management",
            ],
            best_practices=[
                "Choose the warehouse solution (classic WM vs EWM embedded "
                "vs EWM decentralized) based on operational complexity, not "
                "on precedent - the migration from WM to EWM is nontrivial.",
                "Design storage bin naming conventions and warehouse "
                "structure before go-live; bin restructuring is disruptive.",
                "Configure putaway and stock removal strategies explicitly - "
                "the defaults rarely match the business.",
                "Integrate physical inventory cycles with the business's "
                "inventory accuracy requirements.",
            ],
        ),

        # ------------------------------------------------------------------
        # Project System
        # ------------------------------------------------------------------
        "PS": ERPModule(
            name="Project System (PS)",
            description=(
                "Manages project structures, budgets, schedules, and "
                "settlement. Used for capital projects, customer projects, "
                "and internal initiatives."
            ),
            sub_modules=[
                "Project Structures (PS-STRUCT)",
                "Work Breakdown Structure (PS-WBS)",
                "Networks and Activities (PS-NET)",
                "Project Planning Board (PS-PLN)",
                "Project Budgeting (PS-BDG)",
                "Project Settlement (PS-SET)",
            ],
            common_transactions=[
                "CJ01 - Create Project Definition",
                "CJ02 - Change Project",
                "CJ03 - Display Project",
                "CJ20N - Project Builder",
                "CJ30 - Project Budget",
                "CJ31 - Original Budget",
                "CJ41 - Transfer Project Budget",
                "CN21 - Create Network",
                "CJI3 - Project Actual Line Items",
            ],
            integration_points=[
                "CO - Controlling",
                "FI - Financial Accounting",
                "MM - Materials Management",
                "PP - Production Planning",
                "SD - Sales and Distribution",
                "HR - Human Resources",
            ],
            best_practices=[
                "Design the WBS structure with both reporting and billing "
                "in mind; retrofitting is expensive.",
                "Align project settlement rules with the controlling design "
                "and the receiving cost objects (cost centers, assets, "
                "internal orders).",
                "Use investment management (IM) integration if capex "
                "approvals are required.",
                "Configure project budgeting with appropriate tolerance "
                "levels; unmanaged budget overruns are a compliance risk.",
            ],
        ),

        # ------------------------------------------------------------------
        # Human Capital Management
        # ------------------------------------------------------------------
        "HR": ERPModule(
            name="Human Capital Management (HR / HCM)",
            description=(
                "Manages employee master data, organizational structure, "
                "payroll, time, and personnel administration. In S/4HANA, "
                "strategic HR functions have moved to SAP SuccessFactors, "
                "with SAP HCM (on-premise) retained for payroll and "
                "administrative scenarios."
            ),
            sub_modules=[
                "Personnel Administration (PA)",
                "Organizational Management (OM)",
                "Payroll (PY)",
                "Time Management (PT)",
                "Personnel Development (PD)",
                "SAP SuccessFactors (cloud HR)",
            ],
            common_transactions=[
                "PA40 - Personnel Actions",
                "PA30 - Maintain HR Master Data",
                "PA20 - Display HR Master Data",
                "PA03 - Payroll Control Center",
                "PC00_M99_CALC - Payroll Driver",
                "PT60 - Time Evaluation",
                "PP01 - Maintain Object",
                "PPOME - Organization and Staffing",
                "OOQA - Succession Planning",
            ],
            integration_points=[
                "FI - Financial Accounting",
                "CO - Controlling",
                "PS - Project System",
                "SAP SuccessFactors",
            ],
            best_practices=[
                "Clarify early whether payroll stays on SAP HCM on-premise "
                "or moves to SAP SuccessFactors or a third-party provider - "
                "this decision shapes the whole HR solution.",
                "Treat employee master data as sensitive; apply field-level "
                "authorization and log access.",
                "Align organizational structure and cost center assignment "
                "with the controlling design.",
                "Consider localization requirements (country-specific payroll, "
                "tax, and social insurance) early - retrofitting payroll is "
                "high-risk.",
            ],
        ),

        # ------------------------------------------------------------------
        # Business Partner (S/4HANA-specific)
        # ------------------------------------------------------------------
        "BP": ERPModule(
            name="Business Partner (BP)",
            description=(
                "S/4HANA's unified master data model for customers, vendors, "
                "and other business partners. In S/4HANA, vendor and "
                "customer master records are represented as Business "
                "Partners with customer and supplier roles assigned. Any "
                "S/4HANA implementation must address the BP model even if "
                "it doesn't add new BP functionality."
            ),
            sub_modules=[
                "Business Partner Master Data",
                "Business Partner Roles (Customer / Supplier)",
                "Business Partner Relationships",
                "Business Partner Groupings and Number Ranges",
                "CVI - Customer/Vendor Integration",
            ],
            common_transactions=[
                "BP - Maintain Business Partner",
                "BPCA - Business Partner: Customer Role",
                "BPSU - Business Partner: Supplier Role",
                "FLBPC - BP Customer Master",
                "FLBPD - BP Supplier Master",
                "MDS_LOAD_COCKPIT - Master Data Synchronization",
                "CVI_COCKPIT - CVI Cockpit",
            ],
            integration_points=[
                "FI - Financial Accounting (AR / AP)",
                "MM - Materials Management",
                "SD - Sales and Distribution",
                "CRM / C4C",
            ],
            best_practices=[
                "Design the BP grouping and number range scheme before "
                "migration; renumbering after go-live is disruptive.",
                "Decide whether BP data is mastered in SAP S/4HANA or in an "
                "external MDM system, and configure the CVI/IDoc interfaces "
                "accordingly.",
                "For S/4HANA conversions from ECC, use the CVI Cockpit to "
                "validate customer-vendor integration - unresolved CVI errors "
                "block the conversion.",
                "Extend BP with industry-specific roles only where the "
                "business genuinely needs them; unused roles are a source of "
                "confusion in authorizations.",
            ],
        ),
    },
)