"""
Central ERP knowledge registry.

All ERP-specific knowledge is registered here and exposed through
one shared knowledge-base instance.
"""

from src.tools.knowledge.base import (
    ERPModule,
    ERPSystem,
    ERPKnowledgeBase,
    ERPKnowledgeBaseTool,
)

from src.tools.knowledge.sap import SAP
from src.tools.knowledge.dynamics_365 import DYNAMICS_365
from src.tools.knowledge.oracle import ORACLE
from src.tools.knowledge.netsuite import NETSUITE
from src.tools.knowledge.odoo import ODOO
from src.tools.knowledge.infor import INFOR
from src.tools.knowledge.workday import WORKDAY


def create_erp_knowledge_base() -> ERPKnowledgeBase:
    """Create the shared ERP knowledge base and register all ERP systems."""

    kb = ERPKnowledgeBase()

    kb.register_erp(SAP)
    kb.register_erp(DYNAMICS_365)
    kb.register_erp(ORACLE)
    kb.register_erp(NETSUITE)
    kb.register_erp(ODOO)
    kb.register_erp(INFOR)
    kb.register_erp(WORKDAY)

    return kb


erp_kb = create_erp_knowledge_base()
erp_kb_tool = ERPKnowledgeBaseTool(erp_kb)


__all__ = [
    "ERPModule",
    "ERPSystem",
    "ERPKnowledgeBase",
    "ERPKnowledgeBaseTool",
    "erp_kb",
    "erp_kb_tool",
]