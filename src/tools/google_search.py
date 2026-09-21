"""
Google Search tool - SerpAPI wrapper.

Contract:
    GoogleSearchTool()(query: str) -> str

    Returns a formatted string of the top organic results on success, or
    an empty string when SerpAPI returned a valid response with no usable
    results. Raises GoogleSearchError on any failure: missing package,
    missing API key, network error, timeout, or a SerpAPI error response.

Configuration (falls back to defaults if the settings field doesn't exist):
    settings.web_search_timeout_seconds        default 10
    settings.web_search_retry_attempts         default 2
    settings.web_search_cache_ttl_seconds      default 300
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field

from src.config.settings import settings
from src.utils.logger import get_logger
from src.utils.resilience import call_with_retries, OperationTimeoutError

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Import SerpAPI, or record that it isn't available
# ---------------------------------------------------------------------------
# We do NOT install a stub class here. If the package is missing, the
# first call to the tool raises GoogleSearchError and the caller logs a
# source-level error. This is deliberate: an app that silently pretends
# to search is worse than an app that reports it cannot search.
try:
    from serpapi import GoogleSearch as _SerpApiGoogleSearch  # type: ignore
    _SERPAPI_AVAILABLE = True
    _SERPAPI_IMPORT_ERROR: Optional[BaseException] = None
except Exception as _e:  # noqa: BLE001 - import-time, anything could fail
    _SerpApiGoogleSearch = None  # type: ignore[assignment]
    _SERPAPI_AVAILABLE = False
    _SERPAPI_IMPORT_ERROR = _e
    logger.warning(
        "serpapi package not available; web search will raise on use",
        error=str(_e),
    )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_SEARCH_TIMEOUT_SECONDS = float(
    getattr(settings, "web_search_timeout_seconds", 10) or 10
)
_SEARCH_RETRY_ATTEMPTS = int(
    getattr(settings, "web_search_retry_attempts", 2) or 2
)
_CACHE_TTL_SECONDS = float(
    getattr(settings, "web_search_cache_ttl_seconds", 300) or 300
)
_CACHE_MAX_ENTRIES = 128
_MAX_RESULTS_RETURNED = 5


# ---------------------------------------------------------------------------
# Typed error
# ---------------------------------------------------------------------------
class GoogleSearchError(Exception):
    """Raised when a Google search cannot be performed. Callers treat
    this as a source-level failure: they should record it and continue
    with whatever other sources produced, not surface the error text to
    the user as if it were content."""


# ---------------------------------------------------------------------------
# Field coercion
# ---------------------------------------------------------------------------
def _as_field_string(value: Any) -> str:
    """Coerce a SerpAPI result field to a string.

    Only strings are accepted. Any other type - int, float, list, dict,
    or None - is treated as missing and returns "". This prevents a
    malformed individual record from crashing formatting with
    AttributeError and taking down valid sibling records in the same
    response. Does NOT fabricate content: missing stays missing.
    """
    if isinstance(value, str):
        return value.strip()
    return ""


# ---------------------------------------------------------------------------
# TTL cache
# ---------------------------------------------------------------------------
# Process-local. Keyed on the query string. Entries older than the TTL
# are ignored on read and pruned lazily on write. Bounded so a scripted
# flood of unique queries can't grow it without limit.
_cache: Dict[str, "tuple[float, str]"] = {}
_cache_lock = threading.Lock()


def _cache_get(query: str) -> Optional[str]:
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(query)
        if entry is None:
            return None
        ts, value = entry
        if now - ts > _CACHE_TTL_SECONDS:
            _cache.pop(query, None)
            return None
        return value


def _cache_put(query: str, value: str) -> None:
    now = time.monotonic()
    with _cache_lock:
        _cache[query] = (now, value)
        # Cheap bound: drop the oldest key if we're over the limit.
        if len(_cache) > _CACHE_MAX_ENTRIES:
            oldest = min(_cache.items(), key=lambda kv: kv[1][0])
            _cache.pop(oldest[0], None)


# ---------------------------------------------------------------------------
# Schemas (kept for backward compatibility with any existing tools
# consumer; unused internally)
# ---------------------------------------------------------------------------
class GoogleSearchToolInput(BaseModel):
    """Input model for the Google Search tool."""
    query: str = Field(..., description="The search query")


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------
class GoogleSearchTool:
    """Performs a Google search via SerpAPI and returns formatted results.

    Raises GoogleSearchError rather than returning a failure string. The
    calling retriever is responsible for catching that and recording a
    source-level error; the two behaviors are deliberately separated so
    that a genuine empty result and a failed search are distinguishable.
    """

    name: str = "google_search"
    description: str = "Performs a Google search and returns the top results."
    args_schema: Type[BaseModel] = GoogleSearchToolInput

    def __init__(self, api_key: Optional[str] = None):
        """Store the API key. Passing an explicit key is supported for
        tests and for callers that want to override the setting; in
        practice the singleton returned by info_retriever uses the
        settings-provided key."""
        self._api_key = api_key

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def __call__(self, query: str) -> str:
        """Execute the search.

        Returns the formatted top results on success, or an empty string
        when SerpAPI returned a valid response with no usable results.
        Raises GoogleSearchError on any failure.
        """
        if not isinstance(query, str) or not query.strip():
            raise GoogleSearchError("query must be a non-empty string")

        query = query.strip()

        # Cache hit short-circuits everything else.
        cached = _cache_get(query)
        if cached is not None:
            logger.info("Google search cache hit", query_length=len(query))
            return cached

        if not _SERPAPI_AVAILABLE:
            # Deliberately NOT silently returning a stub. The retriever
            # will record this as a source error and proceed with the KB.
            raise GoogleSearchError(
                "serpapi package is not installed in this environment"
            )

        api_key = self._api_key or settings.serpapi_api_key
        if not api_key:
            raise GoogleSearchError(
                "SerpAPI key is not configured; cannot perform web search"
            )

        # call_with_retries retries on any exception, including our own
        # GoogleSearchError, up to _SEARCH_RETRY_ATTEMPTS. Each attempt
        # is bounded by _SEARCH_TIMEOUT_SECONDS via run_with_timeout.
        try:
            formatted = call_with_retries(
                self._do_search,
                query,
                api_key,
                max_attempts=_SEARCH_RETRY_ATTEMPTS,
                timeout=_SEARCH_TIMEOUT_SECONDS,
            )
        except OperationTimeoutError as e:
            logger.warning(
                "Google search timed out",
                query_length=len(query),
                timeout_s=_SEARCH_TIMEOUT_SECONDS,
            )
            raise GoogleSearchError(f"search timed out after {_SEARCH_TIMEOUT_SECONDS}s") from e
        except GoogleSearchError:
            # Already a typed failure from _do_search; propagate.
            raise
        except Exception as e:  # noqa: BLE001 - final boundary
            logger.exception("Google search failed")
            raise GoogleSearchError(f"search failed: {e}") from e

        # Cache successful (even empty) results so the same query doesn't
        # hit SerpAPI again within the TTL window.
        _cache_put(query, formatted)
        return formatted

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    def _do_search(self, query: str, api_key: str) -> str:
        """One search attempt. Raises GoogleSearchError on any failure so
        that call_with_retries sees it as a retryable exception."""
        try:
            search = _SerpApiGoogleSearch({
                "q": query,
                "api_key": api_key,
                # num is SerpAPI's requested-result-count param. The
                # default (10) is larger than we use; asking for 5 keeps
                # the payload smaller without changing behavior.
                "num": _MAX_RESULTS_RETURNED,
            })
        except Exception as e:  # noqa: BLE001 - library-specific errors
            raise GoogleSearchError(f"failed to initialize search: {e}") from e

        try:
            results = search.get_dict()
        except Exception as e:  # noqa: BLE001 - network, TLS, rate-limit, ...
            raise GoogleSearchError(f"search request failed: {e}") from e

        if not isinstance(results, dict):
            raise GoogleSearchError(
                f"unexpected search response type: {type(results).__name__}"
            )

        # SerpAPI reports failures in the response body in several
        # situations (auth, quota, malformed query) instead of raising.
        # Detect and raise so a quota error is never mistaken for "no
        # results."
        error_msg = results.get("error")
        if error_msg:
            raise GoogleSearchError(f"serpapi error: {error_msg}")

        organic = results.get("organic_results") or []
        if not isinstance(organic, list):
            raise GoogleSearchError("malformed organic_results in response")

        if not organic:
            # Valid response, zero results. Empty string is the caller's
            # signal for "searched successfully, found nothing" - it is
            # deliberately not a human-readable string, because the
            # retriever forwards non-empty strings into the synthesis
            # prompt as content.
            return ""

        return self._format_results(organic)

    def _format_results(self, organic_results: List[Dict[str, Any]]) -> str:
        """Format the top results into a compact, prompt-ready string.

        Entries where every field is missing or 'N/A' are dropped: a
        result page with only stub entries yields an empty string, which
        the caller treats as "no usable results."

        Fields are coerced with `_as_field_string`, so a malformed
        individual record (non-string title/link/snippet) is skipped
        rather than crashing formatting and losing the response's valid
        siblings. A malformed-record count is logged at DEBUG so the
        condition is observable without spamming normal runs."""
        formatted: List[str] = []
        skipped = 0

        for result in organic_results[:_MAX_RESULTS_RETURNED]:
            if not isinstance(result, dict):
                skipped += 1
                continue

            title = _as_field_string(result.get("title"))
            link = _as_field_string(result.get("link"))
            snippet = _as_field_string(result.get("snippet"))

            # Skip entries with no usable content.
            if not any([title, link, snippet]):
                skipped += 1
                continue

            parts = []
            if title:
                parts.append(f"Title: {title}")
            if link:
                parts.append(f"Link: {link}")
            if snippet:
                parts.append(f"Snippet: {snippet}")
            formatted.append("\n".join(parts))

        if skipped:
            logger.debug(
                "Skipped malformed search results",
                skipped=skipped,
                kept=len(formatted),
            )

        return "\n---\n".join(formatted)