"""
Microsoft Dynamics 365 ERP knowledge base.

Covers major Dynamics 365 business applications and functional areas
used in ERP consulting, implementation, integration, testing, and
business process design.

The knowledge is intentionally organized around functional domains
rather than treating Dynamics 365 as a single monolithic application.

Content notes
-------------
  * `common_transactions` in this file contains *menu items, forms, and
    tasks* - the D365 equivalents of what a user actually runs. D365 has
    no direct analogue to SAP T-codes; the closest equivalent is a task
    in a workspace or a menu path. The values are accurate for D365 even
    though the field name is inherited from the SAP-oriented schema. A
    future schema extension adding `common_tasks` (or an `ERPModule.
    metadata` dict) would let the two forms sit side by side; until
    then, this file's values are the practical content for D365.

  * Module keys use underscores for multi-word codes
    (CUSTOMER_SERVICE, PROJECT_OPERATIONS, BUSINESS_CENTRAL,
    FIELD_SERVICE). get_module_info uppercases but does not currently
    translate spaces to underscores, so a caller passing "Customer
    Service" resolves to "CUSTOMER SERVICE" and misses. The correct fix
    is a one-line normalization in base.py
    (`module_code.upper().strip().replace(" ", "_").replace("-", "_")`),
    which handles this and any future multi-word module uniformly. The
    aliases below include the space-form vendor names via the ERPSystem
    aliases list, so get_erp("Customer Service") is not the issue - the
    issue is specifically get_module_info with a spaced module code.
"""

from src.tools.knowledge.base import ERPModule, ERPSystem


DYNAMICS_365 = ERPSystem(
    name="Microsoft Dynamics 365",
    vendor="Microsoft",
    aliases=[
        # Vendor / brand
        "Dynamics 365",
        "Microsoft Dynamics",
        "Microsoft D365",
        "MS Dynamics 365",
        "MS D365",
        "Dynamics",
        # Enterprise suite (Finance & Operations)
        "D365 F&O",
        "D365 FnO",
        "D365 F and O",
        "Dynamics 365 F&O",
        "Finance and Operations",
        "Finance & Operations",
        "Microsoft Dynamics 365 Finance and Operations",
        "D365 Finance",
        "Microsoft Dynamics 365 Finance",
        # Legacy enterprise ERP, still widely deployed
        "Dynamics AX",
        "Microsoft Dynamics AX",
        "AX",
        "AX 2012",
        # Customer Engagement suite
        "D365 CE",
        "Dynamics 365 CE",
        "Customer Engagement",
        "Dynamics 365 CRM",
        "Microsoft Dynamics CRM",
        # SMB product
        "D365 BC",
        "Dynamics 365 Business Central",
        "Business Central",
        "Dynamics BC",
        "Microsoft Dynamics 365 Business Central",
        "Microsoft Dynamics NAV",
        "Navision",
    ],
    modules={
        # --------------------------------------------------------------
        # Finance
        # --------------------------------------------------------------

        "FINANCE": ERPModule(
            name="Dynamics 365 Finance",
            description=(
                "Enterprise financial management for general ledger, "
                "accounts payable, accounts receivable, cash and bank "
                "management, budgeting, fixed assets, tax, and financial reporting. "
                "Part of the Finance & Operations (F&O) suite alongside "
                "Supply Chain Management, Project Operations, and Human Resources."
            ),
            sub_modules=[
                "General Ledger",
                "Accounts Payable",
                "Accounts Receivable",
                "Cash and Bank Management",
                "Budgeting",
                "Fixed Assets",
                "Tax",
                "Financial Reporting",
                "Cost Accounting",
                "Electronic Reporting",
                "Subscription Billing",
                "Credit and Collections",
                "Expense Management",
            ],
            common_transactions=[
                "General journal",
                "Vendor invoice",
                "Vendor payment",
                "Customer invoice",
                "Customer payment",
                "Free text invoice",
                "Bank reconciliation",
                "Fixed asset acquisition",
                "Fixed asset depreciation",
                "Financial dimension posting",
                "Budget register entry",
                "Period close",
            ],
            integration_points=[
                "Supply Chain Management",
                "Commerce",
                "Project Operations",
                "Human Resources",
                "Sales",
                "Power Platform",
                "Microsoft Excel",
                "External banking systems",
                "Tax services",
                "Dataverse",
            ],
            best_practices=[
                "Design the chart of accounts and financial dimensions around reporting requirements.",
                "Define legal entities and organizational structures before transaction configuration.",
                "Use posting profiles consistently across subledgers.",
                "Separate financial dimensions from the chart of accounts where the business needs flexible analysis.",
                "Configure workflow approval for material financial transactions.",
                "Reconcile subledgers to the general ledger as part of the close process.",
                "Use Electronic Reporting for controlled regulatory and financial document formats.",
                "Define role-based security and segregation of duties for finance processes.",
                "Use the Financial Reporter and default reports for the periodic close "
                "rather than building custom reports on day one.",
            ],
        ),

        # --------------------------------------------------------------
        # Supply Chain Management
        # --------------------------------------------------------------

        "SCM": ERPModule(
            name="Dynamics 365 Supply Chain Management",
            description=(
                "Manages procurement, inventory, warehousing, product information, "
                "planning, production, quality, and supply chain operations. "
                "Part of the Finance & Operations (F&O) suite."
            ),
            sub_modules=[
                "Procurement and Sourcing",
                "Product Information Management",
                "Inventory Management",
                "Warehouse Management",
                "Master Planning",
                "Production Control",
                "Asset Management",
                "Quality Management",
                "Transportation Management",
                "Cost Management",
                "Engineering Change Management",
            ],
            common_transactions=[
                "Purchase requisition",
                "Purchase order",
                "Product receipt",
                "Vendor invoice",
                "Sales order",
                "Packing slip",
                "Inventory movement",
                "Inventory transfer",
                "Production order",
                "Inventory counting",
                "Load planning",
                "Warehouse work creation",
            ],
            integration_points=[
                "Dynamics 365 Finance",
                "Dynamics 365 Commerce",
                "Dynamics 365 Sales",
                "Project Operations",
                "Warehouse and transportation systems",
                "External suppliers",
                "Power Platform",
                "Dataverse",
            ],
            best_practices=[
                "Establish product and released-product governance before transactional configuration.",
                "Define inventory dimensions according to operational and financial reporting needs.",
                "Separate procurement policy from individual purchasing transactions.",
                "Validate warehouse processes using realistic receiving, picking, packing, and shipping scenarios.",
                "Align planning parameters with actual supply and demand behaviour.",
                "Reconcile physical inventory with system inventory through controlled counting processes.",
                "Define ownership for product, vendor, warehouse, and procurement master data.",
                "Use the Inventory Visibility add-in for cross-channel availability scenarios "
                "where the business operates Commerce and F&O together.",
            ],
        ),

        # --------------------------------------------------------------
        # Sales (Customer Engagement)
        # --------------------------------------------------------------

        "SALES": ERPModule(
            name="Dynamics 365 Sales",
            description=(
                "Manages customer relationships, leads, opportunities, "
                "accounts, contacts, activities, quotations, and sales processes. "
                "Part of the Customer Engagement (CE) suite alongside Customer "
                "Service, Field Service, Marketing, and Customer Insights."
            ),
            sub_modules=[
                "Lead Management",
                "Opportunity Management",
                "Account Management",
                "Contact Management",
                "Activity Management",
                "Product Catalog",
                "Quotes",
                "Sales Orders",
                "Forecasting",
                "Sales Accelerator",
                "Sequences",
            ],
            common_transactions=[
                "Create lead",
                "Qualify lead",
                "Create opportunity",
                "Create quote",
                "Convert opportunity",
                "Create sales order",
                "Update opportunity stage",
                "Record customer activity",
                "Convert quote to order",
                "Close opportunity",
            ],
            integration_points=[
                "Dynamics 365 Finance",
                "Dynamics 365 Supply Chain Management",
                "Dynamics 365 Customer Service",
                "Dynamics 365 Customer Insights",
                "Dynamics 365 Marketing",
                "Dynamics 365 Field Service",
                "Power Platform",
                "Outlook",
                "Microsoft Teams",
                "Dataverse",
            ],
            best_practices=[
                "Define the lead-to-opportunity process before configuring sales stages.",
                "Standardize opportunity qualification criteria.",
                "Control product and price-list governance.",
                "Define ownership and security boundaries for customer records.",
                "Avoid unnecessary customization where standard sales processes meet the requirement.",
                "Define integration ownership between CRM and ERP order processing - "
                "typically via Dual-write for near-real-time or a batch interface "
                "for lower-latency requirements.",
                "Align Sales and Marketing lead-scoring and handoff rules if both "
                "apps are deployed.",
            ],
        ),

        # --------------------------------------------------------------
        # Customer Service
        # --------------------------------------------------------------

        "CUSTOMER_SERVICE": ERPModule(
            name="Dynamics 365 Customer Service",
            description=(
                "Supports customer support operations through cases, knowledge management, "
                "service-level agreements, queues, entitlements, and omnichannel engagement."
            ),
            sub_modules=[
                "Case Management",
                "Knowledge Management",
                "Queues",
                "Entitlements",
                "Service-Level Agreements",
                "Omnichannel",
                "Customer Service Workspace",
                "Service Scheduling",
            ],
            common_transactions=[
                "Create case",
                "Assign case",
                "Escalate case",
                "Resolve case",
                "Create knowledge article",
                "Track service activity",
                "Apply entitlement",
                "Route via omnichannel",
            ],
            integration_points=[
                "Dynamics 365 Sales",
                "Dynamics 365 Finance",
                "Dynamics 365 Field Service",
                "Dynamics 365 Customer Insights",
                "Power Platform",
                "Microsoft Teams",
                "Email channels",
                "Dataverse",
            ],
            best_practices=[
                "Define case categories and resolution codes consistently.",
                "Design queues around operational ownership rather than organizational complexity.",
                "Define SLA rules against measurable service commitments.",
                "Govern knowledge articles through ownership and review processes.",
                "Separate customer-facing processes from internal escalation processes.",
                "Align Field Service dispatch rules with Customer Service case escalation "
                "if the two apps work together.",
            ],
        ),

        # --------------------------------------------------------------
        # Human Resources
        # --------------------------------------------------------------

        "HR": ERPModule(
            name="Dynamics 365 Human Resources",
            description=(
                "Manages employee information, organizational structures, "
                "personnel processes, leave, benefits, compensation, and workforce administration. "
                "Also deployed standalone or alongside third-party payroll providers."
            ),
            sub_modules=[
                "Personnel Management",
                "Organizational Management",
                "Leave and Absence",
                "Benefits",
                "Compensation",
                "Performance Management",
                "Employee Self-Service",
                "Workforce Management",
            ],
            common_transactions=[
                "Hire worker",
                "Transfer worker",
                "Change worker position",
                "Record leave request",
                "Update compensation",
                "Maintain employee records",
                "Approve leave request",
            ],
            integration_points=[
                "Dynamics 365 Finance",
                "Payroll systems",
                "Microsoft Entra ID",
                "Microsoft Teams",
                "Power Platform",
                "Dataverse",
            ],
            best_practices=[
                "Protect employee data through role-based access.",
                "Define organizational hierarchies before configuring HR workflows.",
                "Separate sensitive HR responsibilities through security roles.",
                "Define effective-dated processes for organizational and employee changes.",
                "Validate integrations between HR, payroll, identity, and finance systems.",
                "Confirm payroll localization approach - D365 HR does not include "
                "in-the-box payroll for all countries; many implementations integrate "
                "a local payroll provider.",
            ],
        ),

        # --------------------------------------------------------------
        # Project Operations
        # --------------------------------------------------------------

        "PROJECT_OPERATIONS": ERPModule(
            name="Dynamics 365 Project Operations",
            description=(
                "Supports project-based organizations through project planning, "
                "resource management, time and expense tracking, project accounting, "
                "billing, and project financial management."
            ),
            sub_modules=[
                "Project Planning",
                "Project Management",
                "Resource Management",
                "Time Tracking",
                "Expense Management",
                "Project Accounting",
                "Project Contracts",
                "Project Billing",
                "Project Approvals",
            ],
            common_transactions=[
                "Create project",
                "Create project contract",
                "Create project task",
                "Assign project resource",
                "Submit timesheet",
                "Submit expense",
                "Create project invoice",
                "Post project transaction",
                "Approve timesheet",
                "Approve expense report",
            ],
            integration_points=[
                "Dynamics 365 Finance",
                "Dynamics 365 Sales",
                "Human Resources",
                "Microsoft Teams",
                "Power Platform",
                "Dataverse",
            ],
            best_practices=[
                "Define project financial dimensions before project transactions begin.",
                "Separate project planning from project accounting responsibilities.",
                "Define resource roles and capacity rules clearly.",
                "Validate time and expense approval workflows.",
                "Reconcile project costs, revenue, billing, and general ledger postings.",
                "Align the Project Operations deployment mode (Lite vs. Full) with the "
                "business's project scale and accounting needs.",
            ],
        ),

        # --------------------------------------------------------------
        # Commerce
        # --------------------------------------------------------------

        "COMMERCE": ERPModule(
            name="Dynamics 365 Commerce",
            description=(
                "Supports retail and commerce operations across stores, "
                "e-commerce, point of sale, merchandising, pricing, and customer engagement. "
                "Built on the same data model as Finance and Supply Chain Management, "
                "so retail transactions post directly to F&O."
            ),
            sub_modules=[
                "Retail Stores",
                "Point of Sale",
                "E-commerce",
                "Merchandising",
                "Pricing and Discounts",
                "Product Management",
                "Customer Management",
                "Order Management",
                "Call Center",
            ],
            common_transactions=[
                "Point-of-sale transaction",
                "Customer order",
                "Product receipt",
                "Return transaction",
                "Price adjustment",
                "Inventory movement",
                "Retail payment",
                "Statement posting",
            ],
            integration_points=[
                "Dynamics 365 Finance",
                "Dynamics 365 Supply Chain Management",
                "Dynamics 365 Customer Insights",
                "Payment providers",
                "E-commerce platforms",
                "External marketplaces",
                "Power Platform",
                "Dataverse",
            ],
            best_practices=[
                "Define product, channel, catalog, and assortment structures before deployment.",
                "Test pricing and promotion rules across all relevant sales channels.",
                "Validate payment and settlement reconciliation.",
                "Test offline point-of-sale scenarios where applicable.",
                "Reconcile retail transactions to financial and inventory postings.",
                "Align the statement posting schedule with the finance close calendar.",
            ],
        ),

        # --------------------------------------------------------------
        # Business Central
        # --------------------------------------------------------------

        "BUSINESS_CENTRAL": ERPModule(
            name="Microsoft Dynamics 365 Business Central",
            description=(
                "Cloud ERP for small and mid-sized organizations covering finance, "
                "sales, purchasing, inventory, projects, fixed assets, and operational accounting. "
                "Distinct from the F&O suite - it is a separate product with its own "
                "architecture, extension model (AL), and data model, typically deployed "
                "for organizations that do not need the scale and complexity of F&O."
            ),
            sub_modules=[
                "Financial Management",
                "Sales",
                "Purchasing",
                "Inventory",
                "Warehouse Management",
                "Projects",
                "Fixed Assets",
                "Service Management",
                "Jobs",
                "Manufacturing",
                "Banking and Payments",
            ],
            common_transactions=[
                "General journal",
                "Sales order",
                "Sales invoice",
                "Purchase order",
                "Purchase invoice",
                "Item receipt",
                "Item shipment",
                "Bank reconciliation",
                "Payment journal",
                "Fixed asset transaction",
                "Inventory adjustment",
            ],
            integration_points=[
                "Microsoft 365",
                "Power Platform",
                "Outlook",
                "Excel",
                "Dynamics 365 Sales",
                "External banking systems",
                "Third-party extensions",
                "REST APIs",
                "Dataverse",
            ],
            best_practices=[
                "Keep the chart of accounts aligned with reporting requirements.",
                "Use dimensions for analysis rather than creating unnecessary G/L accounts.",
                "Establish posting groups carefully because they control accounting behaviour.",
                "Use standard workflows before introducing custom approval logic.",
                "Control extensions and AL customizations through source control and testing.",
                "Validate posting setup across sales, purchasing, inventory, and finance.",
                "Design integrations around supported APIs and documented extension points.",
                "Decide Business Central vs. F&O early - migrating between them mid-project "
                "is a re-implementation, not a reconfiguration.",
            ],
        ),

        # --------------------------------------------------------------
        # Field Service
        # --------------------------------------------------------------

        "FIELD_SERVICE": ERPModule(
            name="Dynamics 365 Field Service",
            description=(
                "Manages field service operations including work orders, "
                "scheduling, resource management, inspections, assets, and mobile work."
            ),
            sub_modules=[
                "Work Orders",
                "Scheduling",
                "Resource Management",
                "Customer Assets",
                "Agreements",
                "Inspections",
                "Mobile Application",
                "Inventory",
                "IoT Integration",
            ],
            common_transactions=[
                "Create work order",
                "Assign technician",
                "Schedule work order",
                "Record service activity",
                "Record parts consumption",
                "Complete work order",
                "Capture inspection result",
                "Generate agreement",
            ],
            integration_points=[
                "Dynamics 365 Customer Service",
                "Dynamics 365 Sales",
                "Dynamics 365 Finance",
                "Dynamics 365 Supply Chain Management",
                "IoT services",
                "Power Platform",
                "Dataverse",
            ],
            best_practices=[
                "Define work-order lifecycle states clearly.",
                "Align scheduling rules with actual resource skills and availability.",
                "Maintain accurate customer asset records.",
                "Validate mobile workflows under realistic field conditions.",
                "Reconcile parts consumption and service activity with financial transactions.",
                "Decide the field-service-to-finance integration model early - "
                "work order closure and parts consumption both post financially.",
            ],
        ),

        # --------------------------------------------------------------
        # Marketing (Customer Engagement suite)
        # --------------------------------------------------------------

        "MARKETING": ERPModule(
            name="Dynamics 365 Marketing (Customer Insights - Journeys)",
            description=(
                "Customer engagement marketing: campaigns, email, customer journeys, "
                "event management, lead scoring, and landing pages. Rebranded as "
                "'Customer Insights - Journeys' in recent releases; still widely "
                "referred to as D365 Marketing. Part of the Customer Engagement suite."
            ),
            sub_modules=[
                "Customer Journeys",
                "Email Marketing",
                "Lead Scoring",
                "Event Management",
                "Landing Pages",
                "Forms and Surveys",
                "Segments",
                "Compliance and Consent",
            ],
            common_transactions=[
                "Create marketing email",
                "Create customer journey",
                "Create segment",
                "Publish campaign",
                "Record event registration",
                "Score lead",
                "Manage consent",
            ],
            integration_points=[
                "Dynamics 365 Sales",
                "Dynamics 365 Customer Insights",
                "Dynamics 365 Customer Service",
                "Power Platform",
                "Microsoft Teams",
                "Dataverse",
            ],
            best_practices=[
                "Define consent and data-protection requirements before any campaign goes live.",
                "Align lead-scoring rules with Sales' qualification criteria so scores "
                "translate into handoffs.",
                "Govern email templates and brand assets centrally.",
                "Test customer journeys against real segments before launch.",
            ],
        ),

        # --------------------------------------------------------------
        # Customer Insights (Customer Engagement suite)
        # --------------------------------------------------------------

        "CUSTOMER_INSIGHTS": ERPModule(
            name="Dynamics 365 Customer Insights",
            description=(
                "Customer data platform unifying customer data across sources into "
                "a single customer profile, with segments, measures, and AI-driven "
                "insights. Distinct from 'Customer Insights - Journeys' (formerly "
                "Marketing); the two are frequently deployed together."
            ),
            sub_modules=[
                "Data Unification",
                "Customer Profiles",
                "Segments",
                "Measures",
                "Predictions",
                "Connectors",
                "Exports",
            ],
            common_transactions=[
                "Configure data source",
                "Run unification",
                "Create segment",
                "Define measure",
                "Publish profile",
            ],
            integration_points=[
                "Dynamics 365 Sales",
                "Dynamics 365 Customer Service",
                "Dynamics 365 Marketing",
                "Dynamics 365 Commerce",
                "Power Platform",
                "Dataverse",
                "Azure Data Lake",
                "External CRM and ERP systems",
            ],
            best_practices=[
                "Define the unified customer key before ingesting data - "
                "post-hoc changes to unification rules invalidate published segments.",
                "Confirm data-protection and residency requirements for the regions "
                "where customer data is processed.",
                "Align segments consumed by Sales and Marketing to a single "
                "segment-naming and lifecycle convention.",
            ],
        ),
    },
)