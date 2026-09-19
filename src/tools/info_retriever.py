"""
Info Retriever - Decides between internal KB, memory, or web search and
returns aggregated results for the chat synthesis step.

Responsibilities:

  This module gathers candidate reference material and hands back
  something the synthesis prompt can consume. It is NOT responsible for
  deciding whether the content is correct or relevant beyond its own
  ranking - that's the synthesis model's job, and the prompt in
  src/utils/prompts.py wraps the returned text in untrusted-data markers
  for exactly that reason.

  Because the returned text becomes part of a prompt, this module:
    - bounds every external call (KB, memory, web) with a timeout, so a
      slow source can't hold the chat HTTP thread indefinitely,
    - isolates each source's failures so a KB outage still permits a web
      answer and vice versa,
    - caps result counts and truncates individual items, so a single
      retrieval can't blow the prompt token budget,
    - formats each item as a compact string (no dict reprs in prompts),
    - strips prompt-marker escape sequences (`</reference_data>` and
      friends) from externally fetched text, since the synthesis prompt's
      injection defense relies on those markers being intact.

Caching: not implemented here. A repeated query hits SerpAPI again.
Adding a TTL cache (e.g. cachetools.TTLCache keyed on
(query, prefer_web, session_id)) would reduce external cost; left as a
follow-up because cache-invalidation semantics deserve their own review.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from src.config.settings import settings
from src.memory.project_memory import project_memory_store
from src.tools import google_search as google_search_tool
from src.tools.erp_knowledge_base import erp_kb
from src.tools.reasoning import reasoning_tool
from src.utils.logger import AgentLogger
from src.utils.resilience import run_with_timeout, OperationTimeoutError

logger = AgentLogger("InfoRetriever")


# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------
# Web search is the slowest and most failure-prone source, and until now
# had no timeout at all - a hung SerpAPI request would hold the chat
# HTTP worker indefinitely. These are overridable via settings so they
# can be tuned per-deployment without code change.
_WEB_SEARCH_TIMEOUT_SECONDS = float(
    getattr(settings, "web_search_timeout_seconds", 10) or 10
)
_KB_SEARCH_TIMEOUT_SECONDS = float(
    getattr(settings, "kb_search_timeout_seconds", 5) or 5
)
_MEMORY_SEARCH_TIMEOUT_SECONDS = float(
    getattr(settings, "memory_search_timeout_seconds", 3) or 3
)

# Caps per source. get_synthesis_prompt only consumes the first 3 of each
# list anyway, but retrieval would happily return many more - so cap here,
# closer to where the external cost is incurred.
_MAX_KB_RESULTS = 5
_MAX_MEMORY_RESULTS = 5

# Hard cap on the total characters of web content forwarded to the
# synthesis prompt. A single search-result page can be hundreds of KB;
# forwarding all of it both blows the prompt budget and provides no
# benefit (the synthesis prompt only reads the first few items).
_MAX_WEB_TEXT_CHARS = 8_000

# Escape sequences that could break out of the untrusted-data wrapper in
# the synthesis prompt. Neutralized on the way out of this module - see
# module docstring.
_PROMPT_MARKER_ESCAPE_PATTERN = re.compile(
    r"</?\s*(?:reference_data|system|instruction|assistant|human|user)\s*>",
    re.IGNORECASE,
)

# Small English stopword list for query tokenization. Not exhaustive - the
# goal is to avoid the pathological case where a natural-language
# question's function words dominate a keyword search on project memory.
_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "does", "for",
    "from", "has", "have", "how", "i", "if", "in", "is", "it", "its",
    "me", "my", "no", "not", "of", "on", "or", "our", "should", "so",
    "than", "that", "the", "their", "them", "then", "there", "these",
    "they", "this", "those", "to", "up", "us", "was", "we", "were",
    "what", "when", "where", "which", "who", "why", "will", "with",
    "would", "you", "your",
})


# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------
# The Google search tool is stateless across calls. Instantiating it per
# call - as the previous version did - rebuilt the SerpAPI client on every
# chat message.
_google_search_singleton: Optional[Any] = None
_google_search_singleton_lock = None  # initialized lazily to avoid import-time threading


def _get_google_search_tool():
    global _google_search_singleton, _google_search_singleton_lock
    if _google_search_singleton_lock is None:
        import threading
        _google_search_singleton_lock = threading.Lock()
    with _google_search_singleton_lock:
        if _google_search_singleton is None:
            _google_search_singleton = google_search_tool.GoogleSearchTool()
    return _google_search_singleton


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def _sanitize_external_text(text: Any) -> str:
    """Neutralize prompt-marker escape sequences in externally-sourced
    text. Returns a string (empty for None)."""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    return _PROMPT_MARKER_ESCAPE_PATTERN.sub("[removed-marker]", text)


def _format_kb_hit(hit: Any) -> Optional[str]:
    """Render a KB hit as a compact, prompt-ready string. Returns None
    for entries that can't be usefully rendered (so callers can filter
    them out rather than emitting an empty bullet)."""
    if not isinstance(hit, dict):
        text = _sanitize_external_text(hit)
        return text or None

    t = hit.get("type")
    if t == "module":
        parts: List[str] = [f"[module] {_sanitize_external_text(hit.get('name', 'Unnamed module'))}"]
        if hit.get("code"):
            parts.append(f"({_sanitize_external_text(hit['code'])})")
        if hit.get("erp"):
            parts.append(f"on {_sanitize_external_text(hit['erp'])}")
        if hit.get("description"):
            parts.append(f"- {_sanitize_external_text(hit['description'])}")
        return " ".join(parts).strip()

    if t == "concept":
        name = _sanitize_external_text(hit.get("name", "concept"))
        desc = _sanitize_external_text(hit.get("description", ""))
        return f"[concept] {name}: {desc}".strip(" :")

    if t == "erp":
        name = _sanitize_external_text(hit.get("name", "ERP system"))
        vendor = _sanitize_external_text(hit.get("vendor", ""))
        return f"[erp] {name}" + (f" ({vendor})" if vendor else "")

    # Unknown shape - fall back to a comma-joined key=value summary that
    # avoids the raw dict repr and stays readable.
    if hit:
        return "; ".join(
            f"{k}: {_sanitize_external_text(v)}"
            for k, v in hit.items() if v not in (None, "", [], {})
        )
    return None


def _format_memory_hit(entry: Any) -> Optional[str]:
    """Render a memory entry as a compact, prompt-ready string."""
    if entry is None:
        return None
    # MemoryEntry instances expose .to_dict(); the store returns those
    # objects. A caller could in principle pass a dict already, so handle
    # both.
    if hasattr(entry, "to_dict") and callable(entry.to_dict):
        try:
            entry = entry.to_dict()
        except Exception:  # noqa: BLE001 - fall through to str() path
            entry = None
    if isinstance(entry, dict):
        category = entry.get("category", "note")
        content = entry.get("content", "")
        content = _sanitize_external_text(content)
        if not content:
            return None
        return f"[project memory / {category}] {content}"
    text = _sanitize_external_text(entry)
    return text or None


def _tokenize_query(query: str) -> List[str]:
    """Extract meaningful keywords from a natural-language query.

    Lowercase, keep alphanumerics, drop stopwords, drop tokens under 3
    characters (single-letter and two-letter matches are almost always
    noise). The output is passed to the memory keyword search."""
    tokens = re.findall(r"[a-z0-9][a-z0-9\-]*", (query or "").lower())
    return [
        t for t in tokens
        if len(t) >= 3 and t not in _STOPWORDS
    ]


# ---------------------------------------------------------------------------
# Source decision
# ---------------------------------------------------------------------------
def _decide_sources(
    query: str, context: Dict[str, Any], prefer_web: bool,
) -> Dict[str, Any]:
    """Decide which sources to consult. Returns a decision dict shaped
    like reasoning_tool.assess_source's output, or a conservative
    default ('hybrid') if the reasoning call fails."""
    if prefer_web:
        return {
            "decision": "hybrid",
            "confidence": 0.9,
            "reasoning": "caller forced web; KB and memory still consulted",
        }

    try:
        decision = reasoning_tool.assess_source(query, context.get("summary", ""))
        # Defensive: a reasoning tool that returns an unexpected shape
        # shouldn't take down retrieval.
        if not isinstance(decision, dict) or decision.get("decision") not in ("kb", "web", "hybrid"):
            raise ValueError(f"unexpected decision shape: {decision!r}")
        return decision
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "Source reasoning failed; defaulting to hybrid",
            error=str(e),
        )
        return {
            "decision": "hybrid",
            "confidence": 0.0,
            "reasoning": "reasoning tool unavailable; conservative default",
        }


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
def retrieve(
    query: str,
    context: Optional[Dict[str, Any]] = None,
    prefer_web: bool = False,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieve information about a query using KB, memory, and/or web.

    session_id scopes the memory source to one project's own knowledge.
    A query asked with no active project (session_id=None) simply has no
    project memory to search, so that source is skipped entirely rather
    than searching across every project.

    Every external call is bounded and every source is isolated: a
    failure or timeout on one source contributes no results but does not
    prevent the others. The return payload always has the same shape.

    Returns:
        {
          'query': str,
          'decision': {...},          # which sources were consulted, and why
          'kb_results': [str],        # internal KB + memory, prompt-ready
          'web_results': [str],       # web content, sanitized and truncated
          'sources': [str],           # human-readable citation hints
          'errors': [str],            # non-fatal source errors, for observability
        }
    """
    context = context or {}
    query = (query or "").strip()

    payload: Dict[str, Any] = {
        'query': query,
        'decision': None,
        'kb_results': [],
        'web_results': [],
        'sources': [],
        'errors': [],
    }

    if not query:
        payload['decision'] = {
            'decision': 'none',
            'confidence': 1.0,
            'reasoning': 'empty query',
        }
        return payload

    decision = _decide_sources(query, context, prefer_web)
    payload['decision'] = decision

    # ------------------------------------------------------------------
    # Internal sources (KB + project memory)
    # ------------------------------------------------------------------
    if decision['decision'] in ('kb', 'hybrid'):
        # KB search
        try:
            kb_hits = run_with_timeout(
                erp_kb.search_knowledge,
                query,
                timeout=_KB_SEARCH_TIMEOUT_SECONDS,
            ) or []
        except OperationTimeoutError:
            payload['errors'].append('kb: timeout')
            logger.warning("KB search timed out", timeout_s=_KB_SEARCH_TIMEOUT_SECONDS)
            kb_hits = []
        except Exception as e:  # noqa: BLE001
            payload['errors'].append('kb: error')
            logger.exception("KB search failed")
            kb_hits = []

        kb_formatted = [
            s for s in (_format_kb_hit(h) for h in kb_hits[:_MAX_KB_RESULTS]) if s
        ]
        if kb_formatted:
            payload['kb_results'].extend(kb_formatted)
            payload['sources'].append(
                f"ERP knowledge base ({len(kb_formatted)} result(s))"
            )

        # Project memory search - scoped to this session; skipped when no
        # session is active.
        if session_id:
            keywords = _tokenize_query(query)
            if keywords:
                try:
                    mem_hits = run_with_timeout(
                        project_memory_store.search_by_keywords,
                        session_id,
                        keywords,
                        limit=_MAX_MEMORY_RESULTS,
                        timeout=_MEMORY_SEARCH_TIMEOUT_SECONDS,
                    ) or []
                except OperationTimeoutError:
                    payload['errors'].append('memory: timeout')
                    logger.warning(
                        "Memory search timed out",
                        timeout_s=_MEMORY_SEARCH_TIMEOUT_SECONDS,
                    )
                    mem_hits = []
                except Exception:  # noqa: BLE001
                    payload['errors'].append('memory: error')
                    logger.exception("Memory search failed")
                    mem_hits = []

                mem_formatted = [
                    s for s in (_format_memory_hit(m) for m in mem_hits[:_MAX_MEMORY_RESULTS]) if s
                ]
                if mem_formatted:
                    # Merged into kb_results so the existing synthesis
                    # prompt (which reads kb_results + web_results) sees
                    # them; the [project memory / ...] prefix makes them
                    # distinguishable in the prompt.
                    payload['kb_results'].extend(mem_formatted)
                    payload['sources'].append(
                        f"Project memory ({len(mem_formatted)} result(s))"
                    )

    # ------------------------------------------------------------------
    # Web search
    # ------------------------------------------------------------------
    if decision['decision'] in ('web', 'hybrid'):
        try:
            search_tool = _get_google_search_tool()
            web_txt = run_with_timeout(
                search_tool,
                query,
                timeout=_WEB_SEARCH_TIMEOUT_SECONDS,
            )
        except OperationTimeoutError:
            payload['errors'].append('web: timeout')
            logger.warning(
                "Web search timed out",
                timeout_s=_WEB_SEARCH_TIMEOUT_SECONDS,
            )
            web_txt = None
        except Exception:  # noqa: BLE001
            payload['errors'].append('web: error')
            logger.exception("Web search failed")
            web_txt = None

        if web_txt:
            sanitized = _sanitize_external_text(web_txt)
            if len(sanitized) > _MAX_WEB_TEXT_CHARS:
                sanitized = (
                    sanitized[:_MAX_WEB_TEXT_CHARS]
                    + "\n[...web content truncated by retriever...]"
                )
            payload['web_results'].append(sanitized)
            payload['sources'].append("Web search")

            # Extract URLs from the web blob if present, as citable
            # source entries. The synthesis prompt renders each source
            # entry as a bullet.
            for url in re.findall(r"https?://[^\s\)\]]+", sanitized)[:5]:
                payload['sources'].append(url)

    # ------------------------------------------------------------------
    # Summary log line - the routing decision was previously invisible.
    # ------------------------------------------------------------------
    logger.info(
        "Retrieval complete",
        decision=decision.get('decision'),
        kb_count=len(payload['kb_results']),
        web_count=len(payload['web_results']),
        error_count=len(payload['errors']),
        session_scoped=bool(session_id),
    )

    return payload


# Expose as module API
info_retriever = retrieve