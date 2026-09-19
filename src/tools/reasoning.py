"""
Reasoning Tool - Higher-level reasoning and decision support for agents
and the orchestrator.

Public API is unchanged: reasoning_tool.assess_source(query, context)
and reasoning_tool.make_plan(instruction, context). Both methods return
the same dict shapes they always have, with additive fields.

Design notes on this revision:

  * assess_source now short-circuits on a small heuristic for clear-cut
    cases. Every chat message used to trigger an LLM call just to pick
    between kb/web/hybrid; the heuristic catches the obvious cases (a
    module code, "our project", a year >= 2024) and returns without a
    network round-trip. Ambiguous queries still fall through to the LLM,
    and the LLM path itself is now bounded by a timeout.

  * Both methods use response_schema when the underlying LLM supports
    it. The previous version parsed the LLM's free-text reply with
    substring matching and float-on-whitespace-token extraction, both of
    which produce the wrong answer on perfectly reasonable LLM output
    ("hybrid is overkill here, this is pure KB" would resolve to
    'hybrid'). Structured output removes the parsing layer entirely.

  * The make_plan justification bug is fixed. The old code located the
    matched line via list.index(), which returns the first line equal to
    the match - not the position in the reversed iteration - and could
    splice in the wrong slice of the response when any line appeared
    more than once.

  * assess_source results are cached (small LRU, process-local) so
    repeated identical questions don't re-invoke the LLM.

  * reload_model now calls reload_llm() to actually re-initialize the
    shared LLM client, instead of re-fetching the existing singleton.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from threading import Lock
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from typing import Literal

from src.utils.llm import get_llm, reload_llm
from src.config.settings import settings
from src.utils.logger import AgentLogger
from src.utils.model_selection import TaskCategory
from src.utils.resilience import run_with_timeout, OperationTimeoutError


# ---------------------------------------------------------------------------
# Structured output schemas
# ---------------------------------------------------------------------------
class SourceDecision(BaseModel):
    """LLM's routing decision, as structured output. Enforcing the shape
    at the schema level removes the fragile substring parsing the
    previous version did."""
    decision: Literal["kb", "web", "hybrid"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(default="", max_length=500)


class PlanOutput(BaseModel):
    """Step-by-step plan as structured output. steps must be non-empty;
    the model is instructed to produce 3-8."""
    steps: List[str] = Field(min_length=1, max_length=12)
    justification: str = Field(default="", max_length=1000)


# ---------------------------------------------------------------------------
# Heuristic pre-classifier
# ---------------------------------------------------------------------------
# Well-documented ERP module codes. Matched as standalone uppercase words
# so "FI" is a signal but "profile" is not. Deliberately conservative -
# the heuristic only returns a decision when the signal is strong, and
# returns None otherwise so the LLM path still runs.
_MODULE_CODE_PATTERN = re.compile(
    r"\b(?:FI|CO|MM|SD|PP|QM|PM|WM|EWM|PS|HR|HCM|TM|PM|"
    r"AP|AR|GL|AA|TR|IM|CATS|EC|CS|RE|RE-FX|IS-Retail|S4|S/4HANA)\b"
)

# Phrases that indicate the user is asking about the *current project's*
# own context, which lives in memory (part of the kb/hybrid path).
_PROJECT_CONTEXT_PATTERN = re.compile(
    r"\b(?:our project|our requirements|we (?:decided|agreed|chose)|"
    r"the (?:design|process map|requirements|solution)|"
    r"uploaded (?:document|file)|this project|the baseline)\b",
    re.IGNORECASE,
)

# Phrases that strongly indicate the answer needs current information
# beyond what an internal KB or an uploaded document would contain.
_WEB_SIGNAL_PATTERN = re.compile(
    r"\b(?:latest|current(?:ly)?|recent|news|roadmap|upcoming|released?|"
    r"release notes|update[sd]? in 20\d\d|in 20\d\d|compar(?:e|ing|ison)|"
    r"vs\.?|versus|benchmark)\b",
    re.IGNORECASE,
)


def _heuristic_source_decision(query: str) -> Optional[Dict[str, Any]]:
    """Return a decision dict if the query has a strong signal for one
    source, or None to defer to the LLM. The bar for firing is high -
    only decisive signals count, so the LLM path still handles anything
    genuinely ambiguous."""
    if not query:
        return None

    # Strong web signal takes precedence over KB signals: if the user is
    # explicitly asking about something time-sensitive, a KB lookup alone
    # is the wrong answer even if a module code also appears.
    if _WEB_SIGNAL_PATTERN.search(query):
        return {
            'decision': 'hybrid',
            'confidence': 0.75,
            'reasoning': 'time-sensitive or comparison query; hybrid is safest',
            'source': 'heuristic',
        }

    # Direct reference to the project's own context → memory is authoritative,
    # and the KB often helps too. hybrid.
    if _PROJECT_CONTEXT_PATTERN.search(query):
        return {
            'decision': 'hybrid',
            'confidence': 0.75,
            'reasoning': 'query references this project\'s own artifacts',
            'source': 'heuristic',
        }

    # A specific module code, without time-sensitivity, is usually answerable
    # from the KB.
    if _MODULE_CODE_PATTERN.search(query):
        return {
            'decision': 'kb',
            'confidence': 0.7,
            'reasoning': 'query names a specific ERP module; KB lookup is preferred',
            'source': 'heuristic',
        }

    return None


# ---------------------------------------------------------------------------
# LRU cache for assess_source
# ---------------------------------------------------------------------------
# Process-local. Bounded. Thread-safe. Keyed on the pair (query, context)
# so a caller passing context still gets a fresh decision when context
# differs.
_ASSESS_CACHE_MAX = 256
_assess_cache: "OrderedDict[tuple, Dict[str, Any]]" = OrderedDict()
_assess_cache_lock = Lock()


def _cache_get(query: str, context: str) -> Optional[Dict[str, Any]]:
    key = (query, context)
    with _assess_cache_lock:
        hit = _assess_cache.get(key)
        if hit is None:
            return None
        _assess_cache.move_to_end(key)
        return dict(hit)  # copy so callers can't mutate the cache


def _cache_put(query: str, context: str, value: Dict[str, Any]) -> None:
    key = (query, context)
    with _assess_cache_lock:
        _assess_cache[key] = dict(value)
        _assess_cache.move_to_end(key)
        while len(_assess_cache) > _ASSESS_CACHE_MAX:
            _assess_cache.popitem(last=False)


# ---------------------------------------------------------------------------
# Bounded LLM call
# ---------------------------------------------------------------------------
_REASONING_LLM_TIMEOUT_SECONDS = float(
    getattr(settings, "reasoning_llm_timeout_seconds", 15) or 15
)


class ReasoningTool:
    """Wraps the LLM to produce plans, justifications, and route decisions."""

    def __init__(self):
        self.logger = AgentLogger("ReasoningTool")
        self.model = get_llm()

        # Generation config for reasoning calls. Structured output is set
        # per-call (below), not here, since assess_source and make_plan
        # use different schemas.
        self.generation_config = {
            'temperature': 0.2,
            'max_output_tokens': 512,
            'task': TaskCategory.LIGHTWEIGHT,
        }

    def reload_model(self) -> None:
        """Re-initialize the shared LLM client. Previously this called
        get_llm(), which returns the existing singleton and does not
        actually reload anything."""
        self.model = reload_llm()

    # ------------------------------------------------------------------ #
    # Source decision
    # ------------------------------------------------------------------ #
    def assess_source(self, query: str, context: str = "") -> Dict[str, Any]:
        """Decide whether to consult the internal KB, web search, or both.

        Returns a dict with keys:
            decision:    'kb' | 'web' | 'hybrid'
            confidence:  float in [0, 1]
            reasoning:   short justification (from LLM or from the
                         heuristic, depending on which produced the answer)
            source:      'heuristic' | 'llm' | 'fallback' - which path
                         produced this decision (new field; additive)

        Order of operations:
          1. Cache hit (same query + context within this process).
          2. Heuristic, for clear-cut cases.
          3. LLM, with structured output and a timeout.
          4. Fallback to a conservative 'hybrid' if the LLM call fails.
        """
        query = (query or "").strip()
        context = context or ""

        # 1. Cache
        cached = _cache_get(query, context)
        if cached is not None:
            return cached

        # 2. Heuristic for clear-cut queries
        heuristic = _heuristic_source_decision(query)
        if heuristic is not None:
            _cache_put(query, context, heuristic)
            self.logger.info(
                "Source decision via heuristic",
                decision=heuristic['decision'],
                confidence=heuristic['confidence'],
                query_length=len(query),
            )
            return heuristic

        # 3. LLM with structured output
        self.logger.info(
            "Assessing source decision via LLM",
            query_length=len(query),
        )
        decision = self._assess_via_llm(query, context)

        _cache_put(query, context, decision)
        return decision

    def _assess_via_llm(self, query: str, context: str) -> Dict[str, Any]:
        """Ask the LLM, enforcing structured output. On any failure,
        return a conservative hybrid default (which is strictly more
        information-gathering than either 'kb' or 'web' alone)."""
        prompt = (
            "You are a routing assistant for an ERP consulting tool. Given "
            "a short user query, decide which reference sources to consult.\n\n"
            "Sources:\n"
            "  - kb: internal ERP knowledge base (module structure, standard "
            "transactions, general best practices) and the current project's "
            "own memory (uploaded documents, decisions, requirements). Use "
            "when the answer is stable ERP reference content or refers to "
            "the project's own material.\n"
            "  - web: external web search. Use when the answer needs "
            "time-sensitive information (recent releases, current vendor "
            "roadmaps, up-to-date comparisons).\n"
            "  - hybrid: consult both. Prefer this when the query is "
            "ambiguous or touches both stable reference and current events.\n\n"
            f"Query: {query}\n"
            f"Project context summary: {context or '(none)'}\n\n"
            "Return a decision, a confidence in [0, 1], and one short "
            "sentence of reasoning."
        )

        try:
            response = run_with_timeout(
                self.model.generate_content,
                prompt,
                generation_config={
                    **self.generation_config,
                    'response_schema': SourceDecision,
                },
                timeout=_REASONING_LLM_TIMEOUT_SECONDS,
            )
        except OperationTimeoutError:
            self.logger.warning(
                "Source decision LLM call timed out; defaulting to hybrid",
                timeout_s=_REASONING_LLM_TIMEOUT_SECONDS,
            )
            return self._fallback_decision('timeout')
        except Exception as e:  # noqa: BLE001
            self.logger.exception("Reasoning assess_source LLM call failed")
            return self._fallback_decision(str(e))

        text = getattr(response, 'text', None) or ''
        if not text.strip():
            return self._fallback_decision('empty LLM response')

        try:
            parsed = SourceDecision.model_validate_json(text)
        except Exception as e:  # noqa: BLE001
            # Structured output should have prevented this, but be
            # defensive: an unexpected shape must not break routing.
            self.logger.warning(
                "Source decision response failed schema validation",
                error=str(e),
            )
            return self._fallback_decision('schema validation failed')

        return {
            'decision': parsed.decision,
            'confidence': parsed.confidence,
            'reasoning': parsed.reasoning,
            'source': 'llm',
        }

    @staticmethod
    def _fallback_decision(reason: str) -> Dict[str, Any]:
        """Conservative fallback. 'hybrid' consults every source, which is
        strictly a superset of consulting one - it's the safest default
        when the LLM is unavailable."""
        return {
            'decision': 'hybrid',
            'confidence': 0.3,
            'reasoning': f'fallback to hybrid: {reason}',
            'source': 'fallback',
        }

    # ------------------------------------------------------------------ #
    # Planning
    # ------------------------------------------------------------------ #
    def make_plan(self, instruction: str, context: str = "") -> Dict[str, Any]:
        """Generate a step-by-step plan with a short justification.

        Returns a dict with keys:
            steps:         List[str]
            justification: str
            raw:           the raw LLM text (or empty on fallback)
            source:        'llm' | 'fallback' (new field; additive)
        """
        if not instruction or not instruction.strip():
            return {
                'steps': [],
                'justification': 'no instruction provided',
                'raw': '',
                'source': 'fallback',
            }

        prompt = (
            "You are a planning assistant for an ERP consulting tool. "
            "Given an instruction and any available context, produce a "
            "concise numbered plan (3-8 steps), plus a short justification "
            "for the approach.\n\n"
            f"Instruction: {instruction}\n"
            f"Context: {context or '(none)'}\n\n"
            "Each step must be a discrete action. Do not include a "
            "restatement of the instruction as a step."
        )

        try:
            response = run_with_timeout(
                self.model.generate_content,
                prompt,
                generation_config={
                    **self.generation_config,
                    'response_schema': PlanOutput,
                },
                timeout=_REASONING_LLM_TIMEOUT_SECONDS,
            )
        except OperationTimeoutError:
            self.logger.warning(
                "make_plan LLM call timed out",
                timeout_s=_REASONING_LLM_TIMEOUT_SECONDS,
            )
            return self._plan_fallback('timeout')
        except Exception as e:  # noqa: BLE001
            self.logger.exception("Reasoning make_plan LLM call failed")
            return self._plan_fallback(str(e))

        text = getattr(response, 'text', None) or ''
        if not text.strip():
            return self._plan_fallback('empty LLM response')

        try:
            parsed = PlanOutput.model_validate_json(text)
        except Exception as e:  # noqa: BLE001
            self.logger.warning(
                "Plan response failed schema validation",
                error=str(e),
            )
            return self._plan_fallback('schema validation failed', raw=text)

        return {
            'steps': list(parsed.steps),
            'justification': parsed.justification,
            'raw': text,
            'source': 'llm',
        }

    @staticmethod
    def _plan_fallback(reason: str, raw: str = "") -> Dict[str, Any]:
        return {
            'steps': [],
            'justification': f'fallback: {reason}',
            'raw': raw,
            'source': 'fallback',
        }


# Global instance
reasoning_tool = ReasoningTool()