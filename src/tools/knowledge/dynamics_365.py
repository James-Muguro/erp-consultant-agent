"""
Microsoft Dynamics 365 ERP knowledge base.

Covers major Dynamics 365 business applications and functional areas
used in ERP consulting, implementation, integration, testing, and
business process design.

The knowledge is intentionally organized around functional domains
rather than treating Dynamics 365 as a single monolithic application.
"""

from src.tools.knowledge.base import ERPModule, ERPSystem


DYNAMICS_365 = ERPSystem(
    name="Microsoft Dynamics 365",
    vendor="Microsoft",
    aliases=[
        "Dynamics 365",
        "D365",
        "Microsoft D365",
        "MS Dynamics 365",
        "Dynamics",
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
                "management, budgeting, fixed assets, tax, and financial reporting."
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
            ],
        ),

        # --------------------------------------------------------------
        # Supply Chain Management
        # --------------------------------------------------------------

        "SCM": ERPModule(
            name="Dynamics 365 Supply Chain Management",
            description=(
                "Manages procurement, inventory, warehousing, product information, "
                "planning, production, quality, and supply chain operations."
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
            ],
            integration_points=[
                "Dynamics 365 Finance",
                "Dynamics 365 Commerce",
                "Dynamics 365 Sales",
                "Project Operations",
                "Warehouse and transportation systems",
                "External suppliers",
                "Power Platform",
            ],
            best_practices=[
                "Establish product and released-product governance before transactional configuration.",
                "Define inventory dimensions according to operational and financial reporting needs.",
                "Separate procurement policy from individual purchasing transactions.",
                "Validate warehouse processes using realistic receiving, picking, packing, and shipping scenarios.",
                "Align planning parameters with actual supply and demand behaviour.",
                "Reconcile physical inventory with system inventory through controlled counting processes.",
                "Define ownership for product, vendor, warehouse, and procurement master data.",
            ],
        ),

        # --------------------------------------------------------------
        # Sales
        # --------------------------------------------------------------

        "SALES": ERPModule(
            name="Dynamics 365 Sales",
            description=(
                "Manages customer relationships, leads, opportunities, "
                "accounts, contacts, activities, quotations, and sales processes."
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
            ],
            integration_points=[
                "Dynamics 365 Finance",
                "Dynamics 365 Supply Chain Management",
                "Dynamics 365 Customer Service",
                "Dynamics 365 Customer Insights",
                "Power Platform",
                "Outlook",
                "Microsoft Teams",
            ],
            best_practices=[
                "Define the lead-to-opportunity process before configuring sales stages.",
                "Standardize opportunity qualification criteria.",
                "Control product and price-list governance.",
                "Define ownership and security boundaries for customer records.",
                "Avoid unnecessary customization where standard sales processes meet the requirement.",
                "Define integration ownership between CRM and ERP order processing.",
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
            ],
            integration_points=[
                "Dynamics 365 Sales",
                "Dynamics 365 Finance",
                "Dynamics 365 Field Service",
                "Customer Insights",
                "Power Platform",
                "Microsoft Teams",
                "Email channels",
            ],
            best_practices=[
                "Define case categories and resolution codes consistently.",
                "Design queues around operational ownership rather than organizational complexity.",
                "Define SLA rules against measurable service commitments.",
                "Govern knowledge articles through ownership and review processes.",
                "Separate customer-facing processes from internal escalation processes.",
            ],
        ),

        # --------------------------------------------------------------
        # Human Resources
        # --------------------------------------------------------------

        "HR": ERPModule(
            name="Dynamics 365 Human Resources",
            description=(
                "Manages employee information, organizational structures, "
                "personnel processes, leave, benefits, compensation, and workforce administration."
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
            ],
            integration_points=[
                "Dynamics 365 Finance",
                "Payroll systems",
                "Microsoft Entra ID",
                "Microsoft Teams",
                "Power Platform",
            ],
            best_practices=[
                "Protect employee data through role-based access.",
                "Define organizational hierarchies before configuring HR workflows.",
                "Separate sensitive HR responsibilities through security roles.",
                "Define effective-dated processes for organizational and employee changes.",
                "Validate integrations between HR, payroll, identity, and finance systems.",
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
            ],
            integration_points=[
                "Dynamics 365 Finance",
                "Dynamics 365 Sales",
                "Human Resources",
                "Microsoft Teams",
                "Power Platform",
            ],
            best_practices=[
                "Define project financial dimensions before project transactions begin.",
                "Separate project planning from project accounting responsibilities.",
                "Define resource roles and capacity rules clearly.",
                "Validate time and expense approval workflows.",
                "Reconcile project costs, revenue, billing, and general ledger postings.",
            ],
        ),

        # --------------------------------------------------------------
        # Commerce
        # --------------------------------------------------------------

        "COMMERCE": ERPModule(
            name="Dynamics 365 Commerce",
            description=(
                "Supports retail and commerce operations across stores, "
                "e-commerce, point of sale, merchandising, pricing, and customer engagement."
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
            ],
            common_transactions=[
                "Point-of-sale transaction",
                "Customer order",
                "Product receipt",
                "Return transaction",
                "Price adjustment",
                "Inventory movement",
                "Retail payment",
            ],
            integration_points=[
                "Dynamics 365 Finance",
                "Dynamics 365 Supply Chain Management",
                "Dynamics 365 Customer Insights",
                "Payment providers",
                "E-commerce platforms",
                "External marketplaces",
            ],
            best_practices=[
                "Define product, channel, catalog, and assortment structures before deployment.",
                "Test pricing and promotion rules across all relevant sales channels.",
                "Validate payment and settlement reconciliation.",
                "Test offline point-of-sale scenarios where applicable.",
                "Reconcile retail transactions to financial and inventory postings.",
            ],
        ),

        # --------------------------------------------------------------
        # Business Central
        # --------------------------------------------------------------

        "BUSINESS_CENTRAL": ERPModule(
            name="Microsoft Dynamics 365 Business Central",
            description=(
                "Cloud ERP for small and mid-sized organizations covering finance, "
                "sales, purchasing, inventory, projects, fixed assets, and operational accounting."
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
            ],
            common_transactions=[
                "Create work order",
                "Assign technician",
                "Schedule work order",
                "Record service activity",
                "Record parts consumption",
                "Complete work order",
                "Capture inspection result",
            ],
            integration_points=[
                "Dynamics 365 Customer Service",
                "Dynamics 365 Sales",
                "Dynamics 365 Finance",
                "Dynamics 365 Supply Chain Management",
                "IoT services",
                "Power Platform",
            ],
            best_practices=[
                "Define work-order lifecycle states clearly.",
                "Align scheduling rules with actual resource skills and availability.",
                "Maintain accurate customer asset records.",
                "Validate mobile workflows under realistic field conditions.",
                "Reconcile parts consumption and service activity with financial transactions.",
            ],
        ),
    },
)