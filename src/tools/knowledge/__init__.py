"""
ERP Knowledge Base Initialization

Loads and registers all supported ERP systems into a central knowledge base.
"""

from typing import Any, Dict

from src.tools.knowledge.base import (
    ERPKnowledgeBase,
    ERPModule,
    ERPSystem,
    ERPKnowledgeBaseTool,
)
from src.tools.knowledge.sap import SAP
from src.tools.knowledge.dynamics_365 import DYNAMICS_365
from src.tools.knowledge.oracle import ORACLE
from src.tools.knowledge.netsuite import NETSUITE
from src.tools.knowledge.odoo import ODOO
from src.tools.knowledge.infor import INFOR
from src.tools.knowledge.workday import WORKDAY


def _convert_to_erp_system(obj: Any) -> ERPSystem:
    """Normalize ERP-specific knowledge exports to ERPSystem.

    Module keys are normalized to uppercase here because
    ERPKnowledgeBase.get_module_info() uppercases the module code it's
    given before looking it up. SAP and Dynamics 365 are authored as
    ERPSystem instances directly with uppercase keys already, so they
    pass through the first branch untouched. Oracle, NetSuite, Odoo,
    Infor, and Workday are authored with lowercase/snake_case keys
    ("financials", "order_management") in their source dicts/classes,
    so without this normalization those five ERPs' module lookups
    silently never matched anything.
    """

    if isinstance(obj, ERPSystem):
        return obj

    if isinstance(obj, dict):
        name = obj.get("name", "Unknown")
        vendor = obj.get("vendor", name)
        aliases = obj.get("aliases", [name])

        raw_modules = obj.get("modules", {})
        modules: Dict[str, ERPModule] = {}

        for key, mod in raw_modules.items():
            normalized_key = key.upper()

            if isinstance(mod, ERPModule):
                modules[normalized_key] = mod

            elif isinstance(mod, dict):
                transactions = mod.get(
                    "common_transactions",
                    mod.get("common_processes", []),
                )

                modules[normalized_key] = ERPModule(
                    name=mod.get("name", key),
                    description=mod.get("description", ""),
                    sub_modules=mod.get("sub_modules", []),
                    common_transactions=transactions,
                    integration_points=mod.get("integration_points", []),
                    best_practices=mod.get("best_practices", []),
                )

        return ERPSystem(
            name=name,
            vendor=vendor,
            aliases=aliases,
            modules=modules,
        )

    erp_name = getattr(obj, "ERP_NAME", None)

    if erp_name:
        raw_modules = getattr(obj, "modules", {})
        modules: Dict[str, ERPModule] = {}

        for key, mod in raw_modules.items():
            if isinstance(mod, dict):
                modules[key.upper()] = ERPModule(
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

    raise TypeError(
        f"Cannot convert {type(obj).__name__} to ERPSystem"
    )


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


# Central populated knowledge base.
erp_kb = create_erp_knowledge_base()

# Agent-facing tool using the same knowledge base instance.
erp_kb_tool = ERPKnowledgeBaseTool(erp_kb)