"""
ERP Knowledge Base public interface.

Keeps the existing import path used by agents while the underlying
knowledge is organized into separate ERP-specific modules.

This module is the boundary agents import from
(`from src.tools.erp_knowledge_base import erp_kb`). The implementation
lives in src/tools/knowledge/, one ERP per module (sap.py,
microsoft_dynamics.py, oracle.py, ...), and each of those is responsible
for calling erp_kb.register_erp(...) at import time.

Diagnostic on import
--------------------
The erp_kb singleton is empty by default - it only knows about ERP
systems that have registered themselves. If the knowledge package's
__init__ fails to import the per-ERP modules (a new module added without
being wired in, an import error swallowed somewhere, a packaging issue
that leaves one file out of the deploy), every module lookup returns
None and every agent proceeds with empty context - the failure is silent
downstream. To make that visible, this module inspects the KB once on
first import and logs a warning if it is empty. The check is cheap
(a dict length read) and idempotent.
"""
from __future__ import annotations

import logging

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


_logger = logging.getLogger(__name__)


def _warn_if_kb_empty() -> None:
    """Log a one-shot WARNING if no ERP systems are registered. Uses the
    diagnostic helpers added to ERPKnowledgeBase in the base module
    review (list_erps / list_module_codes) if available, and falls back
    to attribute probing if not - so this import-time check remains
    compatible with a base module that predates those helpers."""
    try:
        if hasattr(erp_kb, "list_erps"):
            registered = list(erp_kb.list_erps() or [])
        else:
            # Legacy base module without the helper: inspect the private
            # registry the class has always had.
            registered = list(getattr(erp_kb, "_erps", {}).values())
            registered = [getattr(e, "name", str(e)) for e in registered]
    except Exception as e:  # noqa: BLE001 - diagnostic must never break import
        _logger.debug(
            "Could not inspect ERP knowledge base on import: %s", e,
        )
        return

    if not registered:
        _logger.warning(
            "ERP knowledge base is empty: no ERP systems are registered. "
            "Every erp_kb.get_module_info(...) call will return None, and "
            "agents will run with no KB context. Check that the ERP-specific "
            "modules in src/tools/knowledge/ (sap.py, oracle.py, ...) are "
            "imported by src/tools/knowledge/__init__.py and that each "
            "calls erp_kb.register_erp(...) at import time."
        )
    else:
        # Only log at debug to avoid noise; the base module already logs
        # each registration at INFO when it happens.
        _logger.debug(
            "ERP knowledge base has %d registered ERP system(s): %s",
            len(registered),
            ", ".join(registered),
        )


# Run the diagnostic once, on this module's first import.
_warn_if_kb_empty()