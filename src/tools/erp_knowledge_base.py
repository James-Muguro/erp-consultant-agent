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
            # Additional modules (MM, SD, PP, HR) as in your previous code...
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
    
    def get_best_practices(self, module_code: str) -> List[str]:
        """Get best practices for a module"""
        module = self.sap_modules.get(module_code.upper())
        return module.best_practices if module else []
    
    def search_knowledge(self, query: str) -> List[Dict[str, Any]]:
        """Search knowledge base for relevant information"""
        results = []
        query_lower = query.lower()
        
        # Search modules
        for code, module in self.sap_modules.items():
            if query_lower in module.name.lower() or query_lower in module.description.lower():
                results.append({
                    'type': 'module',
                    'code': code,
                    'name': module.name,
                    'description': module.description
                })
        
        return results


class ERPKnowledgeBaseTool:
    """
    Tool wrapper for the ERP Knowledge Base.
    Provides a simplified interface for agents to query the KB.
    """

    def __init__(self, kb: ERPKnowledgeBase):
        self.kb = kb

    def query_module(self, module_code: str):
        return self.kb.get_module_info(module_code)

    def query_transactions(self, module_code: str):
        return self.kb.get_transactions_by_module(module_code)

    def query_best_practices(self, module_code: str):
        return self.kb.get_best_practices(module_code)

    def search(self, query: str):
        return self.kb.search_knowledge(query)


# Global knowledge base instance
erp_kb = ERPKnowledgeBase()

# Optional: pre-built tool instance for agents
erp_kb_tool = ERPKnowledgeBaseTool(erp_kb)
