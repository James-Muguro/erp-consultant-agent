"""
Repairs common Unicode mojibake in LLM-generated text (e.g. a UTF-8
non-breaking hyphen or bidirectional arrow that got misdecoded somewhere
in the pipeline, showing up as sequences like 'â€‑' or 'â†”'). Applied
once, right after an agent parses its structured LLM response, before
that text is persisted or used to generate a document.
"""
from typing import Any
import ftfy


def clean_text(value: Any) -> Any:
    """Recursively repairs mojibake in every string found inside value -
    a dict, list, or plain string. Non-string values pass through
    unchanged."""
    if isinstance(value, str):
        return ftfy.fix_text(value)
    if isinstance(value, dict):
        return {k: clean_text(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean_text(v) for v in value]
    return value