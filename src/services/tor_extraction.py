"""TOR document extraction.

Primary path: Word (.docx) via python-docx, already a dependency.
Fallback path: Excel (.xlsx) via openpyxl, which is pinned explicitly
in requirements.txt (see Phase 2.5 D1 Q9).

Each parser returns a list of dicts:
    {external_code, category, description, source_excerpt}

External codes are assigned sequentially by this module (TOR-001, ...)
because TOR documents rarely carry stable identifiers. The codes are
unique per opportunity and become the RequirementItemRecord external
codes after Mark-as-Won.
"""
from __future__ import annotations

import io
import logging
import re
from typing import Any, Dict, List, Optional

from src.utils.logger import get_logger


logger = get_logger(__name__)


class TorExtractionError(Exception):
    """Raised when a TOR cannot be parsed at all. Callers turn this into
    a 422 with a clear message."""


def _next_code(counter: List[int]) -> str:
    counter[0] += 1
    return f"TOR-{counter[0]:03d}"


def _clip(value: Optional[str], limit: int = 500) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


# ---------------------------------------------------------------------------
# Word
# ---------------------------------------------------------------------------
def _extract_from_word(content: bytes) -> List[Dict[str, Any]]:
    from docx import Document  # python-docx

    try:
        doc = Document(io.BytesIO(content))
    except Exception as e:  # noqa: BLE001
        raise TorExtractionError(
            f"Could not open the Word document: {e}"
        )

    counter = [0]
    rows: List[Dict[str, Any]] = []

    # Prefer table extraction when any table exists. TOR documents that
    # carry tables almost always put one requirement per row.
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            # Skip a header row: the first non-empty cell is a known
            # header keyword.
            if not any(cells):
                continue
            first = cells[0].lower() if cells else ""
            if first in ("id", "ref", "requirement id", "no.", "no", "#"):
                continue
            if len(cells) >= 2:
                description = cells[1] if len(cells) > 1 else cells[0]
                if not description:
                    continue
                category = cells[2] if len(cells) > 2 and cells[2] else None
            else:
                description = cells[0]
                category = None
            if not description:
                continue
            rows.append({
                "external_code": _next_code(counter),
                "category": category,
                "description": description,
                "source_excerpt": _clip(" | ".join(cells)),
            })

    if rows:
        return rows

    # No tables: fall back to paragraph parsing, one requirement per
    # non-trivial paragraph. This is lossy by design; the Business Development
    # reviews and edits every row.
    for para in doc.paragraphs:
        text = para.text.strip()
        if len(text) < 20:
            continue
        if re.fullmatch(r"[\W\d_]+", text):
            continue
        rows.append({
            "external_code": _next_code(counter),
            "category": None,
            "description": text,
            "source_excerpt": _clip(text),
        })

    return rows


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
def _extract_from_excel(content: bytes) -> List[Dict[str, Any]]:
    try:
        from openpyxl import load_workbook
    except ImportError as e:
        raise TorExtractionError(
            "Excel support requires the openpyxl package. It is not "
            "installed on this server. Please provide the TOR as a Word "
            "document (.docx)."
        ) from e

    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001
        raise TorExtractionError(f"Could not open the Excel workbook: {e}")

    counter = [0]
    rows: List[Dict[str, Any]] = []

    for ws in wb.worksheets:
        header_skipped = False
        for raw_row in ws.iter_rows(values_only=True):
            cells = [
                (str(c).strip() if c is not None else "") for c in raw_row
            ]
            if not any(cells):
                continue
            if not header_skipped:
                header_skipped = True
                first = cells[0].lower() if cells else ""
                if first in ("id", "ref", "requirement id", "no.", "no", "#",
                             "requirement", "requirement text"):
                    continue
            # Heuristic: description is the longest non-trivial cell.
            non_empty = [c for c in cells if c]
            if not non_empty:
                continue
            description = max(non_empty, key=len)
            if len(description) < 5:
                continue
            rows.append({
                "external_code": _next_code(counter),
                "category": None,
                "description": description,
                "source_excerpt": _clip(" | ".join(non_empty)),
            })

    return rows


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------
def extract_tor(content: bytes, source_format: str) -> List[Dict[str, Any]]:
    """Extract requirements from a TOR file.

    `source_format` is 'word' or 'excel'. Unknown formats raise
    TorExtractionError with a clear message. Returned rows carry
    sequential TOR-NNN external codes scoped to this extraction call;
    when persisted to opportunity_requirements, the unique constraint on
    (opportunity_id, external_code) applies.
    """
    if source_format == "word":
        return _extract_from_word(content)
    if source_format == "excel":
        return _extract_from_excel(content)
    raise TorExtractionError(f"Unsupported TOR format: {source_format!r}")


def detect_format(filename: str, content_type: str) -> Optional[str]:
    """Return 'word' | 'excel' for a filename, or None if unknown.

    Extension is checked before content type because the client's MIME
    reporting for .xlsx is unreliable across browsers.
    """
    name = (filename or "").lower()
    if name.endswith(".docx") or name.endswith(".doc"):
        return "word"
    if name.endswith(".xlsx") or name.endswith(".xls"):
        return "excel"
    ct = (content_type or "").lower()
    if "word" in ct or "officedocument.wordprocessingml" in ct:
        return "word"
    if "spreadsheet" in ct or "excel" in ct or "officedocument.spreadsheetml" in ct:
        return "excel"
    return None