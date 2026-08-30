"""
ERP Knowledge Base Initialization

Loads and registers all supported ERP systems into a central knowledge base.
"""

from typing import Any, Dict, List, Optional

from src.tools.knowledge.base import ERPKnowledgeBase, ERPSystem, ERPModule
from src.tools.knowledge.sap import SAP
from src.tools.knowledge.dynamics_365 import DYNAMICS_365
from src.tools.knowledge.oracle import ORACLE
from src.tools.knowledge.netsuite import NETSUITE
from src.tools.knowledge.odoo import ODOO
from src.tools.knowledge.infor import INFOR
from src.tools.knowledge.workday import WORKDAY


def _convert_to_erp_system(obj: Any) -> ERPSystem:
    """Normalize various knowledge module exports to an ERPSystem instance."""
    
    # Already an ERPSystem — pass through
    if isinstance(obj, ERPSystem):
        return obj
    
    # Dict-based exports (ORACLE, INFOR, WORKDAY)
    if isinstance(obj, dict):
        name = obj.get("name", "Unknown")
        vendor = obj.get("vendor", name)
        aliases = obj.get("aliases", [name])
        
        raw_modules = obj.get("modules", {})
        modules: Dict[str, ERPModule] = {}
        for key, mod in raw_modules.items():
            if isinstance(mod, ERPModule):
                modules[key] = mod
            elif isinstance(mod, dict):
                # ORACLE uses 'common_processes' instead of 'common_transactions'
                transactions = mod.get(
                    "common_transactions",
                    mod.get("common_processes", [])
                )
                modules[key] = ERPModule(
                    name=mod.get("name", key),
                    description=mod.get("description", ""),
                    sub_modules=mod.get("sub_modules", []),
                    common_transactions=transactions,
                    integration_points=mod.get("integration_points", []),
                    best_practices=mod.get("best_practices", []),
                )
            else:
                continue
        return ERPSystem(name=name, vendor=vendor, aliases=aliases, modules=modules)
    
    # Custom knowledge-base classes (NetSuiteKnowledgeBase, OdooKnowledgeBase)
    erp_name = getattr(obj, "ERP_NAME", None)
    if erp_name:
        raw_modules = getattr(obj, "modules", {})
        modules: Dict[str, ERPModule] = {}
        for key, mod in raw_modules.items():
            if isinstance(mod, dict):
                modules[key] = ERPModule(
                    name=mod.get("name", key),
                    description=mod.get("description", ""),
                    sub_modules=mod.get("sub_modules", []),
                    common_transactions=mod.get("common_transactions", []),
                    integration_points=mod.get("integration_points", []),
                    best_practices=mod.get("best_practices", []),
                )
        return ERPSystem(
            name=erp_name,
            vendor=erp_name,
            aliases=[erp_name],
            modules=modules,
        )
    
    raise TypeError(f"Cannot convert {type(obj).__name__} to ERPSystem")


def create_erp_knowledge_base() -> ERPKnowledgeBase:
    """Create and populate the central ERP knowledge base."""
    kb = ERPKnowledgeBase()
    kb.register_erp(_convert_to_erp_system(SAP))
    kb.register_erp(_convert_to_erp_system(DYNAMICS_365))
    kb.register_erp(_convert_to_erp_system(ORACLE))
    kb.register_erp(_convert_to_erp_system(NETSUITE))
    kb.register_erp(_convert_to_erp_system(ODOO))
    kb.register_erp(_convert_to_erp_system(INFOR))
    kb.register_erp(_convert_to_erp_system(WORKDAY))
    return kb


# Central knowledge base instance — must exist before ERPKnowledgeBaseTool
erp_kb = create_erp_knowledge_base()


class ERPKnowledgeBaseTool:
    """Tool wrapper for the ERP Knowledge Base."""

    def __init__(self):
        self.kb = erp_kb

    def search_knowledge(self, query: str, erp_system: str = None) -> List[Dict[str, Any]]:
        return self.kb.search_knowledge(query, erp_system)

    def get_module_info(self, module_code: str, erp_system: str = None) -> Optional[Dict[str, Any]]:
        return self.kb.get_module_info(module_code, erp_system)

    def get_standard_process(self, process_name: str, erp_system: str = None) -> Optional[Dict[str, Any]]:
        return self.kb.get_standard_process(process_name, erp_system)

    def get_best_practices(self, module_code: str, erp_system: str = None) -> List[str]:
        return self.kb.get_best_practices(module_code, erp_system)

    def get_integration_points(self, module_code: str, erp_system: str = None) -> List[str]:
        return self.kb.get_integration_points(module_code, erp_system)

    def get_all_systems(self) -> List[str]:
        return self.kb.get_all_systems()


# Shared ERP Knowledge Base tool instance
erp_kb_tool = ERPKnowledgeBaseTool()