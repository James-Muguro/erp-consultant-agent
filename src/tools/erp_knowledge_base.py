"""
ERP Knowledge Base public interface.

Keeps the existing import path used by agents while the underlying
knowledge is organized into separate ERP-specific modules.
"""

from src.tools.knowledge import (
    ERPModule,
    ERPSystem,
    ERPKnowledgeBase,
    ERPKnowledgeBaseTool,
    erp_kb,
    erp_kb_tool,
)

__all__ = [
    "ERPModule",
    "ERPSystem",
    "ERPKnowledgeBase",
    "ERPKnowledgeBaseTool",
    "erp_kb",
    "erp_kb_tool",
]