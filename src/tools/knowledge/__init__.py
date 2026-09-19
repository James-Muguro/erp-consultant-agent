"""
ERP Knowledge Base Initialization.

Loads and registers every supported ERP system into the shared
knowledge-base singleton. Runs once, at import time.

Architectural note: singleton identity
--------------------------------------
src/tools/knowledge/base.py defines a module-level singleton:

    erp_kb = ERPKnowledgeBase()
    erp_kb_tool = ERPKnowledgeBaseTool(erp_kb)

That object is a legitimate import target. Before this revision, this
module constructed a *second*, separate ERPKnowledgeBase and assigned
it to a local `erp_kb` name. The result was two distinct KB objects in
the same process: one populated with every registered ERP, the other
empty. Consumers going through the package re-export chain
(src.tools.erp_knowledge_base -> src.tools.knowledge) got the populated
one; any consumer importing from base.py directly got the empty one.
Nothing errored; lookups simply returned None with no signal.

The fix: this module registers into the base module's singleton rather
than constructing a parallel one. After this module runs, every import
path that resolves to `erp_kb` — src.tools.knowledge,
src.tools.erp_knowledge_base, src.tools.knowledge.base — yields the same
populated object.

Normalization
-------------
Module codes are canonicalized by ERPKnowledgeBase.register_erp, not by
this loader. Previously the loader applied its own `str(key).upper()`
before handing the ERPSystem to register_erp; that duplicates logic
and, more importantly, produced the wrong canonical form for multi-word
codes ("customer service" -> "CUSTOMER SERVICE", not the correct
"CUSTOMER_SERVICE"). The loader now passes module keys through
unchanged and lets register_erp apply the single source of truth:
`_normalize_module_code` (uppercase; spaces and dashes to underscores).

Fields populated during conversion
----------------------------------
  * name, vendor, aliases, modules   - from explicit keys, if present.
  * common_transactions               - from `common_transactions` or
                                        the `common_processes` fallback
                                        (some sources use one name,
                                        some the other).
  * common_tasks                      - from `common_tasks` if the
                                        source declares it. Sources that
                                        haven't been updated yet leave
                                        this empty; no error.
  * metadata                          - every unrecognized top-level key
                                        on a dict source, plus a
                                        `METADATA` class attribute on a
                                        class source. This is how
                                        Oracle's `core_concepts`,
                                        `testing`, `consulting_focus`,
                                        etc. become reachable through
                                        erp_kb.get_erp_metadata(...).
                                        Without this, those keys were
                                        silently dropped.

Logging
-------
Logs from this module use the shared structlog logger
(src.utils.logger.get_logger), not stdlib logging, so lines emitted here
carry the same context fields (request_id, user_id, session_id,
agent_name) and render in the same format as the rest of the codebase.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from src.tools.knowledge.base import (
    ERPKnowledgeBase,
    ERPModule,
    ERPSystem,
    ERPKnowledgeBaseTool,
    erp_kb as _base_singleton,
)
from src.tools.knowledge.sap import SAP
from src.tools.knowledge.dynamics_365 import DYNAMICS_365
from src.tools.knowledge.oracle import ORACLE
from src.tools.knowledge.netsuite import NETSUITE
from src.tools.knowledge.odoo import ODOO
from src.tools.knowledge.infor import INFOR
from src.tools.knowledge.workday import WORKDAY
from src.utils.logger import get_logger

logger = get_logger(__name__)


# Every ERP source module this loader knows about, paired with a
# human-readable label used in logs. Kept as data so the registration
# loop is uniform and adding a new ERP is one tuple entry, not a new
# block of code.
_ERP_SOURCES: Tuple[Tuple[str, Any], ...] = (
    ("SAP", SAP),
    ("Dynamics 365", DYNAMICS_365),
    ("Oracle", ORACLE),
    ("NetSuite", NETSUITE),
    ("Odoo", ODOO),
    ("Infor", INFOR),
    ("Workday", WORKDAY),
)


# Top-level keys that _convert_dict_source consumes explicitly. Every
# other top-level key on a dict source is preserved in metadata so that
# source-specific content (core concepts, testing hints, implementation
# lifecycle notes, ...) remains reachable via get_erp_metadata.
_DICT_SOURCE_RECOGNIZED_KEYS = frozenset({
    "name", "vendor", "aliases", "modules",
})


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------
def _convert_to_erp_system(obj: Any) -> ERPSystem:
    """Normalize an ERP-specific knowledge export into an ERPSystem.

    Three source shapes are supported:

      * An ERPSystem instance: passed through unchanged.
      * A dict with top-level keys name/vendor/aliases/modules:
        converted field by field; any additional top-level keys are
        preserved in the returned ERPSystem's metadata dict.
      * A class or module with an ERP_NAME attribute and a `modules`
        mapping: converted to an ERPSystem; a `METADATA` class
        attribute (if present) is carried into metadata.

    Module keys are passed through unchanged. ERPKnowledgeBase.
    register_erp canonicalizes them (uppercase; spaces and dashes to
    underscores), which is the single source of truth for module-code
    normalization.

    Raises TypeError for input matching none of the supported shapes,
    with a message naming the source type so the failure is diagnosable
    from the log alone.
    """
    if isinstance(obj, ERPSystem):
        return obj

    if isinstance(obj, dict):
        return _convert_dict_source(obj)

    erp_name = getattr(obj, "ERP_NAME", None)
    if erp_name:
        return _convert_class_source(obj, erp_name)

    raise TypeError(
        f"Cannot convert {type(obj).__name__} to ERPSystem: it is neither "
        "an ERPSystem instance, a dict with an ERP shape, nor a class with "
        "an ERP_NAME attribute."
    )


def _build_module(
    mod: Any,
    key: Any,
    source_name: str,
) -> Optional[ERPModule]:
    """Build an ERPModule from a module dict, or return None if the
    entry is malformed (caller logs the warning so it names the ERP).

    Shared by both conversion branches. Reads:
      * name, description, sub_modules, integration_points, best_practices
      * common_transactions (preferred) or common_processes (fallback)
      * common_tasks
    """
    if isinstance(mod, ERPModule):
        return mod

    if not isinstance(mod, dict):
        return None

    # Sources disagree on whether the action list lives under
    # 'common_transactions' (SAP-style, T-codes) or 'common_processes'
    # (Oracle-style, process families). Prefer common_transactions when
    # both are present.
    transactions = mod.get(
        "common_transactions",
        mod.get("common_processes", []),
    )

    return ERPModule(
        name=mod.get("name", str(key)),
        description=mod.get("description", ""),
        sub_modules=mod.get("sub_modules", []) or [],
        common_transactions=transactions or [],
        common_tasks=mod.get("common_tasks", []) or [],
        integration_points=mod.get("integration_points", []) or [],
        best_practices=mod.get("best_practices", []) or [],
    )


def _convert_dict_source(obj: Dict[str, Any]) -> ERPSystem:
    name = obj.get("name", "Unknown")
    vendor = obj.get("vendor", name)
    aliases = obj.get("aliases", [name])

    raw_modules = obj.get("modules", {})
    if not isinstance(raw_modules, dict):
        raise TypeError(
            f"ERP dict for {name!r} has non-dict 'modules': "
            f"{type(raw_modules).__name__}"
        )

    modules: Dict[str, ERPModule] = {}
    for key, mod in raw_modules.items():
        module = _build_module(mod, key, source_name=name)
        if module is None:
            logger.warning(
                "Skipping malformed module entry in ERP source %r: "
                "module code %r has unsupported value of type %s",
                name, key, type(mod).__name__,
            )
            continue
        modules[key] = module

    # Preserve any top-level key we don't consume explicitly. This is
    # how Oracle's core_concepts / testing / consulting_focus and
    # similar source-specific content stays reachable through
    # erp_kb.get_erp_metadata(erp_name, key).
    metadata = {
        k: v for k, v in obj.items()
        if k not in _DICT_SOURCE_RECOGNIZED_KEYS
    }

    return ERPSystem(
        name=name,
        vendor=vendor,
        aliases=aliases or [name],
        modules=modules,
        metadata=metadata,
    )


def _convert_class_source(obj: Any, erp_name: str) -> ERPSystem:
    raw_modules = getattr(obj, "modules", None)

    # Defensive: a class attribute named `modules` is expected to be a
    # mapping. If a source uses a method or property instead, iterating
    # it would raise deep inside the conversion with a stack trace that
    # doesn't name the ERP. Fail with a specific message here instead.
    if not isinstance(raw_modules, dict):
        raise TypeError(
            f"ERP class for {erp_name!r} exposes 'modules' as "
            f"{type(raw_modules).__name__}, expected dict"
        )

    modules: Dict[str, ERPModule] = {}
    for key, mod in raw_modules.items():
        module = _build_module(mod, key, source_name=erp_name)
        if module is None:
            logger.warning(
                "Skipping malformed module entry in ERP source %r: "
                "module code %r has unsupported value of type %s",
                erp_name, key, type(mod).__name__,
            )
            continue
        modules[key] = module

    # Class sources can declare a METADATA attribute for the same
    # purpose as a dict source's extra top-level keys.
    metadata = getattr(obj, "METADATA", None)
    if not isinstance(metadata, dict):
        metadata = {}

    return ERPSystem(
        name=str(erp_name),
        vendor=str(erp_name),
        aliases=[str(erp_name)],
        modules=modules,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _validate_erp_system(erp: ERPSystem, source_label: str) -> bool:
    """Log warnings if a converted ERPSystem looks unusable. Returns
    True if the ERP should be registered, False if it looks broken
    enough that registering it would be worse than skipping it.

    A silent miss here is the failure mode that costs an hour of
    production debugging: an ERP is registered but unreachable under
    any name a caller might pass, and every module lookup for it
    returns None with no signal. A warning at registration time turns
    that into a visible problem.
    """
    ok = True

    if not erp.name or erp.name == "Unknown":
        logger.warning(
            "ERP source %r produced an ERPSystem with a missing/placeholder "
            "name; it will not be reachable via get_erp() under any real "
            "name. Skipping registration.", source_label,
        )
        return False

    if not erp.modules:
        logger.warning(
            "ERP system %r (%s) has no modules; module lookups for it will "
            "return None. Registering anyway.", erp.name, source_label,
        )
        # A no-module ERP is unusual but not fatal; keep it registered so
        # `list_erps()` reflects the intent and a later fix is visible.
        ok = True

    if not erp.aliases:
        logger.warning(
            "ERP system %r (%s) has no aliases; only the exact name %r "
            "will resolve via get_erp().", erp.name, source_label, erp.name,
        )

    return ok


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def create_erp_knowledge_base(
    target: Optional[ERPKnowledgeBase] = None,
) -> ERPKnowledgeBase:
    """Register every supported ERP system into `target`.

    If `target` is None, a fresh ERPKnowledgeBase is created and
    returned. When called with an explicit target — as this module does
    at import time with the base module's singleton — the ERPs are
    registered into that object, so the process ends up with exactly
    one canonical populated KB.

    Idempotency: calling this function twice against the same target
    will register each ERP twice. The base module's register_erp
    replaces rather than duplicates in that case, so the result is
    still correct, but this is intended to be called exactly once.
    """
    kb = target if target is not None else ERPKnowledgeBase()

    registered = 0
    skipped = 0

    for source_label, source_obj in _ERP_SOURCES:
        try:
            erp = _convert_to_erp_system(source_obj)
        except Exception as e:  # noqa: BLE001
            # One malformed ERP source must not prevent the app from
            # starting. Log and skip; the KB remains usable for the
            # others.
            logger.error(
                "Failed to convert ERP source %r to ERPSystem; skipping: %s",
                source_label, e,
            )
            skipped += 1
            continue

        if not _validate_erp_system(erp, source_label):
            skipped += 1
            continue

        try:
            kb.register_erp(erp)
            registered += 1
        except Exception as e:  # noqa: BLE001
            logger.error(
                "Failed to register ERP %r (%s); skipping: %s",
                erp.name, source_label, e,
            )
            skipped += 1

    logger.debug(
        "ERP registration loop complete: %d registered, %d skipped",
        registered, skipped,
    )

    return kb


# ---------------------------------------------------------------------------
# Module-level initialization
# ---------------------------------------------------------------------------
# Populate the base module's singleton in place rather than constructing
# a parallel instance. Any code that imported base.erp_kb earlier holds
# a reference to the same object and now sees it populated.
create_erp_knowledge_base(target=_base_singleton)


# Local names alias the same object as base.erp_kb, so every import path
# (this package, src.tools.erp_knowledge_base, src.tools.knowledge.base)
# yields the same populated KB.
erp_kb = _base_singleton
erp_kb_tool = ERPKnowledgeBaseTool(erp_kb)


# ---------------------------------------------------------------------------
# Startup summary
# ---------------------------------------------------------------------------
def _log_kb_summary() -> None:
    """One INFO line summarizing what was registered. Answers the
    "is the KB actually populated?" question at boot, instead of via an
    agent silently running with no KB context and a downstream quality
    surprise.

    Also reports which ERPs carry metadata, so it's visible at boot
    whether the source files' extra content (core_concepts, testing,
    etc.) actually reached the KB - a common silent-loss mode if a
    source is later refactored without preserving the extra keys."""
    try:
        if hasattr(erp_kb, "list_erps"):
            erps = list(erp_kb.list_erps() or [])
        else:
            erps = [getattr(e, "name", str(e))
                    for e in getattr(erp_kb, "_erps", {}).values()]

        if hasattr(erp_kb, "list_module_codes"):
            module_codes = set(erp_kb.list_module_codes())
        else:
            module_codes = set()
            for erp in getattr(erp_kb, "_erps", {}).values():
                module_codes.update(getattr(erp, "modules", {}).keys())

        if not erps:
            logger.warning(
                "ERP knowledge base is empty after initialization; every "
                "get_module_info() call will return None. Check the ERP "
                "source modules in src/tools/knowledge/."
            )
            return

        # Count ERPs with non-empty metadata, for a one-line diagnostic.
        erps_with_metadata: list[str] = []
        internal_erps = getattr(erp_kb, "_erps", {})
        for erp in internal_erps.values() if internal_erps else []:
            md = getattr(erp, "metadata", None)
            if isinstance(md, dict) and md:
                erps_with_metadata.append(getattr(erp, "name", str(erp)))

        logger.info(
            "ERP knowledge base initialized: %d ERP system(s), "
            "%d unique module code(s), %d ERP(s) with metadata",
            len(erps), len(module_codes), len(erps_with_metadata),
        )
        logger.debug("Registered ERP systems: %s", ", ".join(erps))
        if erps_with_metadata:
            logger.debug(
                "ERPs with metadata: %s", ", ".join(erps_with_metadata),
            )
    except Exception as e:  # noqa: BLE001 - diagnostic must not break import
        logger.debug("Could not summarize ERP knowledge base: %s", e)


_log_kb_summary()