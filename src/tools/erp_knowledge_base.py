"""
ERP Knowledge Base Tool - Provides domain-specific ERP knowledge
"""
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from src.utils.logger import AgentLogger


@dataclass
class ERPModule:
    """Represents an ERP module with its components"""
    name: str
    description: str
    sub_modules: List[str]
    common_transactions: List[str]
    integration_points: List[str]
    best_practices: List[str]


class ERPKnowledgeBase:
    """Knowledge base for ERP systems, modules, and best practices"""
    
    def __init__(self):
        self.logger = AgentLogger("ERPKnowledgeBase")
        self._initialize_knowledge()
    
    def _initialize_knowledge(self):
        """Initialize ERP knowledge base"""
        
        # SAP S/4HANA Modules
        self.sap_modules = {
            'FI': ERPModule(
                name='Financial Accounting (FI)',
                description='Manages financial accounting and reporting',
                sub_modules=[
                    'General Ledger (FI-GL)',
                    'Accounts Payable (FI-AP)',
                    'Accounts Receivable (FI-AR)',
                    'Asset Accounting (FI-AA)',
                    'Bank Accounting (FI-BL)'
                ],
                common_transactions=[
                    'FB50 - G/L Account Posting',
                    'FB60 - Vendor Invoice Entry',
                    'FB70 - Customer Invoice Entry',
                    'F-02 - General Posting',
                    'FS00 - G/L Account Master',
                    'FK01 - Vendor Master Creation'
                ],
                integration_points=[
                    'CO - Controlling',
                    'MM - Materials Management',
                    'SD - Sales and Distribution',
                    'AA - Asset Accounting'
                ],
                best_practices=[
                    'Use standard chart of accounts where possible',
                    'Implement proper document types for traceability',
                    'Configure automatic payment programs',
                    'Set up proper authorization controls',
                    'Use parking documents for approval workflows'
                ]
            ),
            'CO': ERPModule(
                name='Controlling (CO)',
                description='Manages cost accounting and internal reporting',
                sub_modules=[
                    'Cost Center Accounting (CO-CCA)',
                    'Internal Orders (CO-IO)',
                    'Product Costing (CO-PC)',
                    'Profitability Analysis (CO-PA)',
                    'Profit Center Accounting (CO-PCA)'
                ],
                common_transactions=[
                    'KS01 - Create Cost Center',
                    'KO01 - Create Internal Order',
                    'KB11N - Cost Center Posting',
                    'KSH1 - Display Cost Center Reports',
                    'KE5Z - Profitability Analysis'
                ],
                integration_points=[
                    'FI - Financial Accounting',
                    'PP - Production Planning',
                    'SD - Sales and Distribution',
                    'MM - Materials Management'
                ],
                best_practices=[
                    'Design hierarchical cost center structures',
                    'Use cost elements aligned with G/L accounts',
                    'Implement activity-based costing where applicable',
                    'Set up periodic allocations and distributions',
                    'Configure profitability segments properly'
                ]
            ),
            'MM': ERPModule(
                name='Materials Management (MM)',
                description='Manages procurement and inventory',
                sub_modules=[
                    'Purchasing (MM-PUR)',
                    'Inventory Management (MM-IM)',
                    'Warehouse Management (MM-WM)',
                    'Invoice Verification (MM-IV)',
                    'Material Master (MM-MAT)'
                ],
                common_transactions=[
                    'ME21N - Create Purchase Order',
                    'MIGO - Goods Receipt',
                    'MIRO - Invoice Verification',
                    'MM01 - Create Material Master',
                    'ME51N - Create Purchase Requisition',
                    'MB51 - Material Document List'
                ],
                integration_points=[
                    'FI - Financial Accounting',
                    'SD - Sales and Distribution',
                    'PP - Production Planning',
                    'QM - Quality Management'
                ],
                best_practices=[
                    'Standardize material master data structure',
                    'Implement three-way match for invoice verification',
                    'Use material groups for classification',
                    'Configure proper valuation procedures',
                    'Set up automatic goods receipt for services'
                ]
            ),
            'SD': ERPModule(
                name='Sales and Distribution (SD)',
                description='Manages sales processes and customer relationships',
                sub_modules=[
                    'Sales (SD-SLS)',
                    'Shipping (SD-SHP)',
                    'Billing (SD-BIL)',
                    'Pricing (SD-PRI)',
                    'Credit Management (SD-CRM)'
                ],
                common_transactions=[
                    'VA01 - Create Sales Order',
                    'VL01N - Create Outbound Delivery',
                    'VF01 - Create Billing Document',
                    'VD01 - Create Customer Master',
                    'VA05 - List of Sales Orders',
                    'VKM1 - Create Customer Material Info'
                ],
                integration_points=[
                    'FI - Financial Accounting',
                    'MM - Materials Management',
                    'PP - Production Planning',
                    'LE - Logistics Execution'
                ],
                best_practices=[
                    'Design flexible pricing procedures',
                    'Use sales document types for different processes',
                    'Configure automatic credit checks',
                    'Implement proper delivery scheduling',
                    'Set up output determination for documents'
                ]
            ),
            'PP': ERPModule(
                name='Production Planning (PP)',
                description='Manages manufacturing and production processes',
                sub_modules=[
                    'Production Planning (PP-MP)',
                    'Production Execution (PP-SFC)',
                    'Bills of Material (PP-BOM)',
                    'Work Centers (PP-WC)',
                    'Product Costing (PP-PC)'
                ],
                common_transactions=[
                    'MD01 - Run MRP',
                    'CO01 - Create Production Order',
                    'CO02 - Change Production Order',
                    'CS01 - Create BOM',
                    'CR01 - Create Work Center',
                    'COOIS - Production Order Information System'
                ],
                integration_points=[
                    'MM - Materials Management',
                    'QM - Quality Management',
                    'CO - Controlling',
                    'PM - Plant Maintenance'
                ],
                best_practices=[
                    'Maintain accurate BOMs and routings',
                    'Use production versions for flexibility',
                    'Implement realistic lead times',
                    'Configure proper goods issue backflushing',
                    'Set up capacity planning correctly'
                ]
            ),
            'HR': ERPModule(
                name='Human Resources (HR)',
                description='Manages human capital and payroll',
                sub_modules=[
                    'Personnel Administration (PA)',
                    'Organizational Management (OM)',
                    'Time Management (TM)',
                    'Payroll (PY)',
                    'Talent Management (TM)'
                ],
                common_transactions=[
                    'PA30 - Maintain HR Master Data',
                    'PA40 - Personnel Actions',
                    'PT60 - Time Recording',
                    'PC00 - Payroll Run',
                    'PO13 - Maintain Org Structure'
                ],
                integration_points=[
                    'FI - Financial Accounting',
                    'CO - Controlling',
                    'SuccessFactors - Cloud HR',
                    'Time Management Systems'
                ],
                best_practices=[
                    'Design clear organizational structures',
                    'Implement proper security authorizations',
                    'Configure compliance-aligned payroll schemas',
                    'Use personnel actions for audit trails',
                    'Integrate with time management systems'
                ]
            )
        }
        
        # General ERP concepts
        self.erp_concepts = {
            'master_data': {
                'description': 'Core business data that remains consistent',
                'examples': [
                    'Customer master',
                    'Vendor master',
                    'Material master',
                    'G/L account master',
                    'Cost center master'
                ],
                'best_practices': [
                    'Centralize master data governance',
                    'Implement data quality rules',
                    'Use standardized naming conventions',
                    'Regular data cleansing activities'
                ]
            },
            'transactional_data': {
                'description': 'Business events and transactions',
                'examples': [
                    'Sales orders',
                    'Purchase orders',
                    'Goods receipts',
                    'Invoices',
                    'Journal entries'
                ],
                'best_practices': [
                    'Use document types for classification',
                    'Implement proper number ranges',
                    'Configure approval workflows',
                    'Set up archiving strategies'
                ]
            },
            'integration': {
                'description': 'Data flow between modules and systems',
                'types': [
                    'Real-time integration',
                    'Batch integration',
                    'Event-driven integration',
                    'API-based integration'
                ],
                'best_practices': [
                    'Map integration points early',
                    'Design error handling mechanisms',
                    'Implement monitoring and alerts',
                    'Document interface specifications'
                ]
            }
        }
        
        # Testing strategies
        self.testing_strategies = {
            'unit_testing': {
                'description': 'Test individual components',
                'focus': 'Configuration, master data, single transactions',
                'coverage': 'All custom code, critical configurations'
            },
            'integration_testing': {
                'description': 'Test cross-module scenarios',
                'focus': 'End-to-end processes, data flow',
                'coverage': 'All integration points, interfaces'
            },
            'uat_testing': {
                'description': 'Business user validation',
                'focus': 'Real business scenarios, usability',
                'coverage': 'All business processes, reports'
            },
            'performance_testing': {
                'description': 'System performance validation',
                'focus': 'Response times, batch jobs, concurrent users',
                'coverage': 'Critical transactions, peak loads'
            }
        }
    
    def get_module_info(self, module_code: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific ERP module"""
        self.logger.log_tool_usage(
            "get_module_info",
            {'module_code': module_code},
            "Retrieved module information"
        )
        
        module = self.sap_modules.get(module_code.upper())
        if not module:
            return None
        
        return {
            'name': module.name,
            'description': module.description,
            'sub_modules': module.sub_modules,
            'common_transactions': module.common_transactions,
            'integration_points': module.integration_points,
            'best_practices': module.best_practices
        }
    
    def get_transactions_by_module(self, module_code: str) -> List[str]:
        """Get common transactions for a module"""
        module = self.sap_modules.get(module_code.upper())
        return module.common_transactions if module else []
    
    def get_integration_points(self, module_code: str) -> List[str]:
        """Get integration points for a module"""
        module = self.sap_modules.get(module_code.upper())
        return module.integration_points if module else []
    
    def get_best_practices(self, module_code: str) -> List[str]:
        """Get best practices for a module"""
        module = self.sap_modules.get(module_code.upper())
        return module.best_practices if module else []
    
    def get_concept_info(self, concept: str) -> Optional[Dict[str, Any]]:
        """Get information about an ERP concept"""
        return self.erp_concepts.get(concept.lower())
    
    def get_testing_strategy(self, test_type: str) -> Optional[Dict[str, Any]]:
        """Get testing strategy information"""
        return self.testing_strategies.get(test_type.lower())
    
    def search_knowledge(self, query: str) -> List[Dict[str, Any]]:
        """Search knowledge base for relevant information"""
        results = []
        query_lower = query.lower()
        
        # Search modules
        for code, module in self.sap_modules.items():
            if (query_lower in module.name.lower() or 
                query_lower in module.description.lower() or
                query_lower in code.lower()):
                results.append({
                    'type': 'module',
                    'code': code,
                    'name': module.name,
                    'description': module.description
                })
        
        # Search transactions
        for code, module in self.sap_modules.items():
            for transaction in module.common_transactions:
                if query_lower in transaction.lower():
                    results.append({
                        'type': 'transaction',
                        'transaction': transaction,
                        'module': code
                    })
        
        # Search concepts
        for concept, info in self.erp_concepts.items():
            if query_lower in concept or query_lower in info['description'].lower():
                results.append({
                    'type': 'concept',
                    'concept': concept,
                    'description': info['description']
                })
        
        self.logger.log_tool_usage(
            "search_knowledge",
            {'query': query},
            f"Found {len(results)} results"
        )
        
        return results
    
    def get_all_modules(self) -> List[str]:
        """Get list of all available modules"""
        return list(self.sap_modules.keys())
    
    def get_process_flow(self, process_name: str) -> Optional[Dict[str, Any]]:
        """Get standard process flow for common ERP processes"""
        process_flows = {
            'procure_to_pay': {
                'name': 'Procure to Pay',
                'modules': ['MM', 'FI'],
                'steps': [
                    '1. Create Purchase Requisition (ME51N)',
                    '2. Convert to Purchase Order (ME21N)',
                    '3. Goods Receipt (MIGO)',
                    '4. Invoice Verification (MIRO)',
                    '5. Payment Processing (F110)'
                ],
                'integration_points': [
                    'MM -> FI: Goods Receipt posting',
                    'MM -> FI: Invoice verification posting',
                    'FI: Vendor payment'
                ]
            },
            'order_to_cash': {
                'name': 'Order to Cash',
                'modules': ['SD', 'MM', 'FI'],
                'steps': [
                    '1. Create Sales Order (VA01)',
                    '2. Create Outbound Delivery (VL01N)',
                    '3. Post Goods Issue (VL02N)',
                    '4. Create Billing Document (VF01)',
                    '5. Customer Payment (F-28)'
                ],
                'integration_points': [
                    'SD -> MM: ATP check, goods issue',
                    'SD -> FI: Billing posting',
                    'FI: Customer payment clearing'
                ]
            },
            'plan_to_produce': {
                'name': 'Plan to Produce',
                'modules': ['PP', 'MM', 'CO'],
                'steps': [
                    '1. Run MRP (MD01)',
                    '2. Convert Planned Order to Production Order (CO40)',
                    '3. Release Production Order (CO02)',
                    '4. Confirm Production (CO15)',
                    '5. Goods Receipt (MIGO)',
                    '6. Settle Production Order (KO88)'
                ],
                'integration_points': [
                    'PP -> MM: Material requirements, goods movements',
                    'PP -> CO: Production costs',
                    'CO: Cost settlement'
                ]
            }
        }
        
        return process_flows.get(process_name.lower())


# Global knowledge base instance
erp_kb = ERPKnowledgeBase()


