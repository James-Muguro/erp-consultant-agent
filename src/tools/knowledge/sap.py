"""
SAP ERP knowledge base.

This module contains SAP-specific module knowledge.
The central ERPKnowledgeBase remains ERP-agnostic.
"""

from src.tools.knowledge.base import ERPModule, ERPSystem


SAP = ERPSystem(
    name="SAP",
    vendor="SAP",
    aliases=[
        "SAP ERP",
        "SAP S/4HANA",
        "S/4HANA",
        "S4HANA",
    ],
    modules={
        "FI": ERPModule(
            name="Financial Accounting (FI)",
            description="Manages financial accounting, statutory reporting, and core financial transactions.",
            sub_modules=[
                "General Ledger (FI-GL)",
                "Accounts Payable (FI-AP)",
                "Accounts Receivable (FI-AR)",
                "Asset Accounting (FI-AA)",
                "Bank Accounting",
            ],
            common_transactions=[
                "FB50 - G/L Account Posting",
                "FB60 - Vendor Invoice Entry",
                "FB70 - Customer Invoice Entry",
                "F-02 - General Posting",
                "FS00 - G/L Account Master",
                "FK01 - Vendor Master Creation",
            ],
            integration_points=[
                "CO - Controlling",
                "MM - Materials Management",
                "SD - Sales and Distribution",
                "AA - Asset Accounting",
            ],
            best_practices=[
                "Use a chart of accounts aligned with reporting requirements.",
                "Define document types and posting controls consistently.",
                "Configure appropriate approval and payment controls.",
                "Apply role-based authorization and segregation of duties.",
                "Maintain clear audit trails for financial transactions.",
            ],
        ),

        "CO": ERPModule(
            name="Controlling (CO)",
            description="Supports management accounting, cost allocation, internal reporting, and profitability analysis.",
            sub_modules=[
                "Cost Center Accounting (CO-CCA)",
                "Internal Orders (CO-IO)",
                "Product Costing (CO-PC)",
                "Profitability Analysis (CO-PA)",
                "Profit Center Accounting (CO-PCA)",
            ],
            common_transactions=[
                "KS01 - Create Cost Center",
                "KO01 - Create Internal Order",
                "KB11N - Cost Center Posting",
                "KSH1 - Cost Center Group",
                "KE5Z - Profitability Analysis",
            ],
            integration_points=[
                "FI - Financial Accounting",
                "PP - Production Planning",
                "SD - Sales and Distribution",
                "MM - Materials Management",
            ],
            best_practices=[
                "Design cost center structures around management reporting needs.",
                "Align cost elements and G/L accounts with the accounting design.",
                "Define allocation and distribution rules before implementation.",
                "Establish consistent profit center structures.",
                "Validate profitability reporting against financial postings.",
            ],
        ),

        "MM": ERPModule(
            name="Materials Management (MM)",
            description="Manages procurement, inventory, material master data, and goods movements.",
            sub_modules=[
                "Purchasing",
                "Inventory Management",
                "Material Requirements Planning",
                "Invoice Verification",
                "Vendor Management",
            ],
            common_transactions=[
                "ME21N - Create Purchase Order",
                "ME51N - Create Purchase Requisition",
                "MIGO - Goods Movement",
                "MIRO - Enter Incoming Invoice",
                "MM03 - Display Material",
            ],
            integration_points=[
                "FI - Financial Accounting",
                "CO - Controlling",
                "PP - Production Planning",
                "SD - Sales and Distribution",
            ],
            best_practices=[
                "Maintain controlled material master data.",
                "Define purchasing approval workflows.",
                "Validate goods receipt and invoice matching.",
                "Separate procurement responsibilities where required.",
                "Monitor inventory movements and valuation.",
            ],
        ),

        "SD": ERPModule(
            name="Sales and Distribution (SD)",
            description="Manages customer-facing sales processes from quotation through delivery, billing, and financial posting.",
            sub_modules=[
                "Sales",
                "Shipping",
                "Billing",
                "Pricing",
                "Customer Master Data",
            ],
            common_transactions=[
                "VA01 - Create Sales Order",
                "VA02 - Change Sales Order",
                "VL01N - Create Outbound Delivery",
                "VF01 - Create Billing Document",
                "VA03 - Display Sales Order",
            ],
            integration_points=[
                "FI - Financial Accounting",
                "MM - Materials Management",
                "CO - Controlling",
                "PP - Production Planning",
            ],
            best_practices=[
                "Define clear order-to-cash process ownership.",
                "Control pricing and discount rules.",
                "Validate customer master data.",
                "Reconcile delivery, billing, and accounting stages.",
                "Design exception handling for blocked orders and billing.",
            ],
        ),

        "PP": ERPModule(
            name="Production Planning (PP)",
            description="Supports production planning, material requirements, manufacturing execution, and production costing.",
            sub_modules=[
                "Demand Management",
                "Material Requirements Planning",
                "Production Orders",
                "Capacity Planning",
                "Shop Floor Control",
            ],
            common_transactions=[
                "MD01 - MRP Run",
                "MD04 - Stock/Requirements List",
                "CO01 - Create Production Order",
                "CO02 - Change Production Order",
                "CO03 - Display Production Order",
            ],
            integration_points=[
                "MM - Materials Management",
                "CO - Controlling",
                "FI - Financial Accounting",
                "SD - Sales and Distribution",
            ],
            best_practices=[
                "Keep bills of material and routings governed.",
                "Align planning parameters with actual supply constraints.",
                "Reconcile material consumption with production output.",
                "Monitor production variances.",
                "Define clear master data ownership.",
            ],
        ),
    },
)