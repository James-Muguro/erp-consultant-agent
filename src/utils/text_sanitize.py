"""
Repairs common Unicode mojibake in LLM-generated text (e.g. a UTF-8
non-breaking hyphen or bidirectional arrow that got misdecoded somewhere
in the pipeline, showing up as sequences like 'â€‑' or 'â†”'). Applied
once, right after an agent parses its structured LLM response, before
that text is persisted or used to generate a document.

Behavioural notes:

  * `clean_text` uses `ftfy.fix_text`, which repairs mojibake AND
    performs NFC normalization, uncurls typographic quotes, normalizes
    ligatures, and strips control characters. For pure-ASCII fields
    (requirement IDs, transaction codes, status strings) it is a no-op.
    For fields containing curly quotes, non-ASCII names, or special
    punctuation, it may alter characters the model intentionally
    produced. Callers who need strict mojibake-only repairs (preserving
    all other Unicode) can use `clean_text(value, mode='encoding_only')`.
    Use `clean_text_with_report` to audit exactly what changed.

  * idempotent: calling clean_text twice on the same value produces the
    same result as calling it once.

  * ftfy is imported defensively. A missing ftfy used to raise
    ImportError on any import of this module - which would take down
    every agent (they all import clean_text at module load). Missing
    ftfy now degrades to a no-op sanitizer with a one-time WARNING, so
    the pipeline keeps running and the operator sees the degraded state.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ftfy - defensive import
# ---------------------------------------------------------------------------
try:
    import ftfy as _ftfy

    _FTFY_AVAILABLE = True
except ImportError:  # pragma: no cover - only in minimal installs
    _ftfy = None  # type: ignore[assignment]
    _FTFY_AVAILABLE = False

_warned_missing_ftfy = False


# Recursion depth cap. Agent output is at most ~5 levels deep in practice;
# a cap of 100 turns an impossible-to-debug RecursionError into a clear,
# specific error at the point of failure.
_MAX_DEPTH = 100

# Literal types for the `mode` parameter, referenced by the public function
# signatures and by callers reading this module's docs.
Mode = Literal["full", "encoding_only"]


class CleanTextError(ValueError):
    """Raised by clean_text(strict=True) for structural problems -
    currently only for values nested deeper than _MAX_DEPTH."""


def _fix_string(s: str, mode: Mode) -> str:
    """Return the repaired form of a single string.

    mode='full'          ftfy.fix_text (default; repairs mojibake plus
                         NFC normalization, quote uncurling, ligature
                         normalization, control-character removal).
    mode='encoding_only' ftfy.fix_text_encoding (repairs only the
                         encoding-level mojibake; preserves all other
                         Unicode exactly as it was produced).

    When ftfy is unavailable, returns the input unchanged and logs a
    one-shot warning so an operator can see that sanitization is
    inactive in this deployment."""
    global _warned_missing_ftfy
    if not _FTFY_AVAILABLE:
        if not _warned_missing_ftfy:
            logger.warning(
                "ftfy is not installed; clean_text is running as a no-op. "
                "Mojibake in LLM output will not be repaired. Install with "
                "`pip install ftfy` to enable."
            )
            _warned_missing_ftfy = True
        return s
    if mode == "encoding_only":
        # fix_text_encoding is idempotent and only repairs the encoding
        # layer, which is the narrowest interpretation of "mojibake fixer."
        return _ftfy.fix_text_encoding(s)
    return _ftfy.fix_text(s)


def _clean_inner(
    value: Any,
    depth: int,
    mode: Mode,
    changes: Optional[List[Tuple[str, str, str]]],
    path: str,
    strict: bool,
) -> Any:
    """Recursive worker. When `changes` is not None, appends
    (path, before, after) tuples for every string that was actually
    modified - so a caller can audit exactly what ftfy altered."""
    if depth > _MAX_DEPTH:
        msg = (
            f"clean_text recursion depth exceeded ({_MAX_DEPTH}); "
            f"value is nested deeper than expected for agent output "
            f"(path={path!r})"
        )
        if strict:
            raise CleanTextError(msg)
        logger.warning(msg + " - passing value through unchanged")
        return value

    if isinstance(value, str):
        fixed = _fix_string(value, mode)
        if changes is not None and fixed != value:
            changes.append((path, value, fixed))
        return fixed

    if isinstance(value, dict):
        out: Dict[Any, Any] = {}
        for k, v in value.items():
            new_key = (
                _clean_inner(k, depth + 1, mode, changes, f"{path}.<key>", strict)
                if isinstance(k, str)
                else k
            )
            out[new_key] = _clean_inner(
                v, depth + 1, mode, changes, f"{path}.{k}", strict,
            )
        return out

    if isinstance(value, list):
        return [
            _clean_inner(v, depth + 1, mode, changes, f"{path}[{i}]", strict)
            for i, v in enumerate(value)
        ]

    if isinstance(value, tuple):
        # Preserve tuple type but sanitize contents. The previous version
        # returned tuples unchanged, so string contents inside tuples were
        # never repaired - an inconsistency with list handling.
        return tuple(
            _clean_inner(v, depth + 1, mode, changes, f"{path}[{i}]", strict)
            for i, v in enumerate(value)
        )

    # Pydantic v1/v2 model instance passed by mistake - a common slip when
    # a caller forgets to call .model_dump()/.to_legacy_dict() first.
    # Previously this silently passed through unchanged, which made the
    # caller believe sanitization had run. Now it's visible: a warning
    # (default) or an error (strict=True).
    model_dump = getattr(value, "model_dump", None) or getattr(value, "dict", None)
    if callable(model_dump):
        msg = (
            f"clean_text received a Pydantic model instance at {path!r}; "
            "call .model_dump() (or .to_legacy_dict()) before passing it "
            "in. Sanitizing a model instance in place is not supported."
        )
        if strict:
            raise CleanTextError(msg)
        logger.warning(msg + " - passing value through unchanged")
        return value

    # All other types (int, float, bool, None, datetime, UUID, Decimal, ...)
    # pass through unchanged - they cannot contain mojibake.
    return value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def clean_text(value: Any, mode: Mode = "full", strict: bool = False) -> Any:
    """Recursively repair mojibake in every string found inside `value`.

    Accepts nested dicts, lists, tuples, and plain strings. Non-string
    scalars (int, float, bool, None, datetime, ...) pass through unchanged.
    Dictionary keys are also sanitized if they are strings.

    Args:
        value:  Any structure to sanitize.
        mode:   'full' (default) repairs mojibake and additionally applies
                NFC normalization, quote uncurling, and control-character
                removal. 'encoding_only' repairs only the encoding layer,
                preserving all other Unicode exactly as the model produced
                it. Use 'encoding_only' when downstream code compares
                strings against known values (IDs, names) and cannot
                tolerate incidental character normalization.
        strict: When True, structural problems (nested deeper than the
                internal cap, or a Pydantic model instance passed by
                mistake) raise CleanTextError. When False (default), those
                problems are logged as warnings and the value is passed
                through unchanged - matching the previous version's
                permissive behaviour so existing callers don't break.

    Signature is backward compatible: existing calls like
    `clean_text(structured_dict)` are unchanged. The new keyword args
    have defaults that preserve prior behaviour.
    """
    return _clean_inner(
        value, depth=0, mode=mode, changes=None, path="$", strict=strict,
    )


def clean_text_with_report(
    value: Any, mode: Mode = "full", strict: bool = False,
) -> Tuple[Any, List[Tuple[str, str, str]]]:
    """Same as clean_text, but also returns a list of (path, before, after)
    tuples describing every string that was actually modified.

    Intended for tests, diagnostics, and one-off audits - the production
    path should use clean_text (which doesn't build the report and is
    therefore marginally cheaper on large documents).

    Example:
        cleaned, changes = clean_text_with_report({"name": "cafÃ©"})
        # changes == [("$.name", "cafÃ©", "café")]
    """
    changes: List[Tuple[str, str, str]] = []
    cleaned = _clean_inner(
        value, depth=0, mode=mode, changes=changes, path="$", strict=strict,
    )
    return cleaned, changes


def is_ftfy_available() -> bool:
    """Return True if ftfy was successfully imported.

    Useful for startup checks and health endpoints, so an operator can
    see whether sanitization is active in a given deployment without
    inspecting logs or dependency manifests."""
    return _FTFY_AVAILABLE