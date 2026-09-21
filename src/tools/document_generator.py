"""
Document Generator Tool - Creates formatted Word documents for ERP projects,
persisted durably in Postgres (see GeneratedDocument) rather than relying on
local disk, which Render wipes on every redeploy or free-tier idle-restart.

"""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

from src.config.settings import settings
from src.utils.logger import AgentLogger

ACCENT_COLOR = RGBColor(0x1F, 0x5F, 0x4A)  # matches the frontend's pine-green accent


# ----------------------------------------------------------------------
# Filename / path-component safety
#
# The local file is transient (see module docstring); the durable artifact
# lives in Postgres. But the file on disk is the *source bytes* copied into
# that durable record by _persist_to_db, so its path must be deterministic,
# session-isolated, and incapable of escaping self.output_dir even when
# upstream values (project name, process name, session ID) are untrusted.
# ----------------------------------------------------------------------

_UNSAFE_CHARS_RE = re.compile(r'[\x00-\x1f\x7f]')   # NUL, C0 controls, DEL
_PATH_SEPS_RE = re.compile(r'[\\/]+')                # /, \, and runs thereof
_WHITESPACE_RE = re.compile(r'\s+')

_WINDOWS_RESERVED_NAMES = frozenset(
    {'CON', 'PRN', 'AUX', 'NUL'}
    | {f'COM{i}' for i in range(1, 10)}
    | {f'LPT{i}' for i in range(1, 10)}
)


def _truncate_utf8(text: str, max_bytes: int) -> str:
    """Truncate `text` to fit within `max_bytes` once UTF-8 encoded,
    without splitting a multi-byte codepoint. Returns "" if even one
    codepoint does not fit."""
    encoded = text.encode('utf-8')
    if len(encoded) <= max_bytes:
        return text
    cut = encoded[:max_bytes]
    while cut:
        try:
            return cut.decode('utf-8')
        except UnicodeDecodeError:
            cut = cut[:-1]
    return ""


def _sanitize_component(
    value: Any,
    *,
    fallback: str,
    max_bytes: int = 64,
) -> str:
    """Produce a safe, single path-component from an untrusted string.

    Guarantees:
      * no path separators (`/`, `\\`) remain
      * no NUL bytes or other control characters
      * empty / whitespace-only / all-punctuation inputs yield `fallback`
      * leading/trailing `.` and `-` are stripped (no hidden files, no `..`)
      * Windows reserved device names are escaped with a leading `_`
      * length is bounded to `max_bytes` (UTF-8), with a short hash suffix
        so two distinct long inputs sharing a prefix do not collide
      * valid Unicode is preserved (no transliteration)

    The returned value is a single filename component. It never contains
    a separator and can never resolve outside of its parent directory.
    """
    if value is None:
        return fallback
    text = str(value)

    # Strip control chars (incl. NUL) — these can truncate or confuse the FS.
    text = _UNSAFE_CHARS_RE.sub('', text)

    # Normalize whitespace runs (incl. tabs, newlines) to '_'.
    text = _WHITESPACE_RE.sub('_', text.strip())

    # Collapse path separators to a single '-' so no separator survives.
    text = _PATH_SEPS_RE.sub('-', text)

    # Strip leading/trailing '.' and '-' — kills '..', hidden files, and
    # empty-looking residue from separator collapsing.
    text = text.strip('.-')

    if not text:
        return fallback

    # Windows reserved device name (even with an extension).
    stem = text.split('.', 1)[0].upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        text = f"_{text}"

    # Byte-aware length bounding with a hash suffix for uniqueness.
    encoded = text.encode('utf-8')
    if len(encoded) > max_bytes:
        digest = hashlib.sha256(str(value).encode('utf-8')).hexdigest()[:8]
        suffix = f"_{digest}"
        budget = max_bytes - len(suffix.encode('ascii'))
        head = _truncate_utf8(text, max(0, budget))
        text = f"{head}{suffix}"

    return text


def _process_scoped_label(base: str, process_name: Any) -> str:
    """Compose a deterministic, collision-safe `label` for a generated
    document whose logical identity within GeneratedDocument is scoped to
    a specific process (e.g. a training user manual for a named process).

    GeneratedDocument's logical identity is (session_id, phase, label).
    Using a constant label like "user_manual" for every process would
    collapse two distinct processes' manuals into one logical document:
    regenerating process B would supersede process A's current artifact.

    The label produced here:
      * is stable across regenerations of the same process name (so the
        second generation supersedes the first rather than creating a
        new logical artifact),
      * differs between distinct process names, including names whose
        filesystem-safe sanitizations coincide (e.g. `Procure / Pay` and
        `Procure \\ Pay` both sanitize to `Procure-Pay` in the filename
        helper — the short digest of the raw pre-sanitization string
        disambiguates them here),
      * contains no path separators, NUL bytes, or control characters,
      * is bounded (sanitized name part capped at 48 UTF-8 bytes; total
        label stays well below any practical VARCHAR / TEXT bound).

    The digest is computed from the raw `process_name`, not its sanitized
    form, so two distinct raw inputs cannot collide on the digest merely
    because sanitization made them equal.
    """
    safe = _sanitize_component(process_name, fallback="unnamed", max_bytes=48)
    digest = hashlib.sha256(str(process_name).encode('utf-8')).hexdigest()[:8]
    return f"{base}_{safe}_{digest}"


def _atomic_save_docx(doc: Document, final_path: Path) -> None:
    """Save a python-docx Document to `final_path` atomically.

    Writes to a uniquely-named temp sibling in the same directory and then
    `os.replace`s into place. os.replace is atomic on POSIX and on Windows
    (same volume), so a crash mid-write cannot leave a truncated file at
    `final_path` that a subsequent reader could mistake for a complete
    artifact, and concurrent writers cannot interleave partial bytes.

    On failure the temp file is cleaned up on a best-effort basis and the
    original exception is re-raised unchanged.
    """
    tmp_path = final_path.parent / f".{final_path.name}.{uuid.uuid4().hex}.tmp"
    try:
        doc.save(str(tmp_path))
        os.replace(str(tmp_path), str(final_path))
    except BaseException:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DocumentGenerator:
    """Generates formatted Word (.docx) documentation for ERP projects."""

    def __init__(self):
        self.logger = AgentLogger("DocumentGenerator")
        self.output_dir = Path(settings.output_dir) / "documents"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Shared building blocks
    # ------------------------------------------------------------------

    def _new_document(self, title: str, subtitle: str) -> Document:
        doc = Document()

        title_para = doc.add_heading(title or "Untitled", level=0)
        title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in title_para.runs:
            run.font.color.rgb = ACCENT_COLOR

        subtitle_para = doc.add_paragraph(subtitle or "")
        subtitle_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        # Guard: python-docx only creates a run for non-empty strings.
        if subtitle_para.runs:
            subtitle_para.runs[0].italic = True
            subtitle_para.runs[0].font.size = Pt(11)

        doc.add_paragraph()
        return doc

    @staticmethod
    def _set_cell_text(cell, text: Any, bold: bool = False) -> None:
        """Set cell text safely. python-docx's .text setter does not create
        a run for an empty string, so a naive `cell.paragraphs[0].runs[0]`
        raises IndexError whenever the value is empty. This helper centralizes
        the guard so callers can't reintroduce the crash."""
        value = "" if text is None else str(text)
        cell.text = value
        if bold and cell.paragraphs[0].runs:
            cell.paragraphs[0].runs[0].bold = True

    def _add_info_table(self, doc: Document, rows: List[tuple]) -> None:
        table = doc.add_table(rows=0, cols=2)
        table.style = 'Light Grid Accent 1'
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        for label, value in rows:
            row = table.add_row().cells
            self._set_cell_text(row[0], label, bold=True)
            self._set_cell_text(row[1], value)
        doc.add_paragraph()

    @staticmethod
    def _format_structured_item(item: Any) -> str:
        """Render a list entry that may be a plain string (legacy shape, or
        the heuristic-parser fallback) or a dict (the shape the current
        schemas produce for decision points, integration points, and open
        questions). The previous `str(item)` on a dict produced raw
        `{'condition': ..., 'outcomes': [...]}` reprs in the document, which
        is not what a client-ready deliverable should contain."""
        if not isinstance(item, dict):
            return str(item)

        # Decision point
        if 'condition' in item:
            condition = item.get('condition', '')
            outcomes = item.get('outcomes') or []
            if outcomes:
                branch = " / ".join(str(o) for o in outcomes)
                return f"{condition}  →  {branch}"
            return str(condition)

        # Integration point
        if 'direction' in item or ('source' in item and 'target' in item):
            name = item.get('name') or f"{item.get('source', '')} → {item.get('target', '')}"
            direction = item.get('direction') or ''
            trigger = item.get('trigger') or ''
            transport = item.get('transport') or item.get('type') or ''
            bits = [name]
            if direction:
                bits.append(f"[{direction}]")
            if transport:
                bits.append(f"via {transport}")
            if trigger:
                bits.append(f"on {trigger}")
            return " ".join(str(b) for b in bits if b)

        # Open question
        if 'question' in item:
            topic = item.get('topic') or ''
            question = item.get('question') or ''
            owner = item.get('owner') or ''
            blocking = " [BLOCKING]" if item.get('blocking') else ""
            head = f"{topic}: {question}" if topic else question
            if owner:
                head = f"{head} (owner: {owner})"
            return f"{head}{blocking}"

        # Requirement-like
        if 'description' in item:
            rid = item.get('id') or ''
            desc = item.get('description') or ''
            prio = item.get('priority') or ''
            bits = [f"[{rid}]" if rid else "", str(desc), f"({prio})" if prio else ""]
            return " ".join(b for b in bits if b)

        # Fallback: join non-empty values
        parts = [f"{k}={v}" for k, v in item.items() if v]
        return " | ".join(parts) if parts else str(item)

    def _add_bullet_list(self, doc: Document, items: List[Any]) -> None:
        """Render a bullet list. Accepts list entries that are strings or
        structured dicts (see _format_structured_item)."""
        if not items:
            doc.add_paragraph("None specified.", style='Intense Quote')
            return
        for item in items:
            doc.add_paragraph(self._format_structured_item(item), style='List Bullet')

    def _add_data_table(self, doc: Document, headers: List[str], rows: List[List[Any]]) -> None:
        if not rows:
            doc.add_paragraph("None specified.", style='Intense Quote')
            return
        table = doc.add_table(rows=1, cols=len(headers))
        table.style = 'Light Grid Accent 1'
        for i, header in enumerate(headers):
            self._set_cell_text(table.rows[0].cells[i], header, bold=True)
        for row_values in rows:
            row = table.add_row().cells
            for i, value in enumerate(row_values):
                self._set_cell_text(row[i], value)
        doc.add_paragraph()

    def _add_optional_section(self, doc: Document, heading: str, body: str) -> None:
        """Add a heading + paragraph only if `body` has content. Keeps the
        document from becoming a wall of "None specified." when a new
        schema field is genuinely not applicable to a given project."""
        if body and str(body).strip():
            doc.add_heading(heading, level=1)
            doc.add_paragraph(str(body))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _persist_to_db(self, session_id: str, phase: str, label: str, filepath: str) -> None:
        """Persist the just-written document to Postgres and enforce the
        GeneratedDocument lifecycle contract: exactly one is_current=True
        row per logical artifact identity (session_id, phase, label).

        This, not the local file, is the durable source of truth used by
        download_document - the local copy is transient and may not exist
        by the time someone downloads it, especially after a redeploy.

        Regeneration is atomic within a single transaction:
            1. UPDATE the prior current row(s) for the exact identity,
               setting is_current=False
            2. INSERT the new row with is_current=True
            3. COMMIT both as one logical operation

        If step 2 fails, the transaction is rolled back and the prior
        current row remains is_current=True - a failed regeneration must
        never leave the identity without a current artifact.

        The WHERE clause on step 1 is scoped to the exact
        (session_id, phase, label) so this cannot clear another label's
        current row, nor another session's row. Historical rows are only
        touched on the is_current flag and their own updated_at; content
        and created_at are never modified.
        """
        from sqlalchemy import update as sa_update

        from src.db.base import SessionLocal
        from src.db.models import GeneratedDocument

        with open(filepath, 'rb') as f:
            content = f.read()

        new_id = uuid.uuid4().hex

        db = SessionLocal()
        try:
            # Step 1: clear the current row(s) for THIS exact logical
            # identity. A single bulk UPDATE issued immediately inside the
            # transaction that will also carry the INSERT. If the INSERT
            # fails below, the rollback undoes this UPDATE too.
            db.execute(
                sa_update(GeneratedDocument)
                .where(
                    GeneratedDocument.session_id == session_id,
                    GeneratedDocument.phase == phase,
                    GeneratedDocument.label == label,
                    GeneratedDocument.is_current.is_(True),
                )
                .values(is_current=False, updated_at=_utcnow())
            )

            # Step 2: insert the new current row.
            record = GeneratedDocument(
                id=new_id,
                session_id=session_id,
                phase=phase,
                label=label,
                is_current=True,
                filename=Path(filepath).name,
                content=content,
            )
            db.add(record)

            # Step 3: commit both as one transaction.
            db.commit()
        except Exception:
            # Roll back so a failed insert does not leave the prior
            # current row already cleared.
            db.rollback()
            raise
        finally:
            db.close()

        self.logger.log_tool_usage(
            "persist_generated_document",
            {'session': session_id, 'phase': phase, 'label': label},
            f"Persisted document {new_id}",
        )

    def _save(
        self,
        doc: Document,
        prefix: str,
        name: str,
        session_id: Optional[str] = None,
        phase: Optional[str] = None,
        label: Optional[str] = None,
    ) -> str:
        """Save `doc` to a deterministic, session-isolated, path-safe file.

        Artifact identity is:
            <doc-type prefix> + <sanitized session_id> + <sanitized name>
            + <UTC timestamp>  + <short uuid>
        Each field is sanitized independently so a hostile or malformed
        value in any one of them cannot escape self.output_dir, collide
        across sessions, or collide across same-second calls.

        The uuid suffix guarantees that two calls in the same wall-clock
        second — even for the same session, prefix and name — produce
        distinct filenames rather than silently overwriting each other.
        The write itself is atomic (temp file + os.replace)."""
        safe_prefix = _sanitize_component(
            prefix, fallback="document", max_bytes=48,
        )
        safe_name = _sanitize_component(
            name, fallback="unnamed", max_bytes=64,
        )
        safe_session = _sanitize_component(
            session_id, fallback="no-session", max_bytes=48,
        ) if session_id else "no-session"

        timestamp = _utcnow().strftime('%Y%m%d_%H%M%S')
        unique = uuid.uuid4().hex[:8]
        filename = f"{safe_prefix}_{safe_session}_{safe_name}_{timestamp}_{unique}.docx"

        filepath = self.output_dir / filename

        _atomic_save_docx(doc, filepath)

        if session_id:
            self._persist_to_db(
                session_id, phase or prefix, label or prefix, str(filepath),
            )
        else:
            self.logger.warning(
                f"Document generated without session_id - not persisted to DB, "
                f"will not survive a redeploy: {filepath}"
            )

        return str(filepath)

    # ------------------------------------------------------------------
    # Requirements document (final, from real structured requirements)
    # ------------------------------------------------------------------

    def generate_requirements_document(
        self,
        project_name: str,
        module: str,
        requirements: Dict[str, Any],
        metadata: Optional[Dict] = None,
        session_id: Optional[str] = None,
    ) -> str:
        doc = self._new_document("Requirements Document", project_name)

        self._add_info_table(doc, [
            ("Project Name", project_name),
            ("Module", module),
            ("Date", _utcnow().strftime('%Y-%m-%d')),
            ("Version", "1.0"),
            ("Status", "Draft"),
        ])

        doc.add_heading("Executive Summary", level=1)
        doc.add_paragraph(requirements.get('executive_summary') or "To be completed.")

        doc.add_heading("Business Context and Objectives", level=1)
        doc.add_paragraph(requirements.get('business_context') or "To be completed.")
        doc.add_heading("Business Objectives", level=2)
        self._add_bullet_list(doc, requirements.get('objectives', []))

        # ---- Functional requirements ---------------------------------- #
        doc.add_heading("Functional Requirements", level=1)
        functional_reqs = requirements.get('functional_requirements', {}) or {}
        if not functional_reqs:
            doc.add_paragraph("No functional requirements specified.", style='Intense Quote')
        for category, reqs in functional_reqs.items():
            doc.add_heading(category, level=2)
            rows = []
            for r in (reqs or []):
                if isinstance(r, dict):
                    rows.append([
                        r.get('id', 'REQ-XXX'),
                        r.get('description', ''),
                        r.get('priority', 'Medium'),
                        r.get('status', 'Draft'),
                        r.get('acceptance_criteria') or '',
                    ])
                else:
                    rows.append(['REQ-XXX', str(r), 'Medium', 'Draft', ''])
            self._add_data_table(
                doc,
                ["ID", "Description", "Priority", "Status", "Acceptance Criteria"],
                rows,
            )
            # Per-requirement rationale + source, rendered as a compact
            # appendix when present. These are the change-control fields a
            # reviewer needs when scope is renegotiated.
            trace_rows = []
            for r in (reqs or []):
                if isinstance(r, dict) and (r.get('rationale') or r.get('source')):
                    trace_rows.append([
                        r.get('id', ''),
                        r.get('rationale') or '',
                        r.get('source') or '',
                    ])
            if trace_rows:
                doc.add_heading(f"{category} — Rationale and Source", level=3)
                self._add_data_table(doc, ["ID", "Rationale", "Source"], trace_rows)

        # ---- Non-functional requirements ------------------------------ #
        doc.add_heading("Non-Functional Requirements", level=1)
        nfr_items = requirements.get('non_functional_requirements', []) or []
        self._add_bullet_list(
            doc,
            [r.get('description', r) if isinstance(r, dict) else r for r in nfr_items],
        )

        doc.add_heading("Technical Requirements", level=1)
        self._add_bullet_list(doc, [
            r.get('description', r) if isinstance(r, dict) else r
            for r in (requirements.get('technical_requirements') or [])
        ])

        doc.add_heading("Integration Requirements", level=1)
        self._add_bullet_list(doc, [
            r.get('description', r) if isinstance(r, dict) else r
            for r in (requirements.get('integration_requirements') or [])
        ])

        doc.add_heading("Reporting Requirements", level=1)
        self._add_bullet_list(doc, [
            r.get('description', r) if isinstance(r, dict) else r
            for r in (requirements.get('reporting_requirements') or [])
        ])

        doc.add_heading("Dependencies and Constraints", level=1)
        doc.add_heading("Dependencies", level=2)
        self._add_bullet_list(doc, requirements.get('dependencies', []) or [])
        doc.add_heading("Constraints", level=2)
        self._add_bullet_list(doc, requirements.get('constraints', []) or [])

        doc.add_heading("Assumptions", level=1)
        self._add_bullet_list(doc, requirements.get('assumptions', []) or [])

        # ---- Open questions ------------------------------------------- #
        # These are the gaps the requirements agent was instructed to name
        # rather than paper over. Rendering them is the whole point of the
        # epistemic discipline; previously they were dropped entirely.
        doc.add_heading("Open Questions", level=1)
        open_qs = requirements.get('open_questions', []) or []
        if open_qs:
            rows = []
            for q in open_qs:
                if isinstance(q, dict):
                    rows.append([
                        q.get('topic', ''),
                        q.get('question', ''),
                        "Blocking" if q.get('blocking') else "Non-blocking",
                        q.get('owner') or '',
                    ])
                else:
                    rows.append(['', str(q), 'Non-blocking', ''])
            self._add_data_table(doc, ["Topic", "Question", "Blocking?", "Owner"], rows)
        else:
            doc.add_paragraph(
                "No open questions - all input was resolvable from the "
                "information provided.",
                style='Intense Quote',
            )

        doc.add_heading("Approval", level=1)
        self._add_data_table(doc, ["Role", "Name", "Signature", "Date"], [
            ["Business Owner", "", "", ""],
            ["Project Manager", "", "", ""],
            ["Technical Lead", "", "", ""],
            ["Functional Consultant", "", "", ""],
        ])

        sid = session_id or (metadata or {}).get('session_id')
        filepath = self._save(
            doc, "requirements", project_name, session_id=sid,
            phase="requirements_gathering", label="requirements_gathering",
        )
        self.logger.log_tool_usage(
            "generate_requirements_document",
            {'project': project_name, 'module': module},
            f"Document saved to {filepath}",
        )
        return filepath

    # ------------------------------------------------------------------
    # Requirements questionnaire (template - no invented answers)
    # ------------------------------------------------------------------

    def generate_requirements_template(
        self,
        project_name: str,
        module: str,
        erp_system: str,
        context: Dict[str, str],
        session_id: Optional[str] = None,
    ) -> str:
        doc = self._new_document("Requirements Gathering Questionnaire", project_name)

        self._add_info_table(doc, [
            ("Project Name", project_name),
            ("Proposed ERP System", erp_system),
            ("Module", module),
            ("Date", _utcnow().strftime('%Y-%m-%d')),
        ])

        doc.add_heading("Project Context (from intake)", level=1)
        self._add_data_table(doc, ["Field", "Value"], [
            ["Industry", context.get('industry', 'Not specified')],
            ["Organization Size", context.get('company_size', 'Not specified')],
            ["Primary Goal", context.get('primary_goal', 'Not specified')],
            ["Scope Areas", context.get('scope_areas', 'Not specified')],
        ])

        doc.add_heading("Instructions", level=1)
        doc.add_paragraph(
            "Use this questionnaire to interview stakeholders across the scope areas above. "
            "Record their actual answers - do not guess or estimate on their behalf. Once "
            "complete, bring the answers back to continue the requirements-gathering process."
        )

        sections = [
            ("1. Business Context & Objectives", [
                "What are the top 3 business drivers for this initiative?",
                "How will success be measured (KPIs, cost savings, cycle-time reductions)?",
                "What is the timeline and budget envelope for this project?",
            ]),
            ("2. Current Processes & Pain Points", [
                "Which manual or legacy processes cause the most bottlenecks today?",
                "Are there regulatory or compliance constraints that apply?",
                "What existing systems will this replace or integrate with?",
            ]),
            ("3. Functional Requirements", [
                f"For each area in scope ({context.get('scope_areas', 'the stated scope')}), "
                f"what are the must-have capabilities?",
                "What are the nice-to-have capabilities?",
                "Are there any unique workflows standard ERP modules may not cover out of the box?",
            ]),
            ("4. Data & Migration", [
                "What is the approximate volume of master and transactional data?",
                "Which data sources will need to be migrated or integrated?",
                "Are there known data quality issues in the current systems?",
            ]),
            ("5. Integration Requirements", [
                "Which external systems must this ERP connect to?",
                "What data formats or protocols are currently in use?",
            ]),
            ("6. Reporting & Analytics", [
                "What reports or dashboards are critical for each stakeholder role?",
                "Is real-time reporting required, or is periodic reporting sufficient?",
            ]),
            ("7. Constraints & Dependencies", [
                "Are there upcoming regulatory changes or infrastructure upgrades to consider?",
                "Are there vendor, staffing, or budget constraints to be aware of?",
            ]),
            ("8. Acceptance Criteria", [
                "How will each stakeholder validate that their requirements have been met?",
            ]),
        ]
        for heading, questions in sections:
            doc.add_heading(heading, level=1)
            self._add_bullet_list(doc, questions)

        doc.add_paragraph()
        note = doc.add_paragraph(
            "Once this questionnaire has been completed with real stakeholder answers, "
            "paste the responses back into the chat to continue."
        )
        if note.runs:
            note.runs[0].italic = True

        filepath = self._save(
            doc, "requirements_questionnaire", project_name, session_id=session_id,
            phase="requirements_template", label="requirements_template",
        )
        self.logger.log_tool_usage(
            "generate_requirements_template",
            {'project': project_name, 'module': module},
            f"Template saved to {filepath}",
        )
        return filepath

    # ------------------------------------------------------------------
    # Process map
    # ------------------------------------------------------------------

    def generate_process_map(
        self,
        project_name: str,
        process_name: str,
        module: str,
        process_map: Dict[str, Any],
        session_id: Optional[str] = None,
    ) -> str:
        doc = self._new_document(f"Process Map: {process_name}", project_name)

        as_is_or_to_be = process_map.get('as_is_or_to_be') or 'Unspecified'
        self._add_info_table(doc, [
            ("Project Name", project_name),
            ("Process", process_name),
            ("Module", module),
            ("View", as_is_or_to_be),
            ("Date", _utcnow().strftime('%Y-%m-%d')),
        ])

        doc.add_heading("Overview", level=1)
        doc.add_paragraph(process_map.get('overview') or "Not specified.")

        doc.add_heading("Scope", level=1)
        doc.add_paragraph(process_map.get('scope') or "Not specified.")

        doc.add_heading("Roles", level=1)
        self._add_bullet_list(doc, process_map.get('roles', []) or [])

        doc.add_heading("Process Steps", level=1)
        steps = process_map.get('steps', []) or []
        if steps:
            rows = []
            for i, s in enumerate(steps):
                if isinstance(s, dict):
                    rows.append([
                        s.get('number', i + 1),
                        s.get('name', ''),
                        s.get('responsible_role') or '-',
                        s.get('transaction') or '-',
                        s.get('description') or '',
                    ])
                else:
                    rows.append([i + 1, str(s), '-', '-', ''])
            self._add_data_table(
                doc, ["#", "Step", "Responsible Role", "Transaction", "Description"], rows,
            )

            # Detailed per-step appendix - trigger/inputs/outputs/exceptions.
            # These are the fields the process-mapping guardrails require;
            # before this revision they were silently dropped from the .docx.
            detail_rows = []
            for s in steps:
                if not isinstance(s, dict):
                    continue
                trigger = s.get('trigger') or ''
                inputs = s.get('inputs') or []
                outputs = s.get('outputs') or []
                exceptions = s.get('exception_paths') or []
                if trigger or inputs or outputs or exceptions:
                    detail_rows.append([
                        s.get('id', '') or s.get('number', ''),
                        trigger,
                        ", ".join(str(x) for x in inputs),
                        ", ".join(str(x) for x in outputs),
                        "; ".join(str(x) for x in exceptions),
                    ])
            if detail_rows:
                doc.add_heading("Step Detail", level=2)
                self._add_data_table(
                    doc,
                    ["Step", "Trigger", "Inputs", "Outputs", "Exception Paths"],
                    detail_rows,
                )
        else:
            doc.add_paragraph("No steps specified.", style='Intense Quote')

        doc.add_heading("Decision Points", level=1)
        self._add_bullet_list(doc, process_map.get('decision_points', []) or [])

        doc.add_heading("Integration Points", level=1)
        self._add_bullet_list(doc, process_map.get('integration_points', []) or [])

        doc.add_heading("Exceptions", level=1)
        self._add_bullet_list(doc, process_map.get('exceptions', []) or [])

        # Improvements was a pre-existing field that was never rendered.
        doc.add_heading("Identified Improvements", level=1)
        self._add_bullet_list(doc, process_map.get('improvements', []) or [])

        doc.add_heading("Open Questions", level=1)
        open_qs = process_map.get('open_questions', []) or []
        if open_qs:
            self._add_bullet_list(doc, open_qs)
        else:
            doc.add_paragraph(
                "No open questions - the process was fully specified by the "
                "provided input.",
                style='Intense Quote',
            )

        filepath = self._save(
            doc, "process_map", process_name, session_id=session_id,
            phase="process_mapping", label=process_name,
        )
        self.logger.log_tool_usage(
            "generate_process_map",
            {'project': project_name, 'process': process_name},
            f"Document saved to {filepath}",
        )
        return filepath

    # ------------------------------------------------------------------
    # Test cases
    # ------------------------------------------------------------------

    def generate_test_case_document(
        self,
        project_name: str,
        module: str,
        test_cases: List[Dict[str, Any]],
        test_type: str = "QA",
        session_id: Optional[str] = None,
    ) -> str:
        doc = self._new_document(f"{test_type} Test Cases", project_name)

        self._add_info_table(doc, [
            ("Project Name", project_name),
            ("Module", module),
            ("Test Type", test_type),
            ("Date", _utcnow().strftime('%Y-%m-%d')),
            ("Total Test Cases", len(test_cases)),
        ])

        for idx, tc in enumerate(test_cases, 1):
            doc.add_heading(
                f"Test Case {idx}: {tc.get('scenario', 'Test Scenario')}", level=1,
            )

            # UAT-specific metadata is rendered only when populated - QA
            # cases leave role/process/acceptance blank by design.
            info_rows = [
                ("Test Case ID", tc.get('id', f'TC-{idx:03d}')),
                ("Priority", tc.get('priority', 'Medium')),
                ("Test Type", tc.get('type', 'Functional')),
            ]
            if tc.get('user_role'):
                info_rows.append(("User Role", tc['user_role']))
            if tc.get('business_process'):
                info_rows.append(("Business Process", tc['business_process']))
            self._add_info_table(doc, info_rows)

            if tc.get('objective'):
                doc.add_heading("Objective", level=2)
                doc.add_paragraph(tc['objective'])

            doc.add_heading("Preconditions", level=2)
            self._add_bullet_list(doc, tc.get('preconditions', []) or [])

            doc.add_heading("Test Steps", level=2)
            for step_num, step in enumerate(tc.get('steps', []) or [], 1):
                doc.add_paragraph(f"{step_num}. {step}")

            # Test data table, when present. The schema stores it as a list
            # of {key, value} pairs; rendering as a table makes it scannable.
            test_data = tc.get('test_data') or []
            if test_data:
                doc.add_heading("Test Data", level=2)
                rows = []
                for item in test_data:
                    if isinstance(item, dict):
                        rows.append([item.get('key', ''), item.get('value', '')])
                    else:
                        rows.append([str(item), ''])
                self._add_data_table(doc, ["Field", "Value"], rows)

            doc.add_heading("Expected Result", level=2)
            doc.add_paragraph(tc.get('expected_result') or 'Not specified.')

            # Acceptance criteria is UAT's business sign-off statement, and
            # is distinct from expected_result. Rendered only when present.
            if tc.get('acceptance_criteria'):
                doc.add_heading("Acceptance Criteria", level=2)
                doc.add_paragraph(tc['acceptance_criteria'])

            # Traceability: what this test validates. Rendered only when
            # links exist - an empty list is an honest "no traceability
            # established yet" rather than an error.
            trace_bits = []
            if tc.get('related_requirement_ids'):
                trace_bits.append(
                    "Requirements: " + ", ".join(str(r) for r in tc['related_requirement_ids'])
                )
            if tc.get('related_process_step_ids'):
                trace_bits.append(
                    "Process steps: " + ", ".join(str(s) for s in tc['related_process_step_ids'])
                )
            if tc.get('related_design_component'):
                trace_bits.append(f"Design component: {tc['related_design_component']}")
            if trace_bits:
                doc.add_heading("Traceability", level=2)
                for bit in trace_bits:
                    doc.add_paragraph(bit, style='List Bullet')

            # Execution status / failure detail rendered only when set.
            status = tc.get('execution_status') or 'not_run'
            doc.add_heading("Status", level=2)
            if status and status != 'not_run':
                doc.add_paragraph(
                    f"Execution status: {status}"
                    + (f" — {tc.get('failure_classification')}"
                       if tc.get('failure_classification') else "")
                )
                if tc.get('failure_description'):
                    doc.add_paragraph(tc['failure_description'])
            else:
                doc.add_paragraph("☐ Pass    ☐ Fail    ☐ Blocked")

        doc.add_heading("Test Execution Summary", level=1)
        self._add_data_table(
            doc, ["Test Case ID", "Scenario", "Priority", "Status", "Tester", "Date"],
            [[
                tc.get('id', 'TC-XXX'),
                tc.get('scenario', ''),
                tc.get('priority', 'Medium'),
                tc.get('execution_status') or '',
                "",
                "",
            ] for tc in test_cases],
        )

        phase = "qa_testing" if test_type == "QA" else "uat_testing"
        filepath = self._save(
            doc, f"test_cases_{test_type}", project_name, session_id=session_id,
            phase=phase, label=phase,
        )
        self.logger.log_tool_usage(
            "generate_test_case_document",
            {'project': project_name, 'test_type': test_type},
            f"Document saved to {filepath}",
        )
        return filepath

    # ------------------------------------------------------------------
    # User manual
    # ------------------------------------------------------------------

    def generate_user_manual(
        self,
        process_name: str,
        module: str,
        process_steps: List[Dict[str, Any]],
        screenshots: Optional[List[str]] = None,
        session_id: Optional[str] = None,
    ) -> str:
        doc = self._new_document(f"User Manual: {process_name}", module)

        self._add_info_table(doc, [
            ("Module", module),
            ("Process", process_name),
            ("Date", _utcnow().strftime('%Y-%m-%d')),
        ])

        doc.add_heading("Purpose", level=1)
        doc.add_paragraph(
            f"This manual provides step-by-step instructions for executing the "
            f"{process_name} process in the ERP system."
        )

        doc.add_heading("Prerequisites", level=1)
        self._add_bullet_list(doc, [
            f"Access to {module} module",
            "Required authorizations",
            "Basic understanding of ERP navigation",
        ])

        doc.add_heading("Process Steps", level=1)
        for idx, step in enumerate(process_steps or [], 1):
            if not isinstance(step, dict):
                # Legacy shape from the heuristic parser.
                doc.add_heading(f"Step {idx}", level=2)
                doc.add_paragraph(str(step))
                continue

            doc.add_heading(
                f"Step {idx}: {step.get('title', 'Process Step')}", level=2,
            )

            # Metadata line: role + transaction, when present. These are
            # new schema fields that were previously dropped.
            meta_bits = []
            if step.get('role'):
                meta_bits.append(f"Role: {step['role']}")
            if step.get('transaction'):
                meta_bits.append(f"Transaction: {step['transaction']}")
            if meta_bits:
                meta_para = doc.add_paragraph(" | ".join(meta_bits))
                if meta_para.runs:
                    meta_para.runs[0].italic = True

            # Preconditions (new) - what must be in place before the step
            # can be executed.
            preconditions = step.get('preconditions') or []
            if preconditions:
                doc.add_heading("Before You Start", level=3)
                self._add_bullet_list(doc, preconditions)

            doc.add_paragraph(step.get('instructions', 'Not specified.'))

            fields = step.get('fields') or []
            if fields:
                doc.add_heading("Key Fields", level=3)
                rows = []
                for f in fields:
                    if isinstance(f, dict):
                        rows.append([
                            f.get('name', ''),
                            f.get('description', ''),
                            f.get('required', 'No'),
                            f.get('example', ''),
                        ])
                    else:
                        rows.append([str(f), '', '', ''])
                self._add_data_table(doc, ["Field", "Description", "Required", "Example"], rows)

            # Verification (new) - how the user knows the step succeeded.
            if step.get('verification'):
                doc.add_heading("How to Verify", level=3)
                doc.add_paragraph(step['verification'])

            # Common errors (new) - symptom / likely cause / resolution.
            common_errors = step.get('common_errors') or []
            if common_errors:
                doc.add_heading("Common Issues", level=3)
                rows = []
                for ce in common_errors:
                    if isinstance(ce, dict):
                        rows.append([
                            ce.get('symptom', ''),
                            ce.get('likely_cause', ''),
                            ce.get('resolution', ''),
                            ce.get('severity', 'Warning'),
                        ])
                    else:
                        rows.append([str(ce), '', '', ''])
                self._add_data_table(doc, ["Symptom", "Likely Cause", "Resolution", "Severity"], rows)

            tips = step.get('tips')
            if tips:
                doc.add_heading("Tips", level=3)
                self._add_bullet_list(doc, tips)

        # Label must be process-scoped: with a constant label, a second
        # process's manual in the same session would collide on the
        # GeneratedDocument logical identity (session_id, phase, label)
        # and supersede the first process's current artifact.
        filepath = self._save(
            doc, "user_manual", process_name, session_id=session_id,
            phase="training",
            label=_process_scoped_label("user_manual", process_name),
        )
        self.logger.log_tool_usage(
            "generate_user_manual",
            {'process': process_name, 'module': module},
            f"Document saved to {filepath}",
        )
        return filepath

    # ------------------------------------------------------------------
    # Solution design
    # ------------------------------------------------------------------

    def generate_solution_design(
        self,
        project_name: str,
        module: str,
        design: Dict[str, Any],
        session_id: Optional[str] = None,
    ) -> str:
        doc = self._new_document("Solution Design Document", project_name)

        self._add_info_table(doc, [
            ("Project Name", project_name),
            ("Module", module),
            ("Date", _utcnow().strftime('%Y-%m-%d')),
            ("Author", "ERP Consultant AI"),
        ])

        doc.add_heading("Executive Summary", level=1)
        doc.add_paragraph(design.get('executive_summary') or "Not specified.")

        doc.add_heading("Solution Architecture", level=1)
        doc.add_paragraph(design.get('architecture_overview') or "Not specified.")

        # ---- Configurations ------------------------------------------- #
        doc.add_heading("Module Configuration", level=1)
        configs = design.get('configurations') or []
        if not configs:
            doc.add_paragraph("No configurations specified.", style='Intense Quote')
        for config in configs:
            if not isinstance(config, dict):
                continue
            classification = config.get('classification') or 'CONFIGURATION'
            doc.add_heading(
                f"{config.get('component', 'Component')} [{classification}]", level=2,
            )
            if config.get('module'):
                sub = doc.add_paragraph(f"Module: {config['module']}")
                if sub.runs:
                    sub.runs[0].italic = True
            doc.add_paragraph(config.get('description', ''))
            steps = config.get('steps') or []
            if steps:
                self._add_bullet_list(doc, steps)

        # ---- Integrations --------------------------------------------- #
        doc.add_heading("Integration Design", level=1)
        integrations = design.get('integrations') or []
        if not integrations:
            doc.add_paragraph("No integrations specified.", style='Intense Quote')
        for integ in integrations:
            if not isinstance(integ, dict):
                continue
            doc.add_heading(integ.get('name', 'Integration'), level=2)
            rows = [
                ("Type", integ.get('type', 'Real-time')),
                ("Direction", integ.get('direction', '')),
                ("Source", integ.get('source', '')),
                ("Target", integ.get('target', '')),
                ("Trigger", integ.get('trigger', '')),
                ("Transport", integ.get('transport', '')),
                ("Payload", integ.get('payload_summary', '')),
                ("Error handling", integ.get('error_handling', '')),
                ("Idempotency key", integ.get('idempotency_key', '')),
            ]
            self._add_info_table(doc, [(k, v) for k, v in rows if v])
            if integ.get('description'):
                doc.add_paragraph(integ['description'])

        # ---- Customizations ------------------------------------------- #
        doc.add_heading("Customizations", level=1)
        customizations = design.get('customizations') or []
        if customizations:
            rows = []
            for c in customizations:
                if not isinstance(c, dict):
                    continue
                rows.append([
                    c.get('type', ''),
                    c.get('component', ''),
                    c.get('description', ''),
                    c.get('justification', ''),
                    c.get('complexity', ''),
                ])
            self._add_data_table(
                doc,
                ["Type", "Component", "Description", "Justification", "Complexity"],
                rows,
            )

            # Lifecycle impact and alternatives considered render as a
            # per-customization appendix only when populated. These are the
            # fields a steering committee actually asks about.
            appendix_rows = []
            for c in customizations:
                if not isinstance(c, dict):
                    continue
                alternatives = c.get('alternatives_considered') or []
                lifecycle = c.get('lifecycle_impact') or ''
                if alternatives or lifecycle:
                    appendix_rows.append([
                        c.get('component', ''),
                        "; ".join(str(a) for a in alternatives),
                        lifecycle,
                    ])
            if appendix_rows:
                doc.add_heading("Customization Review Detail", level=2)
                self._add_data_table(
                    doc,
                    ["Component", "Alternatives Considered", "Lifecycle Impact"],
                    appendix_rows,
                )
        else:
            doc.add_paragraph(
                "No customizations required. Solution uses standard ERP functionality "
                "and configuration."
            )

        # ---- Master data ---------------------------------------------- #
        # The schema stores master data in two shapes: flattened (keyed by
        # data_type) for backward compatibility, and as a rich list under
        # master_data_items. Prefer the rich list when available; fall back
        # to the flattened dict.
        doc.add_heading("Master Data", level=1)
        md_items = design.get('master_data_items')
        if isinstance(md_items, list) and md_items:
            rows = []
            for m in md_items:
                if not isinstance(m, dict):
                    continue
                rows.append([
                    m.get('data_type', ''),
                    m.get('status', 'TBD'),
                    m.get('owner', ''),
                    m.get('details', ''),
                ])
            self._add_data_table(
                doc, ["Data Type", "Status", "Owner", "Details"], rows,
            )
        else:
            md_flat = design.get('master_data') or {}
            if isinstance(md_flat, dict) and md_flat:
                self._add_data_table(
                    doc, ["Data Type", "Details"],
                    [[k, v] for k, v in md_flat.items()],
                )
            else:
                doc.add_paragraph("No master data specified.", style='Intense Quote')

        # ---- Security ------------------------------------------------- #
        security = design.get('security') or {}
        if isinstance(security, dict) and any(security.values()):
            doc.add_heading("Security and Authorization", level=1)
            self._add_optional_section(doc, "Overview", security.get('overview', ''))
            if security.get('authorization_model'):
                doc.add_heading("Authorization Model", level=2)
                doc.add_paragraph(security['authorization_model'])
            if security.get('roles'):
                doc.add_heading("Roles", level=2)
                self._add_bullet_list(doc, security['roles'])
            if security.get('sod_controls'):
                doc.add_heading("Segregation-of-Duties Controls", level=2)
                self._add_bullet_list(doc, security['sod_controls'])
            if security.get('sensitive_access'):
                doc.add_heading("Sensitive Access", level=2)
                self._add_bullet_list(doc, security['sensitive_access'])

        # ---- Migration ------------------------------------------------ #
        migration = design.get('migration') or {}
        if isinstance(migration, dict) and any(migration.values()):
            doc.add_heading("Migration Strategy", level=1)
            if migration.get('approach'):
                sub = doc.add_paragraph(f"Approach: {migration['approach']}")
                if sub.runs:
                    sub.runs[0].bold = True
            self._add_optional_section(doc, "Summary", migration.get('strategy', ''))
            self._add_optional_section(doc, "Cutover Window", migration.get('cutover_window', ''))
            if migration.get('data_scope'):
                doc.add_heading("Data Scope", level=2)
                self._add_bullet_list(doc, migration['data_scope'])
            self._add_optional_section(
                doc, "Reconciliation", migration.get('reconciliation_approach', ''),
            )
            self._add_optional_section(
                doc, "Rollback Approach", migration.get('rollback_approach', ''),
            )

        # ---- Technical specs ------------------------------------------ #
        ts_items = design.get('technical_specs_items')
        doc.add_heading("Technical Specifications", level=1)
        if isinstance(ts_items, list) and ts_items:
            rows = []
            for t in ts_items:
                if not isinstance(t, dict):
                    continue
                rows.append([t.get('category', ''), t.get('name', ''), t.get('value', '')])
            self._add_data_table(doc, ["Category", "Name", "Value"], rows)
        else:
            ts_flat = design.get('technical_specs') or {}
            if isinstance(ts_flat, dict) and ts_flat:
                self._add_data_table(
                    doc, ["Specification", "Value"],
                    [[k, v] for k, v in ts_flat.items()],
                )
            else:
                doc.add_paragraph("No technical specifications specified.", style='Intense Quote')

        # ---- Assumptions and open questions --------------------------- #
        doc.add_heading("Assumptions", level=1)
        self._add_bullet_list(doc, design.get('assumptions', []) or [])

        doc.add_heading("Open Questions", level=1)
        open_qs = design.get('open_questions', []) or []
        if open_qs:
            rows = []
            for q in open_qs:
                if isinstance(q, dict):
                    rows.append([
                        q.get('topic', ''),
                        q.get('question', ''),
                        "Blocking" if q.get('blocking') else "Non-blocking",
                        q.get('owner') or '',
                    ])
                else:
                    rows.append(['', str(q), 'Non-blocking', ''])
            self._add_data_table(doc, ["Topic", "Question", "Blocking?", "Owner"], rows)
        else:
            doc.add_paragraph(
                "No open questions - the design was fully specified by the "
                "provided input.",
                style='Intense Quote',
            )

        filepath = self._save(
            doc, "solution_design", project_name, session_id=session_id,
            phase="solution_design", label="solution_design",
        )
        self.logger.log_tool_usage(
            "generate_solution_design",
            {'project': project_name, 'module': module},
            f"Document saved to {filepath}",
        )
        return filepath

    # ------------------------------------------------------------------
    # Consolidated project status report (client-ready deliverable)
    # ------------------------------------------------------------------

    def generate_project_report(self, session_id: str) -> str:
        """Assembles the current state of the project - across every phase
        - into a single, professional document a consultant can hand to a
        client for review or sign-off. Deliberately pulls from the same
        structured-data query functions the API and frontend use
        (src/services/project_intelligence.py), not a re-derivation of
        that logic - this is a formatting layer over existing data, not a
        second source of truth for it."""
        from src.memory import session_service
        from src.services import project_intelligence

        session = session_service.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        requirements = project_intelligence.get_requirements(session_id)
        process_steps = project_intelligence.get_process_steps(session_id)
        solution_decisions = project_intelligence.get_solution_decisions(session_id)
        test_cases = project_intelligence.get_test_cases(session_id)
        training_steps = project_intelligence.get_training_steps(session_id)
        open_issues = project_intelligence.get_issues(session_id, status="open")
        health = project_intelligence.get_project_health(session_id)
        gaps = project_intelligence.get_coverage_gaps(session_id)

        doc = self._new_document("Project Status Report", session.project_name)

        self._add_info_table(doc, [
            ("Project Name", session.project_name),
            ("ERP System", session.erp_system),
            ("Module", session.module),
            ("Current Phase", (session.current_phase or '').replace('_', ' ').title()),
            ("Report Date", _utcnow().strftime('%Y-%m-%d')),
            ("Requirement Coverage", f"{health.get('requirements_coverage_pct', 0)}%"),
        ])

        doc.add_heading("Executive Summary", level=1)
        status_line = (
            f"{health.get('requirements_total', 0)} requirements captured, "
            f"{health.get('requirements_coverage_pct', 0)}% with downstream coverage. "
            f"{health.get('open_issues_total', 0)} open item(s) require attention."
        )
        doc.add_paragraph(status_line)

        doc.add_heading("Requirements", level=1)
        by_category: Dict[str, List[Dict]] = {}
        for r in requirements:
            by_category.setdefault(r['category'], []).append(r)
        if not by_category:
            doc.add_paragraph("No requirements captured yet.", style='Intense Quote')
        for category, items in by_category.items():
            doc.add_heading(category, level=2)
            self._add_data_table(doc, ["Description", "Priority", "Status"], [
                [r['description'], r.get('priority') or '-', r['status']] for r in items
            ])

        doc.add_heading("Process Steps", level=1)
        by_process: Dict[str, List[Dict]] = {}
        for s in process_steps:
            by_process.setdefault(s['process_name'], []).append(s)
        if not by_process:
            doc.add_paragraph("No process steps captured yet.", style='Intense Quote')
        for process_name, steps in by_process.items():
            doc.add_heading(process_name, level=2)
            ordered = sorted(steps, key=lambda s: s['step_number'])
            self._add_data_table(doc, ["#", "Step", "Responsible Role"], [
                [s['step_number'], s['name'], s.get('responsible_role') or '-'] for s in ordered
            ])

        doc.add_heading("Solution Decisions", level=1)
        by_type: Dict[str, List[Dict]] = {}
        for d in solution_decisions:
            by_type.setdefault(d['decision_type'], []).append(d)
        if not by_type:
            doc.add_paragraph("No solution decisions recorded yet.", style='Intense Quote')
        for decision_type, decisions in by_type.items():
            doc.add_heading(decision_type.replace('_', ' ').title(), level=2)
            self._add_data_table(doc, ["Component", "Description", "Rationale", "Status"], [
                [d.get('component') or '-', d['description'], d.get('rationale') or '-', d['status']]
                for d in decisions
            ])

        doc.add_heading("Testing & Training", level=1)
        self._add_data_table(doc, ["Metric", "Count"], [
            ["QA test cases", sum(1 for t in test_cases if t['test_type'] == 'QA')],
            ["UAT test cases", sum(1 for t in test_cases if t['test_type'] != 'QA')],
            ["Training steps", len(training_steps)],
        ])

        doc.add_heading("Coverage Gaps", level=1)
        doc.add_heading("Requirements with no downstream coverage", level=2)
        self._add_bullet_list(
            doc, [r['description'] for r in gaps.get('uncovered_requirements', [])],
        )
        doc.add_heading("Requirements with no test coverage", level=2)
        self._add_bullet_list(
            doc, [r['description'] for r in gaps.get('untested_requirements', [])],
        )

        doc.add_heading("Open Items for Review", level=1)
        if open_issues:
            self._add_data_table(doc, ["Type", "Severity", "Description"], [
                [i['issue_type'].replace('_', ' '), i['severity'], i['description']]
                for i in open_issues
            ])
        else:
            doc.add_paragraph("No open items.")

        doc.add_heading("Sign-off", level=1)
        self._add_data_table(doc, ["Role", "Name", "Signature", "Date"], [
            ["Business Owner", "", "", ""],
            ["Project Manager", "", "", ""],
            ["Consulting Lead", "", "", ""],
        ])

        filepath = self._save(
            doc, "project_report", session.project_name, session_id=session_id,
            phase="project_report", label="Project Status Report",
        )
        self.logger.log_tool_usage(
            "generate_project_report",
            {'project': session.project_name},
            f"Report saved to {filepath}",
        )
        return filepath


# Global document generator instance
doc_generator = DocumentGenerator()