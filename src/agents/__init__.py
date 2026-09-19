"""
Specialized ERP Consultant Agents.

Exposes the six agent classes and their module-level singletons. The
singletons are the intended consumers for the orchestrator and API
layers; the classes exist for tests and for callers that need a
non-shared instance.

Import-time cost
----------------
Every module in this package constructs its singleton at import time,
and each singleton's __init__ calls get_llm() (which builds the shared
HybridLLMClient and its provider SDK clients) and instantiates an
AgentLogger. Importing `src.agents` therefore triggers:

  * one HybridLLMClient construction (four SDK clients: Gemini, Groq,
    OpenAI, Anthropic — whichever are configured)
  * six AgentLogger constructions
  * imports of the six agents' supporting tools (erp_kb, doc_generator,
    agent_memory, resilience, prompts, schemas, ...)

None of this is a bug, but it means this package is not a cheap import.
Anything that loads `src.agents` pays the full cost even if it only
uses one agent. If startup latency ever becomes a concern, a lazy
loader (PEP 562 module __getattr__) would let callers pay per-agent —
deliberately not done here, because the failure-loud behavior below is
arguably more valuable than the few milliseconds saved.

Failure contract
----------------
Each of the six agent imports is unguarded. If any one of them fails —
a schema mismatch, a tool import error, a settings access that raises —
`import src.agents` fails and the application does not start. That is
the correct behavior for this particular package: the orchestrator
cannot run the workflow without all six agents, and a partial boot that
silently lacks one phase would produce confusing downstream failures.
The alternative (guard each import, warn and continue) would push the
failure to the first request that needs the missing agent — later,
harder to diagnose, and with no clear signal at boot.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Legacy base-class import
# ---------------------------------------------------------------------------
# `Agent` is imported here for backward compatibility with earlier code
# that referenced `src.agents.Agent`. None of the six agent classes in
# this package currently inherit from it — each defines its own __init__
# and uses AgentLogger directly. The name is kept exported because:
#
#   1. Removing it is a breaking change for any external caller that
#      imports it, and I can't see all consumers from within this file.
#   2. If `base.py` is genuinely dead, the import is harmless when
#      wrapped defensively, and one commit that also removes `base.py`
#      can delete both cleanly.
#
# The import is defensive so that a missing or broken `src/agents/base.py`
# does not take down the entire application at startup. If you confirm
# nothing imports `Agent` from `src.agents` (grep for
# "from src.agents import Agent" and "src.agents.Agent"), delete this
# block AND `src/agents/base.py` in one change.
try:
    from .base import Agent  # noqa: F401 - re-exported for compatibility
    _AGENT_BASE_AVAILABLE = True
except Exception as _e:  # noqa: BLE001 - any import failure is non-fatal here
    Agent = None  # type: ignore[assignment]
    _AGENT_BASE_AVAILABLE = False
    logger.warning(
        "src.agents.base.Agent could not be imported (%s); the name is "
        "still present on src.agents but is None. None of the six agent "
        "classes depend on it, so this does not affect agent behavior - "
        "but any external consumer that imported src.agents.Agent will "
        "need to be updated or base.py restored.",
        _e,
    )


# ---------------------------------------------------------------------------
# The six specialized agents
# ---------------------------------------------------------------------------
# Each import loads the module and constructs its singleton. See the
# "Failure contract" note in the module docstring for why these are
# intentionally unguarded.
from .requirements_agent import RequirementsAgent, requirements_agent
from .process_mapping_agent import ProcessMappingAgent, process_mapping_agent
from .solution_design_agent import SolutionDesignAgent, solution_design_agent
from .testing_agents import (
    QATestingAgent,
    UATTestingAgent,
    qa_testing_agent,
    uat_testing_agent,
)
from .training_agent import TrainingAgent, training_agent


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------
__all__ = [
    # -- Legacy base class ------------------------------------------------
    # Exported for backward compatibility; None if base.py could not be
    # imported. See the block above.
    "Agent",

    # -- Agent classes ----------------------------------------------------
    # Use these when you need an instance that is not shared with the
    # rest of the process (tests, edge-case tooling).
    "RequirementsAgent",
    "ProcessMappingAgent",
    "SolutionDesignAgent",
    "QATestingAgent",
    "UATTestingAgent",
    "TrainingAgent",

    # -- Pre-built singletons ---------------------------------------------
    # These are what the orchestrator and the API layer import. Safe to
    # share across threads: each agent opens its own resources per call.
    "requirements_agent",
    "process_mapping_agent",
    "solution_design_agent",
    "qa_testing_agent",
    "uat_testing_agent",
    "training_agent",
]


# ---------------------------------------------------------------------------
# Diagnostic
# ---------------------------------------------------------------------------
def _log_agent_import_summary() -> None:
    """One INFO line summarizing what this package loaded. Provides the
    same 'is everything here?' answer for agents that the knowledge-base
    loader provides for ERPs. Cheap, and it surfaces an agent whose
    singleton was constructed in a degraded state without taking the app
    down."""
    try:
        loaded: list[str] = []
        for name, obj in (
            ("requirements", requirements_agent),
            ("process_mapping", process_mapping_agent),
            ("solution_design", solution_design_agent),
            ("qa_testing", qa_testing_agent),
            ("uat_testing", uat_testing_agent),
            ("training", training_agent),
        ):
            if obj is not None:
                loaded.append(name)

        logger.info(
            "Agent package initialized: %d/6 singletons loaded",
            len(loaded),
        )
        if _AGENT_BASE_AVAILABLE:
            logger.debug("src.agents.base.Agent present")
        else:
            logger.warning(
                "src.agents.base.Agent is not available; legacy imports of "
                "that name will resolve to None"
            )
    except Exception as e:  # noqa: BLE001 - diagnostic must not break import
        logger.debug("Could not summarize agent package: %s", e)


_log_agent_import_summary()