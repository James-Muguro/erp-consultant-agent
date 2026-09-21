"""
Reasoning Tool - Higher-level reasoning and decision support for agents
and the orchestrator.

Public API is unchanged: reasoning_tool.assess_source(query, context)
and reasoning_tool.make_plan(instruction, context). Both methods return
the same dict shapes they always have, with additive fields.

Resilience contract (LLM outage):

  A complete LLM provider outage must not turn source assessment into a
  single point of failure for retrieval. When the LLM path fails for
  any reason - timeout, exception, empty response, schema violation -
  this layer returns a deterministic decision (`decision='hybrid'`,
  `confidence=0.3`, `source='fallback'`) that consults every available
  reference source. The `source` field lets callers distinguish an
  LLM-derived decision from a heuristic one from a fallback one. The
  fallback is a routing choice only; it never fabricates an answer and
  never claims the model responded.

  Exception logging in this layer is deliberately not `logger.exception`
  for LLM-call failures: the LLM wrapper in src/utils/llm.py has already
  logged the provider outage, and a full traceback here would duplicate
  it. The reasoning layer records a single structured event naming the
  stage, the reason, and the resulting decision instead.
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
                         produced this decision

        Order of operations:
          1. Cache hit (same query + context within this process).
          2. Heuristic, for clear-cut cases.
          3. LLM, with structured output and a timeout.
          4. Fallback to a conservative 'hybrid' if the LLM call fails.

        LLM-failure resilience: a timeout, a raised exception from the LLM
        wrapper, an empty response, or a schema violation each produce a
        deterministic 'hybrid' decision with `source='fallback'`. This
        never claims to come from the model and never propagates the
        provider outage to the caller - retrieval continues against both
        reference sources. Fallback decisions are deliberately not
        cached, so once the LLM is reachable again the next identical
        query re-invokes the LLM instead of replaying the stale fallback.
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

        # 4. Cache only LLM-derived decisions. Caching the deterministic
        # fallback would pin every ambiguous query seen during an LLM
        # outage to the fallback outcome even after the LLM recovers.
        if decision.get('source') == 'llm':
            _cache_put(query, context, decision)
        return decision

    def _assess_via_llm(self, query: str, context: str) -> Dict[str, Any]:
        """Ask the LLM, enforcing structured output. On any failure,
        return a conservative hybrid default (which is strictly more
        information-gathering than either 'kb' or 'web' alone).

        None of the branches below propagates an exception: an LLM
        provider outage must not turn into a retrieval outage. Each
        branch returns the deterministic fallback, which records a
        single structured event via `_fallback_decision`.
        """
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
            return self._fallback_decision(
                'timeout',
                timeout_s=_REASONING_LLM_TIMEOUT_SECONDS,
            )
        except Exception as e:  # noqa: BLE001
            # Warning, not exception: the LLM wrapper in src/utils/llm.py
            # has already logged the provider outage with full detail.
            # A duplicate traceback here adds no diagnostic value.
            return self._fallback_decision('llm_call_failed', error=str(e))

        text = getattr(response, 'text', None) or ''
        if not text.strip():
            return self._fallback_decision('empty LLM response')

        try:
            parsed = SourceDecision.model_validate_json(text)
        except Exception as e:  # noqa: BLE001
            # Structured output should have prevented this, but be
            # defensive: an unexpected shape must not break routing.
            return self._fallback_decision(
                'schema_validation_failed', error=str(e),
            )

        return {
            'decision': parsed.decision,
            'confidence': parsed.confidence,
            'reasoning': parsed.reasoning,
            'source': 'llm',
        }

    def _fallback_decision(self, reason: str, **extra: Any) -> Dict[str, Any]:
        """Conservative fallback. 'hybrid' consults every source, which is
        strictly a superset of consulting one - it's the safest default
        when the LLM is unavailable.

        Records a single structured event naming the stage, the reason,
        and the resulting decision, so operators can distinguish an
        LLM-derived decision from a fallback one without having to parse
        free-text log lines. No secrets and no traceback are included.
        """
        result = {
            'decision': 'hybrid',
            'confidence': 0.3,
            'reasoning': f'fallback to hybrid: {reason}',
            'source': 'fallback',
        }
        self.logger.warning(
            "Source assessment fell back to deterministic default",
            stage='assess_source',
            reason=reason,
            decision=result['decision'],
            confidence=result['confidence'],
            source=result['source'],
            **extra,
        )
        return result

    # ------------------------------------------------------------------ #
    # Planning
    # ------------------------------------------------------------------ #
    def make_plan(self, instruction: str, context: str = "") -> Dict[str, Any]:
        """Generate a step-by-step plan with a short justification.

        Returns a dict with keys:
            steps:         List[str]
            justification: str
            raw:           the raw LLM text (or empty on fallback)
            source:        'llm' | 'fallback'
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
            return self._plan_fallback(
                'timeout',
                timeout_s=_REASONING_LLM_TIMEOUT_SECONDS,
            )
        except Exception as e:  # noqa: BLE001
            return self._plan_fallback('llm_call_failed', error=str(e))

        text = getattr(response, 'text', None) or ''
        if not text.strip():
            return self._plan_fallback('empty LLM response')

        try:
            parsed = PlanOutput.model_validate_json(text)
        except Exception as e:  # noqa: BLE001
            return self._plan_fallback(
                'schema_validation_failed', raw=text, error=str(e),
            )

        return {
            'steps': list(parsed.steps),
            'justification': parsed.justification,
            'raw': text,
            'source': 'llm',
        }

    def _plan_fallback(
        self, reason: str, raw: str = "", **extra: Any,
    ) -> Dict[str, Any]:
        """Deterministic empty plan. Same logging discipline as
        `_fallback_decision`: one structured event, no traceback, no
        secrets."""
        result = {
            'steps': [],
            'justification': f'fallback: {reason}',
            'raw': raw,
            'source': 'fallback',
        }
        self.logger.warning(
            "Planning fell back to deterministic empty plan",
            stage='make_plan',
            reason=reason,
            source=result['source'],
            **extra,
        )
        return result


# Global instance
reasoning_tool = ReasoningTool()